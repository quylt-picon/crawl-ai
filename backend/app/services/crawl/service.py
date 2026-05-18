"""Crawl service — thin, focused wrapper around Crawl4AI.

The service exposes one method per workflow concern (homepage UI extraction,
typed search, plain crawl, expand-then-crawl). It is *intentionally* unaware
of LLMs and FastAPI; only the workflow orchestrator stitches things together.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.crawl.js_snippets import (
    AGGRESSIVE_EXTRACT_UI_JS,
    EXPAND_SECTIONS_JS,
    EXTRACT_UI_JS,
)

_log = get_logger(__name__)


@dataclass
class UIExtraction:
    page_url: str
    page_title: str
    inputs: list[dict[str, Any]]
    buttons: list[dict[str, Any]]
    forms: list[dict[str, Any]]
    nav_links: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_url": self.page_url,
            "page_title": self.page_title,
            "inputs": self.inputs,
            "buttons": self.buttons,
            "forms": self.forms,
            "nav_links": self.nav_links,
        }


@dataclass
class CrawlResult:
    url: str
    final_url: str
    status_code: int
    markdown: str
    internal_links: list[dict[str, Any]]
    external_links: list[dict[str, Any]]

    @property
    def all_links(self) -> list[dict[str, Any]]:
        return self.internal_links + self.external_links


class CrawlService:
    def __init__(self, headless: bool = True, page_timeout_ms: int = 60_000) -> None:
        self._browser_cfg = BrowserConfig(headless=headless, verbose=False)
        self._page_timeout_ms = page_timeout_ms

    # ----------------------------------------------------- STEP 1 / STEP 3-B

    async def extract_ui(self, url: str, aggressive: bool = False) -> UIExtraction:
        """Open a page and return only its UI structure (forms/inputs/buttons/nav).

        The injected JS dismisses cookie banners, clicks search/hamburger
        triggers to reveal hidden inputs, and scrolls to load lazy content
        before snapshotting the DOM. In ``aggressive`` mode it clicks more
        candidate triggers and uses a multi-pass scroll — used as a retry
        when the standard pass yields neither a search box nor a support URL.
        """
        js_code = AGGRESSIVE_EXTRACT_UI_JS if aggressive else EXTRACT_UI_JS
        # The JS itself takes ~1.5s (standard) / ~3.5s (aggressive) due to
        # internal sleeps; this extra delay buffers slow SPAs that re-render
        # after our trigger clicks.
        delay = 3.0 if aggressive else 2.0
        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=1,
            page_timeout=self._page_timeout_ms,
            js_code=js_code,
            wait_for="js:() => !!window.__crawl_ui_data__",
            delay_before_return_html=delay,
        )
        async with AsyncWebCrawler(config=self._browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)

        if not result.success:
            raise CrawlError(f"extract_ui failed: {result.error_message}")

        payload = _read_window_var(result, "__crawl_ui_data__") or {}
        return UIExtraction(
            page_url=payload.get("page_url", url),
            page_title=payload.get("page_title", ""),
            inputs=payload.get("inputs", []),
            buttons=payload.get("buttons", []),
            forms=payload.get("forms", []),
            nav_links=payload.get("nav_links", []),
        )

    # ----------------------------------------------------- STEP 3 (interact)

    async def search_via_selectors(
        self,
        url: str,
        input_selector: str,
        button_selector: Optional[str],
        query: str,
    ) -> CrawlResult:
        """Type into a search input and submit, then return the results page."""
        type_js = _build_type_js(input_selector, query)
        submit_js = _build_submit_js(input_selector, button_selector)

        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=1,
            page_timeout=self._page_timeout_ms,
            js_code=[type_js, submit_js],
            delay_before_return_html=2.0,
        )
        async with AsyncWebCrawler(config=self._browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)

        if not result.success:
            raise CrawlError(f"search_via_selectors failed: {result.error_message}")

        return _to_crawl_result(url, result)

    # ----------------------------------------------------- STEP 5 / STEP 7

    async def crawl(self, url: str, expand_sections: bool = False) -> CrawlResult:
        js_code = [EXPAND_SECTIONS_JS] if expand_sections else None
        wait_for = "js:() => window.__crawl_expanded_count__ !== undefined" if expand_sections else None

        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=5,
            page_timeout=self._page_timeout_ms,
            js_code=js_code,
            wait_for=wait_for,
            delay_before_return_html=1.0 if expand_sections else 0.0,
        )
        async with AsyncWebCrawler(config=self._browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)

        if not result.success:
            raise CrawlError(f"crawl failed: {result.error_message}")

        return _to_crawl_result(url, result)


class CrawlError(RuntimeError):
    pass


# ---------------------------------------------------------------------- helpers


def _read_window_var(result: Any, name: str) -> Optional[dict[str, Any]]:
    """Crawl4AI surfaces window vars in different fields across versions.

    We look in `js_execution_result` first (newer versions), then fall back to
    parsing the HTML for an inline script we may have injected. As a last
    resort, return None and let the caller deal with missing data.
    """
    raw: Any = None
    js_res = getattr(result, "js_execution_result", None)
    if isinstance(js_res, dict):
        # Some versions return { "results": [...] }, others { name: value }.
        if name in js_res:
            raw = js_res[name]
        elif "results" in js_res and isinstance(js_res["results"], list):
            for entry in js_res["results"]:
                if isinstance(entry, dict) and name in entry:
                    raw = entry[name]
                    break

    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _to_crawl_result(requested_url: str, result: Any) -> CrawlResult:
    md = result.markdown.raw_markdown if hasattr(result.markdown, "raw_markdown") else str(result.markdown or "")
    links = result.links or {}
    return CrawlResult(
        url=requested_url,
        final_url=getattr(result, "url", requested_url) or requested_url,
        status_code=getattr(result, "status_code", 0) or 0,
        markdown=md,
        internal_links=list(links.get("internal") or []),
        external_links=list(links.get("external") or []),
    )


def _build_type_js(selector: str, query: str) -> str:
    safe_selector = json.dumps(selector)
    safe_query = json.dumps(query)
    return f"""
(async () => {{
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const el = document.querySelector({safe_selector});
  if (!el) {{ window.__crawl_search_typed__ = false; return; }}
  el.focus();
  el.value = '';
  el.dispatchEvent(new Event('input', {{bubbles: true}}));
  el.value = {safe_query};
  el.dispatchEvent(new Event('input', {{bubbles: true}}));
  el.dispatchEvent(new Event('change', {{bubbles: true}}));
  await sleep(150);
  window.__crawl_search_typed__ = true;
}})();
"""


def _build_submit_js(input_selector: str, button_selector: Optional[str]) -> str:
    safe_input = json.dumps(input_selector)
    safe_button = json.dumps(button_selector or "")
    return f"""
(async () => {{
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  let submitted = false;
  const btn = {safe_button} ? document.querySelector({safe_button}) : null;
  if (btn) {{
    btn.click();
    submitted = true;
  }} else {{
    const inp = document.querySelector({safe_input});
    const form = inp ? inp.closest('form') : null;
    if (form) {{
      form.submit();
      submitted = true;
    }} else if (inp) {{
      const ev = new KeyboardEvent('keydown', {{key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}});
      inp.dispatchEvent(ev);
      submitted = true;
    }}
  }}
  await sleep(2000);
  window.__crawl_search_submitted__ = submitted;
}})();
"""


# ---------------------------------------------------------------------- factory

_service: CrawlService | None = None


def get_crawl_service() -> CrawlService:
    global _service
    if _service is None:
        settings = get_settings()
        _service = CrawlService(
            headless=settings.crawl_headless,
            page_timeout_ms=settings.crawl_page_timeout_ms,
        )
        _log.info(
            "Crawl service initialized: headless=%s timeout=%dms",
            settings.crawl_headless,
            settings.crawl_page_timeout_ms,
        )
    return _service

"""Crawl service — thin, focused wrapper around Crawl4AI.

The service exposes one method per workflow concern (homepage HTML snapshot,
typed search, plain crawl, LLM-driven manual extraction). It is
*intentionally* unaware of FastAPI; only the workflow orchestrator stitches
things together.

Homepage discovery deliberately avoids custom probing JS — we rely on
Crawl4AI's built-in popup dismissal, user simulation, and full-page scroll,
then hand the final HTML to the LLM and let it pick selectors.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, LLMConfig
from crawl4ai.extraction_strategy import LLMExtractionStrategy

from app.core.config import get_settings
from app.core.logging import get_logger

_log = get_logger(__name__)


@dataclass
class HomepageSnapshot:
    page_url: str
    page_title: str
    html: str
    links: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_url": self.page_url,
            "page_title": self.page_title,
            "html_chars": len(self.html),
            "link_count": len(self.links),
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


@dataclass
class ManualExtractionCrawlResult(CrawlResult):
    """A CrawlResult plus the raw extracted-content JSON from the LLM strategy."""

    extracted_raw: str = ""


class CrawlService:
    def __init__(self, headless: bool = True, page_timeout_ms: int = 60_000) -> None:
        self._browser_cfg = BrowserConfig(headless=headless, verbose=False)
        self._page_timeout_ms = page_timeout_ms

    # ----------------------------------------------------- STEP 1 / STEP 3-B

    async def snapshot_page(self, url: str) -> HomepageSnapshot:
        """Open a page and capture its final cleaned HTML for LLM analysis.

        No custom probing JS — popup dismissal, user-behavior simulation, and
        lazy-content loading are delegated to Crawl4AI built-ins. The LLM
        receives the resulting HTML and is responsible for picking selectors.
        """
        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=1,
            page_timeout=self._page_timeout_ms,
            remove_overlay_elements=True,
            remove_consent_popups=True,
            simulate_user=True,
            magic=True,
            scan_full_page=True,
            max_scroll_steps=10,
            scroll_delay=0.5,
            delay_before_return_html=2.5,
        )
        async with AsyncWebCrawler(config=self._browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)

        if not result.success:
            raise CrawlError(f"snapshot_page failed: {result.error_message}")

        html = getattr(result, "cleaned_html", None) or getattr(result, "html", None) or ""
        links = result.links or {}
        return HomepageSnapshot(
            page_url=getattr(result, "url", url) or url,
            page_title=_extract_title(result, html),
            html=html,
            links=list(links.get("internal") or []) + list(links.get("external") or []),
        )

    # ----------------------------------------------------- STEP 3 (interact)

    async def search_via_selectors(
        self,
        url: str,
        input_selector: str,
        button_selector: Optional[str],
        query: str,
    ) -> CrawlResult:
        """Type into a search input and submit, then return the results page.

        Uses the same popup-dismiss + user-simulation knobs as ``snapshot_page``
        so the search UI is rendered into the DOM the same way it was when the
        LLM picked the selectors. The injected JS polls for the input / button
        before clicking, so there is no need for a brittle ``wait_for`` on a
        selector that may only become visible after a magnifier-icon click.

        Headers, footers, navs, and asides are stripped so the resulting
        markdown contains only the search-result body — the downstream LLM
        match step pays for every token of that content.
        """
        js_code = _build_search_js(input_selector, button_selector, query)

        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=1,
            page_timeout=self._page_timeout_ms,
            remove_overlay_elements=True,
            remove_consent_popups=True,
            simulate_user=True,
            magic=True,
            js_code=js_code,
            delay_before_return_html=3.0,
            excluded_tags=["header", "footer", "nav", "aside"],
            excluded_selector=(
                "header, footer, nav, aside, "
                "[role=banner], [role=contentinfo], [role=navigation], "
                ".header, .site-header, .page-header, "
                ".footer, .site-footer, .page-footer, "
                ".nav, .navbar, .navigation, .menu, .breadcrumb, .breadcrumbs"
            ),
        )
        async with AsyncWebCrawler(config=self._browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)

        if not result.success:
            raise CrawlError(f"search_via_selectors failed: {result.error_message}")

        return _to_crawl_result(url, result)

    # ----------------------------------------------------- STEP 5+6+7 / fetch

    async def crawl(self, url: str) -> CrawlResult:
        """Plain crawl — fetch markdown + links for ``url``. No JS injection."""
        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=5,
            page_timeout=self._page_timeout_ms,
            excluded_tags=["header", "footer", "nav", "aside"],
        )
        async with AsyncWebCrawler(config=self._browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)

        if not result.success:
            raise CrawlError(f"crawl failed: {result.error_message}")

        return _to_crawl_result(url, result)

    async def extract_manual(
        self,
        url: str,
        *,
        llm_provider: str,
        llm_api_token: str,
        instruction: str,
        schema: dict[str, Any],
    ) -> "ManualExtractionCrawlResult":
        """Crawl ``url`` and let the LLM extract a manual locator from it.

        Headers, footers, navs, and asides are stripped so the LLM sees only
        the product body — the place where support/manual sections actually
        live. No JS is injected: we rely on Crawl4AI's built-in popup
        dismissal and the LLM's ability to reason about collapsed tabs from
        the markdown alone (links inside collapsed sections are still in the
        rendered DOM).
        """
        strategy = LLMExtractionStrategy(
            llm_config=LLMConfig(provider=llm_provider, api_token=llm_api_token),
            schema=schema,
            extraction_type="schema",
            instruction=instruction,
            input_format="markdown",
            apply_chunking=False,
            force_json_response=True,
        )
        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=5,
            page_timeout=self._page_timeout_ms,
            remove_overlay_elements=True,
            remove_consent_popups=True,
            excluded_tags=["header", "footer", "nav", "aside"],
            excluded_selector=(
                "header, footer, nav, aside, "
                "[role=banner], [role=contentinfo], [role=navigation], "
                ".header, .site-header, .page-header, "
                ".footer, .site-footer, .page-footer, "
                ".nav, .navbar, .navigation, .menu, .breadcrumb, .breadcrumbs"
            ),
            extraction_strategy=strategy,
        )
        async with AsyncWebCrawler(config=self._browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)

        if not result.success:
            raise CrawlError(f"extract_manual failed: {result.error_message}")

        base = _to_crawl_result(url, result)
        extracted_raw = getattr(result, "extracted_content", None) or ""
        return ManualExtractionCrawlResult(
            url=base.url,
            final_url=base.final_url,
            status_code=base.status_code,
            markdown=base.markdown,
            internal_links=base.internal_links,
            external_links=base.external_links,
            extracted_raw=extracted_raw,
        )


class CrawlError(RuntimeError):
    pass


# ---------------------------------------------------------------------- helpers


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _extract_title(result: Any, html: str) -> str:
    md = getattr(result, "metadata", None)
    if isinstance(md, dict):
        title = md.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    m = _TITLE_RE.search(html or "")
    if m:
        return m.group(1).strip()[:200]
    return ""


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


def _build_search_js(
    input_selector: str,
    button_selector: Optional[str],
    query: str,
) -> str:
    """Build the search-trigger JS for the LLM-chosen selectors.

    Polls for the input (and the button, when given) so we tolerate search
    UIs that only mount their input on a magnifier-click. Then sets the
    value, fires input/change, and either clicks the submit button or
    submits the enclosing form / dispatches Enter as fallback.
    """
    safe_input = json.dumps(input_selector)
    safe_query = json.dumps(query)
    safe_button = json.dumps(button_selector or "")
    return f"""
(async () => {{
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const waitFor = async (sel, timeoutMs) => {{
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {{
      const el = document.querySelector(sel);
      if (el) return el;
      await sleep(150);
    }}
    return null;
  }};
  const inp = await waitFor({safe_input}, 8000);
  if (!inp) return;
  try {{ inp.focus(); }} catch (e) {{}}
  inp.value = {safe_query};
  inp.dispatchEvent(new Event('input', {{bubbles: true}}));
  inp.dispatchEvent(new Event('change', {{bubbles: true}}));
  const btnSel = {safe_button};
  if (btnSel) {{
    const btn = await waitFor(btnSel, 4000);
    if (btn) {{ btn.click(); return; }}
  }}
  const form = inp.closest('form');
  if (form) {{ form.submit(); return; }}
  inp.dispatchEvent(new KeyboardEvent('keydown',
    {{key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}}));
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

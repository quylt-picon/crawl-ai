"""Deep-crawl workflow: web-search the product's support/detail page, then run
the 3-hop manual extraction directly against it.

This is a *standalone* pipeline, intentionally independent of the other
orchestrators so it can be changed without affecting the running services:

  1. FIND_PAGE     — a grounded web search (Google, via the LLM) locates the
                     product's OWN manufacturer page (support / downloads /
                     manuals / detail). The *search prompt* comes from the UI.
  2. FIND_MANUAL   — the LLM extraction strategy runs on that page; if the
                     manuals live on a linked support/downloads hub it follows
                     that link and extracts again (up to 3 hops total).
  3. FINALIZE      — pick the primary document and report the totals.

It reuses only stateless infrastructure (the Gemini web-search provider and the
crawl service); it does NOT import or modify the websearch / crawl-workflow /
combined orchestrators.
"""
from __future__ import annotations

import json

from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.constants import StepId, StepStatus
from app.core.logging import get_logger
from app.events.emitter import Emitter
from app.schemas.llm import ManualEntry, ManualExtraction, OfficialSite
from app.schemas.responses import ManualResult
from app.services.crawl import CrawlService, get_crawl_service
from app.services.crawl.service import CrawlError, ManualExtractionCrawlResult
from app.services.deepcrawl.prompts import TARGET_PAGE_SYSTEM
from app.services.llm.prompts import MANUAL_EXTRACTION_INSTRUCTION_TEMPLATE
from app.services.websearch.provider import GeminiWebSearchProvider, WebSearchRaw
from app.utils.json_parse import JsonParseError, extract_json

_log = get_logger(__name__)

MAX_MANUAL_EXTRACTION_HOPS = 3

# Cap how many sources/queries we spell out line-by-line in the timeline; the
# structured ``data`` payload still carries them all for the frontend panels.
_MAX_DETAIL_LINES = 30


class DeepCrawlError(RuntimeError):
    pass


class DeepCrawlOrchestrator:
    def __init__(
        self,
        provider: GeminiWebSearchProvider,
        crawl: CrawlService,
        *,
        llm_provider: str,
        llm_api_token: str,
        max_retries: int = 3,
    ) -> None:
        self._provider = provider
        self._crawl = crawl
        self._llm_provider = llm_provider
        self._llm_api_token = llm_api_token
        self._max_retries = max_retries

    async def run(
        self,
        *,
        product_name: str,
        product_code: str,
        search_prompt: str,
        emitter: Emitter,
        model: str | None = None,
    ) -> ManualResult:
        try:
            site = await self._step_find_page(
                product_name=product_name,
                product_code=product_code,
                search_prompt=search_prompt,
                model=model,
                emitter=emitter,
            )
            if not site.found or not site.url:
                await emitter.completion(success=False, error="support_page_not_found")
                return ManualResult(type="not_found")

            manuals = await self._step_extract_manual(
                product_url=site.url,
                product_name=product_name,
                product_code=product_code,
                emitter=emitter,
            )
            result = await self._step_finalize(manuals, emitter)
            await emitter.completion(
                success=result.type != "not_found",
                manual_type=result.type,
                manual_url=result.url,
                has_content=bool(result.content),
            )
            return result
        except (DeepCrawlError, CrawlError) as exc:
            _log.exception("deep-crawl workflow failed: %s", exc)
            await emitter.fail_active_step(str(exc))
            await emitter.log(f"Deep-crawl failed: {exc}", level="error")
            await emitter.completion(success=False, error=str(exc))
            return ManualResult(type="not_found")
        except Exception as exc:  # last-resort safety net
            _log.exception("unexpected deep-crawl failure: %s", exc)
            await emitter.fail_active_step(f"Unexpected error: {exc}")
            await emitter.log(f"Unexpected error: {exc}", level="error")
            await emitter.completion(success=False, error=f"unexpected: {exc}")
            return ManualResult(type="not_found")

    # ------------------------------------------------ STEP 1: find support page

    async def _step_find_page(
        self,
        *,
        product_name: str,
        product_code: str,
        search_prompt: str,
        model: str | None,
        emitter: Emitter,
    ) -> OfficialSite:
        used_model = model or self._provider.default_model
        await emitter.progress(
            StepId.FIND_PAGE,
            StepStatus.RUNNING,
            f"Web-searching for the support/detail page of '{product_name}' ({product_code})",
        )

        prompt = _render_prompt(search_prompt, product_name, product_code)
        await emitter.log(
            f"Model: {used_model} · target: {product_name} / {product_code}",
            step=StepId.FIND_PAGE,
        )
        await emitter.log(f"Prompt used:\n{prompt}", step=StepId.FIND_PAGE)

        site, sources, queries = await self._search_target_page(prompt, model=model)

        if queries:
            await emitter.log(
                f"Model ran {_n_queries(len(queries))}:", step=StepId.FIND_PAGE
            )
            for q in queries[:_MAX_DETAIL_LINES]:
                await emitter.log(f"  • {q}", step=StepId.FIND_PAGE)
        if sources:
            await emitter.log(
                f"Consulted {len(sources)} web source(s):", step=StepId.FIND_PAGE
            )
            for i, s in enumerate(sources[:_MAX_DETAIL_LINES], start=1):
                await emitter.log(f"  {_fmt_source(i, s)}", step=StepId.FIND_PAGE)

        data = {"site": site.model_dump(), "sources": sources, "queries": queries}
        if site.found and site.url:
            brand = f" ({site.brand})" if site.brand else ""
            await emitter.progress(
                StepId.FIND_PAGE,
                StepStatus.SUCCESS,
                f"Support/detail page{brand}: {site.url}",
                data=data,
            )
        else:
            await emitter.progress(
                StepId.FIND_PAGE,
                StepStatus.ERROR,
                "No support/detail page found"
                + (f": {site.reason}" if site.reason else ""),
                data=data,
            )
        return site

    async def _search_target_page(
        self, prompt: str, *, model: str | None
    ) -> tuple[OfficialSite, list[dict[str, str]], list[str]]:
        """Grounded web search for the target page. Mirrors the soft-miss
        handling of the websearch service: a hard provider failure raises
        :class:`DeepCrawlError`, a "no valid JSON" outcome returns found=false.
        """
        last_raw: WebSearchRaw | None = None
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=5.0),
                retry=retry_if_exception_type((JsonParseError, ValidationError)),
                reraise=True,
            ):
                with attempt:
                    raw = await self._provider.search(
                        prompt, model=model, system=TARGET_PAGE_SYSTEM
                    )
                    last_raw = raw
                    site = OfficialSite.model_validate(extract_json(raw.text))
                    if site.url:
                        site.url = _normalize_url(site.url)
                    return site, raw.sources, raw.queries
        except (JsonParseError, ValidationError, RetryError) as exc:
            _log.warning("target-page search returned no valid JSON: %s", exc)
            return (
                OfficialSite(
                    found=False,
                    reason="The model did not return a valid target-page result.",
                ),
                last_raw.sources if last_raw else [],
                last_raw.queries if last_raw else [],
            )
        except Exception as exc:  # provider / network / auth failure
            raise DeepCrawlError(f"target-page search failed: {exc}") from exc

        raise DeepCrawlError("target-page search did not return")  # pragma: no cover

    # ------------------------------------------- STEP 2: 3-hop manual extraction

    async def _step_extract_manual(
        self,
        *,
        product_url: str,
        product_name: str,
        product_code: str,
        emitter: Emitter,
    ) -> list[ManualEntry]:
        """Run the LLM extraction strategy on the page, following at most one
        support/downloads link per hop, up to ``MAX_MANUAL_EXTRACTION_HOPS``."""
        await emitter.progress(
            StepId.FIND_MANUAL,
            StepStatus.RUNNING,
            f"Extracting manuals from {product_url}",
        )

        instruction = MANUAL_EXTRACTION_INSTRUCTION_TEMPLATE.format(
            product_name=product_name,
            product_code=product_code,
        )
        schema = ManualExtraction.model_json_schema()

        current_url = product_url
        visited: set[str] = set()
        hops: list[dict] = []
        collected: list[ManualEntry] = []
        last_extraction: ManualExtraction | None = None
        last_page_markdown = ""
        last_page_links: list[dict] = []

        for hop_idx in range(MAX_MANUAL_EXTRACTION_HOPS):
            if current_url in visited:
                await emitter.log(
                    f"Already visited {current_url}; stopping to avoid a loop.",
                    step=StepId.FIND_MANUAL,
                    level="warning",
                )
                break
            visited.add(current_url)

            await emitter.log(
                f"Hop {hop_idx + 1}: extracting from {current_url}",
                step=StepId.FIND_MANUAL,
            )
            page = await self._crawl.extract_manual(
                url=current_url,
                llm_provider=self._llm_provider,
                llm_api_token=self._llm_api_token,
                instruction=instruction,
                schema=schema,
            )
            last_page_markdown = page.markdown
            last_page_links = page.all_links
            extraction = _parse_manual_extraction(page)
            last_extraction = extraction

            hops.append(
                {
                    "hop": hop_idx + 1,
                    "url": current_url,
                    "final_url": page.final_url,
                    "markdown_chars": len(page.markdown),
                    "link_count": len(page.all_links),
                    "extraction": extraction.model_dump(),
                    "extracted_raw": page.extracted_raw,
                }
            )

            for entry in extraction.manuals:
                if _dedup_key(entry) in {_dedup_key(e) for e in collected}:
                    continue
                collected.append(entry)

            if extraction.final or not extraction.follow_url:
                break
            next_url = extraction.follow_url.strip()
            if not next_url or next_url == current_url:
                break
            current_url = next_url

        if collected:
            primary = collected[0]
            msg = f"Found {len(collected)} manual(s); primary type={primary.type}"
            status = StepStatus.SUCCESS
        else:
            msg = f"No manual found after {len(hops)} hop(s)" + (
                f": {last_extraction.reason}"
                if last_extraction and last_extraction.reason
                else ""
            )
            status = StepStatus.ERROR

        await emitter.progress(
            StepId.FIND_MANUAL,
            status,
            msg,
            data={
                "manuals": [m.model_dump() for m in collected],
                "manual_count": len(collected),
                "hops": hops,
                "hops_used": len(hops),
                "last_markdown": last_page_markdown,
                "last_links": last_page_links,
            },
        )
        return collected

    # ----------------------------------------------------------- STEP 3: finalize

    async def _step_finalize(
        self,
        manuals: list[ManualEntry],
        emitter: Emitter,
    ) -> ManualResult:
        await emitter.progress(
            StepId.FINALIZE, StepStatus.RUNNING, "Finalizing manual result"
        )

        if not manuals:
            result = ManualResult(type="not_found")
            await emitter.progress(
                StepId.FINALIZE,
                StepStatus.ERROR,
                "No manual to finalize.",
                data=result.model_dump(),
            )
            return result

        primary = manuals[0]
        primary_content = primary.content
        if primary.type == "html_url" and primary.url and not primary_content:
            await emitter.log(
                f"Crawling primary html_url manual {primary.url}",
                step=StepId.FINALIZE,
            )
            try:
                fetched = await self._crawl.crawl(primary.url)
                primary_content = fetched.markdown
            except CrawlError as exc:
                await emitter.log(
                    f"Failed to fetch html_url manual: {exc}",
                    step=StepId.FINALIZE,
                    level="warning",
                )

        result = ManualResult(
            type=primary.type,
            url=primary.url,
            content=primary_content,
            manuals=manuals,
        )

        result_dump = result.model_dump()
        if result_dump.get("content"):
            result_dump["content_chars"] = len(result_dump["content"])
        await emitter.progress(
            StepId.FINALIZE,
            StepStatus.SUCCESS,
            f"Done ({len(manuals)} manual{'s' if len(manuals) != 1 else ''}, "
            f"primary type={result.type})",
            data=result_dump,
        )
        return result


# ----------------------------------------------------------------------- helpers


def _render_prompt(prompt: str, product_name: str, product_code: str) -> str:
    """Substitute the ``{product_name}`` / ``{product_code}`` placeholders with
    a plain replace (not ``str.format``) so stray braces can't raise."""
    return (
        prompt.replace("{product_name}", product_name)
        .replace("{product_code}", product_code)
    )


def _normalize_url(url: str) -> str:
    """Add a scheme when missing so the crawler always gets an absolute URL."""
    from urllib.parse import urlparse

    cleaned = (url or "").strip()
    if not cleaned:
        return cleaned
    if not urlparse(cleaned).scheme:
        return f"https://{cleaned.lstrip('/')}"
    return cleaned


def _parse_manual_extraction(page: ManualExtractionCrawlResult) -> ManualExtraction:
    """Parse Crawl4AI's extracted_content (a JSON-encoded string) into a
    :class:`ManualExtraction`, tolerating list-wrapped / chunked payloads."""
    raw = (page.extracted_raw or "").strip()
    if not raw:
        return ManualExtraction(final=True, reason="empty extraction")
    try:
        payload = extract_json(raw)
    except JsonParseError:
        return ManualExtraction(final=True, reason="invalid extraction JSON")

    if isinstance(payload, list):
        with_manuals = [p for p in payload if isinstance(p, dict) and p.get("manuals")]
        with_follow = [p for p in payload if isinstance(p, dict) and p.get("follow_url")]
        payload = (with_manuals or with_follow or payload)[0] if payload else {}

    if not isinstance(payload, dict):
        return ManualExtraction(final=True, reason="extraction was not an object")

    payload.pop("index", None)
    payload.pop("error", None)
    try:
        return ManualExtraction.model_validate(payload)
    except ValidationError as exc:
        _log.warning(
            "ManualExtraction validation failed: %s; payload=%s",
            exc,
            json.dumps(payload)[:500],
        )
        return ManualExtraction(
            final=True, reason=f"validation error: {exc.errors()[0].get('msg', exc)}"
        )


def _dedup_key(entry: ManualEntry) -> str:
    return f"{entry.type}|{(entry.url or '').strip().lower()}|{(entry.label or '').strip().lower()}"


def _n_queries(n: int) -> str:
    return f"{n} query" if n == 1 else f"{n} queries"


def _fmt_source(i: int, s: dict[str, str]) -> str:
    domain = (s.get("domain") or "").strip()
    title = (s.get("title") or "").strip()
    uri = (s.get("uri") or "").strip()
    head = domain or title or uri or "(unknown source)"
    title_suffix = f" — {title}" if title and title != head else ""
    uri_suffix = f" — {uri}" if uri else ""
    return f"[{i}] {head}{title_suffix}{uri_suffix}"


# ----------------------------------------------------------------------- factory

_orchestrator: DeepCrawlOrchestrator | None = None


def get_deepcrawl_orchestrator() -> DeepCrawlOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        settings = get_settings()
        provider = GeminiWebSearchProvider(
            api_key=settings.gemini_api_token,
            model=settings.gemini_model,
        )
        _orchestrator = DeepCrawlOrchestrator(
            provider,
            get_crawl_service(),
            llm_provider=f"gemini/{settings.gemini_model}",
            llm_api_token=settings.gemini_api_token,
            max_retries=settings.llm_max_retries,
        )
        _log.info(
            "Deep-crawl orchestrator initialized: provider=gemini model=%s",
            settings.gemini_model,
        )
    return _orchestrator

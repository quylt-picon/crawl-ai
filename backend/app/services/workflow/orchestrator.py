"""End-to-end workflow: homepage → search → product detail → manual.

The orchestrator emits one ProgressEvent per workflow step transition and
streams LogEvents in between. Each step is its own private method so the
control flow stays readable. All recoverable failures are caught and
reported via the emitter — exceptions only bubble for truly unexpected bugs.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.constants import StepId, StepStatus
from app.core.logging import get_logger
from app.events.emitter import Emitter
from app.schemas.llm import ManualEntry, ManualExtraction, UIAnalysis
from app.schemas.responses import ManualResult
from app.services.crawl import CrawlService, get_crawl_service
from app.services.crawl.service import (
    CrawlError,
    CrawlResult,
    HomepageSnapshot,
    ManualExtractionCrawlResult,
)
from app.services.llm import LLMService, get_llm_service
from app.services.llm.prompts import MANUAL_EXTRACTION_INSTRUCTION_TEMPLATE
from app.services.llm.service import LLMServiceError
from app.utils.json_parse import JsonParseError, extract_json

_log = get_logger(__name__)

MAX_MANUAL_EXTRACTION_HOPS = 3


class WorkflowError(RuntimeError):
    pass


class WorkflowOrchestrator:
    def __init__(self, crawl: CrawlService, llm: LLMService) -> None:
        self._crawl = crawl
        self._llm = llm
        settings = get_settings()
        self._llm_provider = f"gemini/{settings.gemini_model}"
        self._llm_api_token = settings.gemini_api_token

    async def run(
        self,
        *,
        website_url: str,
        product_name: str,
        product_code: str,
        emitter: Emitter,
    ) -> ManualResult:
        try:
            snapshot = await self._step_crawl_homepage(website_url, emitter)
            analysis = await self._step_analyze_ui(snapshot, emitter)
            search_page = await self._step_search_product(
                website_url=website_url,
                product_code=product_code,
                analysis=analysis,
                emitter=emitter,
            )
            match = await self._step_filter_results(
                search_page=search_page,
                product_name=product_name,
                product_code=product_code,
                emitter=emitter,
            )
            if not match.found or not match.product_url:
                await emitter.progress(
                    StepId.FINALIZE,
                    StepStatus.ERROR,
                    "No matching product detail page was found.",
                )
                await emitter.completion(success=False, error="product_not_found")
                return ManualResult(type="not_found")

            manuals = await self._step_extract_manual(
                product_url=match.product_url,
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

        except (CrawlError, LLMServiceError, WorkflowError) as exc:
            _log.exception("workflow failed: %s", exc)
            await emitter.fail_active_step(str(exc))
            await emitter.log(f"Workflow failed: {exc}", level="error")
            await emitter.completion(success=False, error=str(exc))
            return ManualResult(type="not_found")
        except Exception as exc:  # last-resort safety net
            _log.exception("unexpected workflow failure: %s", exc)
            await emitter.fail_active_step(f"Unexpected error: {exc}")
            await emitter.log(f"Unexpected error: {exc}", level="error")
            await emitter.completion(success=False, error=f"unexpected: {exc}")
            return ManualResult(type="not_found")

    # ----------------------------------------------------------- STEP 1

    async def _step_crawl_homepage(
        self,
        url: str,
        emitter: Emitter,
    ) -> HomepageSnapshot:
        await emitter.progress(
            StepId.CRAWL_HOMEPAGE,
            StepStatus.RUNNING,
            f"Opening {url} and capturing rendered HTML",
        )
        snapshot = await self._crawl.snapshot_page(url)
        await emitter.progress(
            StepId.CRAWL_HOMEPAGE,
            StepStatus.SUCCESS,
            f"Captured homepage HTML ({len(snapshot.html):,} chars, {len(snapshot.links)} links)",
            data={
                "page_title": snapshot.page_title,
                "page_url": snapshot.page_url,
                "html_chars": len(snapshot.html),
                "link_count": len(snapshot.links),
                "links": snapshot.links,
            },
        )
        return snapshot

    # ----------------------------------------------------------- STEP 2

    async def _step_analyze_ui(self, snapshot: HomepageSnapshot, emitter: Emitter) -> UIAnalysis:
        await emitter.progress(StepId.ANALYZE_UI, StepStatus.RUNNING, "Sending homepage HTML to LLM for analysis")
        analysis = await self._llm.analyze_ui(
            page_url=snapshot.page_url,
            page_title=snapshot.page_title,
            html=snapshot.html,
        )
        if analysis.has_search_box:
            msg = (
                f"Found search box (input={analysis.search_input_selector!r}, "
                f"button={analysis.search_button_selector!r})"
            )
        elif analysis.search_page_url:
            msg = (
                f"No search box on homepage. Will use search page: {analysis.search_page_url}"
            )
        else:
            msg = "No search box and no search-page URL found"
        await emitter.progress(
            StepId.ANALYZE_UI,
            StepStatus.SUCCESS,
            msg,
            data={
                "analysis": analysis.model_dump(),
                "input_sent_summary": {
                    "page_title": snapshot.page_title,
                    "page_url": snapshot.page_url,
                    "html_chars": len(snapshot.html),
                    "link_count": len(snapshot.links),
                },
            },
        )
        return analysis

    # ----------------------------------------------------------- STEP 3

    async def _step_search_product(
        self,
        *,
        website_url: str,
        product_code: str,
        analysis: UIAnalysis,
        emitter: Emitter,
    ) -> CrawlResult:
        await emitter.progress(
            StepId.SEARCH_PRODUCT,
            StepStatus.RUNNING,
            "Performing product search",
        )

        if analysis.has_search_box and analysis.search_input_selector:
            await emitter.log(
                f"Typing '{product_code}' into {analysis.search_input_selector!r}",
                step=StepId.SEARCH_PRODUCT,
            )
            page = await self._crawl.search_via_selectors(
                url=website_url,
                input_selector=analysis.search_input_selector,
                button_selector=analysis.search_button_selector,
                query=product_code,
            )
        else:
            search_page_url = analysis.search_page_url
            if not search_page_url:
                raise WorkflowError(
                    "No search box on homepage and no search-page URL — cannot proceed."
                )

            await emitter.log(
                f"Opening search page {search_page_url} to perform the search there",
                step=StepId.SEARCH_PRODUCT,
            )
            search_page_snapshot = await self._crawl.snapshot_page(search_page_url)
            sub_analysis = await self._llm.analyze_ui(
                page_url=search_page_snapshot.page_url,
                page_title=search_page_snapshot.page_title,
                html=search_page_snapshot.html,
            )
            if not (sub_analysis.has_search_box and sub_analysis.search_input_selector):
                raise WorkflowError("Could not locate a search input on the search page.")
            page = await self._crawl.search_via_selectors(
                url=search_page_url,
                input_selector=sub_analysis.search_input_selector,
                button_selector=sub_analysis.search_button_selector,
                query=product_code,
            )

        await emitter.progress(
            StepId.SEARCH_PRODUCT,
            StepStatus.SUCCESS,
            f"Got search results page ({len(page.markdown):,} chars markdown, {len(page.all_links)} links)",
            data={
                "final_url": page.final_url,
                "status": page.status_code,
                "markdown_chars": len(page.markdown),
                "markdown": page.markdown,
                "link_counts": {
                    "internal": len(page.internal_links),
                    "external": len(page.external_links),
                },
                "links": page.all_links,
            },
        )
        return page

    # ----------------------------------------------------------- STEP 4

    async def _step_filter_results(
        self,
        *,
        search_page: CrawlResult,
        product_name: str,
        product_code: str,
        emitter: Emitter,
    ):
        await emitter.progress(
            StepId.FILTER_RESULTS,
            StepStatus.RUNNING,
            "Asking LLM to pick the most relevant product link from search results",
        )
        all_links = search_page.all_links
        await emitter.log(
            f"Sending full search-results markdown ({len(search_page.markdown):,} chars) "
            f"and {len(all_links)} link(s) to LLM",
            step=StepId.FILTER_RESULTS,
        )

        match = await self._llm.match_product(
            product_name=product_name,
            product_code=product_code,
            markdown=search_page.markdown,
            links=all_links,
        )
        status = StepStatus.SUCCESS if match.found else StepStatus.ERROR
        msg = (
            f"Picked: {match.product_url}"
            if match.found and match.product_url
            else "LLM could not identify a matching product."
        )
        await emitter.progress(
            StepId.FILTER_RESULTS,
            status,
            msg,
            data={
                "match": match.model_dump(),
                "total_links_seen": len(all_links),
                "markdown_chars": len(search_page.markdown),
            },
        )
        return match

    # ----------------------------------------------------------- STEP 5 (merged)

    async def _step_extract_manual(
        self,
        *,
        product_url: str,
        product_name: str,
        product_code: str,
        emitter: Emitter,
    ) -> list[ManualEntry]:
        """Single step that replaces open / expand / find.

        Runs Crawl4AI with an LLMExtractionStrategy against the product page;
        header/footer/nav are stripped server-side so the LLM only sees the
        product body. If the page only links to a dedicated support / manuals
        hub (final=false + follow_url), we re-crawl that URL with the same
        strategy. Hops are capped at ``MAX_MANUAL_EXTRACTION_HOPS`` to avoid
        loops. All manuals collected along the way are returned.
        """
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

            hops.append({
                "hop": hop_idx + 1,
                "url": current_url,
                "final_url": page.final_url,
                "markdown_chars": len(page.markdown),
                "link_count": len(page.all_links),
                "extraction": extraction.model_dump(),
                "extracted_raw": page.extracted_raw,
            })

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
            msg = (
                f"Found {len(collected)} manual(s); primary type={primary.type}"
            )
            status = StepStatus.SUCCESS
        else:
            msg = (
                f"No manual found after {len(hops)} hop(s)"
                + (f": {last_extraction.reason}" if last_extraction and last_extraction.reason else "")
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

    # ----------------------------------------------------------- STEP 6 (finalize)

    async def _step_finalize(
        self,
        manuals: list[ManualEntry],
        emitter: Emitter,
    ) -> ManualResult:
        await emitter.progress(StepId.FINALIZE, StepStatus.RUNNING, "Finalizing manual result")

        if not manuals:
            result = ManualResult(type="not_found")
            await emitter.progress(
                StepId.FINALIZE,
                StepStatus.ERROR,
                "No manual to finalize.",
                data=result.model_dump(),
            )
            return result

        # Single-manual: keep top-level fields filled (back-compat with UI).
        # Multi-manual: fill top-level from the first entry and put the rest
        # in ``manuals`` so the frontend can render all of them.
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
            f"Done ({len(manuals)} manual{'s' if len(manuals) != 1 else ''}, primary type={result.type})",
            data=result_dump,
        )
        return result


# ----------------------------------------------------------------------- helpers


def _parse_manual_extraction(page: ManualExtractionCrawlResult) -> ManualExtraction:
    """Crawl4AI returns extracted_content as a JSON-encoded string.

    With ``extraction_type='schema'`` and ``apply_chunking=False`` it is
    usually a single object — but historically the strategy wraps results in
    a list of per-chunk dicts. Tolerate both: peel a single-element list,
    pick the most-promising entry from a multi-element list, and merge stray
    duplicate ``index`` markers that litellm sometimes injects.
    """
    raw = (page.extracted_raw or "").strip()
    if not raw:
        return ManualExtraction(final=True, reason="empty extraction")

    try:
        payload = extract_json(raw)
    except JsonParseError:
        return ManualExtraction(final=True, reason="invalid extraction JSON")

    if isinstance(payload, list):
        # Pick the entry that actually has manuals; otherwise pick one with a
        # follow_url; otherwise take the first.
        with_manuals = [p for p in payload if isinstance(p, dict) and p.get("manuals")]
        with_follow = [p for p in payload if isinstance(p, dict) and p.get("follow_url")]
        payload = (with_manuals or with_follow or payload)[0] if payload else {}

    if not isinstance(payload, dict):
        return ManualExtraction(final=True, reason="extraction was not an object")

    # Strip litellm's per-chunk meta keys so they don't fail validation.
    payload.pop("index", None)
    payload.pop("error", None)

    try:
        return ManualExtraction.model_validate(payload)
    except ValidationError as exc:
        _log.warning("ManualExtraction validation failed: %s; payload=%s", exc, json.dumps(payload)[:500])
        return ManualExtraction(final=True, reason=f"validation error: {exc.errors()[0].get('msg', exc)}")


def _dedup_key(entry: ManualEntry) -> str:
    return f"{entry.type}|{(entry.url or '').strip().lower()}|{(entry.label or '').strip().lower()}"


# ----------------------------------------------------------------------- factory

_orchestrator: WorkflowOrchestrator | None = None


def get_orchestrator() -> WorkflowOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = WorkflowOrchestrator(get_crawl_service(), get_llm_service())
    return _orchestrator

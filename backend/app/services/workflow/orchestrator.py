"""End-to-end workflow: homepage → search → product page → manual.

The orchestrator emits one ProgressEvent per workflow step transition and
streams LogEvents in between. Each step is its own private method so the
control flow stays readable. All recoverable failures are caught and
reported via the emitter — exceptions only bubble for truly unexpected bugs.
"""
from __future__ import annotations

from urllib.parse import urljoin

from app.core.constants import StepId, StepStatus
from app.core.logging import get_logger
from app.events.emitter import Emitter
from app.schemas.llm import ManualLocator, ProductMatch, UIAnalysis
from app.schemas.responses import ManualResult
from app.services.crawl import CrawlService, get_crawl_service
from app.services.crawl.service import CrawlError, CrawlResult, UIExtraction
from app.services.llm import LLMService, get_llm_service
from app.services.llm.service import LLMServiceError
from app.services.workflow.result_filter import filter_search_links

_log = get_logger(__name__)

# Used by the heuristic fallback when the LLM finds no support URL.
_SUPPORT_KEYWORDS = (
    "support",
    "manual",
    "manuals",
    "download",
    "downloads",
    "product",
    "products",
    "consumer",
    "appliance",
    "appliances",
    "home-appliances",
    "find",
    "search",
    "where to buy",
    "tài liệu",
    "hỗ trợ",
    "sản phẩm",
    "tìm",
)


def _pick_heuristic_support_url(
    nav_links: list[dict],
    homepage_url: str,
) -> str | None:
    """Find a likely support/product page from nav_links by keyword match.

    Scores each link by how many keywords appear in its href + text, prefers
    same-host links, and returns the highest-scoring URL (or None if nothing
    matches at all).
    """
    from urllib.parse import urlparse

    home_host = urlparse(homepage_url).netloc.lower()
    best: tuple[int, str] | None = None
    for link in nav_links:
        href = (link.get("href") or "").strip()
        text = (link.get("text") or "").strip().lower()
        if not href:
            continue
        href_l = href.lower()
        hay = f"{href_l} {text}"
        score = sum(1 for kw in _SUPPORT_KEYWORDS if kw in hay)
        if score == 0:
            continue
        # Prefer same-host links.
        try:
            if urlparse(href).netloc.lower() == home_host:
                score += 1
        except ValueError:
            pass
        full = urljoin(homepage_url, href)
        if best is None or score > best[0]:
            best = (score, full)
    return best[1] if best else None


class WorkflowError(RuntimeError):
    pass


class WorkflowOrchestrator:
    def __init__(self, crawl: CrawlService, llm: LLMService) -> None:
        self._crawl = crawl
        self._llm = llm

    async def run(
        self,
        *,
        website_url: str,
        product_name: str,
        product_code: str,
        emitter: Emitter,
    ) -> ManualResult:
        try:
            ui = await self._step_crawl_homepage(website_url, emitter)
            analysis = await self._step_analyze_ui(ui, emitter)
            # Retry pass: if the initial extraction yielded neither a usable
            # search box nor a support URL, re-crawl with aggressive triggers
            # (more clicks on aria-haspopup buttons, icon-only buttons, multi-
            # pass scroll) and re-analyze before giving up.
            if not analysis.has_search_box and not analysis.support_url:
                await emitter.log(
                    "Initial homepage analysis found no search and no support URL — "
                    "retrying with aggressive trigger clicks.",
                    level="warning",
                )
                ui = await self._step_crawl_homepage(website_url, emitter, aggressive=True)
                analysis = await self._step_analyze_ui(ui, emitter)
            search_page = await self._step_search_product(
                website_url=website_url,
                product_code=product_code,
                analysis=analysis,
                homepage_ui=ui,
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

            product_page = await self._step_open_product(match.product_url, emitter)
            product_page = await self._step_expand_sections(product_page, emitter)
            locator = await self._step_find_manual(
                product_name=product_name,
                product_code=product_code,
                product_page=product_page,
                emitter=emitter,
            )
            result = await self._step_finalize(locator, emitter)
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
        aggressive: bool = False,
    ) -> UIExtraction:
        mode = "aggressive" if aggressive else "standard"
        await emitter.progress(
            StepId.CRAWL_HOMEPAGE,
            StepStatus.RUNNING,
            f"Opening {url} ({mode} extraction)",
        )
        ui = await self._crawl.extract_ui(url, aggressive=aggressive)
        await emitter.progress(
            StepId.CRAWL_HOMEPAGE,
            StepStatus.SUCCESS,
            f"Extracted UI ({mode}): {len(ui.inputs)} inputs, {len(ui.buttons)} buttons, {len(ui.nav_links)} nav links",
            data={
                "page_title": ui.page_title,
                "page_url": ui.page_url,
                "counts": {
                    "inputs": len(ui.inputs),
                    "buttons": len(ui.buttons),
                    "forms": len(ui.forms),
                    "nav_links": len(ui.nav_links),
                },
                "inputs": ui.inputs,
                "buttons": ui.buttons,
                "forms": ui.forms,
                "nav_links": ui.nav_links,
            },
        )
        return ui

    # ----------------------------------------------------------- STEP 2

    async def _step_analyze_ui(self, ui: UIExtraction, emitter: Emitter) -> UIAnalysis:
        await emitter.progress(StepId.ANALYZE_UI, StepStatus.RUNNING, "Sending UI to LLM for analysis")
        analysis = await self._llm.analyze_ui(ui.to_dict())
        if analysis.has_search_box:
            msg = (
                f"Found search box (input={analysis.search_input_selector!r}, "
                f"button={analysis.search_button_selector!r})"
            )
        elif analysis.support_url:
            msg = f"No search box on homepage. Will use support URL: {analysis.support_url}"
        else:
            msg = "No search box and no support URL found"
        await emitter.progress(
            StepId.ANALYZE_UI,
            StepStatus.SUCCESS,
            msg,
            data={
                "analysis": analysis.model_dump(),
                "input_sent_summary": {
                    "page_title": ui.page_title,
                    "inputs": len(ui.inputs),
                    "buttons": len(ui.buttons),
                    "nav_links": len(ui.nav_links),
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
        homepage_ui: UIExtraction,
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
            support_url = analysis.support_url
            if not support_url:
                # LLM couldn't pick one — fall back to keyword scoring on nav links.
                support_url = _pick_heuristic_support_url(homepage_ui.nav_links, website_url)
                if support_url:
                    await emitter.log(
                        f"LLM returned no support URL; heuristic picked {support_url}",
                        level="warning",
                        step=StepId.SEARCH_PRODUCT,
                    )

            if not support_url:
                raise WorkflowError("No search box and no support URL — cannot proceed.")

            await emitter.log(
                f"Opening support page {support_url} to find search there",
                step=StepId.SEARCH_PRODUCT,
            )
            support_ui = await self._crawl.extract_ui(support_url)
            sub_analysis = await self._llm.analyze_ui(support_ui.to_dict())
            if not (sub_analysis.has_search_box and sub_analysis.search_input_selector):
                raise WorkflowError("Could not locate a search input on the support page.")
            page = await self._crawl.search_via_selectors(
                url=support_url,
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
    ) -> ProductMatch:
        await emitter.progress(StepId.FILTER_RESULTS, StepStatus.RUNNING, "Filtering search results")
        candidates = filter_search_links(search_page.all_links, product_code=product_code)
        await emitter.log(
            f"{len(candidates)} candidate link(s) after heuristic filtering",
            step=StepId.FILTER_RESULTS,
        )
        if not candidates:
            await emitter.progress(
                StepId.FILTER_RESULTS,
                StepStatus.ERROR,
                "No plausible product links found in results.",
            )
            return ProductMatch(found=False)

        match = await self._llm.match_product(product_name, product_code, candidates)
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
                "candidates": candidates,
                "total_links_seen": len(search_page.all_links),
            },
        )
        return match

    # ----------------------------------------------------------- STEP 5

    async def _step_open_product(self, url: str, emitter: Emitter) -> CrawlResult:
        await emitter.progress(StepId.OPEN_PRODUCT_PAGE, StepStatus.RUNNING, f"Opening {url}")
        page = await self._crawl.crawl(url, expand_sections=False)
        await emitter.progress(
            StepId.OPEN_PRODUCT_PAGE,
            StepStatus.SUCCESS,
            f"Loaded product page ({len(page.markdown):,} chars)",
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

    async def _step_expand_sections(self, page: CrawlResult, emitter: Emitter) -> CrawlResult:
        before_chars = len(page.markdown)
        await emitter.progress(
            StepId.EXPAND_SECTIONS,
            StepStatus.RUNNING,
            "Expanding tabs / accordions / support sections",
        )
        expanded = await self._crawl.crawl(page.final_url or page.url, expand_sections=True)
        await emitter.progress(
            StepId.EXPAND_SECTIONS,
            StepStatus.SUCCESS,
            f"Re-crawled with sections expanded ({len(expanded.markdown):,} chars)",
            data={
                "chars_before": before_chars,
                "chars_after": len(expanded.markdown),
                "delta_chars": len(expanded.markdown) - before_chars,
                "markdown": expanded.markdown,
                "link_counts": {
                    "internal": len(expanded.internal_links),
                    "external": len(expanded.external_links),
                },
                "links": expanded.all_links,
            },
        )
        return expanded

    # ----------------------------------------------------------- STEP 6

    async def _step_find_manual(
        self,
        *,
        product_name: str,
        product_code: str,
        product_page: CrawlResult,
        emitter: Emitter,
    ) -> ManualLocator:
        await emitter.progress(StepId.FIND_MANUAL, StepStatus.RUNNING, "Asking LLM to locate the manual")
        locator = await self._llm.find_manual(
            product_name=product_name,
            product_code=product_code,
            markdown=product_page.markdown,
            links=product_page.all_links,
        )
        if locator.type == "not_found":
            await emitter.progress(
                StepId.FIND_MANUAL,
                StepStatus.ERROR,
                "No manual found on product page.",
                data={
                    "locator": locator.model_dump(),
                    "links_seen": len(product_page.all_links),
                    "markdown_chars": len(product_page.markdown),
                    "product_markdown": product_page.markdown,
                    "product_links": product_page.all_links,
                },
            )
        else:
            await emitter.progress(
                StepId.FIND_MANUAL,
                StepStatus.SUCCESS,
                f"Manual located as type={locator.type}",
                data={
                    "locator": locator.model_dump(),
                    "links_seen": len(product_page.all_links),
                    "markdown_chars": len(product_page.markdown),
                    "product_markdown": product_page.markdown,
                    "product_links": product_page.all_links,
                },
            )
        return locator

    # ----------------------------------------------------------- STEP 7

    async def _step_finalize(self, locator: ManualLocator, emitter: Emitter) -> ManualResult:
        await emitter.progress(StepId.FINALIZE, StepStatus.RUNNING, "Finalizing manual result")

        if locator.type == "link" and locator.url:
            result = ManualResult(type="link", url=locator.url)
        elif locator.type == "html_url" and locator.url:
            await emitter.log(f"Crawling manual HTML page {locator.url}", step=StepId.FINALIZE)
            page = await self._crawl.crawl(locator.url, expand_sections=False)
            result = ManualResult(type="html_url", url=locator.url, content=page.markdown)
        elif locator.type == "inline" and locator.content:
            result = ManualResult(type="inline", content=locator.content)
        else:
            result = ManualResult(type="not_found")

        status = StepStatus.ERROR if result.type == "not_found" else StepStatus.SUCCESS
        result_dump = result.model_dump()
        if result_dump.get("content"):
            result_dump["content_chars"] = len(result_dump["content"])
        await emitter.progress(StepId.FINALIZE, status, f"Done (type={result.type})", data=result_dump)
        return result


# ----------------------------------------------------------------------- factory

_orchestrator: WorkflowOrchestrator | None = None


def get_orchestrator() -> WorkflowOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = WorkflowOrchestrator(get_crawl_service(), get_llm_service())
    return _orchestrator

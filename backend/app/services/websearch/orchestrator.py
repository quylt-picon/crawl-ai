"""Web-search workflow: grounded LLM search → review findings → finalize.

Mirrors the event/streaming contract of the crawl orchestrator (so it plugs
into the same job registry, event bus, and SSE endpoints) but runs the
LLM-web-search pipeline instead.

The actual web search is a single grounded LLM call, but the workflow is
broken into three readable phases so the frontend timeline can show, in
detail, *what was found at each step*:

  1. WEB_SEARCH     — run the grounded call; log every search query issued.
  2. REVIEW_RESULTS — log every web source consulted and every document found
                      (label, type, language, URL / inline size).
  3. FINALIZE       — pick the primary document and report the totals.
"""
from __future__ import annotations

from app.core.constants import StepId, StepStatus
from app.core.logging import get_logger
from app.events.emitter import Emitter
from app.schemas.llm import ManualEntry
from app.schemas.responses import ManualResult
from app.services.websearch.service import (
    ManualSearchResult,
    SerpSearch,
    WebSearchError,
    WebSearchService,
    get_web_search_service,
)

_log = get_logger(__name__)

# Cap how many sources/documents we spell out line-by-line so a noisy search
# can't flood the timeline; the structured ``data`` payload still carries them
# all for the frontend panels.
_MAX_DETAIL_LINES = 30


class WebSearchOrchestrator:
    def __init__(self, web_search: WebSearchService) -> None:
        self._web_search = web_search

    async def run(
        self,
        *,
        website_url: str | None,
        product_name: str,
        product_code: str,
        emitter: Emitter,
        model: str | None = None,
        use_serpapi: bool = False,
    ) -> ManualResult:
        try:
            if use_serpapi:
                serp = await self._step_serpapi_search(
                    website_url=website_url,
                    product_name=product_name,
                    product_code=product_code,
                    emitter=emitter,
                )
                search = await self._step_serpapi_filter(
                    serp,
                    website_url=website_url,
                    product_name=product_name,
                    product_code=product_code,
                    model=model,
                    emitter=emitter,
                )
            else:
                search = await self._step_web_search(
                    website_url=website_url,
                    product_name=product_name,
                    product_code=product_code,
                    emitter=emitter,
                    model=model,
                )
                await self._step_review_results(search, emitter)
            result = await self._step_finalize(search, emitter)
            await emitter.completion(
                success=result.type != "not_found",
                manual_type=result.type,
                manual_url=result.url,
                has_content=bool(result.content),
            )
            return result
        except WebSearchError as exc:
            _log.exception("web-search workflow failed: %s", exc)
            await emitter.fail_active_step(str(exc))
            await emitter.log(f"Web-search failed: {exc}", level="error")
            await emitter.completion(success=False, error=str(exc))
            return ManualResult(type="not_found")
        except Exception as exc:  # last-resort safety net
            _log.exception("unexpected web-search failure: %s", exc)
            await emitter.fail_active_step(f"Unexpected error: {exc}")
            await emitter.log(f"Unexpected error: {exc}", level="error")
            await emitter.completion(success=False, error=f"unexpected: {exc}")
            return ManualResult(type="not_found")

    # ----------------------------------------------------------- STEP 1: search

    async def _step_web_search(
        self,
        *,
        website_url: str | None,
        product_name: str,
        product_code: str,
        emitter: Emitter,
        model: str | None = None,
    ) -> ManualSearchResult:
        used_model = model or self._web_search.default_model
        await emitter.progress(
            StepId.WEB_SEARCH,
            StepStatus.RUNNING,
            f"Asking the LLM to web-search documentation for '{product_name}' ({product_code})",
        )
        await emitter.log(
            f"Model: {used_model} · preferred site: {website_url or '(none — open web search)'} · "
            f"target: {product_name} / {product_code}",
            step=StepId.WEB_SEARCH,
        )

        search = await self._web_search.find_manuals(
            website_url=website_url,
            product_name=product_name,
            product_code=product_code,
            model=model,
        )

        # Detail: every query the grounded model actually ran.
        if search.queries:
            await emitter.log(
                f"Model ran {_n_queries(len(search.queries))}:",
                step=StepId.WEB_SEARCH,
            )
            for q in search.queries[:_MAX_DETAIL_LINES]:
                await emitter.log(f"  • {q}", step=StepId.WEB_SEARCH)
        else:
            await emitter.log(
                "Model reported no explicit search queries.",
                step=StepId.WEB_SEARCH,
                level="warning",
            )

        await emitter.progress(
            StepId.WEB_SEARCH,
            StepStatus.SUCCESS,
            f"Search complete — {_n_queries(len(search.queries))} run, "
            f"{len(search.sources)} source(s) consulted",
            data={
                "query_count": len(search.queries),
                "queries": search.queries,
                "source_count": len(search.sources),
                "sources": search.sources,
            },
        )
        return search

    # ----------------------------------------------------------- STEP 2: review

    async def _step_review_results(
        self,
        search: ManualSearchResult,
        emitter: Emitter,
    ) -> None:
        await emitter.progress(
            StepId.REVIEW_RESULTS,
            StepStatus.RUNNING,
            "Reviewing the web sources and documents the search returned",
        )

        # Detail: every web source the model cited.
        if search.sources:
            await emitter.log(
                f"Consulted {len(search.sources)} web source(s):",
                step=StepId.REVIEW_RESULTS,
            )
            for i, s in enumerate(search.sources[:_MAX_DETAIL_LINES], start=1):
                await emitter.log(f"  {_fmt_source(i, s)}", step=StepId.REVIEW_RESULTS)
            if len(search.sources) > _MAX_DETAIL_LINES:
                await emitter.log(
                    f"  … (+{len(search.sources) - _MAX_DETAIL_LINES} more)",
                    step=StepId.REVIEW_RESULTS,
                )
        else:
            await emitter.log(
                "No web sources were cited by the model.",
                step=StepId.REVIEW_RESULTS,
                level="warning",
            )

        # Detail: every document the model extracted.
        if search.manuals:
            await emitter.log(
                f"Found {len(search.manuals)} document(s):",
                step=StepId.REVIEW_RESULTS,
            )
            for i, m in enumerate(search.manuals[:_MAX_DETAIL_LINES], start=1):
                await emitter.log(f"  {_fmt_manual(i, m)}", step=StepId.REVIEW_RESULTS)

        if search.found:
            msg = f"Collected {len(search.manuals)} document(s)" + (
                f" — {search.summary}" if search.summary else ""
            )
            status = StepStatus.SUCCESS
        else:
            msg = "No documentation found" + (f": {search.reason}" if search.reason else "")
            status = StepStatus.ERROR
            await emitter.log(
                msg,
                step=StepId.REVIEW_RESULTS,
                level="warning",
            )

        await emitter.progress(
            StepId.REVIEW_RESULTS,
            status,
            msg,
            data={
                "found": search.found,
                "summary": search.summary,
                "reason": search.reason,
                "manuals": [m.model_dump() for m in search.manuals],
                "manual_count": len(search.manuals),
                "sources": search.sources,
                "queries": search.queries,
            },
        )

    # ------------------------------------------------ STEP 1-B: SerpAPI search

    async def _step_serpapi_search(
        self,
        *,
        website_url: str | None,
        product_name: str,
        product_code: str,
        emitter: Emitter,
    ) -> SerpSearch:
        await emitter.progress(
            StepId.WEB_SEARCH,
            StepStatus.RUNNING,
            f"Querying SerpAPI (Google) for documentation of '{product_name}' ({product_code})",
        )
        serp = await self._web_search.serpapi_search(
            website_url=website_url,
            product_name=product_name,
            product_code=product_code,
        )

        # Detail: the exact queries sent to SerpAPI.
        await emitter.log(
            f"SerpAPI ran {_n_queries(len(serp.queries))}:",
            step=StepId.WEB_SEARCH,
        )
        for q in serp.queries:
            await emitter.log(f"  • {q}", step=StepId.WEB_SEARCH)

        # Detail: the organic results SerpAPI returned.
        sources = [r.to_source() for r in serp.results]
        if sources:
            await emitter.log(
                f"SerpAPI returned {len(sources)} organic result(s):",
                step=StepId.WEB_SEARCH,
            )
            for i, s in enumerate(sources[:_MAX_DETAIL_LINES], start=1):
                await emitter.log(f"  {_fmt_source(i, s)}", step=StepId.WEB_SEARCH)
            if len(sources) > _MAX_DETAIL_LINES:
                await emitter.log(
                    f"  … (+{len(sources) - _MAX_DETAIL_LINES} more)",
                    step=StepId.WEB_SEARCH,
                )
        else:
            await emitter.log(
                "SerpAPI returned no organic results.",
                step=StepId.WEB_SEARCH,
                level="warning",
            )

        await emitter.progress(
            StepId.WEB_SEARCH,
            StepStatus.SUCCESS,
            f"SerpAPI search complete — {_n_queries(len(serp.queries))} run, "
            f"{len(sources)} result(s)",
            data={
                "query_count": len(serp.queries),
                "queries": serp.queries,
                "source_count": len(sources),
                "sources": sources,
            },
        )
        return serp

    # ------------------------------------------------ STEP 2-B: LLM filter/extract

    async def _step_serpapi_filter(
        self,
        serp: SerpSearch,
        *,
        website_url: str | None,
        product_name: str,
        product_code: str,
        model: str | None,
        emitter: Emitter,
    ) -> ManualSearchResult:
        await emitter.progress(
            StepId.REVIEW_RESULTS,
            StepStatus.RUNNING,
            "Filtering the SerpAPI results with the LLM and extracting manual links",
        )
        search = await self._web_search.filter_serp_results(
            website_url=website_url,
            product_name=product_name,
            product_code=product_code,
            serp=serp,
            model=model,
        )

        # Detail: every document the LLM kept as relevant.
        if search.manuals:
            await emitter.log(
                f"LLM kept {len(search.manuals)} relevant document(s):",
                step=StepId.REVIEW_RESULTS,
            )
            for i, m in enumerate(search.manuals[:_MAX_DETAIL_LINES], start=1):
                await emitter.log(f"  {_fmt_manual(i, m)}", step=StepId.REVIEW_RESULTS)

        if search.found:
            msg = f"Filtered to {len(search.manuals)} document(s)" + (
                f" — {search.summary}" if search.summary else ""
            )
            status = StepStatus.SUCCESS
        else:
            msg = "No relevant documentation in the search results" + (
                f": {search.reason}" if search.reason else ""
            )
            status = StepStatus.ERROR
            await emitter.log(msg, step=StepId.REVIEW_RESULTS, level="warning")

        await emitter.progress(
            StepId.REVIEW_RESULTS,
            status,
            msg,
            data={
                "found": search.found,
                "summary": search.summary,
                "reason": search.reason,
                "manuals": [m.model_dump() for m in search.manuals],
                "manual_count": len(search.manuals),
                "sources": search.sources,
                "queries": search.queries,
            },
        )
        return search

    # ----------------------------------------------------------- STEP 3: finalize

    async def _step_finalize(
        self,
        search: ManualSearchResult,
        emitter: Emitter,
    ) -> ManualResult:
        await emitter.progress(StepId.FINALIZE, StepStatus.RUNNING, "Finalizing manual result")
        result = search.to_manual_result()

        if result.type == "not_found":
            await emitter.progress(
                StepId.FINALIZE,
                StepStatus.ERROR,
                "No manual to finalize.",
                data=result.model_dump(),
            )
            return result

        primary = result.manuals[0]
        await emitter.log(
            f"Primary document selected: {_fmt_manual(1, primary)}",
            step=StepId.FINALIZE,
        )

        result_dump = result.model_dump()
        if result_dump.get("content"):
            result_dump["content_chars"] = len(result_dump["content"])
        result_dump["sources"] = search.sources
        await emitter.progress(
            StepId.FINALIZE,
            StepStatus.SUCCESS,
            f"Done — {len(result.manuals)} document"
            f"{'s' if len(result.manuals) != 1 else ''}, primary type={result.type}",
            data=result_dump,
        )
        return result


# ----------------------------------------------------------------------- helpers


def _n_queries(n: int) -> str:
    return f"{n} query" if n == 1 else f"{n} queries"


def _fmt_source(i: int, s: dict[str, str]) -> str:
    """One-line description of a cited web source."""
    domain = (s.get("domain") or "").strip()
    title = (s.get("title") or "").strip()
    uri = (s.get("uri") or "").strip()
    head = domain or title or uri or "(unknown source)"
    title_suffix = f" — {title}" if title and title != head else ""
    uri_suffix = f" — {uri}" if uri else ""
    return f"[{i}] {head}{title_suffix}{uri_suffix}"


def _fmt_manual(i: int, m: ManualEntry) -> str:
    """One-line description of a found document."""
    meta = [f"type={m.type}"]
    if m.language:
        meta.append(f"lang={m.language}")
    label = (m.label or "").strip() or "(untitled)"
    if m.type == "inline":
        where = f"{len(m.content or '')} chars inline"
    else:
        where = (m.url or "").strip() or "(no url)"
    return f"[{i}] {label} ({', '.join(meta)}) → {where}"


# ----------------------------------------------------------------------- factory

_orchestrator: WebSearchOrchestrator | None = None


def get_web_search_orchestrator() -> WebSearchOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = WebSearchOrchestrator(get_web_search_service())
    return _orchestrator

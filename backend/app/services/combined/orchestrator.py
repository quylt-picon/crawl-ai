"""Combined workflow: web-search the official brand site, then crawl it.

This bridges the two existing pipelines:

  1. FIND_SITE       — a grounded web search (Google, via the LLM) locates the
                       product's OFFICIAL manufacturer / brand homepage. The
                       *search prompt* comes from the UI; the backend keeps no
                       task prompt of its own (only the JSON output contract).
  2. CRAWL_HOMEPAGE … FINALIZE
                     — the discovered homepage URL is handed to the existing
                       crawl :class:`WorkflowOrchestrator`, which drives the
                       browser to find the product's manual and emits its own
                       per-step progress and the final completion event.

It shares the job registry, event bus, and SSE contract with the other
pipelines, so the frontend streams its progress the same way.
"""
from __future__ import annotations

from app.core.constants import StepId, StepStatus
from app.core.logging import get_logger
from app.events.emitter import Emitter
from app.schemas.llm import OfficialSite
from app.schemas.responses import ManualResult
from app.services.websearch import (
    OfficialSiteResult,
    WebSearchError,
    WebSearchService,
    get_web_search_service,
)
from app.services.workflow import WorkflowOrchestrator, get_orchestrator

_log = get_logger(__name__)

# Cap how many sources/queries we spell out line-by-line in the timeline; the
# structured ``data`` payload still carries them all for the frontend panels.
_MAX_DETAIL_LINES = 30


class WebSearchCrawlOrchestrator:
    def __init__(
        self,
        web_search: WebSearchService,
        crawl_workflow: WorkflowOrchestrator,
    ) -> None:
        self._web_search = web_search
        self._workflow = crawl_workflow

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
            site = await self._step_find_site(
                product_name=product_name,
                product_code=product_code,
                search_prompt=search_prompt,
                model=model,
                emitter=emitter,
            )
            if not site.found or not site.url:
                # No site to crawl — close out the job ourselves; the crawl
                # workflow (which would otherwise emit completion) never runs.
                await emitter.completion(
                    success=False, error="official_site_not_found"
                )
                return ManualResult(type="not_found")

            # Hand the discovered homepage to the existing crawl pipeline. It
            # emits its own step progress AND the terminal completion event.
            return await self._workflow.run(
                website_url=site.url,
                product_name=product_name,
                product_code=product_code,
                emitter=emitter,
            )
        except WebSearchError as exc:
            _log.exception("combined workflow (site search) failed: %s", exc)
            await emitter.fail_active_step(str(exc))
            await emitter.log(f"Site search failed: {exc}", level="error")
            await emitter.completion(success=False, error=str(exc))
            return ManualResult(type="not_found")
        except Exception as exc:  # last-resort safety net
            _log.exception("unexpected combined workflow failure: %s", exc)
            await emitter.fail_active_step(f"Unexpected error: {exc}")
            await emitter.log(f"Unexpected error: {exc}", level="error")
            await emitter.completion(success=False, error=f"unexpected: {exc}")
            return ManualResult(type="not_found")

    # ----------------------------------------------------- STEP 1: find the site

    async def _step_find_site(
        self,
        *,
        product_name: str,
        product_code: str,
        search_prompt: str,
        model: str | None,
        emitter: Emitter,
    ) -> OfficialSite:
        used_model = model or self._web_search.default_model
        await emitter.progress(
            StepId.FIND_SITE,
            StepStatus.RUNNING,
            f"Web-searching for the official site of '{product_name}' ({product_code})",
        )

        prompt = _render_prompt(search_prompt, product_name, product_code)
        await emitter.log(
            f"Model: {used_model} · target: {product_name} / {product_code}",
            step=StepId.FIND_SITE,
        )
        # Echo the exact prompt used (it came from the UI) so the run is
        # reproducible and the operator can see what drove the search.
        await emitter.log(f"Prompt used:\n{prompt}", step=StepId.FIND_SITE)

        result: OfficialSiteResult = await self._web_search.find_official_site(
            prompt=prompt, model=model
        )
        site = result.site

        if result.queries:
            await emitter.log(
                f"Model ran {_n_queries(len(result.queries))}:", step=StepId.FIND_SITE
            )
            for q in result.queries[:_MAX_DETAIL_LINES]:
                await emitter.log(f"  • {q}", step=StepId.FIND_SITE)
        if result.sources:
            await emitter.log(
                f"Consulted {len(result.sources)} web source(s):",
                step=StepId.FIND_SITE,
            )
            for i, s in enumerate(result.sources[:_MAX_DETAIL_LINES], start=1):
                await emitter.log(f"  {_fmt_source(i, s)}", step=StepId.FIND_SITE)

        data = {
            "site": site.model_dump(),
            "sources": result.sources,
            "queries": result.queries,
        }
        if site.found and site.url:
            brand = f" ({site.brand})" if site.brand else ""
            await emitter.progress(
                StepId.FIND_SITE,
                StepStatus.SUCCESS,
                f"Official site{brand}: {site.url}",
                data=data,
            )
        else:
            await emitter.progress(
                StepId.FIND_SITE,
                StepStatus.ERROR,
                "No official site found"
                + (f": {site.reason}" if site.reason else ""),
                data=data,
            )
        return site


# ----------------------------------------------------------------------- helpers


def _render_prompt(prompt: str, product_name: str, product_code: str) -> str:
    """Substitute the ``{product_name}`` / ``{product_code}`` placeholders.

    A plain ``str.replace`` (not ``str.format``) is used so stray braces or
    JSON examples in the UI-supplied prompt can't raise. Prompts without the
    placeholders pass through unchanged (the operator embedded the values
    themselves).
    """
    return (
        prompt.replace("{product_name}", product_name)
        .replace("{product_code}", product_code)
    )


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


# ----------------------------------------------------------------------- factory

_orchestrator: WebSearchCrawlOrchestrator | None = None


def get_web_search_crawl_orchestrator() -> WebSearchCrawlOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = WebSearchCrawlOrchestrator(
            get_web_search_service(),
            get_orchestrator(),
        )
    return _orchestrator

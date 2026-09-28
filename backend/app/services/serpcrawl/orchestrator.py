"""SerpAPI workflow: LLM generates queries → SerpAPI → LLM evaluates → 3-hop crawl.

A *standalone* pipeline, intentionally independent of the other orchestrators
so it can be tuned without affecting the running services. The LLM is used in
two places, both driven by UI-supplied instructions:

  1. GENERATE_QUERIES — an LLM turns the product (name + model code) into a set
                        of Google search queries, following the operator's
                        ``query_prompt`` (language, keywords, …).
  2. WEB_SEARCH       — SerpAPI runs those queries and returns organic results.
  3. REVIEW_RESULTS   — an LLM evaluates/selects the results against the
                        operator's ``eval_rule``, producing the candidate pages.
  4. FIND_MANUAL      — each selected candidate is crawled and run through the
                        LLM manual-extraction strategy; if the manual lives on a
                        linked support/downloads hub it follows that link and
                        extracts again (up to 3 hops per candidate). This yields
                        the FINAL manual document links.
  5. FINALIZE         — pick the primary document and report the totals.

It reuses only stateless infrastructure (the Gemini provider for plain JSON
generation, the SerpAPI client, and the crawl service); it does NOT import or
modify the websearch / deepcrawl / combined orchestrators.
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

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
from app.schemas.llm import ManualEntry, ManualExtraction, SerpQueries, WebSearchManuals
from app.schemas.responses import ManualResult
from app.services.crawl import CrawlService, get_crawl_service
from app.services.crawl.service import CrawlError, ManualExtractionCrawlResult
from app.services.llm.prompts import MANUAL_EXTRACTION_INSTRUCTION_TEMPLATE
from app.services.serpcrawl.prompts import (
    SERP_EVAL_SYSTEM,
    SERP_EVAL_TEMPLATE,
    SERP_QUERY_SYSTEM,
)
from app.services.websearch.provider import GeminiWebSearchProvider
from app.services.websearch.serpapi import SerpApiClient, SerpApiError, SerpResult
from app.utils.json_parse import JsonParseError, extract_json

_log = get_logger(__name__)

# Cap how many generated queries we actually issue (SerpAPI cost control), how
# many selected candidates we crawl, how many hops per candidate, and how many
# detail lines we spell out in the timeline.
_MAX_QUERIES = 5
_MAX_CANDIDATES = 5
MAX_MANUAL_EXTRACTION_HOPS = 3
_MAX_DETAIL_LINES = 30

# File extensions that mark an already-final document — no point crawling these
# as if they were HTML pages; keep them as-is.
_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")


class SerpCrawlError(RuntimeError):
    pass


class SerpCrawlOrchestrator:
    def __init__(
        self,
        provider: GeminiWebSearchProvider,
        serpapi: SerpApiClient | None,
        crawl: CrawlService,
        *,
        llm_provider: str,
        llm_api_token: str,
        max_retries: int = 3,
        max_queries: int = _MAX_QUERIES,
        max_candidates: int = _MAX_CANDIDATES,
    ) -> None:
        self._provider = provider
        self._serpapi = serpapi
        self._crawl = crawl
        self._llm_provider = llm_provider
        self._llm_api_token = llm_api_token
        self._max_retries = max_retries
        self._max_queries = max_queries
        self._max_candidates = max_candidates

    @property
    def default_model(self) -> str:
        return self._provider.default_model

    async def run(
        self,
        *,
        product_name: str,
        product_code: str,
        query_prompt: str,
        eval_rule: str,
        emitter: Emitter,
        model: str | None = None,
    ) -> ManualResult:
        if self._serpapi is None:
            await emitter.fail_active_step("SerpAPI is not configured (set SERPAPI_API_KEY).")
            await emitter.completion(success=False, error="serpapi_not_configured")
            return ManualResult(type="not_found")

        try:
            queries = await self._step_generate_queries(
                product_name=product_name,
                product_code=product_code,
                query_prompt=query_prompt,
                model=model,
                emitter=emitter,
            )
            if not queries:
                await emitter.completion(success=False, error="no_queries_generated")
                return ManualResult(type="not_found")

            results = await self._step_serpapi_search(queries, emitter=emitter)

            search = await self._step_evaluate(
                results,
                queries=queries,
                product_name=product_name,
                product_code=product_code,
                eval_rule=eval_rule,
                model=model,
                emitter=emitter,
            )

            manuals = await self._step_extract_manuals(
                search.manuals,
                product_name=product_name,
                product_code=product_code,
                emitter=emitter,
            )
            result = await self._step_finalize(manuals, results, emitter)
            await emitter.completion(
                success=result.type != "not_found",
                manual_type=result.type,
                manual_url=result.url,
                has_content=bool(result.content),
            )
            return result
        except (SerpCrawlError, CrawlError) as exc:
            _log.exception("serp-crawl workflow failed: %s", exc)
            await emitter.fail_active_step(str(exc))
            await emitter.log(f"SerpAPI pipeline failed: {exc}", level="error")
            await emitter.completion(success=False, error=str(exc))
            return ManualResult(type="not_found")
        except Exception as exc:  # last-resort safety net
            _log.exception("unexpected serp-crawl failure: %s", exc)
            await emitter.fail_active_step(f"Unexpected error: {exc}")
            await emitter.log(f"Unexpected error: {exc}", level="error")
            await emitter.completion(success=False, error=f"unexpected: {exc}")
            return ManualResult(type="not_found")

    # ------------------------------------------- STEP 1: LLM query generation

    async def _step_generate_queries(
        self,
        *,
        product_name: str,
        product_code: str,
        query_prompt: str,
        model: str | None,
        emitter: Emitter,
    ) -> list[str]:
        used_model = model or self._provider.default_model
        await emitter.progress(
            StepId.GENERATE_QUERIES,
            StepStatus.RUNNING,
            f"Asking the LLM to build search queries for '{product_name}' ({product_code})",
        )

        prompt = _render_prompt(query_prompt, product_name, product_code)
        await emitter.log(
            f"Model: {used_model} · target: {product_name} / {product_code}",
            step=StepId.GENERATE_QUERIES,
        )
        await emitter.log(f"Query prompt used:\n{prompt}", step=StepId.GENERATE_QUERIES)

        queries = await self._generate_queries(prompt, model=model)
        if not queries:
            await emitter.progress(
                StepId.GENERATE_QUERIES,
                StepStatus.ERROR,
                "The model did not return any search queries.",
                data={"queries": []},
            )
            return []

        for q in queries:
            await emitter.log(f"  • {q}", step=StepId.GENERATE_QUERIES)
        await emitter.progress(
            StepId.GENERATE_QUERIES,
            StepStatus.SUCCESS,
            f"Generated {_n_queries(len(queries))}",
            data={"queries": queries},
        )
        return queries

    async def _generate_queries(self, prompt: str, *, model: str | None) -> list[str]:
        """Plain JSON generation (no grounding) → a deduped, capped query list."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=5.0),
                retry=retry_if_exception_type((JsonParseError, ValidationError)),
                reraise=True,
            ):
                with attempt:
                    raw = await self._provider.generate_json(
                        prompt, model=model, system=SERP_QUERY_SYSTEM
                    )
                    parsed = SerpQueries.model_validate(extract_json(raw))
                    return _dedup_queries(parsed.queries, self._max_queries)
        except (JsonParseError, ValidationError, RetryError) as exc:
            _log.warning("query generation returned no valid JSON: %s", exc)
            return []
        except Exception as exc:  # provider / network / auth failure
            raise SerpCrawlError(f"query generation failed: {exc}") from exc

        return []  # pragma: no cover

    # ----------------------------------------------------- STEP 2: SerpAPI search

    async def _step_serpapi_search(
        self, queries: list[str], *, emitter: Emitter
    ) -> list[SerpResult]:
        assert self._serpapi is not None  # guarded in run()
        await emitter.progress(
            StepId.WEB_SEARCH,
            StepStatus.RUNNING,
            f"Querying SerpAPI (Google) with {_n_queries(len(queries))}",
        )

        results: list[SerpResult] = []
        seen: set[str] = set()
        last_error: str | None = None
        for q in queries:
            try:
                hits = await self._serpapi.search(q)
            except SerpApiError as exc:
                last_error = str(exc)
                _log.warning("SerpAPI query %r failed: %s", q, exc)
                await emitter.log(
                    f"SerpAPI query failed: {q} — {exc}",
                    step=StepId.WEB_SEARCH,
                    level="warning",
                )
                continue
            for r in hits:
                if r.link in seen:
                    continue
                seen.add(r.link)
                results.append(r)

        if not results and last_error:
            raise SerpCrawlError(last_error)

        sources = [r.to_source() for r in results]
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
            f"SerpAPI search complete — {len(sources)} result(s)",
            data={
                "query_count": len(queries),
                "queries": queries,
                "source_count": len(sources),
                "sources": sources,
            },
        )
        return results

    # ------------------------------------------- STEP 3: LLM evaluate / select

    async def _step_evaluate(
        self,
        results: list[SerpResult],
        *,
        queries: list[str],
        product_name: str,
        product_code: str,
        eval_rule: str,
        model: str | None,
        emitter: Emitter,
    ) -> WebSearchManuals:
        await emitter.progress(
            StepId.REVIEW_RESULTS,
            StepStatus.RUNNING,
            "Evaluating the SerpAPI results against the rules and selecting manuals",
        )

        if not results:
            search = WebSearchManuals(
                found=False, reason="SerpAPI returned no results to evaluate."
            )
            await emitter.progress(
                StepId.REVIEW_RESULTS,
                StepStatus.ERROR,
                "No results to evaluate.",
                data=_review_data(search, results, queries),
            )
            return search

        rendered_rule = _render_prompt(eval_rule, product_name, product_code)
        await emitter.log(f"Rules used:\n{rendered_rule}", step=StepId.REVIEW_RESULTS)

        results_json = json.dumps(
            [
                {"index": i, "title": r.title, "link": r.link, "snippet": r.snippet}
                for i, r in enumerate(results, start=1)
            ],
            ensure_ascii=False,
        )[:18_000]
        prompt = SERP_EVAL_TEMPLATE.format(
            product_name=product_name,
            product_code=product_code,
            rule=rendered_rule,
            queries="\n".join(f"- {q}" for q in queries),
            results=results_json,
        )

        search = await self._evaluate(prompt, model=model)

        if search.manuals:
            await emitter.log(
                f"LLM selected {len(search.manuals)} document(s):",
                step=StepId.REVIEW_RESULTS,
            )
            for i, m in enumerate(search.manuals[:_MAX_DETAIL_LINES], start=1):
                await emitter.log(f"  {_fmt_manual(i, m)}", step=StepId.REVIEW_RESULTS)

        if search.found and search.manuals:
            msg = f"Selected {len(search.manuals)} document(s)" + (
                f" — {search.summary}" if search.summary else ""
            )
            status = StepStatus.SUCCESS
        else:
            msg = "No result satisfied the rules" + (
                f": {search.reason}" if search.reason else ""
            )
            status = StepStatus.ERROR
            await emitter.log(msg, step=StepId.REVIEW_RESULTS, level="warning")

        await emitter.progress(
            StepId.REVIEW_RESULTS,
            status,
            msg,
            data=_review_data(search, results, queries),
        )
        return search

    async def _evaluate(self, prompt: str, *, model: str | None) -> WebSearchManuals:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=5.0),
                retry=retry_if_exception_type((JsonParseError, ValidationError)),
                reraise=True,
            ):
                with attempt:
                    raw = await self._provider.generate_json(
                        prompt, model=model, system=SERP_EVAL_SYSTEM
                    )
                    return WebSearchManuals.model_validate(extract_json(raw))
        except (JsonParseError, ValidationError, RetryError) as exc:
            _log.warning("result evaluation returned no valid JSON: %s", exc)
            return WebSearchManuals(
                found=False,
                reason="The model did not return a valid documentation list.",
            )
        except Exception as exc:  # provider / network / auth failure
            raise SerpCrawlError(f"result evaluation failed: {exc}") from exc

        return WebSearchManuals(found=False)  # pragma: no cover

    # ------------------------- STEP 4: 3-hop manual extraction per candidate

    async def _step_extract_manuals(
        self,
        selected: list[ManualEntry],
        *,
        product_name: str,
        product_code: str,
        emitter: Emitter,
    ) -> list[ManualEntry]:
        """Crawl each selected result and run the 3-hop manual extraction.

        Direct document files (.pdf/.doc/…) are kept as-is — they are already a
        final manual. Every other candidate is crawled and run through the LLM
        extraction strategy; if the manual lives on a linked support/downloads
        page, that link is followed and extraction re-run (up to 3 hops). Manuals
        are deduplicated globally across all candidates.
        """
        candidates = [e for e in selected if (e.url or "").strip()][: self._max_candidates]
        await emitter.progress(
            StepId.FIND_MANUAL,
            StepStatus.RUNNING,
            f"Crawling {len(candidates)} selected result(s) and extracting manuals "
            f"(≤{MAX_MANUAL_EXTRACTION_HOPS} hops each)",
        )

        if not candidates:
            await emitter.progress(
                StepId.FIND_MANUAL,
                StepStatus.ERROR,
                "No candidate URL to crawl.",
                data={"manuals": [], "manual_count": 0},
            )
            return []

        instruction = MANUAL_EXTRACTION_INSTRUCTION_TEMPLATE.format(
            product_name=product_name,
            product_code=product_code,
        )
        schema = ManualExtraction.model_json_schema()

        collected: list[ManualEntry] = []
        seen_keys: set[str] = set()

        for ci, entry in enumerate(candidates, start=1):
            url = (entry.url or "").strip()

            # Already a downloadable document → keep it, don't crawl it.
            if _looks_like_document(url):
                key = _dedup_key(entry)
                if key not in seen_keys:
                    seen_keys.add(key)
                    collected.append(entry)
                    await emitter.log(
                        f"Result {ci}/{len(candidates)}: direct document → {url}",
                        step=StepId.FIND_MANUAL,
                    )
                continue

            await emitter.log(
                f"Result {ci}/{len(candidates)}: 3-hop extract from {url}",
                step=StepId.FIND_MANUAL,
            )
            await self._extract_from_url(
                url,
                instruction=instruction,
                schema=schema,
                collected=collected,
                seen_keys=seen_keys,
                emitter=emitter,
            )

        if collected:
            msg = f"Found {len(collected)} manual(s) across {len(candidates)} result(s)"
            status = StepStatus.SUCCESS
        else:
            msg = f"No manual found across {len(candidates)} result(s)"
            status = StepStatus.ERROR

        await emitter.progress(
            StepId.FIND_MANUAL,
            status,
            msg,
            data={
                "manuals": [m.model_dump() for m in collected],
                "manual_count": len(collected),
            },
        )
        return collected

    async def _extract_from_url(
        self,
        start_url: str,
        *,
        instruction: str,
        schema: dict,
        collected: list[ManualEntry],
        seen_keys: set[str],
        emitter: Emitter,
    ) -> None:
        """Run the LLM extraction on ``start_url``, following at most one
        support/downloads link per hop, up to ``MAX_MANUAL_EXTRACTION_HOPS``.
        Appends any newly-found manuals to ``collected`` (deduped via
        ``seen_keys``)."""
        current_url = start_url
        visited: set[str] = set()

        for hop_idx in range(MAX_MANUAL_EXTRACTION_HOPS):
            if current_url in visited:
                break
            visited.add(current_url)

            try:
                page = await self._crawl.extract_manual(
                    url=current_url,
                    llm_provider=self._llm_provider,
                    llm_api_token=self._llm_api_token,
                    instruction=instruction,
                    schema=schema,
                )
            except CrawlError as exc:
                await emitter.log(
                    f"  hop {hop_idx + 1}: crawl failed for {current_url}: {exc}",
                    step=StepId.FIND_MANUAL,
                    level="warning",
                )
                break

            extraction = _parse_manual_extraction(page)
            new_count = 0
            for m in extraction.manuals:
                key = _dedup_key(m)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                collected.append(m)
                new_count += 1
            if new_count:
                await emitter.log(
                    f"  hop {hop_idx + 1}: +{new_count} manual(s) from {current_url}",
                    step=StepId.FIND_MANUAL,
                )

            if extraction.final or not extraction.follow_url:
                break
            next_url = extraction.follow_url.strip()
            if not next_url or next_url == current_url:
                break
            current_url = next_url

    # ----------------------------------------------------------- STEP 5: finalize

    async def _step_finalize(
        self,
        manuals: list[ManualEntry],
        results: list[SerpResult],
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
        # Inline the primary HTML manual's text so the UI can show it directly.
        if primary.type == "html_url" and primary.url and not primary_content:
            await emitter.log(
                f"Crawling primary html_url manual {primary.url}", step=StepId.FINALIZE
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
        await emitter.log(
            f"Primary document selected: {_fmt_manual(1, primary)}", step=StepId.FINALIZE
        )

        result_dump = result.model_dump()
        if result_dump.get("content"):
            result_dump["content_chars"] = len(result_dump["content"])
        result_dump["sources"] = [r.to_source() for r in results]
        await emitter.progress(
            StepId.FINALIZE,
            StepStatus.SUCCESS,
            f"Done — {len(manuals)} document"
            f"{'s' if len(manuals) != 1 else ''}, primary type={result.type}",
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


def _dedup_queries(queries: list[str], cap: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        q = (q or "").strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:cap]


def _review_data(
    search: WebSearchManuals, results: list[SerpResult], queries: list[str]
) -> dict:
    return {
        "found": search.found,
        "summary": search.summary,
        "reason": search.reason,
        "manuals": [m.model_dump() for m in search.manuals],
        "manual_count": len(search.manuals),
        "sources": [r.to_source() for r in results],
        "queries": queries,
    }


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


def _fmt_manual(i: int, m: ManualEntry) -> str:
    meta = [f"type={m.type}"]
    if m.language:
        meta.append(f"lang={m.language}")
    label = (m.label or "").strip() or "(untitled)"
    if m.type == "inline":
        where = f"{len(m.content or '')} chars inline"
    else:
        where = (m.url or "").strip() or "(no url)"
    return f"[{i}] {label} ({', '.join(meta)}) → {where}"


def _looks_like_document(url: str) -> bool:
    """True when the URL path points straight at a downloadable document file."""
    try:
        path = urlparse(url).path.lower()
    except ValueError:
        return False
    return path.endswith(_DOC_EXTENSIONS)


def _dedup_key(entry: ManualEntry) -> str:
    return f"{entry.type}|{(entry.url or '').strip().lower()}|{(entry.label or '').strip().lower()}"


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


# ----------------------------------------------------------------------- factory

_orchestrator: SerpCrawlOrchestrator | None = None


def get_serpcrawl_orchestrator() -> SerpCrawlOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        settings = get_settings()
        provider = GeminiWebSearchProvider(
            api_key=settings.gemini_api_token,
            model=settings.gemini_model,
        )
        serpapi = (
            SerpApiClient(settings.serpapi_api_key) if settings.serpapi_api_key else None
        )
        _orchestrator = SerpCrawlOrchestrator(
            provider,
            serpapi,
            get_crawl_service(),
            llm_provider=f"gemini/{settings.gemini_model}",
            llm_api_token=settings.gemini_api_token,
            max_retries=settings.llm_max_retries,
        )
        _log.info(
            "SerpAPI-crawl orchestrator initialized: provider=gemini model=%s serpapi=%s",
            settings.gemini_model,
            "on" if serpapi else "off",
        )
    return _orchestrator

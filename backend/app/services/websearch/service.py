"""LLM web-search manual finder.

A drop-in alternative to the crawl pipeline that takes the *same input*
(website_url, product_name, product_code) but, instead of driving a browser,
asks an LLM grounded on live web search to locate the product's documentation.

It deliberately does not import anything from ``app.services.crawl`` — the two
pipelines are independent so they can be compared head-to-head.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional
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
from app.core.logging import get_logger
from app.schemas.llm import ManualEntry, WebSearchManuals
from app.schemas.responses import ManualResult
from app.services.websearch.prompts import (
    SERPAPI_FILTER_SYSTEM,
    SERPAPI_FILTER_TEMPLATE,
    WEB_SEARCH_MANUAL_TEMPLATE,
    WEB_SEARCH_SYSTEM,
)
from app.services.websearch.provider import GeminiWebSearchProvider, WebSearchRaw
from app.services.websearch.serpapi import SerpApiClient, SerpApiError, SerpResult
from app.utils.json_parse import JsonParseError, extract_json

# How many distinct SerpAPI queries to issue per request (cost control).
_SERP_MAX_QUERIES = 3

# Substituted into the prompts when the caller gives no preferred website, so
# the model knows to search the open web instead of anchoring to a site.
_NO_SITE_PROMPT = "(not specified — search the open web; prefer the official manufacturer / brand sources)"

_log = get_logger(__name__)


def _website_for_prompt(website_url: Optional[str]) -> str:
    """Prompt text for the 'preferred website' line — falls back when absent."""
    cleaned = (website_url or "").strip()
    return cleaned or _NO_SITE_PROMPT


class WebSearchError(RuntimeError):
    pass


@dataclass
class ManualSearchResult:
    """Everything the web-search pass produced for one product.

    ``manuals`` reuses the shared :class:`ManualEntry` shape, so the result can
    be rendered by the same UI as the crawl pipeline. ``sources`` and
    ``queries`` expose the grounding so the workflow can show its work.
    """

    found: bool
    manuals: list[ManualEntry] = field(default_factory=list)
    summary: Optional[str] = None
    reason: Optional[str] = None
    sources: list[dict[str, str]] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    def to_manual_result(self) -> ManualResult:
        """Collapse into the canonical :class:`ManualResult`.

        Top-level ``type/url/content`` are filled from the first manual for the
        existing single-manual UI; the full list rides along in ``manuals``.
        """
        if not self.manuals:
            return ManualResult(type="not_found")
        primary = self.manuals[0]
        return ManualResult(
            type=primary.type,
            url=primary.url,
            content=primary.content,
            manuals=self.manuals,
        )


@dataclass
class SerpSearch:
    """Raw SerpAPI output for one request, before LLM filtering."""

    queries: list[str]
    results: list[SerpResult]


class WebSearchService:
    def __init__(
        self,
        provider: GeminiWebSearchProvider,
        max_retries: int = 3,
        serpapi: Optional[SerpApiClient] = None,
    ) -> None:
        self._provider = provider
        self._max_retries = max_retries
        self._serpapi = serpapi

    @property
    def default_model(self) -> str:
        return self._provider.default_model

    @property
    def serpapi_available(self) -> bool:
        return self._serpapi is not None

    async def list_models(self) -> list[dict[str, str]]:
        """Models usable for the web-search pass (delegated to the provider)."""
        return await self._provider.list_models()

    async def find_manuals(
        self,
        *,
        website_url: Optional[str],
        product_name: str,
        product_code: str,
        model: Optional[str] = None,
    ) -> ManualSearchResult:
        """Search the web (via the LLM) for this product's documentation.

        Raises :class:`WebSearchError` only on a hard provider failure
        (network/auth). A "model could not produce valid JSON / found nothing"
        outcome is returned as a ``found=False`` result — with whatever sources
        the search surfaced — rather than raised, so a soft miss does not 500.
        """
        prompt = WEB_SEARCH_MANUAL_TEMPLATE.format(
            website_url=_website_for_prompt(website_url),
            product_name=product_name,
            product_code=product_code,
        )

        # The provider call can be retried (JSON parse / schema failures); we
        # keep a handle on the last raw response so its grounding survives even
        # when every parse attempt fails.
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
                        prompt, model=model, system=WEB_SEARCH_SYSTEM
                    )
                    last_raw = raw
                    payload = extract_json(raw.text)
                    extraction = WebSearchManuals.model_validate(payload)
                    return _to_result(extraction, raw)
        except (JsonParseError, ValidationError, RetryError) as exc:
            # Soft miss: the model never returned parseable, valid JSON. Surface
            # a not-found result that still carries the grounding we collected.
            _log.warning("web-search returned no valid JSON: %s", exc)
            return ManualSearchResult(
                found=False,
                reason="The model did not return a valid documentation list.",
                sources=last_raw.sources if last_raw else [],
                queries=last_raw.queries if last_raw else [],
            )
        except Exception as exc:  # provider / network / auth failure
            raise WebSearchError(f"web search failed: {exc}") from exc

        raise WebSearchError("web search did not return")  # pragma: no cover

    # ------------------------------------------------------------- SerpAPI mode

    async def serpapi_search(
        self,
        *,
        website_url: Optional[str],
        product_name: str,
        product_code: str,
    ) -> SerpSearch:
        """Run the product-documentation queries through SerpAPI.

        Raises :class:`WebSearchError` if SerpAPI is not configured or if every
        query failed; a query that simply returns nothing is not an error.
        """
        if self._serpapi is None:
            raise WebSearchError("SerpAPI is not configured (set SERPAPI_API_KEY).")

        queries = _build_serp_queries(website_url, product_name, product_code)
        results: list[SerpResult] = []
        seen: set[str] = set()
        last_error: Optional[str] = None
        for q in queries:
            try:
                hits = await self._serpapi.search(q)
            except SerpApiError as exc:
                last_error = str(exc)
                _log.warning("SerpAPI query %r failed: %s", q, exc)
                continue
            for r in hits:
                if r.link in seen:
                    continue
                seen.add(r.link)
                results.append(r)

        if not results and last_error:
            raise WebSearchError(last_error)
        return SerpSearch(queries=queries, results=results)

    async def filter_serp_results(
        self,
        *,
        website_url: Optional[str],
        product_name: str,
        product_code: str,
        serp: SerpSearch,
        model: Optional[str] = None,
    ) -> ManualSearchResult:
        """Use the LLM to filter SerpAPI results and extract the manual URLs."""
        sources = [r.to_source() for r in serp.results]
        if not serp.results:
            return ManualSearchResult(
                found=False,
                reason="SerpAPI returned no results for these queries.",
                sources=sources,
                queries=serp.queries,
            )

        results_json = json.dumps(
            [
                {"index": i, "title": r.title, "link": r.link, "snippet": r.snippet}
                for i, r in enumerate(serp.results, start=1)
            ],
            ensure_ascii=False,
        )[:18_000]
        prompt = SERPAPI_FILTER_TEMPLATE.format(
            product_name=product_name,
            product_code=product_code,
            website_url=_website_for_prompt(website_url),
            queries="\n".join(f"- {q}" for q in serp.queries),
            results=results_json,
        )

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=5.0),
                retry=retry_if_exception_type((JsonParseError, ValidationError)),
                reraise=True,
            ):
                with attempt:
                    raw = await self._provider.generate_json(
                        prompt, model=model, system=SERPAPI_FILTER_SYSTEM
                    )
                    extraction = WebSearchManuals.model_validate(extract_json(raw))
                    return ManualSearchResult(
                        found=extraction.found and bool(extraction.manuals),
                        manuals=extraction.manuals,
                        summary=extraction.summary,
                        reason=extraction.reason,
                        sources=sources,
                        queries=serp.queries,
                    )
        except (JsonParseError, ValidationError, RetryError) as exc:
            _log.warning("SerpAPI filter returned no valid JSON: %s", exc)
            return ManualSearchResult(
                found=False,
                reason="The model did not return a valid documentation list.",
                sources=sources,
                queries=serp.queries,
            )
        except Exception as exc:
            raise WebSearchError(f"SerpAPI result filtering failed: {exc}") from exc

        raise WebSearchError("SerpAPI filtering did not return")  # pragma: no cover


def _build_serp_queries(
    website_url: Optional[str], product_name: str, product_code: str
) -> list[str]:
    """Build the SerpAPI query set: a site-restricted query plus general ones.

    With no ``website_url`` the ``site:`` query is simply skipped, so the search
    runs against the open web."""
    base = " ".join(p for p in (product_name, product_code) if p).strip()
    domain = _registrable_domain(website_url)
    if domain:
        raw = [
            f'site:{domain} "{product_code}" manual',
            f'site:{domain} "{product_code}" user guide',
            f'site:{domain} "{product_code}" documentation',
            f'site:{domain} "{base}" manual',
            f'site:{domain} "{base}" user guide',
            f'site:{domain} "{base}" documentation',
        ]
    else:
        raw = [
            f'"{product_code}" manual',
            f'"{product_code}" user guide',
            f'"{product_code}" documentation',
            f'"{base}" manual',
            f'"{base}" user guide',
            f'"{base}" documentation',
        ]
    out: list[str] = []
    seen: set[str] = set()
    for q in raw:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:_SERP_MAX_QUERIES]


def _registrable_domain(website_url: Optional[str]) -> str:
    if not website_url:
        return ""
    try:
        host = urlparse(website_url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _to_result(extraction: WebSearchManuals, raw: WebSearchRaw) -> ManualSearchResult:
    return ManualSearchResult(
        found=extraction.found and bool(extraction.manuals),
        manuals=extraction.manuals,
        summary=extraction.summary,
        reason=extraction.reason,
        sources=raw.sources,
        queries=raw.queries,
    )


# ----------------------------------------------------------------------- factory

_service: WebSearchService | None = None


def get_web_search_service() -> WebSearchService:
    global _service
    if _service is None:
        settings = get_settings()
        model = "gemini-3.5-flash"
        provider = GeminiWebSearchProvider(
            api_key=settings.gemini_api_token,
            model=model,
        )
        serpapi = (
            SerpApiClient(settings.serpapi_api_key) if settings.serpapi_api_key else None
        )
        _service = WebSearchService(
            provider,
            max_retries=settings.llm_max_retries,
            serpapi=serpapi,
        )
        _log.info(
            "Web-search service initialized: provider=gemini model=%s serpapi=%s",
            model,
            "on" if serpapi else "off",
        )
    return _service

"""Request DTOs."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class CrawlSearchRequest(BaseModel):
    website_url: HttpUrl = Field(..., description="Website homepage URL")
    product_name: str = Field(..., min_length=1, max_length=300)
    product_code: str = Field(..., min_length=1, max_length=120)

    @field_validator("product_name", "product_code")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class WebSearchRequest(CrawlSearchRequest):
    """Same as the crawl search request, plus an optional model override.

    ``model`` is the Gemini model id (e.g. ``gemini-2.5-flash``) chosen in the
    UI dropdown; when omitted the service falls back to its configured default.
    """

    # Unlike the crawl pipeline (which needs a site to crawl), web search can
    # run with no preferred website at all — just the product name + code, and
    # let the search itself discover authoritative sources. ``None``/omitted =
    # open-web search with no site preference.
    website_url: Optional[HttpUrl] = Field(
        None,
        description="Manufacturer / preferred website (optional — omit to search the open web)",
    )

    model: Optional[str] = Field(None, max_length=120)
    # When true, search via SerpAPI then have the LLM filter/extract the manual
    # links; when false, use the Gemini grounded web search.
    use_serpapi: bool = Field(False)

    @field_validator("model")
    @classmethod
    def _strip_model(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip()
        return v or None


class WebSearchCrawlRequest(BaseModel):
    """Combined pipeline input: web search finds the official brand site, then
    the crawl pipeline runs against it.

    There is no ``website_url`` — the site is *discovered* from the product
    name + code. ``search_prompt`` is the instruction the UI sends for the
    site-finding web search (the UI ships a default); the backend deliberately
    has no hardcoded search prompt of its own. ``{product_name}`` and
    ``{product_code}`` placeholders in the prompt are substituted server-side.
    """

    product_name: str = Field(..., min_length=1, max_length=300)
    product_code: str = Field(..., min_length=1, max_length=120)
    search_prompt: str = Field(..., min_length=1, max_length=8000)
    model: Optional[str] = Field(None, max_length=120)

    @field_validator("product_name", "product_code", "search_prompt")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("model")
    @classmethod
    def _strip_model(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip()
        return v or None


class SerpCrawlRequest(BaseModel):
    """SerpAPI pipeline input: an LLM generates the search queries, SerpAPI runs
    them, then an LLM evaluates/selects the results against an operator rule set.

    Both LLM instructions come from the UI: ``query_prompt`` drives the
    query-generation step and ``eval_rule`` drives the result-selection step.
    The backend keeps no task prompt of its own (only the JSON output
    contracts). ``{product_name}`` / ``{product_code}`` placeholders in either
    field are substituted server-side.
    """

    product_name: str = Field(..., min_length=1, max_length=300)
    product_code: str = Field(..., min_length=1, max_length=120)
    query_prompt: str = Field(..., min_length=1, max_length=8000)
    eval_rule: str = Field(..., min_length=1, max_length=8000)
    model: Optional[str] = Field(None, max_length=120)

    @field_validator("product_name", "product_code", "query_prompt", "eval_rule")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("model")
    @classmethod
    def _strip_model(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip()
        return v or None

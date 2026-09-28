"""Workflow constants — step identifiers and status enums kept here for reuse."""
from __future__ import annotations

from enum import Enum


class StepId(str, Enum):
    CRAWL_HOMEPAGE = "crawl_homepage"
    ANALYZE_UI = "analyze_ui"
    SEARCH_PRODUCT = "search_product"
    FILTER_RESULTS = "filter_results"
    FIND_MANUAL = "find_manual"
    FINALIZE = "finalize"
    # Web-search pipeline (LLM grounded on live web search) — an alternative
    # to the crawl pipeline that shares the FINALIZE step.
    WEB_SEARCH = "web_search"
    REVIEW_RESULTS = "review_results"
    # Combined pipeline: web search locates the official brand site, then the
    # crawl pipeline (above steps) runs against it. FIND_SITE is its first step.
    FIND_SITE = "find_site"
    # Deep-crawl pipeline: web search locates the product's support/detail page,
    # then the 3-hop manual extraction (FIND_MANUAL) runs directly against it.
    FIND_PAGE = "find_page"
    # SerpAPI pipeline: an LLM generates the search queries (GENERATE_QUERIES),
    # SerpAPI runs them (WEB_SEARCH), then an LLM evaluates/selects the results
    # against an operator rule set (REVIEW_RESULTS).
    GENERATE_QUERIES = "generate_queries"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


STEP_LABELS: dict[StepId, str] = {
    StepId.CRAWL_HOMEPAGE: "Crawling homepage",
    StepId.ANALYZE_UI: "Analyzing UI structure",
    StepId.SEARCH_PRODUCT: "Searching product",
    StepId.FILTER_RESULTS: "Filtering search results",
    StepId.FIND_MANUAL: "Extracting manual",
    StepId.FINALIZE: "Finalizing result",
    StepId.WEB_SEARCH: "Searching the web with LLM",
    StepId.REVIEW_RESULTS: "Reviewing found documents",
    StepId.FIND_SITE: "Finding the official site",
    StepId.FIND_PAGE: "Finding the support page",
    StepId.GENERATE_QUERIES: "Generating search queries",
}

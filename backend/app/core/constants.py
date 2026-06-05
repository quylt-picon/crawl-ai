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
}

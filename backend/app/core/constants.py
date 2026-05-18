"""Workflow constants — step identifiers and status enums kept here for reuse."""
from __future__ import annotations

from enum import Enum


class StepId(str, Enum):
    CRAWL_HOMEPAGE = "crawl_homepage"
    ANALYZE_UI = "analyze_ui"
    SEARCH_PRODUCT = "search_product"
    FILTER_RESULTS = "filter_results"
    OPEN_PRODUCT_PAGE = "open_product_page"
    EXPAND_SECTIONS = "expand_sections"
    FIND_MANUAL = "find_manual"
    FINALIZE = "finalize"


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
    StepId.OPEN_PRODUCT_PAGE: "Opening product page",
    StepId.EXPAND_SECTIONS: "Expanding tabs & sections",
    StepId.FIND_MANUAL: "Finding user manual",
    StepId.FINALIZE: "Finalizing result",
}

"""Schemas for LLM I/O — keeps parsing strict and testable."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class UIAnalysis(BaseModel):
    has_search_box: bool = False
    search_input_selector: Optional[str] = None
    search_button_selector: Optional[str] = None
    # Element that must be clicked BEFORE the input is reachable — typically
    # the magnifier-icon trigger on sites where the search UI is lazy-mounted
    # into a popup/modal. Empty string when the input is already in the DOM.
    search_trigger_selector: Optional[str] = None
    search_page_url: Optional[str] = None


class ProductMatch(BaseModel):
    found: bool = False
    product_url: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


ManualType = Literal["link", "html_url", "inline"]


class ManualEntry(BaseModel):
    type: ManualType
    url: Optional[str] = None
    content: Optional[str] = None
    language: Optional[str] = None  # e.g. "en", "vi", "Vietnamese"
    label: Optional[str] = None     # e.g. "User Manual (PDF)", "Quick Start Guide"


class ManualExtraction(BaseModel):
    """Single-step output from the LLM extraction pass on a product page.

    ``final`` tells the orchestrator whether to stop. If ``final`` is False
    and ``follow_url`` is set, the orchestrator opens that URL and runs the
    extraction again so the LLM can drill into a dedicated "support/manuals"
    page that only links to the actual manual files.
    """

    final: bool = False
    manuals: List[ManualEntry] = Field(default_factory=list)
    follow_url: Optional[str] = None
    reason: Optional[str] = None


class WebSearchManuals(BaseModel):
    """Output of the LLM *web-search* manual finder.

    Mirrors :class:`ManualExtraction` but is produced by a single
    web-search-grounded LLM call instead of by crawling pages. ``manuals``
    holds every document/guide the model surfaced from the live web; reuse the
    shared :class:`ManualEntry` shape so the same frontend can render results
    from either pipeline.
    """

    found: bool = False
    manuals: List[ManualEntry] = Field(default_factory=list)
    summary: Optional[str] = None
    reason: Optional[str] = None

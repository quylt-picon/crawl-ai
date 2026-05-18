"""Schemas for LLM I/O — keeps parsing strict and testable."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class UIAnalysis(BaseModel):
    has_search_box: bool = False
    search_input_selector: Optional[str] = None
    search_button_selector: Optional[str] = None
    support_url: Optional[str] = None


class ProductMatch(BaseModel):
    found: bool = False
    product_url: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class ManualLocator(BaseModel):
    type: Literal["link", "html_url", "inline", "not_found"] = "not_found"
    url: Optional[str] = None
    content: Optional[str] = None

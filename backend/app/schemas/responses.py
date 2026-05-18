"""Response DTOs."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.llm import ManualEntry


class ManualResult(BaseModel):
    """Final result returned to the frontend.

    ``manuals`` is the canonical, multi-entry list. ``type/url/content`` are
    kept populated from the *primary* manual (first entry) for the existing
    UI that renders a single manual — no breaking change to consumers that
    only read those three fields.
    """

    type: Literal["link", "html_url", "inline", "not_found"] = "not_found"
    url: Optional[str] = None
    content: Optional[str] = None
    manuals: List[ManualEntry] = Field(default_factory=list)


class CrawlSearchResponse(BaseModel):
    success: bool
    job_id: str
    manual: ManualResult = Field(default_factory=ManualResult)
    error: Optional[str] = None


class JobCreatedResponse(BaseModel):
    job_id: str
    stream_url: str

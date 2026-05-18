"""Response DTOs."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ManualResult(BaseModel):
    type: Literal["link", "html_url", "inline", "not_found"] = "not_found"
    url: Optional[str] = None
    content: Optional[str] = None


class CrawlSearchResponse(BaseModel):
    success: bool
    job_id: str
    manual: ManualResult = Field(default_factory=ManualResult)
    error: Optional[str] = None


class JobCreatedResponse(BaseModel):
    job_id: str
    stream_url: str

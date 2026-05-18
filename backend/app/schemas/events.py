"""SSE event payload schemas — what the frontend timeline consumes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.core.constants import StepId, StepStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProgressEvent(BaseModel):
    """Single step update sent to the frontend over SSE."""

    job_id: str
    step: StepId
    status: StepStatus
    message: str
    timestamp: datetime = Field(default_factory=_now)
    data: Optional[dict[str, Any]] = None


class LogEvent(BaseModel):
    job_id: str
    level: Literal["info", "warning", "error", "debug"] = "info"
    message: str
    timestamp: datetime = Field(default_factory=_now)
    step: Optional[StepId] = None


class CompletionEvent(BaseModel):
    job_id: str
    success: bool
    manual_type: Optional[str] = None
    manual_url: Optional[str] = None
    has_content: bool = False
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=_now)

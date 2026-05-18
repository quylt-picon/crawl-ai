"""Tiny helper that gives services a stable interface for emitting progress.

Workflow steps receive an Emitter instance scoped to one job_id, so they do
not need to know about the EventBus singleton or about job-id plumbing.
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.constants import StepId, StepStatus
from app.events.bus import EventBus
from app.schemas.events import CompletionEvent, LogEvent, ProgressEvent


class Emitter:
    def __init__(self, bus: EventBus, job_id: str) -> None:
        self._bus = bus
        self._job_id = job_id
        # Tracks the step currently in RUNNING state so failures can transition
        # it to ERROR before completion fires (otherwise the UI stays spinning).
        self._active_step: Optional[StepId] = None

    @property
    def job_id(self) -> str:
        return self._job_id

    async def progress(
        self,
        step: StepId,
        status: StepStatus,
        message: str,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        if status == StepStatus.RUNNING:
            self._active_step = step
        elif self._active_step == step:
            self._active_step = None
        await self._bus.publish(
            self._job_id,
            ProgressEvent(
                job_id=self._job_id,
                step=step,
                status=status,
                message=message,
                data=data,
            ),
        )

    async def fail_active_step(self, message: str) -> None:
        """Mark the currently-running step as ERROR. No-op if nothing is running."""
        if self._active_step is None:
            return
        step = self._active_step
        self._active_step = None
        await self._bus.publish(
            self._job_id,
            ProgressEvent(
                job_id=self._job_id,
                step=step,
                status=StepStatus.ERROR,
                message=message,
            ),
        )

    async def log(
        self,
        message: str,
        *,
        level: str = "info",
        step: Optional[StepId] = None,
    ) -> None:
        await self._bus.publish(
            self._job_id,
            LogEvent(
                job_id=self._job_id,
                level=level,  # type: ignore[arg-type]
                message=message,
                step=step,
            ),
        )

    async def completion(
        self,
        *,
        success: bool,
        manual_type: Optional[str] = None,
        manual_url: Optional[str] = None,
        has_content: bool = False,
        error: Optional[str] = None,
    ) -> None:
        await self._bus.publish(
            self._job_id,
            CompletionEvent(
                job_id=self._job_id,
                success=success,
                manual_type=manual_type,
                manual_url=manual_url,
                has_content=has_content,
                error=error,
            ),
        )
        await self._bus.close(self._job_id)

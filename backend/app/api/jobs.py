"""Tiny in-memory job registry — survives only the process lifetime.

Each job tracks its background task + final result so two endpoints can share
the same workflow run: POST /crawl/search starts it, GET /crawl/stream/{id}
streams its events.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.schemas.responses import ManualResult


@dataclass
class JobRecord:
    job_id: str
    task: Optional[asyncio.Task] = None
    manual: Optional[ManualResult] = None
    error: Optional[str] = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self) -> JobRecord:
        job_id = uuid.uuid4().hex
        record = JobRecord(job_id=job_id)
        async with self._lock:
            self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> Optional[JobRecord]:
        return self._jobs.get(job_id)

    async def drop(self, job_id: str) -> None:
        async with self._lock:
            self._jobs.pop(job_id, None)


_registry: JobRegistry | None = None


def get_job_registry() -> JobRegistry:
    global _registry
    if _registry is None:
        _registry = JobRegistry()
    return _registry

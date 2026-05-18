"""In-process pub/sub event bus driving the SSE stream.

One asyncio.Queue per job_id. Producers (the workflow orchestrator) call
publish(); consumers (the SSE endpoint) iterate stream(). The bus is kept
intentionally simple — single process, single instance. For multi-worker
deployments swap this for Redis pub/sub without changing call sites.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from app.core.logging import get_logger
from app.schemas.events import CompletionEvent, LogEvent, ProgressEvent

_log = get_logger(__name__)

EventPayload = ProgressEvent | LogEvent | CompletionEvent


@dataclass
class _JobChannel:
    queue: asyncio.Queue[EventPayload] = field(default_factory=asyncio.Queue)
    closed: bool = False


class EventBus:
    def __init__(self) -> None:
        self._channels: dict[str, _JobChannel] = {}
        self._lock = asyncio.Lock()

    async def register(self, job_id: str) -> None:
        async with self._lock:
            if job_id not in self._channels:
                self._channels[job_id] = _JobChannel()

    async def publish(self, job_id: str, event: EventPayload) -> None:
        chan = self._channels.get(job_id)
        if chan is None or chan.closed:
            _log.debug("dropping event for unknown/closed job %s", job_id)
            return
        await chan.queue.put(event)

    async def close(self, job_id: str) -> None:
        chan = self._channels.get(job_id)
        if chan is None:
            return
        if chan.closed:
            # Idempotent — failure paths can hit close() more than once.
            return
        chan.closed = True
        # Sentinel so the consumer iterator can exit cleanly.
        await chan.queue.put(_SENTINEL)  # type: ignore[arg-type]

    async def drop(self, job_id: str) -> None:
        async with self._lock:
            self._channels.pop(job_id, None)

    async def stream(self, job_id: str) -> AsyncIterator[EventPayload]:
        chan = self._channels.get(job_id)
        if chan is None:
            return
        # If a client reconnects after the workflow has already finished, drain
        # whatever is left in the queue then exit — do not block on an empty
        # closed channel (that would hang the request forever).
        if chan.closed:
            while not chan.queue.empty():
                event = chan.queue.get_nowait()
                if event is _SENTINEL:  # type: ignore[comparison-overlap]
                    return
                yield event
            return
        while True:
            event = await chan.queue.get()
            if event is _SENTINEL:  # type: ignore[comparison-overlap]
                break
            yield event


_SENTINEL: object = object()

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus

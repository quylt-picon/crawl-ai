"""HTTP routes — thin controllers, no business logic.

POST /api/crawl/search
    Start a crawl job. Returns the job_id and stream_url. The workflow runs
    in a background asyncio.Task so the response returns immediately.

GET  /api/crawl/stream/{job_id}
    Server-Sent Events feed of progress/log/completion events for one job.

GET  /api/crawl/result/{job_id}
    Final result (blocks until the job finishes). Useful for non-SSE clients.

GET  /api/health
    Liveness probe.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import EventBus, WorkflowOrchestrator, get_event_bus, get_orchestrator
from app.api.jobs import JobRegistry, get_job_registry
from app.core.logging import get_logger
from app.events.emitter import Emitter
from app.schemas.requests import CrawlSearchRequest
from app.schemas.responses import CrawlSearchResponse, JobCreatedResponse, ManualResult

router = APIRouter(prefix="/api", tags=["crawl"])

_log = get_logger(__name__)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/crawl/search", response_model=JobCreatedResponse, status_code=202)
async def start_search(
    payload: CrawlSearchRequest,
    bus: EventBus = Depends(get_event_bus),
    orchestrator: WorkflowOrchestrator = Depends(get_orchestrator),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobCreatedResponse:
    record = await registry.create()
    await bus.register(record.job_id)
    emitter = Emitter(bus, record.job_id)

    async def _run() -> None:
        try:
            manual = await orchestrator.run(
                website_url=str(payload.website_url),
                product_name=payload.product_name,
                product_code=payload.product_code,
                emitter=emitter,
            )
            record.manual = manual
        except Exception as exc:
            _log.exception("job %s crashed: %s", record.job_id, exc)
            record.error = str(exc)
            record.manual = ManualResult(type="not_found")
            await emitter.completion(success=False, error=str(exc))
        finally:
            record.done.set()

    record.task = asyncio.create_task(_run(), name=f"job:{record.job_id}")

    return JobCreatedResponse(
        job_id=record.job_id,
        stream_url=f"/api/crawl/stream/{record.job_id}",
    )


@router.get("/crawl/stream/{job_id}")
async def stream(
    job_id: str,
    request: Request,
    bus: EventBus = Depends(get_event_bus),
    registry: JobRegistry = Depends(get_job_registry),
) -> EventSourceResponse:
    if registry.get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_source() -> AsyncIterator[dict]:
        async for event in bus.stream(job_id):
            if await request.is_disconnected():
                break
            kind = type(event).__name__  # ProgressEvent / LogEvent / CompletionEvent
            yield {
                "event": _event_name(kind),
                "data": event.model_dump_json(),
            }

    return EventSourceResponse(event_source(), ping=15)


@router.get("/crawl/result/{job_id}", response_model=CrawlSearchResponse)
async def get_result(
    job_id: str,
    registry: JobRegistry = Depends(get_job_registry),
) -> CrawlSearchResponse:
    record = registry.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")

    await record.done.wait()
    return CrawlSearchResponse(
        success=record.error is None and (record.manual is not None and record.manual.type != "not_found"),
        job_id=job_id,
        manual=record.manual or ManualResult(type="not_found"),
        error=record.error,
    )


def _event_name(class_name: str) -> str:
    return {
        "ProgressEvent": "progress",
        "LogEvent": "log",
        "CompletionEvent": "completion",
    }.get(class_name, "message")

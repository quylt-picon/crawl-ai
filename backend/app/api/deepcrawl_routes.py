"""HTTP routes for the deep-crawl pipeline (web search → support page → 3-hop
manual extraction).

Standalone from the combined pipeline so it can change independently. Reuses
the shared job registry + event bus, so progress streams over SSE the same way.
Takes the SAME request body as the combined pipeline (no website_url; the page
is discovered from the product name + code + UI prompt).

POST /api/sitecrawl/deep/search       Start a deep-crawl job.
GET  /api/sitecrawl/deep/stream/{id}  SSE feed of progress/log/completion events.
GET  /api/sitecrawl/deep/result/{id}  Final result (blocks until the job finishes).
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.api.jobs import JobRegistry, get_job_registry
from app.core.logging import get_logger
from app.events.bus import EventBus, get_event_bus
from app.events.emitter import Emitter
from app.schemas.requests import WebSearchCrawlRequest
from app.schemas.responses import CrawlSearchResponse, JobCreatedResponse, ManualResult
from app.services.deepcrawl import DeepCrawlOrchestrator, get_deepcrawl_orchestrator

router = APIRouter(prefix="/api/sitecrawl/deep", tags=["deepcrawl"])

_log = get_logger(__name__)


@router.post("/search", response_model=JobCreatedResponse, status_code=202)
async def start_search(
    payload: WebSearchCrawlRequest,
    bus: EventBus = Depends(get_event_bus),
    orchestrator: DeepCrawlOrchestrator = Depends(get_deepcrawl_orchestrator),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobCreatedResponse:
    record = await registry.create()
    await bus.register(record.job_id)
    emitter = Emitter(bus, record.job_id)

    async def _run() -> None:
        try:
            manual = await orchestrator.run(
                product_name=payload.product_name,
                product_code=payload.product_code,
                search_prompt=payload.search_prompt,
                emitter=emitter,
                model=payload.model,
            )
            record.manual = manual
        except Exception as exc:
            _log.exception("deepcrawl job %s crashed: %s", record.job_id, exc)
            record.error = str(exc)
            record.manual = ManualResult(type="not_found")
            await emitter.completion(success=False, error=str(exc))
        finally:
            record.done.set()

    record.task = asyncio.create_task(_run(), name=f"deepcrawl:{record.job_id}")

    return JobCreatedResponse(
        job_id=record.job_id,
        stream_url=f"/api/sitecrawl/deep/stream/{record.job_id}",
    )


@router.get("/stream/{job_id}")
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


@router.get("/result/{job_id}", response_model=CrawlSearchResponse)
async def get_result(
    job_id: str,
    registry: JobRegistry = Depends(get_job_registry),
) -> CrawlSearchResponse:
    record = registry.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")

    await record.done.wait()
    return CrawlSearchResponse(
        success=record.error is None
        and (record.manual is not None and record.manual.type != "not_found"),
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

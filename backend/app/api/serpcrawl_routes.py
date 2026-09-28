"""HTTP routes for the SerpAPI pipeline (LLM query-gen → SerpAPI → LLM evaluate).

Standalone from the other pipelines so it can change independently. Reuses the
shared job registry + event bus, so progress streams over SSE the same way.
Unlike the combined/deep pipelines, the request carries TWO UI-supplied prompts:
``query_prompt`` (drives query generation) and ``eval_rule`` (drives result
selection).

POST /api/sitecrawl/serp/search       Start a SerpAPI job.
GET  /api/sitecrawl/serp/stream/{id}  SSE feed of progress/log/completion events.
GET  /api/sitecrawl/serp/result/{id}  Final result (blocks until the job finishes).
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
from app.schemas.requests import SerpCrawlRequest
from app.schemas.responses import CrawlSearchResponse, JobCreatedResponse, ManualResult
from app.services.serpcrawl import SerpCrawlOrchestrator, get_serpcrawl_orchestrator

router = APIRouter(prefix="/api/sitecrawl/serp", tags=["serpcrawl"])

_log = get_logger(__name__)


@router.post("/search", response_model=JobCreatedResponse, status_code=202)
async def start_search(
    payload: SerpCrawlRequest,
    bus: EventBus = Depends(get_event_bus),
    orchestrator: SerpCrawlOrchestrator = Depends(get_serpcrawl_orchestrator),
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
                query_prompt=payload.query_prompt,
                eval_rule=payload.eval_rule,
                emitter=emitter,
                model=payload.model,
            )
            record.manual = manual
        except Exception as exc:
            _log.exception("serpcrawl job %s crashed: %s", record.job_id, exc)
            record.error = str(exc)
            record.manual = ManualResult(type="not_found")
            await emitter.completion(success=False, error=str(exc))
        finally:
            record.done.set()

    record.task = asyncio.create_task(_run(), name=f"serpcrawl:{record.job_id}")

    return JobCreatedResponse(
        job_id=record.job_id,
        stream_url=f"/api/sitecrawl/serp/stream/{record.job_id}",
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

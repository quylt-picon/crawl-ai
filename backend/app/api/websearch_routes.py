"""HTTP routes for the LLM web-search manual finder.

Symmetric with the crawl routes but backed by the web-search orchestrator.
Takes the SAME request body as /api/crawl/search, and reuses the shared job
registry + event bus so progress streams over SSE the same way.

POST /api/websearch/search       Start a web-search job.
GET  /api/websearch/stream/{id}  SSE feed of progress/log/completion events.
GET  /api/websearch/result/{id}  Final result (blocks until the job finishes).
GET  /api/websearch/models       List selectable Gemini models + the default.
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
from app.schemas.requests import WebSearchRequest
from app.schemas.responses import CrawlSearchResponse, JobCreatedResponse, ManualResult
from app.services.websearch import (
    WebSearchOrchestrator,
    WebSearchService,
    get_web_search_orchestrator,
    get_web_search_service,
)

router = APIRouter(prefix="/api/websearch", tags=["websearch"])

_log = get_logger(__name__)


@router.get("/models")
async def list_models(
    service: WebSearchService = Depends(get_web_search_service),
) -> dict:
    """Models usable for web search, fetched live with the configured API key.

    Always returns the configured default; on a fetch failure the model list is
    empty (the UI still works with the default) and ``error`` explains why.
    """
    default = service.default_model
    serpapi_available = service.serpapi_available
    try:
        models = await service.list_models()
        return {
            "models": models,
            "default": default,
            "serpapi_available": serpapi_available,
            "error": None,
        }
    except Exception as exc:  # network / auth / quota
        _log.warning("could not list models: %s", exc)
        return {
            "models": [],
            "default": default,
            "serpapi_available": serpapi_available,
            "error": str(exc),
        }


@router.post("/search", response_model=JobCreatedResponse, status_code=202)
async def start_search(
    payload: WebSearchRequest,
    bus: EventBus = Depends(get_event_bus),
    orchestrator: WebSearchOrchestrator = Depends(get_web_search_orchestrator),
    registry: JobRegistry = Depends(get_job_registry),
) -> JobCreatedResponse:
    record = await registry.create()
    await bus.register(record.job_id)
    emitter = Emitter(bus, record.job_id)

    async def _run() -> None:
        try:
            manual = await orchestrator.run(
                website_url=str(payload.website_url) if payload.website_url else None,
                product_name=payload.product_name,
                product_code=payload.product_code,
                emitter=emitter,
                model=payload.model,
                use_serpapi=payload.use_serpapi,
            )
            record.manual = manual
        except Exception as exc:
            _log.exception("websearch job %s crashed: %s", record.job_id, exc)
            record.error = str(exc)
            record.manual = ManualResult(type="not_found")
            await emitter.completion(success=False, error=str(exc))
        finally:
            record.done.set()

    record.task = asyncio.create_task(_run(), name=f"websearch:{record.job_id}")

    return JobCreatedResponse(
        job_id=record.job_id,
        stream_url=f"/api/websearch/stream/{record.job_id}",
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

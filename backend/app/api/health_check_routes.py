"""URL Health Check HTTP routes — FastAPI + SSE.

Endpoints (mount dưới prefix /api/hc):
  GET  /api/hc/presets          -> list URL preset từ health_check.URLS
  POST /api/hc/start            -> bắt đầu job, trả job_id + stream_url
  GET  /api/hc/stream/{job_id}  -> SSE stream events cho job

Event types:
  legend   uid_to_url mapping ({uid: url}) ở đầu mỗi run
  section  phân đoạn phase (PHASE-1, PHASE-2, ...)
  log      1 dòng log của 1 URL: uid, step, message, dt_ms
  result   kết quả cuối của 1 URL: status, status_code, response_time_ms, via
  summary  tổng kết toàn bộ run: total_ms
  error    lỗi không thể phục hồi
  done     sentinel đánh dấu kết thúc stream
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import health_check as hc

router = APIRouter(prefix="/api/hc", tags=["health-check"])

# Lưu queue của các job đang chạy: job_id -> asyncio.Queue[dict | None]
_active_jobs: dict[str, asyncio.Queue] = {}


class CheckRequest(BaseModel):
    urls: list[str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/presets")
async def get_presets():
    """Trả về danh sách URL preset từ health_check.URLS."""
    return {"urls": hc.URLS}


@router.post("/start")
async def start_check(req: CheckRequest):
    """Tạo job mới. Trả job_id để client subscribe SSE stream."""
    if not req.urls:
        raise HTTPException(status_code=422, detail="urls list is empty")

    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _active_jobs[job_id] = queue
    asyncio.create_task(_run_job(job_id, req.urls, queue))

    return {
        "job_id": job_id,
        "stream_url": f"/api/hc/stream/{job_id}",
        "started_at": _now(),
        "url_count": len(req.urls),
    }


@router.get("/stream/{job_id}")
async def stream_job(job_id: str):
    """SSE endpoint: stream events cho đến khi job hoàn thành."""
    if job_id not in _active_jobs:
        raise HTTPException(status_code=404, detail="Job not found or already completed")

    queue = _active_jobs[job_id]

    async def event_generator():
        try:
            while True:
                item = await queue.get()
                if item is None:  # done sentinel
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            _active_jobs.pop(job_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _run_job(job_id: str, urls: list[str], queue: asyncio.Queue) -> None:
    """
    Chạy check_urls() trong background task.
    Inject custom log function qua ContextVar (_log_fn) để capture mọi
    log event từ health_check — không có side-effect với các job khác
    nhờ asyncio ContextVar isolation.
    """
    t_start = datetime.now(timezone.utc)

    def emit(event: dict) -> None:
        """Đưa event vào queue để SSE stream."""
        event.setdefault("type", "log")
        event["job_id"] = job_id
        event.setdefault("timestamp", _now())
        queue.put_nowait(event)

    # Ghi đè log function cho task này (ContextVar không ảnh hưởng task khác).
    token = hc._log_fn.set(emit)
    try:
        results = await hc.check_urls(urls)

        # Emit kết quả từng URL.
        for r in results:
            emit({
                "type": "result",
                "url": r.url,
                "uid": hc._uid(r.url),
                "status": r.status,
                "status_code": r.status_code,
                "response_time_ms": round(r.response_time * 1000, 1),
                "via": r.via,
                "step": "RESULT",
                "message": str(r),
                "dt_ms": None,
                "phase": "summary",
            })

        # Emit tổng kết.
        total_ms = (datetime.now(timezone.utc) - t_start).total_seconds() * 1000
        valid_n = sum(1 for r in results if r.status == "valid")
        dead_n = sum(1 for r in results if r.status == "dead")
        blocked_n = sum(1 for r in results if r.status == "blocked")
        error_n = sum(1 for r in results if r.status == "error")
        emit({
            "type": "summary",
            "url": None,
            "uid": "----",
            "step": "SUMMARY",
            "message": (
                f"{len(results)} URLs — "
                f"{valid_n} valid, {dead_n} dead, "
                f"{blocked_n} blocked, {error_n} error"
            ),
            "dt_ms": None,
            "total_ms": round(total_ms, 1),
            "phase": "summary",
            "counts": {
                "valid": valid_n,
                "dead": dead_n,
                "blocked": blocked_n,
                "error": error_n,
                "total": len(results),
            },
        })

    except Exception as exc:
        emit({
            "type": "error",
            "url": None,
            "uid": "----",
            "step": "FATAL",
            "message": f"{type(exc).__name__}: {exc}",
            "dt_ms": None,
            "phase": "error",
        })
    finally:
        hc._log_fn.reset(token)
        queue.put_nowait(None)  # done sentinel

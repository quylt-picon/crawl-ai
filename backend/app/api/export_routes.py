"""Persist the Web Search + Crawl run history to a JSON file.

The history lives in the browser's localStorage, so only the browser can read
it. This endpoint receives that array from the UI and writes it to a JSON file
in the frontend's public/ folder (so it is also served at /<filename> by the
dev server). Purely additive — independent of the search pipelines.

POST /api/sitecrawl/export   body: {"runs": [...], "filename": "optional.json"}
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/api/sitecrawl", tags=["sitecrawl-export"])

_log = get_logger(__name__)

_DEFAULT_FILENAME = "sitecrawl-history.json"


class ExportRequest(BaseModel):
    runs: list[Any] = Field(default_factory=list)
    filename: Optional[str] = None


@router.post("/export")
async def export_history(payload: ExportRequest) -> dict:
    export_dir = _resolve_export_dir()
    filename = _safe_filename(payload.filename)
    path = export_dir / filename
    body = json.dumps(payload.runs, ensure_ascii=False, indent=2)
    try:
        export_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"cannot write {path}: {exc}")

    _log.info("Exported %d run(s) to %s", len(payload.runs), path)
    return {
        "path": str(path),
        "filename": filename,
        "served_url": f"/{filename}",
        "count": len(payload.runs),
        "bytes": len(body.encode("utf-8")),
    }


def _resolve_export_dir() -> Path:
    """Target directory for the export.

    Defaults to the frontend's ``public/`` folder (resolved from this file's
    location, so it is independent of the working directory), overridable via
    ``SITECRAWL_EXPORT_DIR``.
    """
    settings = get_settings()
    configured = settings.sitecrawl_export_dir.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    # backend/app/api/export_routes.py → parents[3] is the repo root.
    return Path(__file__).resolve().parents[3] / "frontend" / "public"


def _safe_filename(name: Optional[str]) -> str:
    """Force a safe, single-segment ``*.json`` filename (no path traversal)."""
    base = os.path.basename((name or "").strip()) or _DEFAULT_FILENAME
    if not base.lower().endswith(".json"):
        base += ".json"
    return base

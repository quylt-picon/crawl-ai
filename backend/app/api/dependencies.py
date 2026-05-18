"""FastAPI Depends() providers — wire singletons into routes."""
from __future__ import annotations

from app.core.config import Settings, get_settings
from app.events.bus import EventBus, get_event_bus
from app.services.workflow import WorkflowOrchestrator, get_orchestrator

__all__ = [
    "Settings",
    "get_settings",
    "EventBus",
    "get_event_bus",
    "WorkflowOrchestrator",
    "get_orchestrator",
]

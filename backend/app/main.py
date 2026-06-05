"""FastAPI entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health_check_routes import router as health_check_router
from app.api.routes import router as crawl_router
from app.api.websearch_routes import router as websearch_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    log = get_logger("app.main")
    log.info("API starting on %s:%d", settings.app_host, settings.app_port)
    yield
    log.info("API shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Product Manual Finder API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(crawl_router)
    app.include_router(websearch_router)
    app.include_router(health_check_router)
    return app


app = create_app()

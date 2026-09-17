from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.api.workflow import router as workflow_router
from app.config import get_settings
from app.database import Base, engine
from app.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("orthocode.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.app_env.lower() in {"development", "test"}:
        Base.metadata.create_all(bind=engine)
    logger.info("api_started", extra={"status": "ready"})
    yield


app = FastAPI(
    title="OrthoCode AI API",
    description="Evidence-first orthopedic coding platform",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(workflow_router)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.monotonic()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request_complete",
        extra={
            "request_id": request_id,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "status": response.status_code,
        },
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "orthocode-api", "phase": "coding-workflow"}

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from redis import Redis

from app.config import get_settings
from app.database import SessionLocal
from app.reference_data.pipeline import import_reference_bundle

QUEUE_NAME = "orthocode:jobs:queued"
PROCESSING_NAME = "orthocode:jobs:processing"


def enqueue_reference_import(payload: dict[str, Any]) -> str:
    return enqueue_job("reference_import", payload)


def enqueue_chart_processing(chart_id: str) -> str:
    return enqueue_job("chart_processing", {"chart_id": chart_id})


def enqueue_job(job_type: str, payload: dict[str, Any]) -> str:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is not configured")
    job_id = str(uuid.uuid4())
    job = {"id": job_id, "type": job_type, "payload": payload}
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    redis.hset(f"orthocode:job:{job_id}", mapping={"status": "queued", "type": job["type"]})
    redis.rpush(QUEUE_NAME, json.dumps(job))
    return job_id


def run_reference_import_job(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    source_root = Path(payload.get("source_root") or settings.reference_data_path)
    effective = date.fromisoformat(
        payload.get("effective_from") or settings.reference_release_effective_from
    )
    with SessionLocal() as session:
        materialize_ncci = payload.get("materialize_ncci")
        if materialize_ncci is None:
            materialize_ncci = session.get_bind().dialect.name != "sqlite"
        return import_reference_bundle(
            session,
            source_root,
            payload.get("release_name") or settings.reference_release_name,
            effective,
            dry_run=bool(payload.get("dry_run")),
            publish=bool(payload.get("publish")),
            materialize_ncci=bool(materialize_ncci),
            ncci_index_path=settings.ncci_index_path if not materialize_ncci else None,
        )


def run_chart_processing_job(payload: dict[str, Any]) -> dict[str, Any]:
    from app.coding.processing import process_chart

    return process_chart(str(payload["chart_id"]))


def get_job(job_id: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.redis_url:
        return None
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    values = redis.hgetall(f"orthocode:job:{job_id}")
    if not values:
        return None
    if "result" in values:
        values["result"] = json.loads(values["result"])
    return values

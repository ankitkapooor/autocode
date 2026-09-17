from __future__ import annotations

import json
import logging
import time

from redis import Redis

from app.config import get_settings
from app.jobs import (
    PROCESSING_NAME,
    QUEUE_NAME,
    run_chart_processing_job,
    run_reference_import_job,
)
from app.logging import configure_logging


def run() -> None:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("Worker requires REDIS_URL")
    configure_logging(settings.log_level)
    logger = logging.getLogger("orthocode.worker")
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("worker_started")
    while True:
        raw = redis.brpoplpush(QUEUE_NAME, PROCESSING_NAME, timeout=10)
        if raw is None:
            continue
        job = json.loads(raw)
        job_id = job["id"]
        key = f"orthocode:job:{job_id}"
        redis.hset(key, mapping={"status": "running"})
        started = time.monotonic()
        try:
            if job["type"] == "reference_import":
                result = run_reference_import_job(job["payload"])
            elif job["type"] == "chart_processing":
                result = run_chart_processing_job(job["payload"])
            else:
                raise ValueError(f"Unsupported job type: {job['type']}")
            redis.hset(
                key,
                mapping={"status": "complete", "result": json.dumps(result, default=str)},
            )
            logger.info(
                "job_complete",
                extra={"job_id": job_id, "duration_ms": round((time.monotonic() - started) * 1000)},
            )
        except Exception as exc:
            redis.hset(key, mapping={"status": "failed", "error": str(exc)})
            logger.exception("job_failed", extra={"job_id": job_id})
        finally:
            redis.lrem(PROCESSING_NAME, 1, raw)


if __name__ == "__main__":
    run()

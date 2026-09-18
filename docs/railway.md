# Railway deployment

Create separate Railway services for `web`, `api`, and `worker`, plus PostgreSQL and Redis. Build `web` from `frontend/Dockerfile`; build `api` and `worker` from `backend/Dockerfile`, overriding the worker start command with `python -m app.workers`.

Required API/worker variables include `DATABASE_URL`, `REDIS_URL`, `REFERENCE_DATA_PATH`, `APP_ENV`, `PHI_MODE`, and storage configuration. Decision configuration is shared by API and worker: use `CODING_DECISION_ENGINE=jev_primary`, `JEV_ENABLED=true`, `JEV_BASE_URL=https://api.typesafe.ai`, `JEV_MODEL=jev-latest`, `JEV_ACCEPT_THRESHOLD=0.80`, `JEV_REVIEW_THRESHOLD=0.50`, and `AUTONOMOUS_CODING_ENABLED=false`. Configure `JEV_API_KEY` and the approved `JEV_PHI_ALLOWED` value before processing charts. `legacy_llm` remains the explicit rollback mode. The web service needs only `NEXT_PUBLIC_API_URL`.

Reference data should be supplied through a private mounted volume or a controlled import job. Licensed CPT source material must not be copied into the repository, Docker image, or frontend. Run migrations before the API and worker receive traffic. The API health check is `/health`.

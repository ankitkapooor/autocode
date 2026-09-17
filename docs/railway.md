# Railway deployment

Create separate Railway services for `web`, `api`, and `worker`, plus PostgreSQL and Redis. Build `web` from `frontend/Dockerfile`; build `api` and `worker` from `backend/Dockerfile`, overriding the worker start command with `python -m app.workers`.

Required API/worker variables include `DATABASE_URL`, `REDIS_URL`, `REFERENCE_DATA_PATH`, `APP_ENV`, `PHI_MODE`, and storage configuration. The web service needs only `NEXT_PUBLIC_API_URL`.

Reference data should be supplied through a private mounted volume or a controlled import job. Licensed CPT source material must not be copied into the repository, Docker image, or frontend. Run migrations before the API and worker receive traffic. The API health check is `/health`.

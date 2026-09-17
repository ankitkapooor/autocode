FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./
COPY migrations ./migrations

RUN pip install .

RUN useradd --create-home --uid 10001 orthocode && chown -R orthocode:orthocode /app
USER orthocode

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

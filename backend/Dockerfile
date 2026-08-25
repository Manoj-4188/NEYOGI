# NEYOGI backend + Celery worker.
# One image serves both roles; docker-compose overrides the command.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq for psycopg, curl for the container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so the layer caches across source edits.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# The API imports ml_pipeline directly (indices, GAUL resolution, supply
# arithmetic), so both packages ship in the image.
COPY backend ./backend
COPY ml_pipeline ./ml_pipeline

# Reference configs and model artifacts. The compose file also bind-mounts
# ./data so a model trained on the host is picked up without a rebuild.
COPY data ./data

# Operational diagnostics (scripts/README.md documents them). Small, and they
# are referenced by path in the docs, so they belong in the image.
COPY scripts ./scripts

# Run unprivileged.
RUN useradd --create-home --uid 10001 neyogi \
    && chown -R neyogi:neyogi /app
USER neyogi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

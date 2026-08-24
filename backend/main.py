"""NEYOGI FastAPI application.

Start-up applies the idempotent schema and seeds officer accounts, then opens
the PostGIS pool. A start-up failure is logged and re-raised: serving requests
against a database that is not migrated would produce confidently wrong
answers, which is worse than being down.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend import db, security
from backend.api.v1.router import api_router
from backend.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("neyogi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    try:
        await db.apply_schema()
        await security.seed_officer_accounts()
    except Exception:
        logger.exception("Start-up initialisation failed")
        await db.close_pool()
        raise
    logger.info("NEYOGI API ready (environment=%s)", settings.environment)
    try:
        yield
    finally:
        await db.close_pool()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "GIS platform for perishable-crop market intelligence in Karnataka.\n\n"
        "Every response that carries data also carries a `status` object naming "
        "the source and its age. Cached data is never presented as live, and "
        "districts without verified ground truth are never classified."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["meta"], summary="Liveness and dependency health")
async def health() -> JSONResponse:
    database = await db.health_check()
    payload = {
        "service": "neyogi-api",
        "version": "1.0.0",
        "environment": settings.environment,
        "time": datetime.now(tz=timezone.utc).isoformat(),
        "dependencies": [database],
        "configured": {
            "agmarknet": settings.agmarknet_configured,
            "twilio": settings.twilio_configured,
            "earth_engine": bool(
                settings.gee_service_account_email or settings.gee_project_id
            ),
        },
    }
    healthy = bool(database.get("healthy"))
    return JSONResponse(payload, status_code=200 if healthy else 503)


@app.get("/", tags=["meta"], include_in_schema=False)
async def root() -> dict:
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "health": "/health",
        "api": settings.api_v1_prefix,
    }

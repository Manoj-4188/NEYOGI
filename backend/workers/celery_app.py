"""Celery application and beat schedule.

The worker runs the scheduled halves of the pipeline: Sentinel-2 ingestion,
AGMARKNET refresh, weekly farmer briefings, and the WhatsApp retry queue.

Async helpers from the API layer are reused by opening a short-lived PostGIS
pool per task via :func:`run_async`. Tasks are infrequent and the pool is
cheap, and sharing one code path with the API means a query cannot behave
differently in the worker than it does in a request.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from celery import Celery
from celery.schedules import crontab

from backend.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "neyogi",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["backend.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    # Earth Engine ingestion is slow; give it room but bound it.
    task_soft_time_limit=45 * 60,
    task_time_limit=50 * 60,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    # Sentinel-2 revisit is ~5 days; a daily run keeps the 16-day composites
    # current without hammering the Earth Engine quota.
    "ingest-sentinel2-daily": {
        "task": "neyogi.ingest_composites",
        "schedule": crontab(hour=2, minute=30),
    },
    # AGMARKNET publishes through the day; refresh in the evening so the cache
    # holds a complete day before the morning briefings.
    "refresh-mandi-prices": {
        "task": "neyogi.refresh_prices",
        "schedule": crontab(hour=19, minute=0),
    },
    "classify-verified-parcels": {
        "task": "neyogi.classify_districts",
        "schedule": crontab(hour=4, minute=0),
    },
    # Monday morning advisory.
    "weekly-farmer-briefings": {
        "task": "neyogi.send_weekly_briefings",
        "schedule": crontab(day_of_week=1, hour=7, minute=0),
    },
    # Safety net for messages whose retry task was lost with the broker.
    "sweep-outbound-queue": {
        "task": "neyogi.sweep_outbound_queue",
        "schedule": crontab(minute="*/15"),
    },
}


def run_async(factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run an async task body with a PostGIS pool open for its duration."""
    from backend import db

    async def _runner() -> Any:
        await db.open_pool()
        try:
            return await factory()
        finally:
            await db.close_pool()

    return asyncio.run(_runner())

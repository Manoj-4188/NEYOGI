"""``/api/v1/classification/*`` -- district crop classification.

Serves the stored spectral-model classification. ``POST /run`` triggers a fresh
sampling run, which takes tens of seconds and so is never done implicitly on a
page load.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status as http_status

from backend import db
from backend.services import classification

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/classification", tags=["classification"])


@router.get("/district", summary="Latest spectral crop classification")
async def district_classification(
    district: Annotated[str, Query(description="District name")],
) -> dict:
    try:
        return await classification.get_classification(district)
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc


@router.post("/run", summary="Run classification for a district now")
async def run_classification(
    district: Annotated[str, Query(description="District name")],
    samples: Annotated[int, Query(ge=50, le=2000)] = 400,
) -> dict:
    """Sample and classify the district's cropland.

    Runs in a worker thread: Earth Engine sampling is blocking and would
    otherwise stall the event loop for the whole request.
    """
    from anyio import to_thread

    try:
        return await to_thread.run_sync(
            classification.run_classification_sync, district, samples
        )
    except Exception as exc:  # noqa: BLE001 - ee and joblib raise many types
        logger.exception("Classification run failed for %s", district)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=f"Classification failed: {exc}",
        ) from exc

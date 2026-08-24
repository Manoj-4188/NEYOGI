"""``GET /api/v1/parcel/{id}/ndvi`` -- one parcel's index history."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status as http_status

from backend import db
from backend.services import parcels
from ml_pipeline.feature_engineering import INDEX_NAMES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/parcel", tags=["parcel"])


@router.get("/{parcel_id}/ndvi", summary="Historical index time series for a parcel")
async def parcel_series(
    parcel_id: Annotated[int, Path(ge=1)],
    index: Annotated[
        str | None,
        Query(description=f"One of: {', '.join(INDEX_NAMES)}. Omit for all."),
    ] = None,
    since: Annotated[date | None, Query(description="Earliest composite date")] = None,
) -> dict:
    """Index values as observed. Windows with no cloud-free imagery are simply
    absent from the series -- gaps are gaps, not zeros."""
    if index and index not in INDEX_NAMES:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown index {index!r}. Supported: {', '.join(INDEX_NAMES)}",
        )

    try:
        payload = await parcels.parcel_time_series(
            parcel_id, index_name=index, since=since
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

    if not payload:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"No parcel with id {parcel_id}",
        )

    payload["notes"] = [
        "Absent dates had no cloud-free Sentinel-2 observation; values are "
        "never interpolated across a gap."
    ]
    return payload

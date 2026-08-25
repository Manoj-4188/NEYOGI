"""``GET /api/v1/infrastructure/cold-storage`` -- registered cold storage.

Answers the question an oversupply warning raises: if the belt is projected to
produce more than the mandi absorbs, where could a grower hold the crop
instead of dumping it?

Licensed capacity only. See ``backend/services/cold_storage.py`` for why free
space is not, and cannot honestly be, reported.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status as http_status

from backend import db
from backend.services import cold_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/infrastructure", tags=["infrastructure"])


@router.get("/cold-storage", summary="Cold storage facilities registered in a district")
async def cold_storage_for_district(
    district: Annotated[str, Query(description="GAUL district name")],
) -> dict:
    try:
        return await cold_storage.get_cold_storage(district)
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

"""``GET /api/v1/forecast/supply`` -- supply projection and oversupply ratio."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status as http_status

from backend import db
from backend.config import settings
from backend.services import supply

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/supply", summary="Projected supply versus observed mandi arrivals")
async def supply_forecast(
    district: Annotated[str, Query(description="GAUL district name")],
    window_days: Annotated[
        int | None, Query(ge=1, le=180, description="Comparison window in days")
    ] = None,
) -> dict:
    """Projected volume = classified area x verified baseline yield.

    Any crop without a verified yield constant reports
    ``YIELD_BASELINE_UNAVAILABLE`` and its measured area, but no tonnage. Any
    crop with no published mandi arrivals reports
    ``INSUFFICIENT_ARRIVAL_DATA`` and no ratio.
    """
    try:
        return await supply.district_forecast(
            district, window_days=window_days or settings.supply_window_days
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc


@router.get("/best-markets", summary="Markets ranked by net profit after haulage")
async def best_markets(
    district: Annotated[str, Query(description="District the produce ships from")],
    crop_type: Annotated[str, Query(description="tomato | onion | potato | leafy_greens")],
    quantity_quintals: Annotated[
        float, Query(gt=0, le=100000, description="Quantity to sell, in quintals")
    ],
    top: Annotated[int, Query(ge=1, le=10)] = 3,
) -> dict:
    """Rank markets on ``(price x quantity) - (distance x 2.5 x quantity / 10)``.

    Only markets with a real published quote are ranked. When AGMARKNET has
    published nothing for the crop, the list comes back empty with a status
    explaining why rather than with markets scored on assumed prices.
    """
    from backend.services import markets as market_service

    try:
        return await market_service.best_markets(
            district=district,
            crop=crop_type,
            quantity_quintals=quantity_quintals,
            top_n=top,
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

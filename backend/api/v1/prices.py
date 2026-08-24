"""``GET /api/v1/prices/mandi`` -- live AGMARKNET with a 30-day cached fallback."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status as http_status

from backend import db, status
from backend.services import agmarknet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("/mandi", summary="Mandi prices, live or cached")
async def mandi_prices(
    district: Annotated[str, Query(description="District name")],
    crop: Annotated[
        str | None, Query(description="Tomato | Onion | Potato | Leafy Greens")
    ] = None,
    include_average: Annotated[
        bool, Query(description="Include the 30-day moving average")
    ] = True,
) -> dict:
    if crop and crop not in agmarknet.CROP_TO_COMMODITIES:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown crop {crop!r}. Supported: "
                f"{', '.join(agmarknet.CROP_TO_COMMODITIES)}"
            ),
        )

    try:
        quotes, badge = await agmarknet.get_prices(district, crop)
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

    badges = status.StatusSet().add(badge)

    averages: dict[str, dict | None] = {}
    if include_average:
        crops = [crop] if crop else list(agmarknet.CROP_TO_COMMODITIES)
        for name in crops:
            try:
                averages[name] = await agmarknet.moving_average(district, name)
            except db.DatabaseUnavailable:
                averages[name] = None

    return {
        "district": district,
        "crop": crop,
        "quotes": [q.to_dict() for q in quotes],
        "quote_count": len(quotes),
        "moving_average_30d": averages,
        "status": badges.to_dict(),
        "notes": [
            "Prices are in INR per quintal, as published by AGMARKNET via "
            "data.gov.in.",
            "arrival_volume_mt is null where the upstream feed did not publish "
            "arrival tonnage; it is never inferred from price movement.",
        ],
    }

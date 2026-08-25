"""``GET /api/v1/prices/mandi`` -- live AGMARKNET with a 30-day cached fallback."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status as http_status

from backend import db, status
from backend.services import agmarknet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("/history", summary="Daily modal price series per crop")
async def price_history(
    district: Annotated[str, Query(description="District name")],
    days: Annotated[int, Query(ge=7, le=365)] = 90,
) -> dict:
    """One row per date, with a column per crop, for the dashboard chart.

    Dates with no published quote are simply absent, and crops with no quote on
    a present date are ``null``. The chart leaves both as gaps rather than
    interpolating a price nobody recorded.
    """
    from datetime import datetime, timedelta, timezone

    since = datetime.now(tz=timezone.utc).date() - timedelta(days=days)
    try:
        rows = await db.fetch_all(
            """
            SELECT arrival_date, crop, AVG(modal_price)::float
            FROM mandi_prices_cache
            WHERE district = %s AND arrival_date >= %s AND modal_price IS NOT NULL
            GROUP BY arrival_date, crop
            ORDER BY arrival_date
            """,
            (district, since),
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

    # Crop names are folded to the classifier's vocabulary so the chart series
    # keys line up with what the classification card shows.
    key_for = {
        "Tomato": "tomato",
        "Onion": "onion",
        "Potato": "potato",
        "Leafy Greens": "leafy_greens",
    }

    by_date: dict[str, dict] = {}
    for arrival_date, crop, price in rows:
        iso = arrival_date.isoformat()
        entry = by_date.setdefault(iso, {"date": iso})
        key = key_for.get(crop, str(crop).lower().replace(" ", "_"))
        entry[key] = round(float(price), 2)

    return {
        "district": district,
        "window_days": days,
        "series": [by_date[k] for k in sorted(by_date)],
        "point_count": len(by_date),
        "notes": [
            "Dates with no published quote are absent from the series; they "
            "are never interpolated.",
        ],
    }


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

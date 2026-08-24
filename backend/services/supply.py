"""Supply forecast assembly for the API.

Bridges the deterministic arithmetic in ``ml_pipeline.supply_estimation`` to the
live database: measured classified area on one side, observed mandi arrivals on
the other. This module adds no modelling of its own -- it gathers the two
measured inputs, calls the arithmetic, and attaches the badges.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from backend import db, status
from backend.config import settings
from backend.services import agmarknet, parcels
from ml_pipeline import supply_estimation as se

logger = logging.getLogger(__name__)


async def arrivals_by_crop(
    district: str, crops: list[str], window_days: int
) -> dict[str, float | None]:
    """Observed arrival tonnage per crop over the window.

    A crop maps to ``None`` when AGMARKNET published no arrival figures -- which
    is common, and is reported as such rather than as zero arrivals.
    """
    out: dict[str, float | None] = {}
    for crop in crops:
        try:
            out[crop] = await agmarknet.total_arrivals_mt(district, crop, window_days)
        except db.DatabaseUnavailable as exc:
            logger.warning("Could not read arrivals for %s/%s: %s", district, crop, exc)
            out[crop] = None
    return out


async def daily_series(
    district: str, crop: str, window_days: int
) -> list[dict]:
    """Per-day observed arrivals and modal price, for the dashboard chart.

    Days with no published quote are omitted rather than zero-filled, so the
    chart shows a gap where the feed was silent.
    """
    since = datetime.now(tz=timezone.utc).date() - timedelta(days=window_days)
    rows = await db.fetch_all(
        """
        SELECT arrival_date,
               AVG(modal_price)::float,
               SUM(arrival_volume)::float,
               COUNT(*) FILTER (WHERE arrival_volume IS NOT NULL)
        FROM mandi_prices_cache
        WHERE district = %s AND crop = %s AND arrival_date >= %s
        GROUP BY arrival_date
        ORDER BY arrival_date
        """,
        (district, crop, since),
    )
    return [
        {
            "date": r[0].isoformat(),
            "modal_price": round(r[1], 2) if r[1] is not None else None,
            "arrival_volume_mt": round(r[2], 3) if r[3] else None,
        }
        for r in rows
    ]


async def district_forecast(
    district: str, window_days: int | None = None
) -> dict:
    """Full supply forecast for a district, with badges for every gap."""
    window_days = window_days or settings.supply_window_days
    as_of = datetime.now(tz=timezone.utc).date()

    validation = await parcels.district_validation(district)
    badges = status.StatusSet().add(validation.badge())

    if not validation.is_validated:
        # No verified ground truth -> no classified area -> no supply claim.
        forecast = se.forecast_district(
            district, area_by_crop={}, window_days=window_days, as_of=as_of
        )
        payload = forecast.to_dict()
        payload["status"] = badges.to_dict()
        payload["daily_series"] = {}
        return payload

    area_by_crop, parcel_counts = await parcels.classified_area_by_crop(district)
    marketable = [c for c in area_by_crop if c != "Fallow/Non-Crop"]
    arrivals = await arrivals_by_crop(district, marketable, window_days)

    try:
        document = se.load_baseline_document()
    except se.YieldBaselineUnavailable as exc:
        logger.error("Yield baseline document unusable: %s", exc)
        document = {"defaults": {}, "districts": {}}

    forecast = se.forecast_district(
        district,
        area_by_crop=area_by_crop,
        parcels_by_crop=parcel_counts,
        arrivals_by_crop=arrivals,
        window_days=window_days,
        as_of=as_of,
        document=document,
    )

    # Market badge reflects how fresh the arrivals/prices behind the ratio are.
    newest_quote = await db.fetch_one(
        "SELECT MAX(arrival_date) FROM mandi_prices_cache WHERE district = %s",
        (district,),
    )
    quote_date = newest_quote[0] if newest_quote and newest_quote[0] else None
    if quote_date is None:
        badges.add(
            status.market_unavailable(
                f"No cached mandi quotes for {district}; the supply/demand ratio "
                "has no denominator."
            )
        )
    else:
        age = (as_of - quote_date).days
        badges.add(
            status.market_live(quote_date)
            if age <= 1
            else status.market_cached(quote_date)
        )

    series: dict[str, list[dict]] = {}
    for crop in marketable:
        series[crop] = await daily_series(district, crop, window_days)

    payload = forecast.to_dict()
    payload["status"] = badges.to_dict()
    payload["daily_series"] = series
    payload["window_days"] = window_days
    return payload

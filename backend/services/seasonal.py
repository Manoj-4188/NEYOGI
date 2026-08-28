"""Year-on-year comparison: this season's harvest against last year's demand.

Answers the question a grower actually asks before harvesting -- "is more
coming off the field than last year, and did the market absorb that much?" --
by putting two things side by side:

* **Projected production now**, from the current classification.
* **What the mandi absorbed in the same weeks last year**, from cached
  arrivals.

Both halves need history the platform has to accumulate. Nothing here
back-fills it: with an empty price cache the comparison reports what is
missing rather than inventing a baseline, and it starts working once a year of
arrivals has been collected. That is a real wait, and saying so is more useful
than a chart drawn from nothing.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from backend import db

logger = logging.getLogger(__name__)

#: Widen the last-year window by this much either side. Sowing shifts with the
#: monsoon, so the same calendar fortnight is not the same crop stage; a
#: fortnight of slack absorbs the drift without blurring the season.
YEAR_MATCH_SLACK_DAYS = 14


async def _arrivals_between(
    district: str, crop: str, start: date, end: date
) -> tuple[float | None, int]:
    """Total arrivals and the number of days that reported any, in a window."""
    row = await db.fetch_one(
        """
        SELECT SUM(arrival_volume)::float,
               COUNT(*) FILTER (WHERE arrival_volume IS NOT NULL)
        FROM mandi_prices_cache
        WHERE district = %s AND crop = %s
          AND arrival_date >= %s AND arrival_date <= %s
        """,
        (district, crop, start, end),
    )
    if not row or not row[1]:
        return None, 0
    return row[0], int(row[1])


async def _mean_price_between(
    district: str, crop: str, start: date, end: date
) -> tuple[float | None, int]:
    row = await db.fetch_one(
        """
        SELECT AVG(modal_price)::float,
               COUNT(*) FILTER (WHERE modal_price IS NOT NULL)
        FROM mandi_prices_cache
        WHERE district = %s AND crop = %s
          AND arrival_date >= %s AND arrival_date <= %s
        """,
        (district, crop, start, end),
    )
    if not row or not row[1]:
        return None, 0
    return row[0], int(row[1])


async def year_on_year(
    district: str, window_days: int = 21, as_of: date | None = None
) -> dict:
    """Compare the current window against the same weeks a year earlier."""
    as_of = as_of or datetime.now(tz=timezone.utc).date()
    current_start = as_of - timedelta(days=window_days)

    # Same calendar window one year back, widened for sowing drift.
    prior_end = as_of - timedelta(days=365) + timedelta(days=YEAR_MATCH_SLACK_DAYS)
    prior_start = (
        current_start - timedelta(days=365) - timedelta(days=YEAR_MATCH_SLACK_DAYS)
    )

    # Current production comes from the latest classification, priced through
    # the same verified yield constants the supply forecast uses.
    from ml_pipeline import supply_estimation as se

    try:
        rows = await db.fetch_all(
            """
            SELECT crop, area_ha, mean_confidence
            FROM district_classification_latest
            WHERE district = %s
            """,
            (district,),
        )
    except db.DatabaseUnavailable as exc:
        logger.warning("Year-on-year classification lookup failed: %s", exc)
        rows = []

    display = {
        "tomato": "Tomato",
        "onion": "Onion",
        "potato": "Potato",
        "leafy_greens": "Leafy Greens",
    }
    try:
        document = se.load_baseline_document()
    except se.YieldBaselineUnavailable:
        document = {"defaults": {}, "districts": {}}

    crops: list[dict] = []
    for raw_crop, area_ha, confidence in rows:
        name = display.get(str(raw_crop))
        if not name:
            continue

        projected = None
        try:
            baseline = se.get_yield_baseline(name, district=district, document=document)
            projected = se.projected_volume_mt(float(area_ha), baseline.value_mt_ha)
        except se.YieldBaselineUnavailable:
            pass

        prior_arrivals, prior_days = await _arrivals_between(
            district, name, prior_start, prior_end
        )
        current_arrivals, current_days = await _arrivals_between(
            district, name, current_start, as_of
        )
        prior_price, prior_price_days = await _mean_price_between(
            district, name, prior_start, prior_end
        )
        current_price, current_price_days = await _mean_price_between(
            district, name, current_start, as_of
        )

        if prior_arrivals and projected:
            ratio = projected / prior_arrivals
            status = "OK"
            detail = (
                f"{projected:,.0f} MT projected this season against "
                f"{prior_arrivals:,.0f} MT the mandi absorbed in the same weeks "
                "last year."
            )
        elif not prior_arrivals:
            ratio = None
            status = "NO_PRIOR_YEAR_DATA"
            detail = (
                "No mandi arrivals are cached for this district and crop a year "
                "ago. The comparison needs a year of collected history and "
                "starts working once the price feed has been running that long."
            )
        else:
            ratio = None
            status = "NO_PROJECTION"
            detail = (
                "Classified area exists but no verified yield baseline, so this "
                "season's production cannot be projected for comparison."
            )

        price_change = None
        if prior_price and current_price:
            price_change = (current_price - prior_price) / prior_price

        crops.append(
            {
                "crop": name,
                "status": status,
                "classified_area_ha": round(float(area_ha), 1),
                "mean_confidence": round(float(confidence), 3),
                "projected_volume_mt": (
                    round(projected, 1) if projected is not None else None
                ),
                "prior_year_arrivals_mt": (
                    round(prior_arrivals, 1) if prior_arrivals else None
                ),
                "prior_year_reporting_days": prior_days,
                "current_arrivals_mt": (
                    round(current_arrivals, 1) if current_arrivals else None
                ),
                "current_reporting_days": current_days,
                "vs_prior_year_ratio": round(ratio, 3) if ratio is not None else None,
                "prior_year_mean_price": (
                    round(prior_price, 2) if prior_price else None
                ),
                "current_mean_price": (
                    round(current_price, 2) if current_price else None
                ),
                "price_change_pct": (
                    round(price_change * 100, 1) if price_change is not None else None
                ),
                "detail": detail,
            }
        )

    comparable = [c for c in crops if c["status"] == "OK"]
    notes: list[str] = []
    if crops and not comparable:
        notes.append(
            "Nothing is comparable yet. The platform has no mandi arrivals from "
            "a year ago, because the price feed has not been collecting that "
            "long. This fills in on its own as history accumulates."
        )
    if not crops:
        notes.append(
            f"No classification stored for {district}, so there is no current "
            "production to compare against."
        )

    return {
        "district": district,
        "current_window": {"start": current_start.isoformat(), "end": as_of.isoformat()},
        "prior_window": {"start": prior_start.isoformat(), "end": prior_end.isoformat()},
        "slack_days": YEAR_MATCH_SLACK_DAYS,
        "crops": crops,
        "comparable": len(comparable),
        "notes": notes,
    }

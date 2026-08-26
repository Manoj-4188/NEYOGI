"""Supply forecast assembly for the API.

Bridges the deterministic arithmetic in ``ml_pipeline.supply_estimation`` to the
live database: measured classified area on one side, observed mandi arrivals on
the other. This module adds no modelling of its own -- it gathers the two
measured inputs, calls the arithmetic, and attaches the badges.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

from backend import db, status
from backend.config import settings
from backend.services import agmarknet, parcels
from ml_pipeline import supply_estimation as se

logger = logging.getLogger(__name__)

#: A spectral class must clear this mean confidence before its area is allowed
#: to drive a projected tonnage. The classifier chooses between four classes,
#: so chance alone scores 0.25; anything under this floor is close enough to a
#: coin toss that multiplying it by a yield constant would manufacture a
#: precise-looking number out of a guess.
MIN_AREA_CONFIDENCE = float(os.getenv("MIN_AREA_CONFIDENCE", "0.5"))


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


async def _spectral_area_by_crop(district: str) -> tuple[dict, dict, list]:
    """Crop areas from the latest spectral classification.

    Returns ``({crop: hectares}, {crop: sample_count})`` using the platform's
    canonical crop names, so the yield lookup keys line up. The model's
    ``other`` class is dropped -- it is not a marketable crop and has no yield
    baseline.
    """
    display = {
        "tomato": "Tomato",
        "onion": "Onion",
        "potato": "Potato",
        "leafy_greens": "Leafy Greens",
    }
    try:
        rows = await db.fetch_all(
            """
            SELECT crop, area_ha, sample_count, mean_confidence
            FROM district_classification_latest
            WHERE district = %s
            """,
            (district,),
        )
    except db.DatabaseUnavailable as exc:
        logger.warning("Spectral area lookup failed for %s: %s", district, exc)
        return {}, {}, []

    areas: dict[str, float] = {}
    counts: dict[str, int] = {}
    low_confidence: list[tuple[str, float, float]] = []
    for crop, area_ha, sample_count, mean_confidence in rows:
        name = display.get(str(crop))
        if not name:
            continue

        # A tonnage claim inherits all the uncertainty of the area behind it.
        # The classifier picks between four classes, so chance alone scores
        # 0.25; below MIN_AREA_CONFIDENCE the class is barely better than a
        # coin toss and its area must not become a supply projection someone
        # acts on. The area itself is still shown on the classification card,
        # with its confidence beside it -- it is only barred from driving a
        # derived tonnage.
        if float(mean_confidence) < MIN_AREA_CONFIDENCE:
            logger.info(
                "Excluding %s in %s from the supply forecast: mean confidence "
                "%.2f is below the %.2f floor for a tonnage claim.",
                crop,
                district,
                float(mean_confidence),
                MIN_AREA_CONFIDENCE,
            )
            low_confidence.append(
                (str(crop), float(area_ha), float(mean_confidence))
            )
            continue

        areas[name] = float(area_ha)
        counts[name] = int(sample_count)
    return areas, counts, low_confidence


async def district_forecast(
    district: str, window_days: int | None = None
) -> dict:
    """Full supply forecast for a district, with badges for every gap."""
    window_days = window_days or settings.supply_window_days
    as_of = datetime.now(tz=timezone.utc).date()

    validation = await parcels.district_validation(district)
    badges = status.StatusSet().add(validation.badge())

    # Verified parcels are the preferred basis. Where none exist, fall back to
    # the spectral model's sample-extrapolated district areas so the forecast
    # is not silently blocked on a field survey that may never happen. The two
    # are never combined, and `area_basis` records which one produced the
    # numbers so the caller can weight them accordingly.
    area_by_crop, parcel_counts = await parcels.classified_area_by_crop(district)
    area_basis = "verified_parcels"

    if not area_by_crop:
        area_by_crop, parcel_counts, low_confidence = await _spectral_area_by_crop(
            district
        )
        area_basis = "spectral_model"
        if area_by_crop:
            badges.add(
                status.StatusBadge(
                    source=status.SourceKind.MODEL,
                    status=status.SourceStatus.CACHED,
                    severity=status.Severity.WARN,
                    label="SPECTRAL AREA",
                    detail=(
                        "Crop areas come from the spectral model's point sample, "
                        "not from field-verified parcels. Field verification "
                        "pending."
                    ),
                    is_fallback=True,
                )
            )
    marketable = [c for c in area_by_crop if c != "Fallow/Non-Crop"]
    arrivals = await arrivals_by_crop(district, marketable, window_days)

    try:
        document = se.load_baseline_document()
    except se.YieldBaselineUnavailable as exc:
        logger.error("Yield baseline document unusable: %s", exc)
        document = {"defaults": {}, "districts": {}}

    # A district whose classes were all filtered out has classified area --
    # it is just not confident enough to project from. Saying "no classified
    # area" there would blame the wrong thing and send someone to collect
    # imagery when the real need is a better-calibrated model.
    if not area_by_crop and low_confidence:
        forecast = se.forecast_district(
            district, area_by_crop={}, window_days=window_days, as_of=as_of
        )
        forecast.notes = [
            "Crop areas were classified for "
            + ", ".join(f"{c} ({a:,.0f} ha)" for c, a, _ in low_confidence)
            + ", but every class fell below the "
            f"{MIN_AREA_CONFIDENCE:.2f} confidence floor required before an "
            "area may drive a projected tonnage "
            + "("
            + ", ".join(f"{c} {conf:.2f}" for c, _, conf in low_confidence)
            + "). The areas are shown on the classification card; only the "
            "supply projection is withheld."
        ]
        payload = forecast.to_dict()
        payload["status"] = badges.to_dict()
        payload["daily_series"] = {}
        payload["area_basis"] = "spectral_model_below_confidence_floor"
        return payload

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
    payload["area_basis"] = area_basis
    return payload

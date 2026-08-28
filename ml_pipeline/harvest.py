"""Harvest-date estimation from the NDVI curve.

A field's NDVI rises through vegetative growth, plateaus at canopy closure,
then falls as the crop matures and dries. Harvest sits on that falling limb.
So given enough of the curve, the date can be estimated without knowing
anything about the field beyond its greenness history.

The method
----------
1. Build a district NDVI series, one point per 16-day composite.
2. Find the peak.
3. Estimate harvest as peak plus the crop's senescence interval, and
   cross-check against the observed decline rate where the curve has already
   started falling.

What it will not do
-------------------
**Estimate before the peak has passed.** A rising curve carries no information
about when it will turn; projecting one is guessing at the weather. If the
series is still climbing, or the peak sits at its very end where a later
observation could still exceed it, the estimate is refused with
``PEAK_NOT_REACHED``.

**Work from a handful of points.** Cloud cover leaves gaps, and a curve with
three observations can put its "peak" anywhere. Below a minimum number of
observations the answer is ``INSUFFICIENT_SERIES``.

**Speak for individual fields.** This is a district aggregate. Plantings are
staggered by weeks across a district, so the estimate describes the middle of
a distribution, not a date to send to one farmer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

logger = logging.getLogger(__name__)

#: Composites needed before a curve is worth reading. Four spans roughly two
#: months at a 16-day cadence -- enough to see a rise and a turn.
MIN_OBSERVATIONS = 4

#: A peak in the final position may not be a peak at all: the next observation
#: could be higher. It has to be followed by at least this many points before
#: it is treated as passed.
MIN_POINTS_AFTER_PEAK = 1

#: Days from peak NDVI to harvest, per crop. Senescence duration: the interval
#: between canopy maximum and the crop being taken off. Sourced alongside the
#: harvest spreads in data/reference/baseline_yields.yml.
SENESCENCE_DAYS: dict[str, int] = {
    "tomato": 30,        # picked repeatedly from first ripening
    "onion": 25,         # lifted once tops fall over
    "potato": 25,        # lifted after haulm dies back
    "leafy_greens": 10,  # cut young, close behind peak
}

#: Fraction of peak NDVI at which a crop is generally ready. Used to
#: cross-check the interval estimate against the observed decline.
HARVEST_NDVI_FRACTION = 0.65

#: Beyond this, projecting a decline rate forward stops meaning anything.
#: The slope is fitted to a couple of months of fortnightly points, and a
#: district curve is an average over staggered plantings, so extrapolating
#: it half a year ahead produces a date with no support behind it.
MAX_PROJECTION_DAYS = 60

#: Uncertainty grows with how far ahead the projection reaches. A quarter
#: of the projected distance is a blunt rule, but it beats quoting a
#: fortnight of precision on a three-month extrapolation.
PROJECTION_UNCERTAINTY_FRACTION = 0.25


@dataclass
class NdviPoint:
    observed_on: date
    ndvi: float
    scene_count: int = 0


@dataclass
class HarvestEstimate:
    district: str
    crop: str
    status: str
    observations: int = 0
    peak_date: date | None = None
    peak_ndvi: float | None = None
    latest_date: date | None = None
    latest_ndvi: float | None = None
    estimated_harvest: date | None = None
    #: Plus or minus, in days. Half a composite period at best: the curve is
    #: only sampled every 16 days, so the peak cannot be located finer.
    uncertainty_days: int | None = None
    method: str = ""
    detail: str = ""
    series: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "district": self.district,
            "crop": self.crop,
            "status": self.status,
            "observations": self.observations,
            "peak_date": self.peak_date.isoformat() if self.peak_date else None,
            "peak_ndvi": round(self.peak_ndvi, 4) if self.peak_ndvi is not None else None,
            "latest_date": self.latest_date.isoformat() if self.latest_date else None,
            "latest_ndvi": (
                round(self.latest_ndvi, 4) if self.latest_ndvi is not None else None
            ),
            "estimated_harvest": (
                self.estimated_harvest.isoformat() if self.estimated_harvest else None
            ),
            "days_from_now": (
                (self.estimated_harvest - date.today()).days
                if self.estimated_harvest
                else None
            ),
            "uncertainty_days": self.uncertainty_days,
            "method": self.method,
            "detail": self.detail,
            "series": [
                {"date": p.observed_on.isoformat(), "ndvi": round(p.ndvi, 4)}
                for p in self.series
            ],
        }


def estimate_harvest(
    district: str,
    crop: str,
    series: list[NdviPoint],
    composite_period_days: int = 16,
    today: date | None = None,
) -> HarvestEstimate:
    """Estimate a harvest date from an NDVI series.

    ``series`` need not be sorted; it is ordered here. Points are district
    means, one per composite window.
    """
    today = today or date.today()
    ordered = sorted(series, key=lambda p: p.observed_on)

    estimate = HarvestEstimate(
        district=district,
        crop=crop,
        status="OK",
        observations=len(ordered),
        series=ordered,
    )

    if len(ordered) < MIN_OBSERVATIONS:
        estimate.status = "INSUFFICIENT_SERIES"
        estimate.detail = (
            f"Only {len(ordered)} composite(s) available; at least "
            f"{MIN_OBSERVATIONS} are needed to locate a peak. Cloud cover "
            "leaves gaps in the series, so this fills in as the season clears."
        )
        return estimate

    senescence = SENESCENCE_DAYS.get(crop)
    if senescence is None:
        estimate.status = "NO_SENESCENCE_CONSTANT"
        estimate.detail = (
            f"No senescence interval is recorded for {crop!r}, so the gap "
            "between peak greenness and harvest is unknown."
        )
        return estimate

    peak_index = max(range(len(ordered)), key=lambda i: ordered[i].ndvi)
    peak = ordered[peak_index]
    latest = ordered[-1]

    estimate.peak_date = peak.observed_on
    estimate.peak_ndvi = peak.ndvi
    estimate.latest_date = latest.observed_on
    estimate.latest_ndvi = latest.ndvi

    points_after = len(ordered) - peak_index - 1
    if points_after < MIN_POINTS_AFTER_PEAK:
        estimate.status = "PEAK_NOT_REACHED"
        estimate.detail = (
            "The NDVI curve has not turned yet -- the highest value so far is "
            "the most recent one, so the canopy may still be filling. A rising "
            "curve says nothing about when it will peak, and projecting one "
            "would be guessing at the weather. This resolves once the curve "
            "starts falling."
        )
        return estimate

    # Primary estimate: a fixed interval after the peak.
    projected = peak.observed_on + timedelta(days=senescence)
    projection_days = senescence
    method = f"peak ({peak.observed_on}) + {senescence} days of senescence"

    # Cross-check: where the curve is already falling, project the observed
    # rate forward to the harvest threshold. This uses real decline rather
    # than an assumed interval, so it takes precedence when available.
    threshold = peak.ndvi * HARVEST_NDVI_FRACTION
    if latest.ndvi < peak.ndvi and latest.observed_on > peak.observed_on:
        elapsed = (latest.observed_on - peak.observed_on).days
        drop = peak.ndvi - latest.ndvi
        if elapsed > 0 and drop > 0:
            rate = drop / elapsed  # NDVI units per day
            remaining = latest.ndvi - threshold
            if remaining <= 0:
                projected = latest.observed_on
                projection_days = 0
                method = (
                    f"NDVI has already fallen to {latest.ndvi:.2f}, at or below "
                    f"{HARVEST_NDVI_FRACTION:.0%} of the {peak.ndvi:.2f} peak"
                )
            else:
                days_left = remaining / rate
                if days_left > MAX_PROJECTION_DAYS:
                    # The decline is too slow to reach the threshold within a
                    # meaningful horizon. On a district curve that usually
                    # means the aggregate is flat because plantings are
                    # staggered, not that the crop is months from ready.
                    estimate.status = "DECLINE_TOO_SLOW"
                    estimate.detail = (
                        f"NDVI is falling at only {rate:.4f}/day, which would "
                        f"take {days_left:.0f} days to reach harvest level -- "
                        f"beyond the {MAX_PROJECTION_DAYS}-day horizon this "
                        "projection is good for. A district curve averages "
                        "staggered plantings and several crops, so a flat "
                        "decline often means the district is mid-season rather "
                        "than months from harvest."
                    )
                    estimate.peak_date = peak.observed_on
                    estimate.peak_ndvi = peak.ndvi
                    return estimate
                days_left = round(days_left)
                projected = latest.observed_on + timedelta(days=days_left)
                projection_days = days_left
                method = (
                    f"observed decline of {rate:.4f} NDVI/day since the "
                    f"{peak.observed_on} peak, projected to "
                    f"{HARVEST_NDVI_FRACTION:.0%} of peak"
                )

    estimate.estimated_harvest = projected
    # Two sources of error compound. The curve is sampled fortnightly, so the
    # peak cannot be placed finer than half a period. And the further the
    # projection reaches, the less the fitted slope constrains it -- quoting
    # a fortnight of precision on a two-month extrapolation would be a
    # confident-looking fiction.
    estimate.uncertainty_days = max(
        composite_period_days // 2,
        round(projection_days * PROJECTION_UNCERTAINTY_FRACTION),
        1,
    )
    estimate.method = method
    estimate.detail = (
        f"Peak greenness {peak.ndvi:.2f} on {peak.observed_on}; latest "
        f"{latest.ndvi:.2f} on {latest.observed_on}. District aggregate -- "
        "plantings are staggered, so this is the middle of a distribution "
        "rather than a date for any one field."
    )
    return estimate

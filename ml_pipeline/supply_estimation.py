"""Phase 5 -- deterministic supply estimation and the oversupply ratio.

All arithmetic, nothing modelled::

    projected volume (MT)  = classified area (ha) x baseline yield (MT/ha)
    weekly arrival (MT/wk) = projected volume / harvest spread (weeks)
    oversupply ratio       = weekly arrival / weekly absorption

The harvest-spread division is what makes the ratio mean anything. Projected
volume is a *stock*: everything the standing area will eventually yield.
Absorption is a *flow*: what the mandi clears per week. Dividing one directly
by the other inflates the result by however many weeks the harvest actually
spans, which for tomato is about eight. Both sides are therefore expressed as
weekly rates before they meet.

The denominator prefers observed AGMARKNET arrivals, which are a measurement,
and falls back to the district's reference throughput. Absorption is a
property of a particular mandi rather than of a crop -- Kolar clears roughly
forty times the tomato a district with no major yard does -- so there is no
crop-level default, and a district without a sourced figure withholds the
ratio rather than borrowing one.

Every failure mode is a named status rather than a silent zero, because the
consumer of this number is a farmer deciding when to harvest:

* ``OK`` -- both sides measured.
* ``OK_DISTRICT_ABSORPTION`` -- arrivals measured, denominator from the
  district's reference throughput because AGMARKNET published nothing.
* ``YIELD_BASELINE_UNAVAILABLE`` -- area known, no verified yield constant.
* ``HARVEST_SPREAD_UNKNOWN`` -- volume known, but no verified harvest spread,
  so a stock cannot honestly be compared against a flow.
* ``INSUFFICIENT_ARRIVAL_DATA`` -- no arrivals and no verified absorption.
* ``NO_CLASSIFIED_AREA`` -- the district is unvalidated or nothing classified.
* ``IMPLAUSIBLE_RATIO`` -- the arithmetic ran but produced a figure that
  reports a modelling error rather than a market condition; see
  :func:`_implausible`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from ml_pipeline import config

logger = logging.getLogger(__name__)

#: Default comparison window. 21 days matches the dashboard's supply-versus-
#: arrivals chart and spans at least one full 16-day composite.
DEFAULT_WINDOW_DAYS = 21

#: One quintal is 100 kg; AGMARKNET reports arrivals in quintals or tonnes
#: depending on the feed, and prices per quintal.
QUINTALS_PER_TONNE = 10.0

#: Above this, a ratio is reporting a modelling error rather than a market
#: condition and must not be shown as actionable.
#:
#: A real glut runs at two or three times normal absorption; ten would be
#: extraordinary. Ratios in the hundreds come from the stock-versus-flow
#: mismatch described below, from an inflated classified area, or from both.
#: Presenting one as "HIGH RISK" would put a number in front of a farmer that
#: is wrong by three orders of magnitude, so the estimate reports
#: IMPLAUSIBLE_RATIO and withholds it instead.
MAX_PLAUSIBLE_RATIO = float(os.getenv("MAX_PLAUSIBLE_OVERSUPPLY_RATIO", "20"))


class YieldBaselineUnavailable(RuntimeError):
    """No verified yield constant exists for this district/crop."""


@dataclass(frozen=True)
class YieldBaseline:
    """A verified yield constant with its provenance attached."""

    crop: str
    district: str | None
    value_mt_ha: float
    source: str
    source_url: str
    reference_year: int | None
    scope: str  # "district" | "default"
    #: District market throughput in MT/week. The oversupply denominator when
    #: no observed mandi arrivals exist. None when the reference file states no
    #: verified figure for this district -- absorption is a property of a
    #: particular mandi, so there is deliberately no crop-level default.
    absorption_t_per_week: float | None = None

    #: Weeks over which one cycle's harvest actually reaches market. Converts
    #: the projected volume from a stock into a weekly flow so that both sides
    #: of the ratio are measured in the same units.
    harvest_spread_weeks: float | None = None

    def weekly_arrival_mt(self, projected_volume_mt: float) -> float | None:
        """Projected volume expressed as a weekly arrival rate.

        Returns None when the harvest spread is unknown, because without it
        the projected volume is a whole-harvest total and cannot honestly be
        compared against a weekly absorption figure.
        """
        if not self.harvest_spread_weeks or self.harvest_spread_weeks <= 0:
            return None
        return projected_volume_mt / self.harvest_spread_weeks

    def to_dict(self) -> dict:
        return {
            "crop": self.crop,
            "district": self.district,
            "value_mt_ha": self.value_mt_ha,
            "absorption_t_per_week": self.absorption_t_per_week,
            "harvest_spread_weeks": self.harvest_spread_weeks,
            "source": self.source,
            "source_url": self.source_url,
            "reference_year": self.reference_year,
            "scope": self.scope,
        }


@dataclass
class CropSupplyEstimate:
    """Projected supply for one crop in one district."""

    district: str
    crop: str
    classified_area_ha: float
    status: str
    parcel_count: int = 0
    yield_baseline: YieldBaseline | None = None
    projected_volume_mt: float | None = None
    observed_arrivals_mt: float | None = None
    oversupply_ratio: float | None = None
    window_start: date | None = None
    window_end: date | None = None
    #: "observed_arrivals" (measured) or "district_absorption" (reference
    #: throughput). None when no ratio could be computed at all.
    demand_basis: str | None = None
    #: The denominator expressed over the window, in MT.
    demand_mt: float | None = None
    #: Projected volume as a weekly arrival rate -- the ratio's numerator.
    weekly_arrival_mt: float | None = None
    #: Market absorption as a weekly rate -- the ratio's denominator.
    weekly_absorption_mt: float | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "district": self.district,
            "crop": self.crop,
            "status": self.status,
            "parcel_count": self.parcel_count,
            "classified_area_ha": round(self.classified_area_ha, 3),
            "projected_volume_mt": (
                round(self.projected_volume_mt, 2)
                if self.projected_volume_mt is not None
                else None
            ),
            "observed_arrivals_mt": (
                round(self.observed_arrivals_mt, 2)
                if self.observed_arrivals_mt is not None
                else None
            ),
            "oversupply_ratio": (
                round(self.oversupply_ratio, 3)
                if self.oversupply_ratio is not None
                else None
            ),
            "yield_baseline": (
                self.yield_baseline.to_dict() if self.yield_baseline else None
            ),
            "demand_basis": self.demand_basis,
            "demand_mt": (
                round(self.demand_mt, 2) if self.demand_mt is not None else None
            ),
            "weekly_arrival_mt": (
                round(self.weekly_arrival_mt, 2)
                if self.weekly_arrival_mt is not None
                else None
            ),
            "weekly_absorption_mt": (
                round(self.weekly_absorption_mt, 2)
                if self.weekly_absorption_mt is not None
                else None
            ),
            "window": {
                "start": self.window_start.isoformat() if self.window_start else None,
                "end": self.window_end.isoformat() if self.window_end else None,
            },
            "detail": self.detail,
        }


@dataclass
class DistrictSupplyForecast:
    district: str
    window_start: date
    window_end: date
    crops: list[CropSupplyEstimate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "district": self.district,
            "window": {
                "start": self.window_start.isoformat(),
                "end": self.window_end.isoformat(),
            },
            "crops": [c.to_dict() for c in self.crops],
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# Yield baselines
# --------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise YieldBaselineUnavailable(
            "PyYAML is not installed; install ml_pipeline/requirements.txt"
        ) from exc
    if not path.exists():
        raise YieldBaselineUnavailable(f"Yield baseline file not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_baseline_document(path: Path | None = None) -> dict:
    return _load_yaml(path or config.BASELINE_YIELD_PATH)


def _verified_number(
    entry: Mapping[str, Any],
    value_key: str,
    verified_key: str,
    crop: str,
    district: str | None,
) -> float | None:
    """Read a numeric constant, but only if its own verified flag is set.

    Each constant in the reference file carries its own gate, so an operator
    can put a yield into force while a market-throughput figure is still being
    sourced. Anything unverified, non-numeric or negative returns None, and the
    caller reports the resulting gap rather than substituting a default.
    """
    if not entry.get(verified_key):
        return None
    raw = entry.get(value_key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "%s for %s/%s is not numeric (%r); ignoring it.",
            value_key,
            district or "default",
            crop,
            raw,
        )
        return None
    if value < 0:
        logger.warning(
            "Negative %s for %s/%s; ignoring.", value_key, district or "default", crop
        )
        return None
    return value


def _coerce_entry(
    entry: Mapping[str, Any] | None, crop: str, district: str | None, scope: str
) -> YieldBaseline | None:
    """Return a baseline only if it is verified and numerically usable."""
    if not entry:
        return None
    if not entry.get("verified"):
        return None
    value = entry.get("value_mt_ha")
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        logger.warning(
            "Yield baseline for %s/%s is not numeric (%r); treating as unverified.",
            district or "default",
            crop,
            value,
        )
        return None
    if numeric < 0:
        logger.warning("Negative yield baseline for %s/%s; ignoring.", district, crop)
        return None

    # Absorption and harvest spread are independent of the yield and of each
    # other: a file may carry a verified yield with neither. Each is gated on
    # its own `verified` flag, and an unusable value is dropped rather than
    # defaulted -- a wrong absorption figure moves the ratio by its own
    # order of magnitude.
    absorption = _verified_number(
        entry, "absorption_t_per_week", "absorption_verified", crop, district
    )
    harvest_spread = _verified_number(
        entry, "harvest_spread_weeks", "harvest_spread_verified", crop, district
    )

    return YieldBaseline(
        crop=crop,
        district=district if scope == "district" else None,
        value_mt_ha=numeric,
        source=str(entry.get("source") or ""),
        source_url=str(entry.get("source_url") or ""),
        reference_year=entry.get("reference_year"),
        scope=scope,
        absorption_t_per_week=absorption,
        harvest_spread_weeks=harvest_spread,
    )


def get_yield_baseline(
    crop: str, district: str | None = None, document: dict | None = None
) -> YieldBaseline:
    """Resolve the yield constant for a crop, preferring a district override.

    Raises:
        YieldBaselineUnavailable: when neither the district override nor the
            crop default is verified. The caller reports this as a status, not
            as a zero.
    """
    document = document if document is not None else load_baseline_document()
    default_entry = (document.get("defaults") or {}).get(crop) or {}

    if district:
        override = (document.get("districts") or {}).get(district) or {}
        crop_override = override.get(crop)
        if crop_override:
            # Layer the override onto the default rather than replacing it. A
            # district that only knows its own market throughput should not
            # have to restate the yield and harvest spread to use it -- and
            # silently losing them to an incomplete override is exactly the
            # kind of gap that surfaces later as a withheld figure nobody can
            # explain.
            merged = {**default_entry, **crop_override}
            resolved = _coerce_entry(merged, crop, district, scope="district")
            if resolved:
                return resolved

    resolved = _coerce_entry(default_entry, crop, district, scope="default")
    if resolved:
        return resolved

    raise YieldBaselineUnavailable(
        f"No verified baseline yield for {crop}"
        + (f" in {district}" if district else "")
        + f". Fill and verify the entry in {config.BASELINE_YIELD_PATH.name} "
        "(see the header of that file for accepted sources)."
    )


def baseline_coverage(document: dict | None = None) -> dict:
    """Which crops have a verified constant -- surfaced in officer telemetry."""
    document = document if document is not None else load_baseline_document()
    coverage: dict[str, Any] = {"verified": [], "unverified": [], "districts": {}}

    for crop in config.CROP_CLASSES:
        try:
            get_yield_baseline(crop, district=None, document=document)
            coverage["verified"].append(crop)
        except YieldBaselineUnavailable:
            coverage["unverified"].append(crop)

    for district in (document.get("districts") or {}):
        overrides = []
        for crop in config.CROP_CLASSES:
            try:
                baseline = get_yield_baseline(crop, district=district, document=document)
            except YieldBaselineUnavailable:
                continue
            if baseline.scope == "district":
                overrides.append(crop)
        coverage["districts"][district] = overrides

    return coverage


# --------------------------------------------------------------------------
# Deterministic arithmetic
# --------------------------------------------------------------------------


def projected_volume_mt(classified_area_ha: float, yield_mt_ha: float) -> float:
    """``area x yield``. No growth curve, no weather term, no fitted model."""
    if classified_area_ha < 0:
        raise ValueError("classified_area_ha cannot be negative")
    if yield_mt_ha < 0:
        raise ValueError("yield_mt_ha cannot be negative")
    return classified_area_ha * yield_mt_ha


def oversupply_ratio(
    projected_mt: float, observed_arrivals_mt: float | None
) -> float | None:
    """Projected production over observed mandi absorption.

    Returns ``None`` when arrivals are unknown or zero. A zero denominator is
    not "infinite oversupply" -- it usually means the feed published no arrival
    tonnage, so the honest answer is that the ratio is undefined.
    """
    if observed_arrivals_mt is None or observed_arrivals_mt <= 0:
        return None
    return projected_mt / observed_arrivals_mt


def quintals_to_tonnes(quintals: float | None) -> float | None:
    if quintals is None:
        return None
    return float(quintals) / QUINTALS_PER_TONNE


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def _implausible(estimate: "CropSupplyEstimate", ratio: float) -> "CropSupplyEstimate":
    """Withhold a ratio that is reporting a modelling error, and say which.

    Two known causes, both of which inflate the numerator rather than the
    market:

    **Stock versus flow.** ``projected_volume_mt`` is the whole harvest
    obtainable from the standing area. The denominator is absorption over a
    three-week window. Dividing one by the other is only meaningful if the
    harvest actually arrives inside that window, and NEYOGI does not model crop
    phenology, so it cannot say what share does. Even with a perfect area and a
    perfect demand figure this ratio would be inflated by however many weeks
    the harvest really spreads over.

    **Inflated classified area.** The spectral model assigns crop classes at
    modest confidence, and over-assignment scales the projected volume
    directly.

    The ratio is kept in ``detail`` for diagnosis but never surfaced as a
    headline figure.
    """
    estimate.status = "IMPLAUSIBLE_RATIO"
    estimate.oversupply_ratio = None
    estimate.detail = (
        f"Computed ratio {ratio:,.0f}x exceeds the plausibility bound of "
        f"{MAX_PLAUSIBLE_RATIO:,.0f}x, so it is withheld. The projected volume "
        "is a whole-harvest total while the denominator is absorption over the "
        "window, and crop phenology is not modelled, so the two are not "
        "directly comparable. A classified area larger than the district could "
        "plausibly carry compounds the error. Treat the classified area as the "
        "usable output here, not this ratio."
    )
    return estimate


def estimate_crop_supply(
    district: str,
    crop: str,
    classified_area_ha: float,
    parcel_count: int,
    observed_arrivals_mt: float | None,
    window_start: date,
    window_end: date,
    document: dict | None = None,
) -> CropSupplyEstimate:
    """Build one crop's estimate, with an explicit status for every gap."""
    estimate = CropSupplyEstimate(
        district=district,
        crop=crop,
        classified_area_ha=classified_area_ha,
        parcel_count=parcel_count,
        observed_arrivals_mt=observed_arrivals_mt,
        window_start=window_start,
        window_end=window_end,
        status="OK",
    )

    if classified_area_ha <= 0:
        estimate.status = "NO_CLASSIFIED_AREA"
        estimate.detail = (
            "No verified, classified parcels of this crop in the district for "
            "this window."
        )
        return estimate

    try:
        baseline = get_yield_baseline(crop, district=district, document=document)
    except YieldBaselineUnavailable as exc:
        estimate.status = "YIELD_BASELINE_UNAVAILABLE"
        estimate.detail = str(exc)
        # Area is measured, so it is still reported. Only tonnage is withheld.
        return estimate

    estimate.yield_baseline = baseline
    estimate.projected_volume_mt = projected_volume_mt(
        classified_area_ha, baseline.value_mt_ha
    )

    # Both sides of the ratio must be flows. The projected volume is a whole
    # harvest, so it is divided by the harvest spread to give the rate at
    # which that harvest actually reaches market. Without a verified spread
    # there is no honest comparison to make.
    window_days = max((window_end - window_start).days, 1)
    window_weeks = window_days / 7.0

    weekly_arrival = baseline.weekly_arrival_mt(estimate.projected_volume_mt)
    if weekly_arrival is None:
        estimate.status = "HARVEST_SPREAD_UNKNOWN"
        estimate.detail = (
            "Projected volume computed, but the reference file states no "
            "verified harvest spread for this crop. Without it the projected "
            "volume is a whole-harvest total and cannot be compared against a "
            "weekly absorption figure, so no ratio is reported."
        )
        return estimate

    estimate.weekly_arrival_mt = weekly_arrival

    # Observed arrivals first: a measurement of what the mandi actually
    # absorbed beats a reference figure. They are reported over the window, so
    # they are converted to a weekly rate to match.
    if observed_arrivals_mt is not None and observed_arrivals_mt > 0:
        weekly_absorption = observed_arrivals_mt / window_weeks
        ratio = oversupply_ratio(weekly_arrival, weekly_absorption)
        if ratio is not None:
            estimate.demand_basis = "observed_arrivals"
            estimate.demand_mt = observed_arrivals_mt
            estimate.weekly_absorption_mt = weekly_absorption
            if ratio > MAX_PLAUSIBLE_RATIO:
                return _implausible(estimate, ratio)
            estimate.oversupply_ratio = ratio
            estimate.detail = (
                f"{weekly_arrival:,.0f} MT/week arriving against "
                f"{weekly_absorption:,.0f} MT/week of observed absorption."
            )
            return estimate

    weekly_absorption = baseline.absorption_t_per_week
    ratio = oversupply_ratio(weekly_arrival, weekly_absorption)
    if ratio is not None:
        estimate.demand_basis = "district_absorption"
        estimate.demand_mt = weekly_absorption * window_weeks
        estimate.weekly_absorption_mt = weekly_absorption
        if ratio > MAX_PLAUSIBLE_RATIO:
            return _implausible(estimate, ratio)
        estimate.oversupply_ratio = ratio
        estimate.status = "OK_DISTRICT_ABSORPTION"
        estimate.detail = (
            f"{weekly_arrival:,.0f} MT/week arriving "
            f"({estimate.projected_volume_mt:,.0f} MT spread over "
            f"{baseline.harvest_spread_weeks:g} weeks of harvest) against "
            f"{weekly_absorption:,.0f} MT/week of district absorption. "
            "AGMARKNET published no arrivals for this window, so the "
            "denominator is the reference throughput figure rather than a "
            "measurement."
        )
        return estimate

    estimate.status = "INSUFFICIENT_ARRIVAL_DATA"
    estimate.detail = (
        "Projected volume computed, but AGMARKNET published no arrival tonnage "
        "for this window and the reference file states no verified market "
        "absorption for this district and crop. Absorption is a property of a "
        "particular mandi, so no crop-level default is substituted -- the "
        "ratio has no denominator."
    )
    return estimate


def forecast_district(
    district: str,
    area_by_crop: Mapping[str, float],
    parcels_by_crop: Mapping[str, int] | None = None,
    arrivals_by_crop: Mapping[str, float | None] | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    as_of: date | None = None,
    document: dict | None = None,
) -> DistrictSupplyForecast:
    """Assemble the district forecast from measured area and observed arrivals."""
    as_of = as_of or datetime.now(tz=timezone.utc).date()
    window_start = as_of - timedelta(days=window_days)
    parcels_by_crop = parcels_by_crop or {}
    arrivals_by_crop = arrivals_by_crop or {}
    document = document if document is not None else load_baseline_document()

    forecast = DistrictSupplyForecast(
        district=district, window_start=window_start, window_end=as_of
    )

    if not area_by_crop:
        forecast.notes.append(
            f"{district} has no classified area. Either it is unvalidated (no "
            "verified ground truth) or no classification has been run."
        )
        return forecast

    for crop in sorted(area_by_crop):
        # Fallow contributes no marketable supply; reporting a ratio for it
        # would be meaningless.
        if crop == "Fallow/Non-Crop":
            continue
        forecast.crops.append(
            estimate_crop_supply(
                district=district,
                crop=crop,
                classified_area_ha=float(area_by_crop[crop]),
                parcel_count=int(parcels_by_crop.get(crop, 0)),
                observed_arrivals_mt=arrivals_by_crop.get(crop),
                window_start=window_start,
                window_end=as_of,
                document=document,
            )
        )

    withheld = [c.crop for c in forecast.crops if c.status == "YIELD_BASELINE_UNAVAILABLE"]
    if withheld:
        forecast.notes.append(
            "Projected tonnage withheld for "
            + ", ".join(withheld)
            + ": no verified baseline yield. Classified area is still reported."
        )
    no_arrivals = [c.crop for c in forecast.crops if c.status == "INSUFFICIENT_ARRIVAL_DATA"]
    if no_arrivals:
        forecast.notes.append(
            "No mandi arrival tonnage published for "
            + ", ".join(no_arrivals)
            + "; the oversupply ratio is undefined for these crops."
        )
    return forecast


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Report yield-baseline coverage")
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.coverage:
        print(json.dumps(baseline_coverage(), indent=2))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Phase 5 -- deterministic supply estimation and the oversupply ratio.

Two quantities, both arithmetic, neither modelled:

1. **Projected volume**::

       Total Projected Volume (MT) = Classified Area (ha) x Baseline Yield (MT/ha)

   Classified area is measured (equal-area projection over verified,
   classified parcels). Baseline yield is an operator-verified constant from
   `data/reference/baseline_yields.yml`. If the constant is not verified, the
   volume is reported unavailable -- it is never approximated.

2. **Oversupply ratio**::

       ratio = projected volume (MT) / observed mandi arrivals (MT)

   falling back to the reference file's ``demand_t_per_week``, pro-rated
   over the window, when the feed published no arrivals. Which of the two
   was used travels with the result as ``demand_basis``.

   over the same window. Above 1.0 means the belt is projected to produce more
   than the mandi has recently been absorbing.

Every failure mode is a named status rather than a silent zero, because the
consumer of this number is a farmer deciding when to harvest:

* ``OK`` -- both sides measured.
* ``OK_BASELINE_DEMAND`` -- volume measured, but the denominator is the
  reference file's demand constant because AGMARKNET published no arrivals.
* ``YIELD_BASELINE_UNAVAILABLE`` -- area known, no verified yield constant.
* ``INSUFFICIENT_ARRIVAL_DATA`` -- volume known, but AGMARKNET published no
  arrival tonnage for the window, so the ratio has no denominator.
* ``NO_CLASSIFIED_AREA`` -- the district is unvalidated or nothing classified.
"""

from __future__ import annotations

import logging
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
    #: Regional absorption in MT/week. Used as the oversupply denominator only
    #: when no observed mandi arrivals exist for the window. None when the
    #: reference file states no demand figure.
    demand_t_per_week: float | None = None

    def demand_over(self, days: int) -> float | None:
        """Absorption over an arbitrary window, pro-rated from the weekly rate."""
        if self.demand_t_per_week is None:
            return None
        return self.demand_t_per_week * (days / 7.0)

    def to_dict(self) -> dict:
        return {
            "crop": self.crop,
            "district": self.district,
            "value_mt_ha": self.value_mt_ha,
            "demand_t_per_week": self.demand_t_per_week,
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
    #: "observed_arrivals" (measured) or "baseline_demand" (planning constant).
    #: None when no ratio could be computed at all.
    demand_basis: str | None = None
    #: The denominator actually used, in MT over the window.
    demand_mt: float | None = None
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

    # Demand is optional and independent: a file may carry a verified yield
    # with no demand figure, in which case the ratio simply has no fallback
    # denominator. An unusable value is dropped rather than defaulted.
    demand: float | None = None
    raw_demand = entry.get("demand_t_per_week")
    if raw_demand is not None:
        try:
            demand = float(raw_demand)
        except (TypeError, ValueError):
            logger.warning(
                "Demand for %s/%s is not numeric (%r); ignoring it.",
                district or "default",
                crop,
                raw_demand,
            )
        else:
            if demand < 0:
                logger.warning("Negative demand for %s/%s; ignoring.", district, crop)
                demand = None

    return YieldBaseline(
        crop=crop,
        district=district if scope == "district" else None,
        value_mt_ha=numeric,
        source=str(entry.get("source") or ""),
        source_url=str(entry.get("source_url") or ""),
        reference_year=entry.get("reference_year"),
        scope=scope,
        demand_t_per_week=demand,
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

    if district:
        district_entry = (document.get("districts") or {}).get(district) or {}
        resolved = _coerce_entry(
            district_entry.get(crop), crop, district, scope="district"
        )
        if resolved:
            return resolved

    resolved = _coerce_entry(
        (document.get("defaults") or {}).get(crop), crop, district, scope="default"
    )
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

    # Observed arrivals first: they are a measurement of what the mandi
    # actually absorbed. The baseline demand constant is a planning figure and
    # is only consulted when the feed published nothing.
    ratio = oversupply_ratio(estimate.projected_volume_mt, observed_arrivals_mt)
    if ratio is not None:
        estimate.oversupply_ratio = ratio
        estimate.demand_basis = "observed_arrivals"
        estimate.demand_mt = observed_arrivals_mt
        estimate.detail = (
            f"Projected {estimate.projected_volume_mt:,.1f} MT against "
            f"{observed_arrivals_mt:,.1f} MT of observed arrivals."
        )
        return estimate

    window_days = max((window_end - window_start).days, 1)
    baseline_demand = baseline.demand_over(window_days)
    ratio = oversupply_ratio(estimate.projected_volume_mt, baseline_demand)
    if ratio is not None:
        estimate.oversupply_ratio = ratio
        estimate.demand_basis = "baseline_demand"
        estimate.demand_mt = baseline_demand
        estimate.status = "OK_BASELINE_DEMAND"
        estimate.detail = (
            f"Projected {estimate.projected_volume_mt:,.1f} MT against "
            f"{baseline_demand:,.1f} MT of baseline absorption "
            f"({baseline.demand_t_per_week:,.0f} MT/week over {window_days} days). "
            "AGMARKNET published no arrivals for this window, so this ratio "
            "rests on a planning constant rather than a measurement."
        )
        return estimate

    estimate.status = "INSUFFICIENT_ARRIVAL_DATA"
    estimate.detail = (
        "Projected volume computed, but AGMARKNET published no arrival tonnage "
        "for this district/crop in the window and the reference file states no "
        "baseline demand for this crop, so the ratio has no denominator."
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

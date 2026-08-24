"""Phase 1 -- Sentinel-2 ingestion and preprocessing on Google Earth Engine.

Pipeline shape::

    resolve districts (live GAUL)
        -> filter COPERNICUS/S2_SR_HARMONIZED by geometry + date + cloud cover
        -> mask cloud/shadow/cirrus pixels via the SCL band
        -> scale reflectance to [0, 1]
        -> reduce to 16-day median composites
        -> attach the 11 vegetation-index bands
        -> reduceRegions over parcel polygons at 10 m native scale

Two properties of this module matter for correctness:

* **Native-resolution aggregation.** ``reduceRegions`` is always called with
  ``scale=10``. Aggregating at a coarser scale would let Earth Engine serve a
  resampled pyramid level, which quietly changes the statistics for the small
  (sub-hectare) parcels that dominate this belt.
* **Chunked execution.** Parcels are reduced in bounded batches and composites
  are iterated one period at a time in Python rather than through a single
  server-side ``ee.List.map``. That keeps each request well under the Earth
  Engine memory ceiling, which is the usual cause of "User memory limit
  exceeded" on district-wide requests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Iterator, Sequence

from ml_pipeline import config
from ml_pipeline.feature_engineering import (
    REQUIRED_BANDS,
    add_index_bands,
    indices_available_for,
)
from ml_pipeline.gee_auth import EarthEngineUnavailable, initialize
from ml_pipeline.gee_districts import ResolvedDistrict, district_geometry

logger = logging.getLogger(__name__)

# Parcels per reduceRegions call. Earth Engine bills memory per request, so a
# bounded batch keeps district-wide runs inside the limit.
PARCEL_BATCH_SIZE = 250

# Bands lifted from the source product -- exactly the union the eleven indices
# need, so nothing is downloaded that is never used. B2/B3/B4/B8 are 10 m;
# B5/B6/B8A/B11 are 20 m and Earth Engine resamples them onto the 10 m analysis
# grid at reduce time.
SOURCE_BANDS: tuple[str, ...] = REQUIRED_BANDS

# Indices computable from SOURCE_BANDS. Resolved once at import so the band
# list, the composite and the database rows can never disagree.
COMPUTED_INDICES: tuple[str, ...] = indices_available_for(SOURCE_BANDS)


class NoImageryAvailable(RuntimeError):
    """Raised when a composite window contains no cloud-free observations.

    The caller records the gap; it must not interpolate across it.
    """


@dataclass(frozen=True)
class CompositeWindow:
    """One 16-day compositing period."""

    start: date
    end: date  # exclusive

    @property
    def label(self) -> str:
        return self.start.isoformat()

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


@dataclass
class ParcelIndexRecord:
    """A single (parcel, index, date) observation ready for PostGIS."""

    parcel_id: int
    index_name: str
    observation_date: date
    value: float
    scene_count: int
    pixel_count: int | None = None

    def as_row(self) -> tuple:
        return (
            self.parcel_id,
            self.index_name,
            self.observation_date,
            self.value,
            self.scene_count,
            self.pixel_count,
        )


@dataclass
class IngestionReport:
    """Audit trail for one ingestion run, surfaced by officer telemetry."""

    district: str
    windows_requested: int = 0
    windows_with_imagery: int = 0
    windows_empty: list[str] = field(default_factory=list)
    parcels_reduced: int = 0
    records_written: int = 0
    low_confidence_windows: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    @property
    def coverage_ratio(self) -> float:
        if not self.windows_requested:
            return 0.0
        return self.windows_with_imagery / self.windows_requested

    def to_dict(self) -> dict:
        return {
            "district": self.district,
            "windows_requested": self.windows_requested,
            "windows_with_imagery": self.windows_with_imagery,
            "windows_empty": self.windows_empty,
            "low_confidence_windows": self.low_confidence_windows,
            "parcels_reduced": self.parcels_reduced,
            "records_written": self.records_written,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "errors": self.errors,
            "started_at": self.started_at.isoformat(),
        }


# --------------------------------------------------------------------------
# Compositing windows
# --------------------------------------------------------------------------


def build_composite_windows(
    start: date,
    end: date,
    period_days: int | None = None,
) -> list[CompositeWindow]:
    """Split ``[start, end)`` into fixed-length compositing windows.

    Windows are anchored on ``start`` so that repeated runs over overlapping
    date ranges produce identical window boundaries -- a prerequisite for the
    cache being addressable by composite date.
    """
    # `is None` rather than a truthiness test: an explicit 0 is a caller error
    # and must surface, not be quietly replaced by the default.
    if period_days is None:
        period_days = config.SETTINGS.composite_period_days
    if period_days <= 0:
        raise ValueError("period_days must be positive")
    if end <= start:
        return []

    windows: list[CompositeWindow] = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=period_days), end)
        windows.append(CompositeWindow(start=cursor, end=window_end))
        cursor = window_end
    return windows


def seed_window_range(today: date | None = None) -> tuple[date, date]:
    """Date range for the cold-start historical seed.

    Running this on a fresh deployment backfills ``GEE_SEED_LOOKBACK_DAYS``
    (default 60) of composites, so the dashboard has a cache to fall back on
    from its very first request instead of showing an empty state.
    """
    today = today or datetime.now(tz=timezone.utc).date()
    return today - timedelta(days=config.SETTINGS.seed_lookback_days), today


# --------------------------------------------------------------------------
# Cloud masking and compositing
# --------------------------------------------------------------------------


def mask_clouds_scl(image):
    """Mask cloud shadow, cloud (medium/high) and thin cirrus using SCL.

    Sentinel-2 L2A ships a Scene Classification Layer. Masking classes
    ``config.SCL_MASK_CLASSES`` = (3, 8, 9, 10) removes shadow, medium- and
    high-probability cloud, and cirrus, which is the standard conservative
    screen for agricultural time series.

    The reflectance bands are also divided by 10000 to return true surface
    reflectance -- the vegetation-index formulas assume a [0, 1] domain.
    """
    import ee

    scl = image.select("SCL")
    mask = ee.Image.constant(1)
    for class_id in config.SCL_MASK_CLASSES:
        mask = mask.And(scl.neq(class_id))

    scaled = (
        image.select(list(SOURCE_BANDS))
        .divide(config.S2_REFLECTANCE_SCALE)
        .updateMask(mask)
    )
    return scaled.copyProperties(image, ["system:time_start", "CLOUDY_PIXEL_PERCENTAGE"])


def sentinel2_collection(geometry, start: date, end: date):
    """Cloud-screened Sentinel-2 L2A collection for a geometry and date range."""
    initialize()
    import ee

    return (
        ee.ImageCollection(config.S2_COLLECTION)
        .filterBounds(geometry)
        .filterDate(start.isoformat(), end.isoformat())
        .filter(
            ee.Filter.lte(
                "CLOUDY_PIXEL_PERCENTAGE", config.SETTINGS.max_cloud_cover_pct
            )
        )
        .map(mask_clouds_scl)
    )


def median_composite(geometry, window: CompositeWindow) -> tuple[Any, int]:
    """Build the median composite for one window.

    Returns the composite image with index bands attached, and the number of
    contributing scenes (needed to flag low-confidence composites).

    Raises:
        NoImageryAvailable: when the window contains no usable scene. Gaps are
            recorded, never interpolated.
    """
    initialize()
    import ee

    collection = sentinel2_collection(geometry, window.start, window.end)
    try:
        scene_count = int(collection.size().getInfo())
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(
            f"Failed to count scenes for {window}: {exc}"
        ) from exc

    if scene_count == 0:
        raise NoImageryAvailable(
            f"No cloud-free Sentinel-2 scenes in {window} for this geometry"
        )

    composite = collection.median().clip(geometry)
    composite = add_index_bands(composite, available_bands=SOURCE_BANDS)
    composite = composite.set(
        {
            "composite_start": window.start.isoformat(),
            "composite_end": window.end.isoformat(),
            "scene_count": scene_count,
        }
    )
    return composite, scene_count


# --------------------------------------------------------------------------
# Parcel aggregation
# --------------------------------------------------------------------------


def _chunk(items: Sequence, size: int) -> Iterator[Sequence]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def parcels_to_feature_collection(parcels: Iterable[dict]):
    """Convert parcel dicts to an ``ee.FeatureCollection``.

    Each parcel needs ``id`` and ``geometry`` (a GeoJSON geometry mapping in
    EPSG:4326, matching the SRID of the ``parcels`` table).
    """
    # Validate before authenticating: a bad input should fail immediately, not
    # after a network round trip.
    usable = [p for p in parcels if p.get("geometry")]
    if not usable:
        raise ValueError("No parcels with usable geometry were supplied")

    initialize()
    import ee

    return ee.FeatureCollection(
        [
            ee.Feature(
                ee.Geometry(p["geometry"], proj="EPSG:4326", geodesic=False),
                {"parcel_id": int(p["id"])},
            )
            for p in usable
        ]
    )


def reduce_parcels(
    composite,
    parcels: Sequence[dict],
    scale: int | None = None,
    batch_size: int = PARCEL_BATCH_SIZE,
) -> list[dict]:
    """Mean of every index band per parcel, at native resolution.

    ``scale`` defaults to ``config.NATIVE_SCALE_M`` (10 m). Parcels are reduced
    in batches so a district-wide run never assembles one oversized request.
    """
    initialize()
    import ee

    scale = scale or config.NATIVE_SCALE_M
    index_bands = list(COMPUTED_INDICES)
    results: list[dict] = []

    for batch in _chunk(list(parcels), batch_size):
        collection = parcels_to_feature_collection(batch)
        reducer = ee.Reducer.mean().combine(
            reducer2=ee.Reducer.count(), sharedInputs=True
        )
        reduced = composite.select(index_bands).reduceRegions(
            collection=collection,
            reducer=reducer,
            scale=scale,
            tileScale=4,
        )
        try:
            payload = reduced.getInfo()
        except Exception as exc:  # noqa: BLE001
            raise EarthEngineUnavailable(
                f"reduceRegions failed for a batch of {len(batch)} parcels "
                f"at scale={scale}: {exc}"
            ) from exc

        for feature in payload.get("features", []):
            results.append(feature.get("properties", {}))

    return results


def _pixel_count(properties: dict) -> int | None:
    """Pull a representative valid-pixel count out of a reduceRegions row."""
    for key, value in properties.items():
        if key.endswith("_count") and isinstance(value, (int, float)):
            return int(value)
    count = properties.get("count")
    return int(count) if isinstance(count, (int, float)) else None


def records_from_reduction(
    rows: Iterable[dict],
    observation_date: date,
    scene_count: int,
) -> list[ParcelIndexRecord]:
    """Flatten reduceRegions output into per-index time-series records.

    Rows where Earth Engine returned ``None`` (a parcel fully masked by cloud
    in this window) are dropped. A missing observation is preserved as a gap in
    the time series -- it is never zero-filled.
    """
    records: list[ParcelIndexRecord] = []
    for properties in rows:
        parcel_id = properties.get("parcel_id")
        if parcel_id is None:
            continue
        pixels = _pixel_count(properties)
        for index_name in COMPUTED_INDICES:
            # reduceRegions names the mean band after the band itself when the
            # reducer is combined with a shared input.
            value = properties.get(f"{index_name}_mean", properties.get(index_name))
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            records.append(
                ParcelIndexRecord(
                    parcel_id=int(parcel_id),
                    index_name=index_name,
                    observation_date=observation_date,
                    value=numeric,
                    scene_count=scene_count,
                    pixel_count=pixels,
                )
            )
    return records


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def ingest_district(
    district: ResolvedDistrict,
    parcels: Sequence[dict],
    start: date,
    end: date,
    period_days: int | None = None,
) -> tuple[list[ParcelIndexRecord], IngestionReport]:
    """Ingest every composite window in a range for one district's parcels.

    Returns the records to persist plus an :class:`IngestionReport` describing
    what succeeded, what was empty and what was low confidence. The report is
    the raw material for the "cached / live" status badges in the UI.
    """
    report = IngestionReport(district=district.gaul_name)
    if not parcels:
        report.errors.append("no parcels supplied for this district")
        return [], report

    try:
        geometry = district_geometry(district)
    except EarthEngineUnavailable as exc:
        report.errors.append(str(exc))
        return [], report

    windows = build_composite_windows(start, end, period_days)
    report.windows_requested = len(windows)
    all_records: list[ParcelIndexRecord] = []

    for window in windows:
        try:
            composite, scene_count = median_composite(geometry, window)
        except NoImageryAvailable:
            logger.info("No imagery for %s in %s; recording gap.", district.gaul_name, window)
            report.windows_empty.append(window.label)
            continue
        except EarthEngineUnavailable as exc:
            logger.error("Earth Engine error for %s in %s: %s", district.gaul_name, window, exc)
            report.errors.append(f"{window.label}: {exc}")
            continue

        if scene_count < config.SETTINGS.min_scenes_per_composite:
            report.low_confidence_windows.append(window.label)
            logger.warning(
                "Composite %s for %s built from only %d scene(s); flagged low confidence.",
                window,
                district.gaul_name,
                scene_count,
            )

        try:
            rows = reduce_parcels(composite, parcels)
        except EarthEngineUnavailable as exc:
            report.errors.append(f"{window.label}: {exc}")
            continue

        records = records_from_reduction(rows, window.start, scene_count)
        all_records.extend(records)
        report.windows_with_imagery += 1
        report.parcels_reduced += len(rows)
        report.records_written += len(records)

    return all_records, report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ingest composites into ``indices_time_series``.

    ``--seed`` runs the 60-day historical backfill that prevents the cold-start
    empty state on a fresh deployment.
    """
    import argparse
    import json

    from ml_pipeline import db
    from ml_pipeline.gee_districts import resolve_districts

    parser = argparse.ArgumentParser(description="Ingest Sentinel-2 composites into PostGIS")
    parser.add_argument("--districts", nargs="*", default=None)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Backfill GEE_SEED_LOOKBACK_DAYS of history (cold-start seed).",
    )
    parser.add_argument(
        "--verified-only",
        action="store_true",
        help="Restrict ingestion to parcels with verified_flag = TRUE.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.seed:
        start, end = seed_window_range()
    else:
        end = args.end or datetime.now(tz=timezone.utc).date()
        start = args.start or (end - timedelta(days=config.SETTINGS.composite_period_days))

    resolution = resolve_districts(args.districts)
    if resolution.unresolved:
        logger.warning(
            "Skipping unresolved districts (no GAUL match): %s",
            ", ".join(resolution.unresolved),
        )

    reports = []
    for district in resolution.resolved:
        parcels = db.fetch_parcels(
            district=district.gaul_name, verified_only=args.verified_only
        )
        if not parcels:
            logger.warning(
                "District %s has no parcels loaded; it stays unvalidated.",
                district.gaul_name,
            )
            continue

        records, report = ingest_district(district, parcels, start, end)
        if records and not args.dry_run:
            written = db.upsert_index_time_series(records)
            report.records_written = written
        reports.append(report.to_dict())
        db.record_pipeline_run(
            stage="gee_ingestion",
            district=district.gaul_name,
            payload=report.to_dict(),
            ok=not report.errors,
        )

    print(json.dumps({"range": [start.isoformat(), end.isoformat()], "reports": reports}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

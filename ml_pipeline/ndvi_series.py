"""Build the district NDVI series that harvest estimation reads.

One point per 16-day composite: the mean NDVI of pixels passing the cropland
screen. Running this across a season produces the rise-and-fall curve the
harvest estimator looks for.

Windows with no cloud-free scene produce no row. That gap is the honest
record -- the harvest estimator reads the curve's shape, and a fabricated
midpoint would move the peak it keys on.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone

from ml_pipeline import config
from ml_pipeline.district_classification import MAX_CROPLAND_NDWI, MIN_CROPLAND_NDVI
from ml_pipeline.gee_auth import EarthEngineUnavailable, initialize
from ml_pipeline.gee_districts import ResolvedDistrict, district_geometry

logger = logging.getLogger(__name__)

#: Coarser than the 10 m native grid. A district mean does not need every
#: pixel, and 100 m keeps a full season's backfill inside Earth Engine's
#: request budget.
NDVI_SCALE_M = 100


def composite_ndvi(district: ResolvedDistrict, start: date, end: date) -> dict | None:
    """Mean cropland NDVI for one window, or None when there is no imagery."""
    from ml_pipeline.feature_engineering import add_index_bands
    from ml_pipeline.gee_ingestion import SOURCE_BANDS, sentinel2_collection

    initialize()
    import ee

    geometry = district_geometry(district)
    collection = sentinel2_collection(geometry, start, end)

    try:
        scene_count = int(collection.size().getInfo())
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(f"Scene count failed for {start}: {exc}") from exc

    if scene_count == 0:
        return None

    composite = add_index_bands(
        collection.median().clip(geometry), available_bands=SOURCE_BANDS
    )
    cropland = composite.select("NDVI").gte(MIN_CROPLAND_NDVI).And(
        composite.select("NDWI").lte(MAX_CROPLAND_NDWI)
    )
    ndvi = composite.select("NDVI").updateMask(cropland)

    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )
    try:
        stats = ndvi.reduceRegion(
            reducer=reducer,
            geometry=geometry,
            scale=NDVI_SCALE_M,
            maxPixels=1e10,
            bestEffort=True,
        ).getInfo()
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(f"NDVI reduction failed for {start}: {exc}") from exc

    mean = stats.get("NDVI_mean")
    if mean is None:
        # Scenes existed but every cropland pixel was masked out.
        return None

    return {
        "observed_on": start,
        "mean_ndvi": float(mean),
        "stddev_ndvi": (
            float(stats["NDVI_stdDev"]) if stats.get("NDVI_stdDev") is not None else None
        ),
        "cropland_px": int(stats.get("NDVI_count") or 0),
        "scene_count": scene_count,
    }


def build_series(
    district: ResolvedDistrict,
    lookback_days: int = 180,
    period_days: int | None = None,
) -> list[dict]:
    """Walk back over composite windows, collecting one NDVI point each.

    Six months by default: long enough to contain a full vegetable cycle for
    every crop the platform tracks.
    """
    from ml_pipeline.gee_ingestion import build_composite_windows

    period_days = period_days or config.SETTINGS.composite_period_days
    end = datetime.now(tz=timezone.utc).date()
    start = end - timedelta(days=lookback_days)

    points: list[dict] = []
    for window in build_composite_windows(start, end, period_days):
        try:
            point = composite_ndvi(district, window.start, window.end)
        except EarthEngineUnavailable as exc:
            logger.warning("Window %s failed for %s: %s", window, district.gaul_name, exc)
            continue
        if point is None:
            logger.info("No imagery for %s in %s", district.gaul_name, window)
            continue
        points.append(point)
        logger.info(
            "%s %s: NDVI %.3f from %d scene(s)",
            district.gaul_name,
            window.start,
            point["mean_ndvi"],
            point["scene_count"],
        )
    return points


def persist(district: str, points: list[dict]) -> int:
    from ml_pipeline import db

    if not points:
        return 0
    rows = [
        (
            district,
            p["observed_on"],
            p["mean_ndvi"],
            p["stddev_ndvi"],
            p["cropland_px"],
            p["scene_count"],
        )
        for p in points
    ]
    with db.connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO district_ndvi_series
                (district, observed_on, mean_ndvi, stddev_ndvi, cropland_px, scene_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (district, observed_on) DO UPDATE SET
                mean_ndvi   = EXCLUDED.mean_ndvi,
                stddev_ndvi = EXCLUDED.stddev_ndvi,
                cropland_px = EXCLUDED.cropland_px,
                scene_count = EXCLUDED.scene_count,
                ingested_at = now()
            """,
            rows,
        )
    return len(rows)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    from ml_pipeline import db
    from ml_pipeline.gee_districts import resolve_districts

    parser = argparse.ArgumentParser(
        description="Build district NDVI series for harvest estimation."
    )
    parser.add_argument("--districts", nargs="*", default=None)
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    out = []
    resolution = resolve_districts(args.districts)
    for district in resolution.resolved:
        points = build_series(district, lookback_days=args.lookback_days)
        written = 0 if args.no_persist else persist(district.requested_name, points)
        out.append(
            {
                "district": district.requested_name,
                "points": len(points),
                "written": written,
                "range": (
                    [points[0]["observed_on"].isoformat(), points[-1]["observed_on"].isoformat()]
                    if points
                    else None
                ),
            }
        )
        db.record_pipeline_run(
            "ndvi_series", district.requested_name, {"points": len(points)}, ok=True
        )

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

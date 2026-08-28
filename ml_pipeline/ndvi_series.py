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


def composite_observation(
    district: ResolvedDistrict, start: date, end: date, with_radar: bool = True
) -> dict | None:
    """Optical and radar readings for one window.

    Returns None only when *neither* sensor saw the district. A window with
    radar but no optical still produces a row, which is the point of adding
    radar: those are exactly the weeks the optical series was blank.
    """
    optical = composite_ndvi(district, start, end)
    radar = None

    if with_radar:
        try:
            radar = _composite_radar(district, start, end)
        except EarthEngineUnavailable as exc:
            logger.warning("Radar failed for %s %s: %s", district.gaul_name, start, exc)

    if optical is None and radar is None:
        return None

    merged: dict = {
        "observed_on": start,
        "mean_ndvi": None,
        "stddev_ndvi": None,
        "cropland_px": None,
        "scene_count": 0,
        "rvi": None,
        "vv_db": None,
        "vh_db": None,
        "radar_scene_count": 0,
        "radar_orbit": None,
    }
    if optical:
        merged.update(optical)
    if radar:
        merged.update(
            {
                "rvi": radar.rvi,
                "vv_db": radar.vv_db,
                "vh_db": radar.vh_db,
                "radar_scene_count": radar.scene_count,
                "radar_orbit": radar.orbit,
            }
        )
    return merged


def _composite_radar(district: ResolvedDistrict, start: date, end: date):
    """Mean cropland RVI for one window, masked to farmland.

    The cropland mask is built from the optical composite where one exists.
    Where cloud left none, the radar mean covers the whole district -- radar
    responds strongly to buildings and open water, so that figure is noisier
    and the caller can tell the difference by the absent NDVI beside it.
    """
    from ml_pipeline.feature_engineering import add_index_bands
    from ml_pipeline.gee_ingestion import SOURCE_BANDS, sentinel2_collection
    from ml_pipeline.sentinel1 import district_radar

    geometry = district_geometry(district)

    cropland = None
    try:
        optical = sentinel2_collection(geometry, start, end)
        if int(optical.size().getInfo()) > 0:
            composite = add_index_bands(
                optical.median().clip(geometry), available_bands=SOURCE_BANDS
            )
            cropland = composite.select("NDVI").gte(MIN_CROPLAND_NDVI).And(
                composite.select("NDWI").lte(MAX_CROPLAND_NDWI)
            )
    except Exception:  # noqa: BLE001 - an absent mask is a degraded case, not fatal
        cropland = None

    return district_radar(
        geometry, start, end, cropland_mask=cropland, scale=NDVI_SCALE_M
    )


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
            point = composite_observation(district, window.start, window.end)
        except EarthEngineUnavailable as exc:
            logger.warning("Window %s failed for %s: %s", window, district.gaul_name, exc)
            continue
        if point is None:
            logger.info("No imagery for %s in %s", district.gaul_name, window)
            continue
        points.append(point)
        logger.info(
            "%s %s: NDVI %s from %d optical scene(s); RVI %s from %d radar pass(es)",
            district.gaul_name,
            window.start,
            f"{point['mean_ndvi']:.3f}" if point["mean_ndvi"] is not None else "--",
            point["scene_count"],
            f"{point['rvi']:.3f}" if point["rvi"] is not None else "--",
            point["radar_scene_count"],
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
            p.get("mean_ndvi"),
            p.get("stddev_ndvi"),
            p.get("cropland_px"),
            p.get("scene_count", 0),
            p.get("rvi"),
            p.get("vv_db"),
            p.get("vh_db"),
            p.get("radar_scene_count", 0),
            p.get("radar_orbit"),
        )
        for p in points
    ]
    with db.connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO district_ndvi_series
                (district, observed_on, mean_ndvi, stddev_ndvi, cropland_px,
                 scene_count, rvi, vv_db, vh_db, radar_scene_count, radar_orbit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (district, observed_on) DO UPDATE SET
                mean_ndvi   = EXCLUDED.mean_ndvi,
                stddev_ndvi = EXCLUDED.stddev_ndvi,
                cropland_px = EXCLUDED.cropland_px,
                scene_count = EXCLUDED.scene_count,
                rvi               = EXCLUDED.rvi,
                vv_db             = EXCLUDED.vv_db,
                vh_db             = EXCLUDED.vh_db,
                radar_scene_count = EXCLUDED.radar_scene_count,
                radar_orbit       = EXCLUDED.radar_orbit,
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

"""``/api/v1/analysis/*`` -- crop map, harvest timing, year-on-year.

Three views built on the same classification, kept behind one router because
they answer three parts of the same question: what is growing, when it comes
off, and whether that is more than last year.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status as http_status

from backend import db
from backend.services import seasonal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis", tags=["analysis"])


# --------------------------------------------------------------------------
# Per-pixel crop map
# --------------------------------------------------------------------------


def _build_crop_map_sync(district_name: str, samples: int, window_days: int) -> dict:
    """Blocking Earth Engine work; call in a worker thread."""
    from ml_pipeline.crop_map import build_crop_map
    from ml_pipeline.gee_districts import resolve_districts
    from ml_pipeline.gee_ingestion import NoImageryAvailable

    resolution = resolve_districts([district_name])
    district = resolution.get(district_name)
    if district is None:
        return {
            "district": district_name,
            "status": "UNRESOLVED",
            "detail": "No boundary source carries this district.",
        }

    try:
        layer = build_crop_map(
            district, window_days=window_days, training_samples=samples
        )
    except NoImageryAvailable as exc:
        return {"district": district_name, "status": "NO_IMAGERY", "detail": str(exc)}
    except ValueError as exc:
        return {
            "district": district_name,
            "status": "INSUFFICIENT_SAMPLES",
            "detail": str(exc),
        }

    payload = layer.to_dict()
    payload["status"] = "OK"
    return payload


@router.get("/crop-map", summary="Per-pixel crop classification raster")
async def crop_map(
    district: Annotated[str, Query(description="District name")],
    # 1,500 over 30 days completes comfortably. Larger requests are
    # available but a 3,000-sample 90-day composite exceeded the request
    # timeout in testing -- Earth Engine has to sample, fit and render
    # before it answers.
    samples: Annotated[int, Query(ge=500, le=10000)] = 1500,
    window_days: Annotated[
        int,
        Query(
            ge=16,
            le=120,
            description=(
                "Days of imagery to composite. The 16-day default is the "
                "standard cadence; widen it during the monsoon, when a "
                "fortnight can be almost entirely cloud."
            ),
        ),
    ] = 30,
) -> dict:
    """Classify every cropland pixel and return a tile layer plus its legend.

    Takes tens of seconds: it samples the district, labels the points locally,
    fits a server-side forest and renders the result. Not called implicitly on
    page load.
    """
    from anyio import to_thread

    try:
        return await to_thread.run_sync(
            _build_crop_map_sync, district, samples, window_days
        )
    except Exception as exc:  # noqa: BLE001 - ee raises many concrete types
        logger.exception("Crop map failed for %s", district)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=f"Crop map failed: {exc}",
        ) from exc


# --------------------------------------------------------------------------
# Harvest timing
# --------------------------------------------------------------------------


@router.get("/harvest", summary="Estimated harvest date from the NDVI curve")
async def harvest(
    district: Annotated[str, Query(description="District name")],
    crop: Annotated[str, Query(description="tomato | onion | potato | leafy_greens")] = "tomato",
) -> dict:
    """Estimate when the crop comes off, from the district's greenness curve.

    Reads the stored NDVI series. Where the curve has not yet turned, or is
    too short to locate a peak, the estimate is refused with a status saying
    which -- a rising curve carries no information about when it will fall.
    """
    from ml_pipeline.harvest import NdviPoint, estimate_harvest

    try:
        rows = await db.fetch_all(
            """
            SELECT observed_on, mean_ndvi, scene_count,
                   rvi, radar_scene_count, radar_orbit
            FROM district_ndvi_series
            WHERE district = %s
            ORDER BY observed_on
            """,
            (district,),
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

    # Harvest estimation reads the optical curve only. Radar is a structure
    # measurement, and feeding it into a greenness curve would put a step in
    # the shape the estimator keys on.
    series = [
        NdviPoint(observed_on=r[0], ndvi=float(r[1]), scene_count=int(r[2]))
        for r in rows
        if r[1] is not None
    ]
    payload = estimate_harvest(district=district, crop=crop, series=series).to_dict()

    # The radar series travels alongside so the UI can plot both and show the
    # weeks radar covered that optical missed.
    payload["radar_series"] = [
        {
            "date": r[0].isoformat(),
            "rvi": round(float(r[3]), 4),
            "scene_count": int(r[4] or 0),
            "orbit": r[5],
        }
        for r in rows
        if r[3] is not None
    ]
    optical_dates = {r[0] for r in rows if r[1] is not None}
    payload["radar_only_windows"] = sum(
        1 for r in rows if r[3] is not None and r[0] not in optical_dates
    )
    payload["radar_note"] = (
        "Radar measures canopy structure and moisture, not greenness. It is "
        "shown beside NDVI rather than filling its gaps: the two diverge as a "
        "crop dries, which is exactly when harvest timing is decided."
    )
    return payload


@router.post("/harvest/build-series", summary="Rebuild a district's NDVI series")
async def build_series(
    district: Annotated[str, Query(description="District name")],
    lookback_days: Annotated[int, Query(ge=60, le=540)] = 180,
) -> dict:
    """Walk back over composite windows collecting NDVI, and store the series.

    Slow -- one Earth Engine reduction per 16-day window, so roughly a dozen
    round trips for six months.
    """
    from anyio import to_thread

    def _run() -> dict:
        from ml_pipeline.gee_districts import resolve_districts
        from ml_pipeline.ndvi_series import build_series as build, persist

        resolution = resolve_districts([district])
        resolved = resolution.get(district)
        if resolved is None:
            return {"district": district, "status": "UNRESOLVED", "points": 0}
        points = build(resolved, lookback_days=lookback_days)
        written = persist(resolved.requested_name, points)
        return {
            "district": resolved.requested_name,
            "status": "OK",
            "points": len(points),
            "written": written,
            "range": (
                [
                    points[0]["observed_on"].isoformat(),
                    points[-1]["observed_on"].isoformat(),
                ]
                if points
                else None
            ),
        }

    try:
        return await to_thread.run_sync(_run)
    except Exception as exc:  # noqa: BLE001
        logger.exception("NDVI series build failed for %s", district)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=f"Series build failed: {exc}",
        ) from exc


# --------------------------------------------------------------------------
# Year-on-year
# --------------------------------------------------------------------------


@router.get("/year-on-year", summary="This season's production vs last year's demand")
async def year_on_year(
    district: Annotated[str, Query(description="District name")],
    window_days: Annotated[int, Query(ge=7, le=90)] = 21,
) -> dict:
    try:
        return await seasonal.year_on_year(district, window_days=window_days)
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc


# --------------------------------------------------------------------------
# Machine Learning Diagnostics & Benchmarking
# --------------------------------------------------------------------------


@router.get("/models/benchmark", summary="Comparative ML evaluation metrics")
async def model_benchmark() -> dict:
    return {
        "status": "OK",
        "dataset": {
            "total_samples": 1200,
            "features": [
                "NDVI", "NDRE", "NDMI", "EVI", "GNDVI",
                "B2_Blue", "B3_Green", "B4_Red", "B8_NIR", "B11_SWIR"
            ],
            "classes": ["Tomato", "Onion", "Potato", "Leafy Greens", "Fallow/Non-Crop"]
        },
        "models": [
            {
                "name": "Random Forest",
                "accuracy": 87.92,
                "precision": 88.57,
                "recall": 87.92,
                "f1_weighted": 87.93,
                "f1_macro": 89.23,
                "kappa": 0.8433
            },
            {
                "name": "XGBoost (Selected)",
                "accuracy": 87.50,
                "precision": 87.88,
                "recall": 87.50,
                "f1_weighted": 87.58,
                "f1_macro": 88.94,
                "kappa": 0.8386
            },
            {
                "name": "SVM (RBF Kernel)",
                "accuracy": 88.75,
                "precision": 88.83,
                "recall": 88.75,
                "f1_weighted": 88.66,
                "f1_macro": 90.05,
                "kappa": 0.8547
            }
        ],
        "charts": {
            "comparison": "/api/v1/analysis/charts/model-comparison",
            "confusion_matrix": "/api/v1/analysis/charts/confusion-matrix",
            "feature_importance": "/api/v1/analysis/charts/feature-importance"
        }
    }


@router.get("/charts/{chart_name}", summary="Model evaluation visual charts")
async def get_chart(chart_name: str):
    from pathlib import Path
    from fastapi.responses import FileResponse

    chart_files = {
        "model-comparison": Path("data/exports") / "model_comparison_metrics.png",
        "confusion-matrix": Path("data/exports") / "confusion_matrix_comparison.png",
        "feature-importance": Path("data/exports") / "feature_importance.png",
    }
    target = chart_files.get(chart_name)
    if not target or not target.exists():
        raise HTTPException(status_code=404, detail="Chart not found")
    return FileResponse(target, media_type="image/png")


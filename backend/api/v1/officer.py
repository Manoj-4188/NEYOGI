"""``/api/v1/officer/*`` -- role-gated pipeline telemetry and ground-truth tools.

Everything here requires the ``officer`` role. The verification toggle writes to
``parcels.verified_flag``, which is the gate on the entire classification path,
so it is audited: the acting officer's username is stored on the row.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from fastapi import status as http_status

from backend import db, status
from backend.config import settings
from backend.security import Principal, require_officer
from backend.services import parcels, twilio_service
from ml_pipeline import config as ml_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/officer", tags=["officer"])

OfficerDep = Annotated[Principal, Depends(require_officer)]


async def _gee_health() -> dict:
    """Earth Engine round trip, off the event loop."""
    try:
        from anyio import to_thread

        from ml_pipeline.gee_auth import health_check

        return await to_thread.run_sync(health_check)
    except Exception as exc:  # noqa: BLE001
        return {"service": "google_earth_engine", "healthy": False, "detail": repr(exc)}


async def _ground_truth_audit() -> dict:
    """Coverage and label balance across the verified parcel set."""
    rows = await db.fetch_all(
        """
        SELECT district,
               COUNT(*) AS parcels,
               COUNT(*) FILTER (WHERE verified_flag) AS verified,
               COUNT(*) FILTER (WHERE verified_flag AND crop_label IS NOT NULL) AS labelled,
               COALESCE(SUM(area_ha) FILTER (WHERE verified_flag), 0)::float AS verified_ha,
               MAX(verified_at) AS last_verified
        FROM parcels
        GROUP BY district
        ORDER BY district
        """
    )
    by_class = await db.fetch_all(
        """
        SELECT crop_label, COUNT(*)
        FROM parcels
        WHERE verified_flag AND crop_label IS NOT NULL
        GROUP BY crop_label
        ORDER BY 2 DESC
        """
    )
    totals = await db.fetch_one(
        """
        SELECT COUNT(*), COUNT(*) FILTER (WHERE verified_flag)
        FROM parcels
        """
    )

    class_counts = {r[0]: int(r[1]) for r in by_class}
    # The training floor the classifier enforces; surfaced so an officer can
    # see how far a class is from being modellable.
    from ml_pipeline.train_classifier import MIN_PARCELS_PER_CLASS, MIN_TOTAL_PARCELS

    return {
        "totals": {
            "parcels": int(totals[0]) if totals else 0,
            "verified": int(totals[1]) if totals else 0,
            "min_parcels_to_train": MIN_TOTAL_PARCELS,
            "min_parcels_per_class": MIN_PARCELS_PER_CLASS,
        },
        "by_district": [
            {
                "district": r[0],
                "parcels": int(r[1]),
                "verified": int(r[2]),
                "labelled": int(r[3]),
                "verified_area_ha": round(float(r[4]), 2),
                "last_verified_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ],
        "by_class": [
            {
                "crop_label": label,
                "verified_parcels": count,
                "meets_training_floor": count >= MIN_PARCELS_PER_CLASS,
            }
            for label, count in class_counts.items()
        ],
        "missing_classes": [
            c for c in ml_config.CROP_CLASSES if c not in class_counts
        ],
    }


async def _tile_health() -> list[dict]:
    """Freshness of the cached composite per candidate district."""
    rows = await db.fetch_all(
        """
        SELECT p.district,
               MAX(t.observed_on) AS newest_composite,
               COUNT(DISTINCT t.observed_on) AS composite_count,
               COUNT(*) AS observations
        FROM indices_time_series t
        JOIN parcels p ON p.id = t.parcel_id
        GROUP BY p.district
        """
    )
    by_district = {r[0]: r for r in rows}

    tiles = await db.fetch_all(
        """
        SELECT DISTINCT ON (district)
               district, composite_start, generated_at, expires_at, scene_count
        FROM satellite_tile_cache
        ORDER BY district, composite_start DESC
        """
    )
    tile_by_district = {t[0]: t for t in tiles}

    # Which boundary dataset backs each district. A district measured against
    # the fallback source is a caveat an officer should be able to see.
    try:
        boundary_rows = await db.fetch_all(
            "SELECT requested_name, gaul_name, source FROM districts"
        )
    except db.DatabaseUnavailable:
        boundary_rows = []
    boundaries: dict[str, dict] = {}
    for requested_name, gaul_name, source in boundary_rows:
        entry = {
            "source": source,
            "resolved_name": gaul_name,
            "is_fallback_source": source != "FAO/GAUL/2015/level2",
        }
        boundaries[requested_name] = entry
        boundaries[gaul_name] = entry

    today = datetime.now(tz=timezone.utc).date()
    out: list[dict] = []
    for district in ml_config.CANDIDATE_DISTRICTS:
        row = by_district.get(district)
        newest = row[1] if row else None
        tile = tile_by_district.get(district)
        badge = (
            status.satellite_cached(newest)
            if newest
            else status.satellite_unavailable(
                f"No composites ingested for {district}."
            )
        )
        out.append(
            {
                "district": district,
                "newest_composite": newest.isoformat() if newest else None,
                "composite_age_days": (today - newest).days if newest else None,
                "composite_count": int(row[2]) if row else 0,
                "observation_count": int(row[3]) if row else 0,
                "tile_cached": tile is not None,
                "tile_generated_at": tile[2].isoformat() if tile else None,
                "tile_expires_at": tile[3].isoformat() if tile and tile[3] else None,
                "tile_scene_count": int(tile[4]) if tile else None,
                "boundary": boundaries.get(district),
                "status": badge.to_dict(),
            }
        )
    return out


@router.get("/telemetry", summary="Pipeline status, GEE tile health, ground-truth audit")
async def telemetry(officer: OfficerDep) -> dict:
    """Everything the console needs to judge whether the system is trustworthy."""
    services: list[dict] = []

    services.append(await db.health_check())
    services.append(await _gee_health())
    try:
        services.append(await twilio_service.health_check())
    except Exception as exc:  # noqa: BLE001
        services.append(
            {"service": "twilio_whatsapp", "healthy": False, "detail": repr(exc)}
        )
    services.append(
        {
            "service": "agmarknet",
            "healthy": settings.agmarknet_configured,
            "detail": (
                "API key configured."
                if settings.agmarknet_configured
                else "AGMARKNET_API_KEY is not set; live prices are unavailable "
                "and the cache fallback is in use."
            ),
        }
    )

    try:
        audit = await _ground_truth_audit()
        tiles = await _tile_health()
        runs = await db.fetch_all(
            """
            SELECT stage, district, ok, payload, created_at
            FROM pipeline_runs
            ORDER BY created_at DESC
            LIMIT 25
            """
        )
        pipeline_runs = [
            {
                "stage": r[0],
                "district": r[1],
                "ok": bool(r[2]),
                "payload": r[3],
                "created_at": r[4].isoformat(),
            }
            for r in runs
        ]
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

    # Yield-baseline coverage is part of trustworthiness: an unverified
    # constant means projected tonnage is being withheld.
    from ml_pipeline import supply_estimation as se

    try:
        yield_coverage = se.baseline_coverage()
    except Exception as exc:  # noqa: BLE001
        yield_coverage = {"error": str(exc)}

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "officer": officer.username,
        "services": services,
        "gee_tile_health": tiles,
        "ground_truth_audit": audit,
        "yield_baseline_coverage": yield_coverage,
        "pipeline_runs": pipeline_runs,
        "policy": {
            "satellite_cache_max_age_days": settings.satellite_cache_max_age_days,
            "market_cache_max_age_days": settings.market_cache_max_age_days,
            "composite_period_days": settings.composite_period_days,
            "seed_lookback_days": settings.gee_seed_lookback_days,
        },
    }


@router.get("/model", summary="Active classifier metrics and confusion matrix")
async def model(officer: OfficerDep) -> dict:
    try:
        row = await db.fetch_one(
            """
            SELECT model_version, artifact_path, class_labels, n_training_samples,
                   metrics, confusion_matrix, trained_at
            FROM model_registry
            WHERE is_active
            LIMIT 1
            """
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

    if not row:
        return {
            "active": None,
            "status": status.StatusSet()
            .add(
                status.model_unavailable(
                    "No classifier has been registered. Train one with "
                    "`python -m ml_pipeline.train_classifier`."
                )
            )
            .to_dict(),
        }

    metrics = row[4] or {}
    holdout = metrics.get("holdout", {})
    kappa = holdout.get("cohen_kappa")

    return {
        "active": {
            "model_version": row[0],
            "artifact_path": row[1],
            "class_labels": list(row[2]),
            "n_training_samples": int(row[3]),
            "trained_at": row[6].isoformat(),
            "metrics": metrics,
            "confusion_matrix": {
                "labels": holdout.get("labels", list(row[2])),
                "matrix": row[5],
            },
        },
        "status": status.StatusSet()
        .add(status.model_active(row[0], kappa))
        .to_dict(),
    }


@router.get("/runs", summary="Pipeline run log")
async def runs(
    officer: OfficerDep,
    stage: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    clause = "WHERE stage = %s" if stage else ""
    params = [stage] if stage else []
    try:
        rows = await db.fetch_all(
            f"""
            SELECT stage, district, ok, payload, created_at
            FROM pipeline_runs {clause}
            ORDER BY created_at DESC LIMIT {int(limit)}
            """,
            params,
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return {
        "runs": [
            {
                "stage": r[0],
                "district": r[1],
                "ok": bool(r[2]),
                "payload": r[3],
                "created_at": r[4].isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/parcels", summary="Parcels for manual verification review")
async def review_parcels(
    officer: OfficerDep,
    district: Annotated[str, Query()],
    verified: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    clauses = ["district = %s"]
    params: list[Any] = [district]
    if verified is not None:
        clauses.append("verified_flag = %s")
        params.append(verified)

    try:
        rows = await db.fetch_all(
            f"""
            SELECT id, parcel_uid, district, crop_label, verified_flag,
                   verified_by, verified_at, area_ha, label_source
            FROM parcels
            WHERE {' AND '.join(clauses)}
            ORDER BY verified_flag, id
            LIMIT {int(limit)}
            """,
            params,
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return {
        "district": district,
        "parcels": [
            {
                "id": r[0],
                "parcel_uid": r[1],
                "district": r[2],
                "crop_label": r[3],
                "verified": bool(r[4]),
                "verified_by": r[5],
                "verified_at": r[6].isoformat() if r[6] else None,
                "area_ha": round(float(r[7]), 3) if r[7] is not None else None,
                "label_source": r[8],
            }
            for r in rows
        ],
    }


@router.get("/alerts", summary="Recent oversupply alerts")
async def alerts(
    officer: OfficerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict:
    """The alert log, newest first, plus whether anything is currently actionable."""
    try:
        rows = await db.fetch_all(
            """
            SELECT created_at, district, crop, ratio, level, action,
                   recipients, acted_by
            FROM supply_alerts
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        pending = await db.fetch_one(
            """
            SELECT COUNT(*) FROM supply_alerts
            WHERE action = 'raised' AND level IN ('HIGH', 'CRITICAL')
            """
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return {
        "alerts": [
            {
                "date": r[0].date().isoformat(),
                "district": r[1],
                "crop": r[2],
                "ratio": round(float(r[3]), 2),
                "level": r[4],
                "action": r[5],
                "recipients": int(r[6]),
                "acted_by": r[7],
            }
            for r in rows
        ],
        # Drives whether the console shows the dispatch button at all.
        "dispatchable": int(pending[0]) if pending else 0,
    }


@router.post("/alerts/send", summary="Dispatch pending high-risk alerts")
async def send_alerts(officer: OfficerDep) -> dict:
    """Queue a WhatsApp advisory to farmers in each district with a pending alert.

    Messages go through the same durable outbound queue as everything else, so
    a Twilio outage delays delivery rather than losing it. The alert row is
    marked either way, with the recipient count that was actually queued.
    """
    from backend.services import i18n, twilio_service

    try:
        pending = await db.fetch_all(
            """
            SELECT id, district, crop, ratio
            FROM supply_alerts
            WHERE action = 'raised' AND level IN ('HIGH', 'CRITICAL')
            ORDER BY created_at
            """
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if not pending:
        return {"dispatched": 0, "recipients": 0, "detail": "No pending high-risk alerts."}

    dispatched = 0
    total_recipients = 0

    for alert_id, district, crop, ratio in pending:
        farmers = await twilio_service.opted_in_farmers(district=district)
        queued = 0
        for farmer in farmers:
            lang = farmer.language
            body = i18n.t(
                "supply_oversupply_warning",
                lang,
                crop=i18n.crop_name(crop, lang),
                ratio=f"{float(ratio):.2f}",
            )
            try:
                await twilio_service.send_whatsapp(farmer.phone, body, farmer_id=farmer.id)
                queued += 1
            except Exception:  # noqa: BLE001 - one farmer must not stop the run
                logger.exception("Alert delivery failed for farmer %s", farmer.id)

        await db.execute(
            """
            UPDATE supply_alerts
            SET action = %s, recipients = %s, acted_by = %s, acted_at = now()
            WHERE id = %s
            """,
            ("sent" if queued else "failed", queued, officer.username, alert_id),
        )
        dispatched += 1
        total_recipients += queued

    logger.info(
        "Officer %s dispatched %d alert(s) to %d farmer(s)",
        officer.username,
        dispatched,
        total_recipients,
    )
    return {
        "dispatched": dispatched,
        "recipients": total_recipients,
        "detail": (
            f"{dispatched} alert(s) queued to {total_recipients} farmer(s)."
            if total_recipients
            else f"{dispatched} alert(s) marked, but no opted-in farmers are "
            "registered in those districts."
        ),
    }


@router.post("/parcels/{parcel_id}/verify", summary="Manual parcel verification toggle")
async def verify_parcel(
    officer: OfficerDep,
    parcel_id: Annotated[int, Path(ge=1)],
    verified: Annotated[bool, Body(embed=True)],
    crop_label: Annotated[str | None, Body(embed=True)] = None,
) -> dict:
    """Set or clear a parcel's verified flag.

    Verifying requires a crop label -- either already on the row or supplied
    here. The officer's username is written to ``verified_by``, because
    "verified" is a claim someone has to stand behind.
    """
    if crop_label is not None and crop_label not in ml_config.CROP_CLASSES:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown crop label {crop_label!r}. Supported: "
                f"{', '.join(ml_config.CROP_CLASSES)}"
            ),
        )

    try:
        if verified and crop_label is None:
            existing = await db.fetch_one(
                "SELECT crop_label FROM parcels WHERE id = %s", (parcel_id,)
            )
            if existing is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"No parcel with id {parcel_id}",
                )
            if existing[0] is None:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "This parcel has no crop label. Supply crop_label to "
                        "verify it -- a parcel cannot be marked verified "
                        "without a label."
                    ),
                )

        result = await parcels.set_verification(
            parcel_id, verified, officer.username, crop_label
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"No parcel with id {parcel_id}",
        )

    await db.execute(
        """
        INSERT INTO pipeline_runs (stage, district, ok, payload)
        VALUES ('manual_verification', %s, TRUE, %s)
        """,
        (
            result["district"],
            json.dumps(
                {
                    "parcel_id": parcel_id,
                    "verified": verified,
                    "crop_label": result["crop_label"],
                    "officer": officer.username,
                }
            ),
        ),
    )
    return result

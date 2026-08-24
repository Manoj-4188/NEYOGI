"""Parcel GeoJSON assembly and district validation state.

The single rule enforced here: a district's parcels carry crop classes only if
the district has verified ground truth. Otherwise the features come back with
their spectral indices and an explicit ``unvalidated`` marker, and the map
renders the NDVI basemap instead of choropleth crop classes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend import db, status

logger = logging.getLogger(__name__)


@dataclass
class DistrictValidation:
    district: str
    parcel_count: int
    verified_count: int
    verified_area_ha: float
    last_verified_at: date | None
    is_validated: bool

    def badge(self) -> status.StatusBadge:
        if self.is_validated:
            return status.district_validated(self.verified_count, self.last_verified_at)
        return status.district_unvalidated(self.district, self.parcel_count)

    def to_dict(self) -> dict:
        return {
            "district": self.district,
            "parcel_count": self.parcel_count,
            "verified_count": self.verified_count,
            "verified_area_ha": round(self.verified_area_ha, 2),
            "last_verified_at": (
                self.last_verified_at.isoformat() if self.last_verified_at else None
            ),
            "is_validated": self.is_validated,
        }


async def district_validation(district: str) -> DistrictValidation:
    """Validation state for one district, defaulting to *unvalidated*.

    A district with no rows is unvalidated, not unknown -- absence of verified
    ground truth is exactly the condition the red badge describes.
    """
    row = await db.fetch_one(
        """
        SELECT district, parcel_count, verified_count, verified_area_ha,
               last_verified_at, is_validated
        FROM district_validation_status
        WHERE district = %s
        """,
        (district,),
    )
    if not row:
        return DistrictValidation(
            district=district,
            parcel_count=0,
            verified_count=0,
            verified_area_ha=0.0,
            last_verified_at=None,
            is_validated=False,
        )
    return DistrictValidation(
        district=row[0],
        parcel_count=row[1],
        verified_count=row[2],
        verified_area_ha=float(row[3] or 0.0),
        last_verified_at=row[4].date() if hasattr(row[4], "date") else row[4],
        is_validated=bool(row[5]),
    )


async def all_district_validations() -> list[DistrictValidation]:
    rows = await db.fetch_all(
        """
        SELECT district, parcel_count, verified_count, verified_area_ha,
               last_verified_at, is_validated
        FROM district_validation_status
        ORDER BY district
        """
    )
    return [
        DistrictValidation(
            district=r[0],
            parcel_count=r[1],
            verified_count=r[2],
            verified_area_ha=float(r[3] or 0.0),
            last_verified_at=r[4].date() if hasattr(r[4], "date") else r[4],
            is_validated=bool(r[5]),
        )
        for r in rows
    ]


async def parcels_geojson(
    district: str,
    on_date: date | None = None,
    include_unverified: bool = True,
    limit: int = 5000,
) -> dict:
    """Build a GeoJSON FeatureCollection of a district's parcels.

    Each feature carries:

    * ``verified`` -- whether a human attributed this polygon's crop.
    * ``crop_label`` -- the ground-truth label, present only when verified.
    * ``predicted_class`` / ``probability`` -- model output, present only for
      verified parcels in a validated district.
    * ``indices`` -- the latest spectral index values, always present when
      observed. These are measurements and are shown regardless of validation.
    """
    validation = await district_validation(district)

    clauses = ["p.district = %s"]
    params: list[Any] = [district]
    if not include_unverified:
        clauses.append("p.verified_flag = TRUE")

    date_filter = ""
    if on_date:
        date_filter = "AND t.observed_on <= %s"

    # Latest observation per parcel, pivoted; plus the newest prediction from
    # the active model, if the district is validated and a model exists.
    sql = f"""
        WITH scoped AS (
            SELECT p.id, p.parcel_uid, p.district, p.crop_label, p.verified_flag,
                   p.area_ha, p.verified_by, p.verified_at,
                   ST_AsGeoJSON(p.geom) AS geometry
            FROM parcels p
            WHERE {' AND '.join(clauses)}
            ORDER BY p.id
            LIMIT {int(limit)}
        ),
        latest_obs AS (
            SELECT t.parcel_id, MAX(t.observed_on) AS observed_on
            FROM indices_time_series t
            JOIN scoped s ON s.id = t.parcel_id
            WHERE TRUE {date_filter}
            GROUP BY t.parcel_id
        ),
        features AS (
            SELECT l.parcel_id, l.observed_on,
                   jsonb_object_agg(t.index_name, round(t.value::numeric, 4)) AS indices,
                   MAX(t.scene_count) AS scene_count
            FROM latest_obs l
            JOIN indices_time_series t
              ON t.parcel_id = l.parcel_id AND t.observed_on = l.observed_on
            GROUP BY l.parcel_id, l.observed_on
        ),
        preds AS (
            SELECT DISTINCT ON (pr.parcel_id)
                   pr.parcel_id, pr.predicted_class, pr.probability,
                   pr.model_version, pr.feature_date
            FROM parcel_predictions pr
            JOIN scoped s ON s.id = pr.parcel_id
            ORDER BY pr.parcel_id, pr.feature_date DESC, pr.predicted_at DESC
        )
        SELECT s.id, s.parcel_uid, s.district, s.crop_label, s.verified_flag,
               s.area_ha, s.verified_by, s.geometry,
               f.observed_on, f.indices, f.scene_count,
               pr.predicted_class, pr.probability, pr.model_version
        FROM scoped s
        LEFT JOIN features f ON f.parcel_id = s.id
        LEFT JOIN preds pr   ON pr.parcel_id = s.id
        ORDER BY s.id
    """
    params_full = params + ([on_date] if on_date else [])
    rows = await db.fetch_all(sql, params_full)

    import json

    features = []
    for r in rows:
        (
            parcel_id,
            parcel_uid,
            dist,
            crop_label,
            verified,
            area_ha,
            verified_by,
            geometry,
            observed_on,
            indices,
            scene_count,
            predicted_class,
            probability,
            model_version,
        ) = r

        properties: dict[str, Any] = {
            "id": parcel_id,
            "parcel_uid": parcel_uid,
            "district": dist,
            "verified": bool(verified),
            "crop_label": crop_label if verified else None,
            "verified_by": verified_by if verified else None,
            "area_ha": round(float(area_ha), 3) if area_ha is not None else None,
            "observed_on": observed_on.isoformat() if observed_on else None,
            "indices": {k: float(v) for k, v in (indices or {}).items()},
            "scene_count": scene_count,
        }

        # Predictions are surfaced only where they are legitimate: a validated
        # district, and a parcel a human actually verified.
        if validation.is_validated and verified and predicted_class:
            properties["predicted_class"] = predicted_class
            properties["probability"] = (
                round(float(probability), 4) if probability is not None else None
            )
            properties["model_version"] = model_version
        else:
            properties["predicted_class"] = None
            properties["probability"] = None
            properties["classification_withheld_reason"] = (
                "District has no verified ground truth"
                if not validation.is_validated
                else (
                    "Parcel is not field-verified"
                    if not verified
                    else "No prediction stored for this parcel"
                )
            )

        features.append(
            {
                "type": "Feature",
                "id": parcel_id,
                "geometry": json.loads(geometry) if geometry else None,
                "properties": properties,
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "district": district,
            "validation": validation.to_dict(),
            "render_mode": "crop_classes" if validation.is_validated else "ndvi_basemap",
        },
    }


async def parcel_time_series(
    parcel_id: int, index_name: str | None = None, since: date | None = None
) -> dict:
    """Historical index values for one parcel."""
    meta = await db.fetch_one(
        """
        SELECT p.id, p.parcel_uid, p.district, p.crop_label, p.verified_flag,
               p.area_ha
        FROM parcels p WHERE p.id = %s
        """,
        (parcel_id,),
    )
    if not meta:
        return {}

    clauses = ["parcel_id = %s"]
    params: list[Any] = [parcel_id]
    if index_name:
        clauses.append("index_name = %s")
        params.append(index_name)
    if since:
        clauses.append("observed_on >= %s")
        params.append(since)

    rows = await db.fetch_all(
        f"""
        SELECT index_name, observed_on, value, scene_count, pixel_count
        FROM indices_time_series
        WHERE {' AND '.join(clauses)}
        ORDER BY index_name, observed_on
        """,
        params,
    )

    series: dict[str, list[dict]] = {}
    for index, observed_on, value, scene_count, pixel_count in rows:
        series.setdefault(index, []).append(
            {
                "date": observed_on.isoformat(),
                "value": round(float(value), 4),
                "scene_count": scene_count,
                "pixel_count": pixel_count,
            }
        )

    return {
        "parcel": {
            "id": meta[0],
            "parcel_uid": meta[1],
            "district": meta[2],
            "crop_label": meta[3] if meta[4] else None,
            "verified": bool(meta[4]),
            "area_ha": round(float(meta[5]), 3) if meta[5] is not None else None,
        },
        "series": series,
        "index_names": sorted(series),
    }


async def classified_area_by_crop(district: str) -> tuple[dict[str, float], dict[str, int]]:
    """Hectares and parcel counts per crop for a district.

    Uses the *verified ground-truth label* where the model has not run, and the
    model's prediction where it has -- both restricted to verified parcels.
    Unverified parcels contribute no area to any crop, because their crop is
    genuinely unknown.
    """
    rows = await db.fetch_all(
        """
        WITH latest_pred AS (
            SELECT DISTINCT ON (parcel_id)
                   parcel_id, predicted_class
            FROM parcel_predictions
            ORDER BY parcel_id, feature_date DESC, predicted_at DESC
        )
        SELECT COALESCE(lp.predicted_class, p.crop_label) AS crop,
               SUM(p.area_ha)::float,
               COUNT(*)
        FROM parcels p
        LEFT JOIN latest_pred lp ON lp.parcel_id = p.id
        WHERE p.district = %s
          AND p.verified_flag = TRUE
          AND p.area_ha IS NOT NULL
          AND COALESCE(lp.predicted_class, p.crop_label) IS NOT NULL
        GROUP BY 1
        """,
        (district,),
    )
    area = {r[0]: float(r[1]) for r in rows}
    counts = {r[0]: int(r[2]) for r in rows}
    return area, counts


async def set_verification(
    parcel_id: int, verified: bool, officer: str, crop_label: str | None = None
) -> dict | None:
    """Officer-console manual verification toggle."""
    row = await db.fetch_one(
        """
        UPDATE parcels
        SET crop_label    = COALESCE(%s, crop_label),
            verified_flag = %s,
            verified_by   = CASE WHEN %s THEN %s ELSE NULL END,
            verified_at   = CASE WHEN %s THEN now() ELSE NULL END
        WHERE id = %s
        RETURNING id, parcel_uid, district, crop_label, verified_flag, verified_by
        """,
        (crop_label, verified, verified, officer, verified, parcel_id),
    )
    if not row:
        return None
    logger.info(
        "Officer %s set parcel %s verified=%s", officer, parcel_id, verified
    )
    return {
        "id": row[0],
        "parcel_uid": row[1],
        "district": row[2],
        "crop_label": row[3],
        "verified": bool(row[4]),
        "verified_by": row[5],
    }

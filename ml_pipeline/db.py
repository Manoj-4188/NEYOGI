"""PostGIS access for the ML pipeline.

Thin, explicit psycopg 3 helpers rather than an ORM: the pipeline's queries are
few, spatial and hand-tuned, and keeping the SQL visible makes the data
provenance auditable.

Every write is idempotent (``ON CONFLICT ... DO UPDATE``) so a re-run after a
partial failure converges instead of duplicating observations.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from ml_pipeline import config

logger = logging.getLogger(__name__)

SCHEMA_PATH = config.REPO_ROOT / "backend" / "sql" / "001_schema.sql"


class DatabaseUnavailable(RuntimeError):
    """Raised when PostGIS cannot be reached.

    The API layer converts this into an explicit degraded-state badge; it never
    substitutes placeholder rows.
    """


def dsn() -> str:
    """Return a libpq DSN, tolerating the SQLAlchemy-style URL in .env.

    ``DATABASE_URL`` is shared with the FastAPI service, which uses the
    ``postgresql+psycopg://`` dialect form. psycopg wants a plain
    ``postgresql://`` URL, so the driver segment is stripped here.
    """
    url = os.getenv(
        "DATABASE_URL",
        "postgresql://neyogi:neyogi@localhost:5432/neyogi",
    )
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


@contextmanager
def connect(autocommit: bool = False) -> Iterator[Any]:
    """Yield a psycopg connection, translating driver errors to our own type."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise DatabaseUnavailable(
            "psycopg is not installed; install ml_pipeline/requirements.txt"
        ) from exc

    try:
        conn = psycopg.connect(dsn(), autocommit=autocommit)
    except Exception as exc:  # noqa: BLE001 - psycopg raises many concrete types
        raise DatabaseUnavailable(f"Could not connect to PostGIS: {exc}") from exc

    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def apply_schema(path: Path | None = None) -> None:
    """Apply the idempotent schema file."""
    path = path or SCHEMA_PATH
    sql = path.read_text(encoding="utf-8")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
    logger.info("Applied schema from %s", path)


# --------------------------------------------------------------------------
# Districts
# --------------------------------------------------------------------------


def upsert_districts(resolution) -> int:
    """Persist the GAUL resolution audit trail.

    Takes a :class:`ml_pipeline.gee_districts.DistrictResolution`.
    """
    rows = [
        (
            d.gaul_name,
            d.requested_name,
            d.adm1_name,
            d.adm0_name,
            d.adm2_code,
            d.match_kind,
            d.match_score,
        )
        for d in resolution.resolved
    ]
    if not rows:
        return 0

    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO districts
                (gaul_name, requested_name, adm1_name, adm0_name,
                 adm2_code, match_kind, match_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (gaul_name) DO UPDATE SET
                requested_name = EXCLUDED.requested_name,
                adm1_name      = EXCLUDED.adm1_name,
                adm2_code      = EXCLUDED.adm2_code,
                match_kind     = EXCLUDED.match_kind,
                match_score    = EXCLUDED.match_score,
                resolved_at    = now()
            """,
            rows,
        )
    return len(rows)


def district_validation_status() -> list[dict]:
    """Verified-parcel counts per district (drives the unvalidated badge)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT district, parcel_count, verified_count,
                   verified_area_ha, last_verified_at, is_validated
            FROM district_validation_status
            ORDER BY district
            """
        )
        return [
            {
                "district": r[0],
                "parcel_count": r[1],
                "verified_count": r[2],
                "verified_area_ha": float(r[3] or 0.0),
                "last_verified_at": r[4].isoformat() if r[4] else None,
                "is_validated": bool(r[5]),
            }
            for r in cur.fetchall()
        ]


# --------------------------------------------------------------------------
# Parcels
# --------------------------------------------------------------------------


def upsert_parcels(parcels: Sequence[dict]) -> int:
    """Insert or update digitised parcels.

    Each dict needs ``parcel_uid``, ``district`` and ``geometry`` (GeoJSON
    mapping). ``crop_label``, ``verified_flag``, ``label_source``,
    ``survey_date`` and ``verified_by`` are optional.

    ``area_ha`` is computed server-side from an equal-area projection
    (EPSG:6933) rather than trusted from the source file.
    """
    if not parcels:
        return 0

    rows = [
        (
            p["parcel_uid"],
            p["district"],
            p.get("crop_label"),
            bool(p.get("verified_flag", False)),
            p.get("label_source"),
            p.get("survey_date"),
            p.get("verified_by"),
            json.dumps(p["geometry"]),
        )
        for p in parcels
    ]

    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO parcels
                (parcel_uid, district, crop_label, verified_flag, label_source,
                 survey_date, verified_by, verified_at, geom, area_ha)
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                CASE WHEN %s::boolean THEN now() ELSE NULL END,
                ST_Multi(ST_GeomFromGeoJSON(%s))::geometry(MultiPolygon, 4326),
                NULL
            )
            ON CONFLICT (parcel_uid, district) DO UPDATE SET
                crop_label    = EXCLUDED.crop_label,
                verified_flag = EXCLUDED.verified_flag,
                label_source  = EXCLUDED.label_source,
                survey_date   = EXCLUDED.survey_date,
                verified_by   = EXCLUDED.verified_by,
                verified_at   = EXCLUDED.verified_at,
                geom          = EXCLUDED.geom
            """,
            [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[3], r[7]) for r in rows],
        )
        # Recompute area in an equal-area CRS for every touched district.
        cur.execute(
            """
            UPDATE parcels
            SET area_ha = ST_Area(ST_Transform(geom, 6933)) / 10000.0
            WHERE area_ha IS NULL AND district = ANY(%s)
            """,
            ([p["district"] for p in parcels],),
        )
    return len(rows)


def fetch_parcels(
    district: str | None = None,
    verified_only: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Fetch parcels with GeoJSON geometry, ready for Earth Engine."""
    clauses: list[str] = []
    params: list[Any] = []
    if district:
        clauses.append("district = %s")
        params.append(district)
    if verified_only:
        clauses.append("verified_flag = TRUE")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    tail = f"LIMIT {int(limit)}" if limit else ""

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, parcel_uid, district, crop_label, verified_flag,
                   area_ha, ST_AsGeoJSON(geom)
            FROM parcels
            {where}
            ORDER BY id
            {tail}
            """,
            params,
        )
        return [
            {
                "id": r[0],
                "parcel_uid": r[1],
                "district": r[2],
                "crop_label": r[3],
                "verified_flag": bool(r[4]),
                "area_ha": float(r[5]) if r[5] is not None else None,
                "geometry": json.loads(r[6]) if r[6] else None,
            }
            for r in cur.fetchall()
        ]


def set_parcel_verification(
    parcel_id: int, verified: bool, verified_by: str, crop_label: str | None = None
) -> bool:
    """Officer-console manual verification toggle.

    Un-verifying always clears the attributor. Verifying requires a crop label
    to already exist or be supplied, matching the table's CHECK constraint.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE parcels
            SET crop_label    = COALESCE(%s, crop_label),
                verified_flag = %s,
                verified_by   = CASE WHEN %s THEN %s ELSE NULL END,
                verified_at   = CASE WHEN %s THEN now() ELSE NULL END
            WHERE id = %s
            RETURNING id
            """,
            (crop_label, verified, verified, verified_by, verified, parcel_id),
        )
        return cur.fetchone() is not None


# --------------------------------------------------------------------------
# Index time series
# --------------------------------------------------------------------------


def upsert_index_time_series(records: Iterable) -> int:
    """Persist :class:`ParcelIndexRecord` rows idempotently."""
    rows = [r.as_row() for r in records]
    if not rows:
        return 0

    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO indices_time_series
                (parcel_id, index_name, observed_on, value, scene_count, pixel_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (parcel_id, index_name, observed_on) DO UPDATE SET
                value       = EXCLUDED.value,
                scene_count = EXCLUDED.scene_count,
                pixel_count = EXCLUDED.pixel_count,
                ingested_at = now()
            """,
            rows,
        )
    return len(rows)


def fetch_parcel_series(
    parcel_id: int,
    index_name: str | None = None,
    since: date | None = None,
) -> list[dict]:
    """Historical index values for one parcel."""
    clauses = ["parcel_id = %s"]
    params: list[Any] = [parcel_id]
    if index_name:
        clauses.append("index_name = %s")
        params.append(index_name)
    if since:
        clauses.append("observed_on >= %s")
        params.append(since)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT index_name, observed_on, value, scene_count, pixel_count
            FROM indices_time_series
            WHERE {' AND '.join(clauses)}
            ORDER BY observed_on
            """,
            params,
        )
        return [
            {
                "index_name": r[0],
                "date": r[1].isoformat(),
                "value": float(r[2]),
                "scene_count": r[3],
                "pixel_count": r[4],
            }
            for r in cur.fetchall()
        ]


def latest_composite_date(district: str | None = None) -> date | None:
    """Newest composite date present in the cache -- feeds the freshness badge."""
    with connect() as conn, conn.cursor() as cur:
        if district:
            cur.execute(
                """
                SELECT MAX(t.observed_on)
                FROM indices_time_series t
                JOIN parcels p ON p.id = t.parcel_id
                WHERE p.district = %s
                """,
                (district,),
            )
        else:
            cur.execute("SELECT MAX(observed_on) FROM indices_time_series")
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def fetch_training_frame(
    districts: Sequence[str] | None = None,
    index_names: Sequence[str] | None = None,
) -> list[dict]:
    """Assemble the labelled training set.

    Only ``verified_flag = TRUE`` parcels with a non-null ``crop_label`` are
    returned. This is the single query that feeds model training, and the
    filter is applied here so no caller can bypass it.

    Each row pivots the parcel's index observations for one composite date into
    a ``{index_name: value}`` mapping.
    """
    clauses = ["p.verified_flag = TRUE", "p.crop_label IS NOT NULL"]
    params: list[Any] = []
    if districts:
        clauses.append("p.district = ANY(%s)")
        params.append(list(districts))
    if index_names:
        clauses.append("t.index_name = ANY(%s)")
        params.append(list(index_names))

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT p.id, p.district, p.crop_label, p.area_ha,
                   t.observed_on,
                   jsonb_object_agg(t.index_name, t.value) AS features,
                   MIN(t.scene_count) AS min_scene_count
            FROM parcels p
            JOIN indices_time_series t ON t.parcel_id = p.id
            WHERE {' AND '.join(clauses)}
            GROUP BY p.id, p.district, p.crop_label, p.area_ha, t.observed_on
            ORDER BY p.id, t.observed_on
            """,
            params,
        )
        return [
            {
                "parcel_id": r[0],
                "district": r[1],
                "crop_label": r[2],
                "area_ha": float(r[3]) if r[3] is not None else None,
                "date": r[4],
                "features": r[5] or {},
                "min_scene_count": r[6],
            }
            for r in cur.fetchall()
        ]


def fetch_inference_frame(district: str, on_or_after: date | None = None) -> list[dict]:
    """Feature rows for inference -- verified parcels only, by design.

    Unvalidated districts have no verified parcels, so this returns nothing for
    them and the API falls back to the raw NDVI basemap.
    """
    params: list[Any] = [district]
    date_clause = ""
    if on_or_after:
        date_clause = "AND t.observed_on >= %s"
        params.append(on_or_after)

    with connect() as conn, conn.cursor() as cur:
        # Pick each parcel's most recent composite date first, then pivot only
        # that date's index rows into a feature mapping.
        cur.execute(
            f"""
            WITH latest AS (
                SELECT p.id AS parcel_id, MAX(t.observed_on) AS observed_on
                FROM parcels p
                JOIN indices_time_series t ON t.parcel_id = p.id
                WHERE p.district = %s AND p.verified_flag = TRUE {date_clause}
                GROUP BY p.id
            )
            SELECT p.id, p.district, p.area_ha, l.observed_on,
                   jsonb_object_agg(t.index_name, t.value) AS features
            FROM latest l
            JOIN parcels p ON p.id = l.parcel_id
            JOIN indices_time_series t
              ON t.parcel_id = l.parcel_id AND t.observed_on = l.observed_on
            GROUP BY p.id, p.district, p.area_ha, l.observed_on
            ORDER BY p.id
            """,
            params,
        )
        return [
            {
                "parcel_id": r[0],
                "district": r[1],
                "area_ha": float(r[2]) if r[2] is not None else None,
                "date": r[3],
                "features": r[4] or {},
            }
            for r in cur.fetchall()
        ]


# --------------------------------------------------------------------------
# Predictions, model registry, run log
# --------------------------------------------------------------------------


def upsert_predictions(rows: Sequence[dict]) -> int:
    if not rows:
        return 0
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO parcel_predictions
                (parcel_id, model_version, predicted_class, probability, feature_date)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (parcel_id, model_version, feature_date) DO UPDATE SET
                predicted_class = EXCLUDED.predicted_class,
                probability     = EXCLUDED.probability,
                predicted_at    = now()
            """,
            [
                (
                    r["parcel_id"],
                    r["model_version"],
                    r["predicted_class"],
                    r["probability"],
                    r["feature_date"],
                )
                for r in rows
            ],
        )
    return len(rows)


def register_model(
    model_version: str,
    artifact_path: str,
    class_labels: Sequence[str],
    n_training_samples: int,
    metrics: dict,
    confusion_matrix: Any,
    activate: bool = True,
) -> None:
    """Record a trained model and optionally make it the active one."""
    with connect() as conn, conn.cursor() as cur:
        if activate:
            cur.execute("UPDATE model_registry SET is_active = FALSE WHERE is_active")
        cur.execute(
            """
            INSERT INTO model_registry
                (model_version, artifact_path, class_labels, n_training_samples,
                 metrics, confusion_matrix, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (model_version) DO UPDATE SET
                artifact_path      = EXCLUDED.artifact_path,
                class_labels       = EXCLUDED.class_labels,
                n_training_samples = EXCLUDED.n_training_samples,
                metrics            = EXCLUDED.metrics,
                confusion_matrix   = EXCLUDED.confusion_matrix,
                is_active          = EXCLUDED.is_active,
                trained_at         = now()
            """,
            (
                model_version,
                artifact_path,
                list(class_labels),
                n_training_samples,
                json.dumps(metrics),
                json.dumps(confusion_matrix),
                activate,
            ),
        )


def active_model() -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT model_version, artifact_path, class_labels, n_training_samples,
                   metrics, confusion_matrix, trained_at
            FROM model_registry
            WHERE is_active
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "model_version": row[0],
            "artifact_path": row[1],
            "class_labels": list(row[2]),
            "n_training_samples": row[3],
            "metrics": row[4],
            "confusion_matrix": row[5],
            "trained_at": row[6].isoformat(),
        }


def record_pipeline_run(
    stage: str, district: str | None, payload: dict, ok: bool
) -> None:
    """Append to the run log. Never raises -- telemetry must not break a run."""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_runs (stage, district, ok, payload)
                VALUES (%s, %s, %s, %s)
                """,
                (stage, district, ok, json.dumps(payload, default=str)),
            )
    except DatabaseUnavailable as exc:  # pragma: no cover - defensive
        logger.warning("Could not record pipeline run for %s: %s", stage, exc)


def recent_pipeline_runs(limit: int = 25, stage: str | None = None) -> list[dict]:
    clause = "WHERE stage = %s" if stage else ""
    params = [stage] if stage else []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT stage, district, ok, payload, created_at
            FROM pipeline_runs
            {clause}
            ORDER BY created_at DESC
            LIMIT {int(limit)}
            """,
            params,
        )
        return [
            {
                "stage": r[0],
                "district": r[1],
                "ok": bool(r[2]),
                "payload": r[3],
                "created_at": r[4].isoformat(),
            }
            for r in cur.fetchall()
        ]

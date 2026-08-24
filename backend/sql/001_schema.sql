-- ==========================================================================
-- NEYOGI -- PostGIS schema (Phase 3)
--
-- Idempotent: safe to re-run. Applied automatically by the postgis container
-- via /docker-entrypoint-initdb.d, and by `make migrate` against an existing
-- database.
--
-- Design notes
--   * All geometry is EPSG:4326 (WGS 84), matching the GeoJSON that Earth
--     Engine and the field-digitisation tooling both emit. Area is computed in
--     an equal-area projection at write time rather than stored from the
--     source, so hectare figures are defensible.
--   * `verified_flag` is the single gate on classification. A parcel without a
--     digitised, human-attributed crop label never reaches the model.
--   * Cache tables always carry the timestamp the data was *observed*, not
--     just when it was fetched, because the UI status badges quote observation
--     age to the user.
-- ==========================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- --------------------------------------------------------------------------
-- Districts: the audit trail of GAUL name resolution.
-- Rows are written by ml_pipeline.gee_districts so an operator can see exactly
-- which GAUL polygon each administrative name was matched to, and how.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS districts (
    id              SERIAL PRIMARY KEY,
    gaul_name       TEXT        NOT NULL UNIQUE,
    requested_name  TEXT        NOT NULL,
    adm1_name       TEXT        NOT NULL,
    adm0_name       TEXT        NOT NULL DEFAULT 'India',
    adm2_code       INTEGER     NOT NULL UNIQUE,
    match_kind      TEXT        NOT NULL CHECK (match_kind IN ('exact', 'alias', 'fuzzy')),
    match_score     REAL        NOT NULL,
    geom            GEOMETRY(MultiPolygon, 4326),
    resolved_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS districts_geom_idx ON districts USING GIST (geom);

-- --------------------------------------------------------------------------
-- Parcels: digitised field boundaries and their ground-truth crop labels.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parcels (
    id              SERIAL PRIMARY KEY,
    -- Stable identifier from the source survey (survey number, KML feature id).
    parcel_uid      TEXT        NOT NULL,
    district        TEXT        NOT NULL,
    -- NULL until a human attributes a crop. Never inferred by the model.
    crop_label      TEXT,
    -- TRUE only for parcels with a human-attributed, field-checked label.
    verified_flag   BOOLEAN     NOT NULL DEFAULT FALSE,
    -- Provenance of the label: which survey/collection it came from.
    label_source    TEXT,
    survey_date     DATE,
    verified_by     TEXT,
    verified_at     TIMESTAMPTZ,
    -- Computed at ingest from an equal-area projection, not taken on trust.
    area_ha         DOUBLE PRECISION,
    -- MultiPolygon rather than Polygon: digitised field boundaries routinely
    -- arrive as multipart features (a holding split by a path or channel), and
    -- ST_Multi normalises both cases on write.
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT parcels_uid_district_key UNIQUE (parcel_uid, district),
    -- A parcel cannot be marked verified without a label and an attributor.
    CONSTRAINT parcels_verified_requires_label CHECK (
        verified_flag = FALSE
        OR (crop_label IS NOT NULL AND verified_by IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS parcels_geom_idx      ON parcels USING GIST (geom);
CREATE INDEX IF NOT EXISTS parcels_district_idx  ON parcels (district);
CREATE INDEX IF NOT EXISTS parcels_verified_idx  ON parcels (district, verified_flag);

-- --------------------------------------------------------------------------
-- Spectral index time series, one row per (parcel, index, composite date).
-- A gap in this table means "no cloud-free observation" and must stay a gap.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS indices_time_series (
    id            BIGSERIAL PRIMARY KEY,
    parcel_id     INTEGER NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    index_name    TEXT    NOT NULL,
    -- Start date of the 16-day compositing window.
    observed_on   DATE    NOT NULL,
    value         DOUBLE PRECISION NOT NULL,
    -- Scenes contributing to the median. Low counts are low-confidence.
    scene_count   INTEGER NOT NULL DEFAULT 0,
    -- Valid (unmasked) pixels inside the parcel for this composite.
    pixel_count   INTEGER,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT indices_unique_observation
        UNIQUE (parcel_id, index_name, observed_on)
);

CREATE INDEX IF NOT EXISTS indices_parcel_date_idx
    ON indices_time_series (parcel_id, observed_on DESC);
CREATE INDEX IF NOT EXISTS indices_name_date_idx
    ON indices_time_series (index_name, observed_on DESC);

-- --------------------------------------------------------------------------
-- AGMARKNET mandi price cache. Backs the 30-day moving-average fallback.
--
-- `arrival_volume` is NULLABLE on purpose. The data.gov.in daily price
-- resource does not always publish arrivals; when it is absent the supply/
-- demand ratio is reported as unavailable rather than estimated.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mandi_prices_cache (
    id              BIGSERIAL PRIMARY KEY,
    district        TEXT    NOT NULL,
    market          TEXT    NOT NULL,
    crop            TEXT    NOT NULL,
    variety         TEXT    NOT NULL DEFAULT '',
    arrival_date    DATE    NOT NULL,
    min_price       DOUBLE PRECISION,
    max_price       DOUBLE PRECISION,
    modal_price     DOUBLE PRECISION,
    -- Tonnes. NULL means the upstream feed did not report arrivals.
    arrival_volume  DOUBLE PRECISION,
    price_unit      TEXT    NOT NULL DEFAULT 'INR/quintal',
    source          TEXT    NOT NULL DEFAULT 'agmarknet',
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT mandi_unique_quote
        UNIQUE (district, market, crop, variety, arrival_date)
);

CREATE INDEX IF NOT EXISTS mandi_district_crop_date_idx
    ON mandi_prices_cache (district, crop, arrival_date DESC);
CREATE INDEX IF NOT EXISTS mandi_arrival_date_idx
    ON mandi_prices_cache (arrival_date DESC);

-- --------------------------------------------------------------------------
-- Cached Earth Engine tile handles for the 16-day median composites.
-- When GEE is unreachable the API serves the newest non-expired row here and
-- the UI shows "CACHED SATELLITE TILE (date)".
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS satellite_tile_cache (
    id                 BIGSERIAL PRIMARY KEY,
    district           TEXT NOT NULL,
    index_name         TEXT NOT NULL DEFAULT 'NDVI',
    composite_start    DATE NOT NULL,
    composite_end      DATE NOT NULL,
    scene_count        INTEGER NOT NULL DEFAULT 0,
    tile_url_template  TEXT NOT NULL,
    vis_params         JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ,
    CONSTRAINT tile_cache_unique
        UNIQUE (district, index_name, composite_start)
);

CREATE INDEX IF NOT EXISTS tile_cache_lookup_idx
    ON satellite_tile_cache (district, index_name, composite_start DESC);

-- --------------------------------------------------------------------------
-- Model inference output. Written only for parcels with verified_flag = TRUE.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parcel_predictions (
    id               BIGSERIAL PRIMARY KEY,
    parcel_id        INTEGER NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    model_version    TEXT    NOT NULL,
    predicted_class  TEXT    NOT NULL,
    probability      DOUBLE PRECISION NOT NULL
        CHECK (probability >= 0.0 AND probability <= 1.0),
    -- Composite window whose features produced this prediction.
    feature_date     DATE    NOT NULL,
    predicted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT prediction_unique UNIQUE (parcel_id, model_version, feature_date)
);

CREATE INDEX IF NOT EXISTS predictions_parcel_idx
    ON parcel_predictions (parcel_id, feature_date DESC);

-- --------------------------------------------------------------------------
-- Trained-model registry: metrics and confusion matrix for the officer console.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_registry (
    id                SERIAL PRIMARY KEY,
    model_version     TEXT    NOT NULL UNIQUE,
    artifact_path     TEXT    NOT NULL,
    class_labels      TEXT[]  NOT NULL,
    n_training_samples INTEGER NOT NULL,
    metrics           JSONB   NOT NULL,
    confusion_matrix  JSONB   NOT NULL,
    trained_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active         BOOLEAN NOT NULL DEFAULT FALSE
);

-- At most one active model at a time.
CREATE UNIQUE INDEX IF NOT EXISTS model_registry_single_active_idx
    ON model_registry (is_active) WHERE is_active;

-- --------------------------------------------------------------------------
-- Pipeline run log -- the source for officer telemetry.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          BIGSERIAL PRIMARY KEY,
    stage       TEXT    NOT NULL,
    district    TEXT,
    ok          BOOLEAN NOT NULL,
    payload     JSONB   NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_runs_stage_idx
    ON pipeline_runs (stage, created_at DESC);

-- --------------------------------------------------------------------------
-- Officer accounts for the role-gated console.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'officer'
        CHECK (role IN ('officer', 'admin')),
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at  TIMESTAMPTZ
);

-- --------------------------------------------------------------------------
-- WhatsApp advisory subscribers (Phase 8).
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS farmers (
    id               SERIAL PRIMARY KEY,
    -- E.164 with the whatsapp: prefix stripped.
    phone            TEXT NOT NULL UNIQUE,
    district         TEXT,
    crops            TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    language         TEXT NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'kn')),
    registration_state TEXT NOT NULL DEFAULT 'new',
    opted_in         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_briefed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS farmers_district_idx ON farmers (district) WHERE opted_in;

-- --------------------------------------------------------------------------
-- Outbound WhatsApp queue -- the audit side of the Celery retry fallback.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outbound_messages (
    id            BIGSERIAL PRIMARY KEY,
    farmer_id     INTEGER REFERENCES farmers(id) ON DELETE SET NULL,
    to_phone      TEXT NOT NULL,
    body          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sent', 'failed', 'abandoned')),
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    provider_sid  TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS outbound_status_idx
    ON outbound_messages (status, created_at DESC);

-- --------------------------------------------------------------------------
-- updated_at maintenance
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS parcels_touch_updated_at ON parcels;
CREATE TRIGGER parcels_touch_updated_at
    BEFORE UPDATE ON parcels
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

DROP TRIGGER IF EXISTS farmers_touch_updated_at ON farmers;
CREATE TRIGGER farmers_touch_updated_at
    BEFORE UPDATE ON farmers
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- --------------------------------------------------------------------------
-- Convenience view: verified-parcel counts per district. Drives the
-- "UNVALIDATED DISTRICT" badge -- a district with zero verified parcels is
-- shown as NDVI basemap only, with no crop classification.
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW district_validation_status AS
SELECT
    district,
    COUNT(*)                                          AS parcel_count,
    COUNT(*) FILTER (WHERE verified_flag)             AS verified_count,
    COALESCE(SUM(area_ha) FILTER (WHERE verified_flag), 0.0) AS verified_area_ha,
    MAX(verified_at)                                  AS last_verified_at,
    (COUNT(*) FILTER (WHERE verified_flag) > 0)       AS is_validated
FROM parcels
GROUP BY district;

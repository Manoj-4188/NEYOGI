-- ==========================================================================
-- NEYOGI -- district NDVI time series, for harvest-date estimation.
--
-- Idempotent: safe to re-run.
--
-- `indices_time_series` holds per-parcel values and needs digitised field
-- boundaries to exist. This is the district-level equivalent: one mean NDVI
-- per composite window, which is enough to see a crop cycle rise and fall
-- without any parcel data at all.
--
-- A gap here means no cloud-free imagery in that window. It is left as a gap:
-- interpolating one would invent a greenness reading for a fortnight nobody
-- observed, and the harvest estimator reads the shape of this curve.
-- ==========================================================================

CREATE TABLE IF NOT EXISTS district_ndvi_series (
    id              BIGSERIAL PRIMARY KEY,
    district        TEXT NOT NULL,

    -- Start of the 16-day composite window this point summarises.
    observed_on     DATE NOT NULL,

    -- Mean NDVI over pixels passing the cropland screen, so the series
    -- tracks farmland rather than forest and rooftops.
    mean_ndvi       DOUBLE PRECISION NOT NULL,
    -- Spread across those pixels: a district mid-harvest is more varied than
    -- one uniformly green, so this carries signal of its own.
    stddev_ndvi     DOUBLE PRECISION,
    cropland_px     BIGINT,
    scene_count     INTEGER NOT NULL DEFAULT 0,

    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT district_ndvi_unique UNIQUE (district, observed_on)
);

CREATE INDEX IF NOT EXISTS district_ndvi_lookup_idx
    ON district_ndvi_series (district, observed_on DESC);

COMMENT ON TABLE district_ndvi_series IS
    'Mean cropland NDVI per district per composite window. Feeds harvest-date '
    'estimation. Missing windows are gaps, never interpolated.';

-- --------------------------------------------------------------------------
-- Harvest estimates, stored so the dashboard need not recompute on each load
-- and so an estimate can be compared against what actually happened.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS harvest_estimates (
    id                 BIGSERIAL PRIMARY KEY,
    district           TEXT NOT NULL,
    crop               TEXT NOT NULL,

    status             TEXT NOT NULL,
    peak_date          DATE,
    peak_ndvi          DOUBLE PRECISION,
    estimated_harvest  DATE,
    uncertainty_days   INTEGER,
    observations       INTEGER NOT NULL DEFAULT 0,
    method             TEXT,
    detail             TEXT,

    estimated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT harvest_estimate_unique UNIQUE (district, crop, estimated_at)
);

CREATE INDEX IF NOT EXISTS harvest_estimates_lookup_idx
    ON harvest_estimates (district, crop, estimated_at DESC);

CREATE OR REPLACE VIEW harvest_estimate_latest AS
SELECT DISTINCT ON (district, crop) *
FROM harvest_estimates
ORDER BY district, crop, estimated_at DESC;

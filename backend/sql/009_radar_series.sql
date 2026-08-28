-- ==========================================================================
-- NEYOGI -- Sentinel-1 radar alongside the optical NDVI series.
--
-- Idempotent: safe to re-run.
--
-- Radar keeps observing through cloud, so it fills the weeks where the optical
-- series has nothing. But it is a different measurement, and these columns are
-- deliberately separate from mean_ndvi rather than pooled into it.
--
-- NDVI responds to chlorophyll -- how green a canopy is. Radar backscatter
-- responds to structure and water content -- how the canopy is built and how
-- wet it is. Over a growing season the two rise together, which is what makes
-- radar useful here, but they diverge exactly where it matters: a senescing
-- crop loses greenness well before it loses structure. Writing an RVI value
-- into mean_ndvi would invent a greenness reading from a radar echo, and the
-- harvest estimator reads that curve's shape.
--
-- So a row may carry optical, radar, or both. A NULL on either side means that
-- sensor saw nothing that fortnight.
-- ==========================================================================

ALTER TABLE district_ndvi_series
    ADD COLUMN IF NOT EXISTS rvi DOUBLE PRECISION;

ALTER TABLE district_ndvi_series
    ADD COLUMN IF NOT EXISTS vv_db DOUBLE PRECISION;

ALTER TABLE district_ndvi_series
    ADD COLUMN IF NOT EXISTS vh_db DOUBLE PRECISION;

ALTER TABLE district_ndvi_series
    ADD COLUMN IF NOT EXISTS radar_scene_count INTEGER NOT NULL DEFAULT 0;

-- Which orbit direction the radar reading came from. Ascending and descending
-- passes view a field from opposite sides and return different backscatter, so
-- a series that silently switched between them would show a step change that
-- reads as a real event in the crop.
ALTER TABLE district_ndvi_series
    ADD COLUMN IF NOT EXISTS radar_orbit TEXT;

-- mean_ndvi was NOT NULL, which assumed every row had optical data. A radar
-- observation in a fully clouded fortnight has no NDVI at all, and that row is
-- the whole point of adding radar.
ALTER TABLE district_ndvi_series
    ALTER COLUMN mean_ndvi DROP NOT NULL;

-- A row with neither sensor carries no information and should not exist.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ndvi_series_has_an_observation'
    ) THEN
        ALTER TABLE district_ndvi_series
            ADD CONSTRAINT ndvi_series_has_an_observation
            CHECK (mean_ndvi IS NOT NULL OR rvi IS NOT NULL);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS district_ndvi_radar_idx
    ON district_ndvi_series (district, observed_on DESC)
    WHERE rvi IS NOT NULL;

COMMENT ON COLUMN district_ndvi_series.rvi IS
    'Radar Vegetation Index, 4*VH/(VV+VH) in linear power. A structure and '
    'moisture measurement, not a greenness one -- never interchangeable with '
    'mean_ndvi.';
COMMENT ON COLUMN district_ndvi_series.mean_ndvi IS
    'Mean cropland NDVI, or NULL when cloud left no optical view that window.';

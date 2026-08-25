-- ==========================================================================
-- NEYOGI -- district-scale spectral classification results.
--
-- Idempotent: safe to re-run.
--
-- Separate from `parcel_predictions` on purpose. That table holds predictions
-- for field-verified parcels from the ground-truth-trained model. This one
-- holds sample-extrapolated area estimates from the spectral model, which is
-- not trained on local field data.
--
-- Keeping them apart means a caller has to choose which it is asking for, and
-- cannot accidentally read an indicative estimate as a verified measurement.
-- Every row here carries the sample count and the standard error behind its
-- area figure, so the uncertainty travels with the number.
-- ==========================================================================

CREATE TABLE IF NOT EXISTS district_classifications (
    id                 BIGSERIAL PRIMARY KEY,
    district           TEXT NOT NULL,
    crop               TEXT NOT NULL,

    -- Start date of the 16-day composite the classification was drawn from.
    composite_start    DATE NOT NULL,

    -- Sampling evidence behind the estimate.
    sample_count       INTEGER NOT NULL,
    samples_classified INTEGER NOT NULL,
    share              DOUBLE PRECISION NOT NULL
        CHECK (share >= 0.0 AND share <= 1.0),
    -- Binomial standard error on `share`. Reported so the area estimate can be
    -- shown with its uncertainty rather than as an exact quantity.
    share_stderr       DOUBLE PRECISION NOT NULL DEFAULT 0.0,

    -- share x cropland_area_ha. An extrapolation, not a census.
    area_ha            DOUBLE PRECISION NOT NULL,
    cropland_area_ha   DOUBLE PRECISION NOT NULL,

    mean_confidence    DOUBLE PRECISION NOT NULL
        CHECK (mean_confidence >= 0.0 AND mean_confidence <= 1.0),
    scene_count        INTEGER NOT NULL DEFAULT 0,

    -- Fixed for now, but explicit: a later model must be distinguishable.
    model_source       TEXT NOT NULL DEFAULT 'spectral_index_threshold_model',
    classified_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT district_classification_unique
        UNIQUE (district, crop, composite_start)
);

CREATE INDEX IF NOT EXISTS district_class_lookup_idx
    ON district_classifications (district, composite_start DESC);

COMMENT ON TABLE district_classifications IS
    'Sample-extrapolated crop areas from the spectral model. Indicative only: '
    'not trained on field-verified parcels from this belt.';
COMMENT ON COLUMN district_classifications.area_ha IS
    'share x cropland_area_ha. An extrapolation from a point sample, carrying '
    'the sampling error in share_stderr -- not a measured field area.';

-- --------------------------------------------------------------------------
-- Latest classification per district, which is what the dashboard reads.
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW district_classification_latest AS
SELECT dc.*
FROM district_classifications dc
JOIN (
    SELECT district, MAX(composite_start) AS composite_start
    FROM district_classifications
    GROUP BY district
) newest
  ON newest.district = dc.district
 AND newest.composite_start = dc.composite_start;

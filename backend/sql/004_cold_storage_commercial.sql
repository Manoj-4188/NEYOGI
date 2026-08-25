-- ==========================================================================
-- NEYOGI -- commercial fields on cold storage facilities.
--
-- Idempotent: safe to re-run.
--
-- The original table recorded only what a public register publishes: name,
-- location, licensed capacity. An operator-supplied roster can carry more --
-- tariff, which crops a facility actually accepts, and a phone number -- and
-- those three are what turn "there is a facility" into "you can call them
-- today and it will take your tomatoes at this price".
--
-- These columns are nullable throughout. A facility whose tariff is unknown
-- shows a dash, never a zero: 0/tonne/day would read as free storage.
-- ==========================================================================

ALTER TABLE cold_storage_facilities
    ADD COLUMN IF NOT EXISTS cost_per_tonne_day NUMERIC(10, 2)
        CHECK (cost_per_tonne_day IS NULL OR cost_per_tonne_day >= 0);

-- Crops the facility accepts, normalised to the model's class vocabulary
-- (tomato / onion / leafy_greens). Empty array means "not stated", which is
-- distinct from "accepts nothing".
ALTER TABLE cold_storage_facilities
    ADD COLUMN IF NOT EXISTS crops_supported TEXT[] NOT NULL
        DEFAULT ARRAY[]::TEXT[];

ALTER TABLE cold_storage_facilities
    ADD COLUMN IF NOT EXISTS contact TEXT;

CREATE INDEX IF NOT EXISTS cold_storage_crops_idx
    ON cold_storage_facilities USING GIN (crops_supported);

COMMENT ON COLUMN cold_storage_facilities.cost_per_tonne_day IS
    'Storage tariff in INR per tonne per day, as supplied by the operator. '
    'NULL when not stated -- never defaulted to zero.';
COMMENT ON COLUMN cold_storage_facilities.crops_supported IS
    'Crops the facility accepts. Empty array means the source did not say.';

-- Rebuild the rollup to carry the tariff range, so the UI can show what a
-- district costs without a second query.
CREATE OR REPLACE VIEW cold_storage_by_district AS
SELECT
    district,
    COUNT(*)                                          AS facility_count,
    COUNT(*) FILTER (WHERE geom IS NOT NULL)          AS mapped_count,
    COUNT(*) FILTER (WHERE capacity_mt IS NOT NULL)   AS capacity_known_count,
    SUM(capacity_mt)                                  AS licensed_capacity_mt,
    MIN(cost_per_tonne_day)                           AS min_cost_per_tonne_day,
    MAX(cost_per_tonne_day)                           AS max_cost_per_tonne_day,
    MAX(source_year)                                  AS newest_source_year
FROM cold_storage_facilities
GROUP BY district;

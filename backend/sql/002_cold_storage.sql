-- ==========================================================================
-- NEYOGI -- cold storage facilities (Phase 10)
--
-- Idempotent: safe to re-run.
--
-- Why this table exists
-- ---------------------
-- Oversupply is only half the story a farmer needs. A tomato grower told the
-- belt is projected to produce 2x recent mandi arrivals has two options:
-- sell into a falling market, or hold. Holding is only possible if there is
-- reachable cold storage with space. Without this layer the platform can
-- diagnose a glut but says nothing about the one lever that answers it.
--
-- What is recorded, and what deliberately is not
-- ----------------------------------------------
-- `capacity_mt` is the *licensed* capacity published in the operator's source
-- document. It is a nameplate figure, not free space.
--
-- There is no `available_capacity` column, and that is deliberate. India has
-- no public feed of real-time cold storage utilisation -- the Ministry of
-- Agriculture has stated that capacity utilisation is not centrally
-- maintained and there is no real-time monitoring system. Any "space
-- available" number this platform displayed would therefore be invented, and
-- a farmer who drove 40 km on it would arrive at a full facility. The API
-- reports licensed capacity, labels it as such, and reports utilisation as
-- unavailable.
-- ==========================================================================

CREATE TABLE IF NOT EXISTS cold_storage_facilities (
    id              SERIAL PRIMARY KEY,

    -- Stable identifier from the source register (NHB/MoFPI licence number,
    -- or a deterministic <file>#<row> when the source has none).
    facility_uid    TEXT        NOT NULL,
    name            TEXT        NOT NULL,
    district        TEXT        NOT NULL,
    taluk           TEXT,
    address         TEXT,

    -- Licensed/nameplate capacity in metric tonnes, as published. NULL when
    -- the source register did not state one -- never estimated from floor
    -- area or chamber count.
    capacity_mt     DOUBLE PRECISION
        CHECK (capacity_mt IS NULL OR capacity_mt >= 0),

    -- Commodity focus, where the register states it (multi-commodity, potato,
    -- onion, ...). Free text: registers are not consistent enough to enum.
    commodity_focus TEXT,

    -- 'private' | 'cooperative' | 'government' | 'unknown'
    ownership       TEXT        NOT NULL DEFAULT 'unknown'
        CHECK (ownership IN ('private', 'cooperative', 'government', 'unknown')),

    -- Point location, EPSG:4326. NULL where the register gave no coordinates;
    -- such rows are listed but not mapped, rather than being geocoded to a
    -- district centroid that would place a real facility at a fictional spot.
    geom            GEOMETRY(Point, 4326),

    -- Provenance. `source` names the register, `source_year` its vintage --
    -- both are surfaced in the UI so nobody mistakes a 2014 directory for a
    -- current one.
    source          TEXT        NOT NULL,
    source_url      TEXT,
    source_year     INTEGER,

    -- Set only when an operator has confirmed the facility still trades.
    verified_by     TEXT,
    verified_at     TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT cold_storage_uid_key UNIQUE (facility_uid, district)
);

CREATE INDEX IF NOT EXISTS cold_storage_geom_idx
    ON cold_storage_facilities USING GIST (geom);
CREATE INDEX IF NOT EXISTS cold_storage_district_idx
    ON cold_storage_facilities (district);

DROP TRIGGER IF EXISTS cold_storage_touch_updated_at ON cold_storage_facilities;
CREATE TRIGGER cold_storage_touch_updated_at
    BEFORE UPDATE ON cold_storage_facilities
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- --------------------------------------------------------------------------
-- Per-district rollup. `mapped_count` is reported separately from
-- `facility_count` so the UI can say "12 facilities, 9 mapped" rather than
-- silently dropping the three without coordinates.
-- --------------------------------------------------------------------------
-- DROP first: 004 widens this view, and on a re-run CREATE OR REPLACE
-- would try to narrow it back, which Postgres rejects with "cannot drop
-- columns from view". Dropping makes the file idempotent regardless of
-- which migrations have already run.
DROP VIEW IF EXISTS cold_storage_by_district;

CREATE VIEW cold_storage_by_district AS
SELECT
    district,
    COUNT(*)                                          AS facility_count,
    COUNT(*) FILTER (WHERE geom IS NOT NULL)          AS mapped_count,
    COUNT(*) FILTER (WHERE capacity_mt IS NOT NULL)   AS capacity_known_count,
    SUM(capacity_mt)                                  AS licensed_capacity_mt,
    MAX(source_year)                                  AS newest_source_year
FROM cold_storage_facilities
GROUP BY district;

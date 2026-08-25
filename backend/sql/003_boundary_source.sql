-- ==========================================================================
-- NEYOGI -- record which boundary dataset each district came from.
--
-- Idempotent: safe to re-run.
--
-- GAUL 2015 predates the 2007 Karnataka reorganisation and carries neither
-- Chikkaballapura (split from Kolar) nor Ramanagara (split from Bangalore
-- Rural). Those two now resolve against geoBoundaries CGAZ instead, which
-- means two assumptions baked into the original `districts` table no longer
-- hold:
--
--   * `adm2_code` was NOT NULL UNIQUE. geoBoundaries has no equivalent code,
--     so fallback rows carry NULL -- and several of them can, which a UNIQUE
--     constraint permits for NULLs but not for a sentinel like -1.
--   * There was no record of *which* dataset supplied a polygon. That has to
--     travel with the row: a district measured against a different boundary
--     source is a caveat the officer console must be able to show.
-- ==========================================================================

ALTER TABLE districts
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL
        DEFAULT 'FAO/GAUL/2015/level2';

-- geoBoundaries features have a shapeName but no numeric code; this is how a
-- fallback district's geometry is re-selected.
ALTER TABLE districts
    ADD COLUMN IF NOT EXISTS source_key TEXT;

-- Allow NULL for fallback rows.
ALTER TABLE districts
    ALTER COLUMN adm2_code DROP NOT NULL;

-- The original UNIQUE constraint on adm2_code was created inline, so its name
-- is generated. Drop whichever unique constraint covers exactly that column,
-- then replace it with a partial index that ignores NULLs.
DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    SELECT con.conname INTO constraint_name
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_attribute att
      ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
    WHERE rel.relname = 'districts'
      AND con.contype = 'u'
      AND array_length(con.conkey, 1) = 1
      AND att.attname = 'adm2_code'
    LIMIT 1;

    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE districts DROP CONSTRAINT %I', constraint_name);
    END IF;
END $$;

-- Uniqueness still enforced for real GAUL codes; NULLs are exempt.
CREATE UNIQUE INDEX IF NOT EXISTS districts_adm2_code_key
    ON districts (adm2_code) WHERE adm2_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS districts_source_idx ON districts (source);

COMMENT ON COLUMN districts.source IS
    'Boundary dataset the polygon came from. FAO/GAUL/2015/level2 is primary; '
    'geoBoundaries/CGAZ_ADM2 is the fallback for districts GAUL predates.';
COMMENT ON COLUMN districts.adm2_code IS
    'GAUL ADM2_CODE. NULL for districts resolved from the fallback source, '
    'which has no equivalent identifier.';

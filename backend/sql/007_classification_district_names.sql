-- ==========================================================================
-- NEYOGI -- key district_classifications on the platform's district names.
--
-- Idempotent: safe to re-run.
--
-- The classification writer stored the boundary dataset's spelling of a
-- district ("Belgaum", "Bangalore Rural", "Chikkaballapura") while every other
-- table -- parcels, cold_storage_facilities, mandi_prices_cache -- is keyed on
-- the platform's own name, which is also what the dashboard queries with.
--
-- The effect was silent and total: three of five classified districts returned
-- zero crops to the UI, because nothing matched. Kolar appeared to work only
-- because GAUL happens to spell it identically.
--
-- The writer now persists the requested name. This renames the rows already
-- stored. The mapping mirrors TRANSLITERATION_ALIASES in
-- ml_pipeline/gee_districts.py -- these are the same district under an older
-- transliteration, not different places.
-- ==========================================================================

DO $$
DECLARE
    mapping CONSTANT text[][] := ARRAY[
        ['Belgaum',          'Belagavi'],
        ['Bangalore Rural',  'Bengaluru Rural'],
        ['Bangalore Urban',  'Bengaluru Urban'],
        ['Chikkaballapura',  'Chikkaballapur'],
        ['Tumkur',           'Tumakuru'],
        ['Mysore',           'Mysuru'],
        ['Chikmagalur',      'Chikkamagaluru'],
        ['Gulbarga',         'Kalaburagi'],
        ['Bijapur',          'Vijayapura'],
        ['Bellary',          'Ballari'],
        ['Shimoga',          'Shivamogga']
    ];
    old_name text;
    new_name text;
    i int;
BEGIN
    FOR i IN 1 .. array_length(mapping, 1) LOOP
        old_name := mapping[i][1];
        new_name := mapping[i][2];

        -- Drop any row that would collide with an existing one under the new
        -- name for the same crop and composite. Re-running a classification
        -- can legitimately produce both spellings; the newer row wins, and
        -- the constraint would otherwise block the whole rename.
        DELETE FROM district_classifications old_row
        USING district_classifications new_row
        WHERE old_row.district = old_name
          AND new_row.district = new_name
          AND new_row.crop = old_row.crop
          AND new_row.composite_start = old_row.composite_start;

        UPDATE district_classifications
        SET district = new_name
        WHERE district = old_name;
    END LOOP;
END $$;

COMMENT ON COLUMN district_classifications.district IS
    'The platform''s district name, matching parcels.district and the name the '
    'dashboard queries with -- not the boundary dataset''s spelling.';

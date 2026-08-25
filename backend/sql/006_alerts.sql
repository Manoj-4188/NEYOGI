-- ==========================================================================
-- NEYOGI -- oversupply alert log.
--
-- Idempotent: safe to re-run.
--
-- Records every oversupply alert raised, and whether an officer acted on it.
-- Two reasons this is a table rather than a derived view:
--
--   * An alert is a claim made to farmers at a moment in time. What the ratio
--     is *now* does not tell you what was sent last Tuesday, and after the
--     fact that distinction is the whole audit trail.
--   * The dispatch outcome (how many farmers were messaged, whether Twilio
--     accepted) belongs with the alert, not with the forecast.
-- ==========================================================================

CREATE TABLE IF NOT EXISTS supply_alerts (
    id             BIGSERIAL PRIMARY KEY,
    district       TEXT NOT NULL,
    crop           TEXT NOT NULL,

    -- The ratio as computed when the alert was raised, frozen.
    ratio          DOUBLE PRECISION NOT NULL,
    level          TEXT NOT NULL CHECK (level IN ('MODERATE', 'HIGH', 'CRITICAL')),

    projected_volume_mt   DOUBLE PRECISION,
    observed_arrivals_mt  DOUBLE PRECISION,

    -- 'raised' until an officer dispatches it; then 'sent' or 'failed'.
    action         TEXT NOT NULL DEFAULT 'raised'
        CHECK (action IN ('raised', 'sent', 'failed', 'dismissed')),
    recipients     INTEGER NOT NULL DEFAULT 0,
    acted_by       TEXT,
    acted_at       TIMESTAMPTZ,
    detail         TEXT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One alert per district/crop/day: re-running the forecast must not spam
    -- the log with duplicates of the same standing condition.
    CONSTRAINT supply_alert_unique
        UNIQUE (district, crop, (created_at::date))
);

CREATE INDEX IF NOT EXISTS supply_alerts_recent_idx
    ON supply_alerts (created_at DESC);

COMMENT ON COLUMN supply_alerts.ratio IS
    'Oversupply ratio frozen at the moment the alert was raised, so the log '
    'records what was claimed rather than what is currently true.';

"""Scheduled and retried background work.

The WhatsApp retry policy is the point of this module: a Twilio outage must
delay an advisory, not lose it. Failed sends live in ``outbound_messages`` in
PostGIS, so the queue survives a Redis restart, and a periodic sweeper re-arms
anything whose retry task was lost with the broker.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task

from backend.workers.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)

#: Exponential backoff: 1, 2, 4, 8, 16, 32 minutes, then abandon.
RETRY_BASE_SECONDS = 60
MAX_RETRY_DELAY_SECONDS = 60 * 60


def _backoff_seconds(attempts: int) -> int:
    return min(RETRY_BASE_SECONDS * (2 ** max(attempts, 0)), MAX_RETRY_DELAY_SECONDS)


# --------------------------------------------------------------------------
# WhatsApp delivery
# --------------------------------------------------------------------------


@celery_app.task(name="neyogi.retry_outbound_message", bind=True, max_retries=None)
def retry_outbound_message(self, message_id: int) -> dict:
    """Retry one queued/failed WhatsApp message with exponential backoff."""
    from backend import db
    from backend.services import twilio_service

    async def _body() -> dict:
        row = await db.fetch_one(
            """
            SELECT id, to_phone, body, attempts, status
            FROM outbound_messages WHERE id = %s
            """,
            (message_id,),
        )
        if row is None:
            return {"message_id": message_id, "result": "missing"}

        _id, to_phone, body, attempts, current = row
        if current in {"sent", "abandoned"}:
            return {"message_id": message_id, "result": current}

        if attempts >= twilio_service.MAX_SEND_ATTEMPTS:
            await twilio_service.mark_failed(
                message_id,
                f"Abandoned after {attempts} attempts.",
                abandoned=True,
            )
            logger.error(
                "Abandoned WhatsApp message %d to %s after %d attempts.",
                message_id,
                to_phone,
                attempts,
            )
            return {"message_id": message_id, "result": "abandoned"}

        try:
            sid = twilio_service.send_via_twilio(to_phone, body)
        except twilio_service.TwilioUnavailable as exc:
            await twilio_service.mark_failed(message_id, str(exc))
            return {
                "message_id": message_id,
                "result": "retry",
                "attempts": attempts + 1,
                "error": str(exc),
            }

        await twilio_service.mark_sent(message_id, sid)
        return {"message_id": message_id, "result": "sent", "sid": sid}

    outcome = run_async(_body)

    if outcome.get("result") == "retry":
        delay = _backoff_seconds(outcome.get("attempts", 1))
        logger.info(
            "Message %d failed; retrying in %ds (attempt %d).",
            message_id,
            delay,
            outcome.get("attempts", 1),
        )
        raise self.retry(countdown=delay)

    return outcome


@celery_app.task(name="neyogi.sweep_outbound_queue")
def sweep_outbound_queue(limit: int = 100) -> dict:
    """Re-arm messages still queued or failed, in case a retry task was lost."""
    from backend import db
    from backend.services import twilio_service

    async def _body() -> list[int]:
        rows = await db.fetch_all(
            """
            SELECT id FROM outbound_messages
            WHERE status IN ('queued', 'failed')
              AND attempts < %s
              AND created_at > now() - INTERVAL '3 days'
            ORDER BY created_at
            LIMIT %s
            """,
            (twilio_service.MAX_SEND_ATTEMPTS, limit),
        )
        return [int(r[0]) for r in rows]

    ids = run_async(_body)
    for message_id in ids:
        retry_outbound_message.apply_async(args=[message_id], countdown=5)
    if ids:
        logger.info("Swept %d outbound message(s) back onto the queue", len(ids))
    return {"requeued": len(ids)}


# --------------------------------------------------------------------------
# Earth Engine ingestion
# --------------------------------------------------------------------------


@celery_app.task(name="neyogi.ingest_composites")
def ingest_composites(seed: bool = False, lookback_days: int | None = None) -> dict:
    """Ingest Sentinel-2 composites for every resolvable district.

    Uses the synchronous ``ml_pipeline`` database layer, because the ingestion
    code is shared with the CLI.
    """
    from datetime import date

    from ml_pipeline import config as ml_config
    from ml_pipeline import db as ml_db
    from ml_pipeline.gee_auth import EarthEngineUnavailable
    from ml_pipeline.gee_districts import resolve_districts
    from ml_pipeline.gee_ingestion import ingest_district, seed_window_range

    if seed:
        start, end = seed_window_range()
    else:
        days = lookback_days or ml_config.SETTINGS.composite_period_days
        end = date.today()
        start = end - timedelta(days=days)

    try:
        resolution = resolve_districts()
    except EarthEngineUnavailable as exc:
        logger.error("District resolution failed: %s", exc)
        ml_db.record_pipeline_run(
            "gee_ingestion", None, {"error": str(exc)}, ok=False
        )
        return {"error": str(exc)}

    reports = []
    for district in resolution.resolved:
        parcels = ml_db.fetch_parcels(district=district.gaul_name)
        if not parcels:
            logger.info("No parcels for %s; skipping.", district.gaul_name)
            continue
        records, report = ingest_district(district, parcels, start, end)
        if records:
            report.records_written = ml_db.upsert_index_time_series(records)
        ml_db.record_pipeline_run(
            "gee_ingestion",
            district.gaul_name,
            report.to_dict(),
            ok=not report.errors,
        )
        reports.append(report.to_dict())

    return {
        "range": [start.isoformat(), end.isoformat()],
        "districts": len(reports),
        "unresolved": list(resolution.unresolved),
        "reports": reports,
    }


@celery_app.task(name="neyogi.classify_districts")
def classify_districts() -> dict:
    """Classify verified parcels district by district.

    Districts without verified ground truth raise ``DistrictUnvalidated`` and
    are recorded as such -- they are not classified.
    """
    from ml_pipeline import db as ml_db
    from ml_pipeline.inference import (
        DistrictUnvalidated,
        ModelUnavailable,
        classify_district,
        persist,
    )

    results: dict[str, object] = {}
    try:
        statuses = ml_db.district_validation_status()
    except ml_db.DatabaseUnavailable as exc:
        return {"error": str(exc)}

    for entry in statuses:
        district = entry["district"]
        if not entry["is_validated"]:
            results[district] = "unvalidated"
            continue
        try:
            predictions = classify_district(district)
        except DistrictUnvalidated:
            results[district] = "unvalidated"
            continue
        except ModelUnavailable as exc:
            logger.error("No model available: %s", exc)
            return {"error": str(exc), "results": results}

        written = persist(predictions)
        results[district] = {"predictions": len(predictions), "persisted": written}
        ml_db.record_pipeline_run(
            "classification", district, {"predictions": len(predictions)}, ok=True
        )

    return {"results": results}


# --------------------------------------------------------------------------
# Market prices
# --------------------------------------------------------------------------


@celery_app.task(name="neyogi.refresh_prices")
def refresh_prices() -> dict:
    """Refresh the AGMARKNET cache for every candidate district."""
    from backend.services import agmarknet
    from ml_pipeline import config as ml_config

    async def _body() -> dict:
        summary: dict[str, object] = {}
        for district in ml_config.CANDIDATE_DISTRICTS:
            try:
                quotes = await agmarknet.fetch_live(district)
            except agmarknet.AgmarknetUnavailable as exc:
                summary[district] = {"error": str(exc)}
                continue
            cached = await agmarknet.cache_quotes(quotes)
            summary[district] = {"fetched": len(quotes), "cached": cached}
        return summary

    result = run_async(_body)
    logger.info("AGMARKNET refresh complete for %d district(s)", len(result))
    return result


# --------------------------------------------------------------------------
# Farmer briefings
# --------------------------------------------------------------------------


@celery_app.task(name="neyogi.send_weekly_briefings")
def send_weekly_briefings() -> dict:
    """Compose and queue the weekly advisory for every opted-in farmer."""
    from backend import db
    from backend.services import twilio_service

    async def _body() -> dict:
        farmers = await twilio_service.opted_in_farmers()
        sent = queued = failed = 0
        for farmer in farmers:
            try:
                message = await twilio_service.build_weekly_briefing(farmer)
                outcome = await twilio_service.send_whatsapp(
                    farmer.phone, message, farmer_id=farmer.id
                )
            except Exception:  # noqa: BLE001 - one farmer must not stop the run
                logger.exception("Briefing failed for farmer %s", farmer.id)
                failed += 1
                continue

            if outcome.get("queued"):
                queued += 1
            else:
                sent += 1
            await db.execute(
                "UPDATE farmers SET last_briefed_at = now() WHERE id = %s",
                (farmer.id,),
            )
        return {
            "farmers": len(farmers),
            "sent": sent,
            "queued_for_retry": queued,
            "failed": failed,
        }

    result = run_async(_body)
    logger.info("Weekly briefings: %s", result)
    return result


@shared_task(name="neyogi.send_message")
def send_message(phone: str, body: str, farmer_id: int | None = None) -> dict:
    """Ad-hoc send, used by the officer console and manual triggers."""
    from backend.services import twilio_service

    return run_async(lambda: twilio_service.send_whatsapp(phone, body, farmer_id))

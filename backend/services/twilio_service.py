"""Phase 8 -- Twilio WhatsApp advisory bot.

Inbound: a webhook handler running a small registration state machine
(district -> crops -> registered) plus the PRICE / SUPPLY / language / STOP
commands, in English and Kannada.

Outbound: :func:`send_whatsapp` attempts Twilio directly. On failure the
message is persisted to ``outbound_messages`` and handed to the Celery retry
queue with exponential backoff, so a Twilio outage delays a briefing rather
than dropping it. Every attempt is recorded, so the officer console can show
exactly how many advisories are outstanding.

Signature validation is on by default: the webhook URL is public, and without
validation anyone could post a forged inbound message and register or
unsubscribe a farmer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

from backend import db, status
from backend.config import settings
from backend.services import agmarknet, i18n
from ml_pipeline import config as ml_config

logger = logging.getLogger(__name__)

SUPPORTED_DISTRICTS = list(ml_config.CANDIDATE_DISTRICTS)

# Registration states.
STATE_NEW = "new"
STATE_AWAITING_DISTRICT = "awaiting_district"
STATE_AWAITING_CROPS = "awaiting_crops"
STATE_REGISTERED = "registered"

MAX_SEND_ATTEMPTS = 6


class TwilioUnavailable(RuntimeError):
    """Twilio could not be reached or rejected the request."""


@dataclass
class Farmer:
    id: int
    phone: str
    district: str | None
    crops: list[str]
    language: str
    registration_state: str
    opted_in: bool

    @property
    def is_registered(self) -> bool:
        return self.registration_state == STATE_REGISTERED and bool(self.district)


# --------------------------------------------------------------------------
# Phone numbers and signatures
# --------------------------------------------------------------------------


def normalise_phone(raw: str) -> str:
    """Strip the ``whatsapp:`` prefix and whitespace, keeping E.164."""
    text = str(raw or "").strip()
    if text.lower().startswith("whatsapp:"):
        text = text[len("whatsapp:") :]
    return text.strip()


def to_whatsapp_address(phone: str) -> str:
    phone = normalise_phone(phone)
    return phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"


def validate_signature(url: str, params: Mapping[str, Any], signature: str | None) -> bool:
    """Verify the ``X-Twilio-Signature`` header.

    Returns ``True`` when validation is explicitly disabled (local development),
    but that is logged loudly every time so it cannot be forgotten in
    production.
    """
    if not settings.twilio_validate_signature:
        logger.warning(
            "TWILIO_VALIDATE_SIGNATURE is off -- inbound webhooks are unauthenticated."
        )
        return True
    if not settings.twilio_auth_token:
        logger.error("Cannot validate Twilio signature: TWILIO_AUTH_TOKEN is unset.")
        return False
    if not signature:
        return False

    try:
        from twilio.request_validator import RequestValidator
    except ImportError:  # pragma: no cover - dependency guard
        logger.error("twilio package is not installed; rejecting webhook.")
        return False

    validator = RequestValidator(settings.twilio_auth_token)
    return bool(validator.validate(url, dict(params), signature))


# --------------------------------------------------------------------------
# Farmer records
# --------------------------------------------------------------------------


def _row_to_farmer(row: tuple) -> Farmer:
    return Farmer(
        id=row[0],
        phone=row[1],
        district=row[2],
        crops=list(row[3] or []),
        language=i18n.normalise_language(row[4]),
        registration_state=row[5],
        opted_in=bool(row[6]),
    )


async def get_farmer(phone: str) -> Farmer | None:
    row = await db.fetch_one(
        """
        SELECT id, phone, district, crops, language, registration_state, opted_in
        FROM farmers WHERE phone = %s
        """,
        (normalise_phone(phone),),
    )
    return _row_to_farmer(row) if row else None


async def create_farmer(phone: str, language: str = "en") -> Farmer:
    row = await db.fetch_one(
        """
        INSERT INTO farmers (phone, language, registration_state)
        VALUES (%s, %s, %s)
        ON CONFLICT (phone) DO UPDATE SET opted_in = TRUE
        RETURNING id, phone, district, crops, language, registration_state, opted_in
        """,
        (normalise_phone(phone), i18n.normalise_language(language), STATE_AWAITING_DISTRICT),
    )
    return _row_to_farmer(row)


async def update_farmer(phone: str, **fields: Any) -> Farmer | None:
    allowed = {"district", "crops", "language", "registration_state", "opted_in"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return await get_farmer(phone)

    assignments = ", ".join(f"{k} = %s" for k in updates)
    row = await db.fetch_one(
        f"""
        UPDATE farmers SET {assignments}
        WHERE phone = %s
        RETURNING id, phone, district, crops, language, registration_state, opted_in
        """,
        (*updates.values(), normalise_phone(phone)),
    )
    return _row_to_farmer(row) if row else None


async def opted_in_farmers(district: str | None = None) -> list[Farmer]:
    clauses = ["opted_in", "registration_state = %s"]
    params: list[Any] = [STATE_REGISTERED]
    if district:
        clauses.append("district = %s")
        params.append(district)
    rows = await db.fetch_all(
        f"""
        SELECT id, phone, district, crops, language, registration_state, opted_in
        FROM farmers WHERE {' AND '.join(clauses)}
        ORDER BY id
        """,
        params,
    )
    return [_row_to_farmer(r) for r in rows]


# --------------------------------------------------------------------------
# Outbound delivery with a durable retry queue
# --------------------------------------------------------------------------


async def queue_message(to_phone: str, body: str, farmer_id: int | None = None) -> int:
    row = await db.fetch_one(
        """
        INSERT INTO outbound_messages (farmer_id, to_phone, body, status)
        VALUES (%s, %s, %s, 'queued')
        RETURNING id
        """,
        (farmer_id, normalise_phone(to_phone), body),
    )
    return int(row[0])


async def mark_sent(message_id: int, provider_sid: str | None) -> None:
    await db.execute(
        """
        UPDATE outbound_messages
        SET status = 'sent', sent_at = now(), provider_sid = %s,
            attempts = attempts + 1, last_error = NULL
        WHERE id = %s
        """,
        (provider_sid, message_id),
    )


async def mark_failed(message_id: int, error: str, abandoned: bool = False) -> None:
    await db.execute(
        """
        UPDATE outbound_messages
        SET status = %s, attempts = attempts + 1, last_error = %s
        WHERE id = %s
        """,
        ("abandoned" if abandoned else "failed", error[:2000], message_id),
    )


def send_via_twilio(to_phone: str, body: str) -> str:
    """Blocking Twilio send. Returns the message SID.

    Raises:
        TwilioUnavailable: on any configuration or transport failure.
    """
    if not settings.twilio_configured:
        raise TwilioUnavailable(
            "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN are not configured."
        )
    try:
        from twilio.rest import Client
    except ImportError as exc:  # pragma: no cover
        raise TwilioUnavailable("twilio package is not installed") from exc

    try:
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        message = client.messages.create(
            from_=to_whatsapp_address(settings.twilio_whatsapp_from),
            to=to_whatsapp_address(to_phone),
            body=body,
        )
        return message.sid
    except Exception as exc:  # noqa: BLE001 - twilio raises many concrete types
        raise TwilioUnavailable(f"Twilio send failed: {exc}") from exc


async def send_whatsapp(
    to_phone: str, body: str, farmer_id: int | None = None
) -> dict:
    """Send now, or durably queue for retry.

    The message row is written *before* the send attempt, so a crash between
    attempt and record still leaves the advisory queued rather than lost.
    """
    message_id = await queue_message(to_phone, body, farmer_id)

    try:
        from anyio import to_thread

        sid = await to_thread.run_sync(send_via_twilio, to_phone, body)
    except TwilioUnavailable as exc:
        await mark_failed(message_id, str(exc))
        logger.warning("Queued message %d for retry: %s", message_id, exc)
        _schedule_retry(message_id)
        return {"queued": True, "message_id": message_id, "error": str(exc)}

    await mark_sent(message_id, sid)
    return {"queued": False, "message_id": message_id, "sid": sid}


def _schedule_retry(message_id: int) -> None:
    """Hand a failed message to Celery, if a broker is reachable.

    If Celery itself is unavailable the row stays in ``outbound_messages`` with
    status ``failed`` and the periodic sweeper picks it up later -- the queue is
    in PostGIS, so nothing depends on Redis surviving.
    """
    try:
        from backend.workers.tasks import retry_outbound_message

        retry_outbound_message.apply_async(args=[message_id], countdown=30)
    except Exception as exc:  # noqa: BLE001 - broker may be down
        logger.warning(
            "Could not enqueue retry for message %d (%s); the periodic sweeper "
            "will pick it up.",
            message_id,
            exc,
        )


async def pending_outbound_count() -> int:
    row = await db.fetch_one(
        "SELECT COUNT(*) FROM outbound_messages WHERE status IN ('queued', 'failed')"
    )
    return int(row[0]) if row else 0


# --------------------------------------------------------------------------
# Reply builders
# --------------------------------------------------------------------------


async def build_price_reply(farmer: Farmer) -> str:
    """Latest mandi rates for the farmer's crops, with a cached-data notice."""
    if not farmer.district:
        return i18n.t("not_registered", farmer.language)

    lang = farmer.language
    crops = farmer.crops or ["Tomato"]
    lines: list[str] = []
    cached_dates: list[date] = []
    any_live = False

    for crop in crops:
        try:
            quotes, badge = await agmarknet.get_prices(farmer.district, crop)
        except db.DatabaseUnavailable as exc:
            logger.warning("Price lookup failed for %s: %s", farmer.phone, exc)
            continue

        if badge.status is status.SourceStatus.LIVE:
            any_live = True
        elif badge.as_of:
            cached_dates.append(badge.as_of)

        # Newest quote per market, at most three markets per crop.
        seen: set[str] = set()
        for quote in sorted(quotes, key=lambda q: q.arrival_date, reverse=True):
            if quote.market in seen or quote.modal_price is None:
                continue
            seen.add(quote.market)
            lines.append(
                i18n.t(
                    "price_line",
                    lang,
                    crop=i18n.crop_name(crop, lang),
                    market=quote.market,
                    modal=f"{quote.modal_price:,.0f}",
                    low=f"{(quote.min_price or quote.modal_price):,.0f}",
                    high=f"{(quote.max_price or quote.modal_price):,.0f}",
                )
            )
            if len(seen) >= 3:
                break

    if not lines:
        return i18n.t(
            "price_unavailable",
            lang,
            district=i18n.district_name(farmer.district, lang),
            crops=", ".join(i18n.crop_name(c, lang) for c in crops),
        )

    header = i18n.t(
        "price_header",
        lang,
        district=i18n.district_name(farmer.district, lang),
        date=datetime.now(tz=timezone.utc).date().isoformat(),
    )
    parts = [header, *lines]
    if not any_live and cached_dates:
        parts.append(
            i18n.t("price_cached_notice", lang, date=max(cached_dates).isoformat())
        )
    return "\n".join(parts)


async def build_supply_reply(farmer: Farmer) -> str:
    """Supply outlook, or an explicit statement that it is not available."""
    if not farmer.district:
        return i18n.t("not_registered", farmer.language)

    from backend.services import supply as supply_service

    lang = farmer.language
    payload = await supply_service.district_forecast(farmer.district)

    if not payload.get("crops"):
        return i18n.t(
            "district_unvalidated",
            lang,
            district=i18n.district_name(farmer.district, lang),
        )

    lines = [
        i18n.t(
            "supply_header",
            lang,
            district=i18n.district_name(farmer.district, lang),
            date=datetime.now(tz=timezone.utc).date().isoformat(),
        )
    ]
    interesting = set(farmer.crops) if farmer.crops else None

    for crop in payload["crops"]:
        if interesting and crop["crop"] not in interesting:
            continue
        name = i18n.crop_name(crop["crop"], lang)
        area = f"{crop['classified_area_ha']:,.1f}"

        if crop["status"] == "OK":
            lines.append(
                i18n.t(
                    "supply_line",
                    lang,
                    crop=name,
                    area=area,
                    volume=f"{crop['projected_volume_mt']:,.0f}",
                    arrivals=f"{crop['observed_arrivals_mt']:,.0f}",
                    ratio=f"{crop['oversupply_ratio']:.2f}",
                )
            )
            if crop["oversupply_ratio"] and crop["oversupply_ratio"] > 1.25:
                lines.append(
                    i18n.t(
                        "supply_oversupply_warning",
                        lang,
                        crop=name,
                        ratio=f"{crop['oversupply_ratio']:.2f}",
                    )
                )
        else:
            lines.append(
                i18n.t(
                    "supply_withheld",
                    lang,
                    crop=name,
                    area=area,
                    reason=crop["detail"] or crop["status"],
                )
            )

    return "\n".join(lines)


async def build_weekly_briefing(farmer: Farmer) -> str:
    lang = farmer.language
    header = i18n.t(
        "weekly_briefing_header",
        lang,
        district=i18n.district_name(farmer.district or "", lang),
        date=datetime.now(tz=timezone.utc).date().isoformat(),
    )
    price_block = await build_price_reply(farmer)
    supply_block = await build_supply_reply(farmer)
    return f"{header}\n\n{price_block}\n\n{supply_block}"


# --------------------------------------------------------------------------
# Inbound state machine
# --------------------------------------------------------------------------


async def handle_inbound(from_phone: str, body: str) -> str:
    """Process one inbound WhatsApp message and return the reply text."""
    phone = normalise_phone(from_phone)
    text = (body or "").strip()
    command = text.upper()

    farmer = await get_farmer(phone)

    # --- Language and subscription commands work in any state --------------
    if command in {"KANNADA", "KAN", "ಕನ್ನಡ"}:
        if farmer:
            farmer = await update_farmer(phone, language="kn") or farmer
            return i18n.t("language_set", "kn")
        farmer = await create_farmer(phone, language="kn")
        return i18n.t("welcome", "kn")

    if command in {"ENGLISH", "ENG"}:
        if farmer:
            farmer = await update_farmer(phone, language="en") or farmer
            return i18n.t("language_set", "en")
        farmer = await create_farmer(phone, language="en")
        return i18n.t("welcome", "en")

    if command in {"STOP", "UNSUBSCRIBE", "CANCEL"}:
        if farmer:
            await update_farmer(phone, opted_in=False)
            return i18n.t("unsubscribed", farmer.language)
        return i18n.t("unsubscribed", "en")

    if command in {"START", "SUBSCRIBE"} and farmer and not farmer.opted_in:
        await update_farmer(phone, opted_in=True)
        return i18n.t("resubscribed", farmer.language)

    # --- First contact ------------------------------------------------------
    if farmer is None:
        farmer = await create_farmer(phone)
        return i18n.t("welcome", farmer.language)

    lang = farmer.language

    if command in {"HELP", "MENU", "?"}:
        return i18n.t("help", lang)

    # --- Registration flow --------------------------------------------------
    if farmer.registration_state in {STATE_NEW, STATE_AWAITING_DISTRICT}:
        district = i18n.parse_district(text, SUPPORTED_DISTRICTS)
        if district is None:
            return i18n.t(
                "district_not_recognised",
                lang,
                value=text,
                districts=", ".join(SUPPORTED_DISTRICTS),
            )
        await update_farmer(
            phone, district=district, registration_state=STATE_AWAITING_CROPS
        )
        return i18n.t("ask_crops", lang, district=i18n.district_name(district, lang))

    if farmer.registration_state == STATE_AWAITING_CROPS:
        crops, unknown = i18n.parse_crops(text)
        if not crops:
            return i18n.t("crops_not_recognised", lang, value=text)
        farmer = (
            await update_farmer(
                phone, crops=crops, registration_state=STATE_REGISTERED
            )
            or farmer
        )
        reply = i18n.t(
            "registered",
            lang,
            district=i18n.district_name(farmer.district or "", lang),
            crops=", ".join(i18n.crop_name(c, lang) for c in crops),
        )
        if unknown:
            reply += "\n" + i18n.t(
                "crops_not_recognised", lang, value=", ".join(unknown)
            )
        return reply

    # --- Registered commands ------------------------------------------------
    if command in {"PRICE", "PRICES", "RATE", "RATES", "ದರ"}:
        return await build_price_reply(farmer)

    if command in {"SUPPLY", "FORECAST", "ಪೂರೈಕೆ"}:
        return await build_supply_reply(farmer)

    if command in {"BRIEF", "BRIEFING", "STATUS"}:
        return await build_weekly_briefing(farmer)

    # Allow a registered farmer to change district or crops by just sending them.
    district = i18n.parse_district(text, SUPPORTED_DISTRICTS)
    if district:
        await update_farmer(phone, district=district)
        return i18n.t("ask_crops", lang, district=i18n.district_name(district, lang))

    crops, _ = i18n.parse_crops(text)
    if crops:
        await update_farmer(phone, crops=crops)
        return i18n.t(
            "registered",
            lang,
            district=i18n.district_name(farmer.district or "", lang),
            crops=", ".join(i18n.crop_name(c, lang) for c in crops),
        )

    return i18n.t("help", lang)


def twiml_response(message: str) -> str:
    """Wrap a reply in TwiML, escaping it so message text cannot inject markup."""
    from xml.sax.saxutils import escape

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{escape(message)}</Message></Response>"
    )


async def health_check() -> dict:
    """Delivery health for the officer console."""
    configured = settings.twilio_configured
    try:
        pending = await pending_outbound_count()
    except db.DatabaseUnavailable as exc:
        return {
            "service": "twilio_whatsapp",
            "healthy": False,
            "detail": f"Cannot read the outbound queue: {exc}",
        }
    return {
        "service": "twilio_whatsapp",
        "healthy": configured and pending == 0,
        "configured": configured,
        "pending_messages": pending,
        "detail": (
            "Twilio credentials are not configured."
            if not configured
            else f"{pending} message(s) awaiting retry."
            if pending
            else "Delivery queue is clear."
        ),
    }

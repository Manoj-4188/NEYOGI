"""``/api/v1/webhooks/twilio`` -- inbound WhatsApp webhook.

Twilio posts ``application/x-www-form-urlencoded``. The signature is computed
over the exact public URL plus every POST parameter, so the URL is rebuilt from
``PUBLIC_BASE_URL`` rather than from the request -- behind a proxy the request's
own scheme and host are the proxy's, not the ones Twilio signed.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request, Response, status as http_status

from backend import db
from backend.config import settings
from backend.services import twilio_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

WEBHOOK_PATH = "/api/v1/webhooks/twilio"


@router.post("/twilio", summary="Twilio WhatsApp inbound message webhook")
async def twilio_inbound(
    request: Request,
    x_twilio_signature: str | None = Header(default=None),
) -> Response:
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}

    public_url = settings.public_base_url.rstrip("/") + WEBHOOK_PATH
    if not twilio_service.validate_signature(public_url, params, x_twilio_signature):
        logger.warning(
            "Rejected an inbound webhook with an invalid Twilio signature "
            "(from=%r)",
            params.get("From"),
        )
        return Response(
            content="invalid signature",
            status_code=http_status.HTTP_403_FORBIDDEN,
            media_type="text/plain",
        )

    from_phone = params.get("From", "")
    body = params.get("Body", "")
    if not from_phone:
        return Response(
            content=twilio_service.twiml_response(""),
            media_type="application/xml",
        )

    try:
        reply = await twilio_service.handle_inbound(from_phone, body)
    except db.DatabaseUnavailable as exc:
        logger.error("Webhook could not reach PostGIS: %s", exc)
        # Answer with TwiML anyway: a 5xx makes Twilio retry and the farmer sees
        # nothing at all.
        from backend.services import i18n

        reply = i18n.t("service_degraded", "en")
    except Exception:  # noqa: BLE001
        logger.exception("Unhandled error while processing an inbound message")
        from backend.services import i18n

        reply = i18n.t("service_degraded", "en")

    return Response(
        content=twilio_service.twiml_response(reply),
        media_type="application/xml",
    )


@router.post("/twilio/status", summary="Twilio delivery status callback")
async def twilio_status(
    request: Request,
    x_twilio_signature: str | None = Header(default=None),
) -> Response:
    """Record delivery outcomes reported by Twilio."""
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}

    public_url = settings.public_base_url.rstrip("/") + "/api/v1/webhooks/twilio/status"
    if not twilio_service.validate_signature(public_url, params, x_twilio_signature):
        return Response(status_code=http_status.HTTP_403_FORBIDDEN)

    sid = params.get("MessageSid")
    message_status = (params.get("MessageStatus") or "").lower()
    if sid and message_status in {"failed", "undelivered"}:
        try:
            await db.execute(
                """
                UPDATE outbound_messages
                SET status = 'failed', last_error = %s
                WHERE provider_sid = %s
                """,
                (f"Twilio reported {message_status}", sid),
            )
        except db.DatabaseUnavailable as exc:
            logger.warning("Could not record delivery failure for %s: %s", sid, exc)

    return Response(status_code=http_status.HTTP_204_NO_CONTENT)

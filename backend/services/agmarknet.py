"""AGMARKNET mandi prices, with a 30-day cached fallback.

Source: the daily market-price resource published on data.gov.in, which
republishes AGMARKNET.

**Why the key sanitizer exists.** That feed has changed its JSON field casing
several times: ``Modal_Price``, ``modal_price``, and -- because the upstream
export escapes spaces -- ``Modal_x0020_Price``. Consuming any one spelling
directly means the integration breaks silently on the day it changes, and
silent breakage here shows a farmer a stale price as though it were current.
:func:`sanitise_record` folds every observed spelling onto one canonical
snake_case key, and anything unrecognised is preserved untouched so it can be
inspected rather than dropped.

**On arrival volumes.** The daily price resource does not reliably publish
arrival tonnage. When it is absent, ``arrival_volume`` stays ``None`` and the
supply/demand ratio downstream reports ``INSUFFICIENT_ARRIVAL_DATA``. It is
never inferred from price movement.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from backend import db, status
from backend.config import settings

logger = logging.getLogger(__name__)

#: Our crop classes mapped to the commodity names AGMARKNET actually uses.
#: "Leafy Greens" is an aggregate of several distinct AGMARKNET commodities.
CROP_TO_COMMODITIES: dict[str, tuple[str, ...]] = {
    "Tomato": ("Tomato",),
    "Onion": ("Onion",),
    "Potato": ("Potato",),
    "Leafy Greens": (
        "Amaranthus",
        "Spinach",
        "Coriander(Leaves)",
        "Methi(Leaves)",
        "Green Chilli",
    ),
}

COMMODITY_TO_CROP: dict[str, str] = {
    commodity.lower(): crop
    for crop, commodities in CROP_TO_COMMODITIES.items()
    for commodity in commodities
}

#: Canonical field names, and every upstream spelling seen for each.
FIELD_ALIASES: dict[str, str] = {
    "state": "state",
    "state_name": "state",
    "district": "district",
    "district_name": "district",
    "market": "market",
    "market_name": "market",
    "commodity": "commodity",
    "commodity_name": "commodity",
    "variety": "variety",
    "grade": "grade",
    "arrival_date": "arrival_date",
    "date": "arrival_date",
    "price_date": "arrival_date",
    "min_price": "min_price",
    "minimum_price": "min_price",
    "max_price": "max_price",
    "maximum_price": "max_price",
    "modal_price": "modal_price",
    "model_price": "modal_price",  # upstream typo, seen in older exports
    "arrivals": "arrival_volume",
    "arrival": "arrival_volume",
    "arrivals_in_qtl": "arrival_volume_qtl",
    "arrival_in_qtl": "arrival_volume_qtl",
    "arrivals_tonnes": "arrival_volume",
    "arrival_tonnes": "arrival_volume",
}

_QUINTALS_PER_TONNE = 10.0

#: Attempts per fetch. The feed answers perhaps one call in ten, so a single
#: try reports "down" for a service that is merely flaky.
FETCH_ATTEMPTS = int(os.getenv("AGMARKNET_FETCH_ATTEMPTS", "4"))

#: Connect quickly -- a slow connect means the host is not answering at all.
#: data.gov.in silently drops requests carrying httpx's default User-Agent.
#: The connection is accepted and the TLS handshake completes, then no
#: response ever arrives and the read times out -- which is why this looked
#: for a long time like an unreliable feed rather than a rejected client.
#: Measured from inside the container against the same URL and IP: the
#: default agent times out after 21s on every attempt, while "curl/8.5.0" and
#: an ordinary browser agent both answer in under a second. Any non-Python
#: agent appears to pass, so this identifies the project honestly rather than
#: impersonating a browser.
REQUEST_USER_AGENT = "NEYOGI/1.0 (Karnataka crop market intelligence)"

CONNECT_TIMEOUT = 8.0

#: Backoff between attempts, doubling each time.
RETRY_BASE_SECONDS = 2.0

# Date formats the feed has used.
_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d")


class AgmarknetUnavailable(RuntimeError):
    """The live feed could not be reached or returned an unusable payload."""


@dataclass
class MandiQuote:
    """One market quote, normalised."""

    district: str
    market: str
    crop: str
    commodity: str
    variety: str
    arrival_date: date
    min_price: float | None
    max_price: float | None
    modal_price: float | None
    #: Tonnes. ``None`` means the feed did not publish arrivals.
    arrival_volume: float | None

    def to_dict(self) -> dict:
        return {
            "district": self.district,
            "market": self.market,
            "crop": self.crop,
            "commodity": self.commodity,
            "variety": self.variety,
            "arrival_date": self.arrival_date.isoformat(),
            "min_price": self.min_price,
            "max_price": self.max_price,
            "modal_price": self.modal_price,
            "arrival_volume_mt": self.arrival_volume,
            "price_unit": "INR/quintal",
        }


# --------------------------------------------------------------------------
# Key sanitiser
# --------------------------------------------------------------------------


def sanitise_key(key: str) -> str:
    """Fold an upstream field name to snake_case.

    Handles the three shapes the feed has used:

    >>> sanitise_key("Modal_Price")
    'modal_price'
    >>> sanitise_key("Modal_x0020_Price")
    'modal_price'
    >>> sanitise_key("arrivalDate")
    'arrival_date'
    """
    text = str(key).strip()
    # data.gov.in escapes spaces as the literal sequence "_x0020_".
    text = re.sub(r"_?x0020_?", "_", text, flags=re.IGNORECASE)
    # camelCase / PascalCase -> snake_case, before lowercasing.
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", text)
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_").lower()


def sanitise_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise every key, mapping known aliases onto canonical names.

    Unrecognised keys keep their sanitised form rather than being discarded, so
    a newly added upstream field shows up in logs instead of vanishing.
    """
    out: dict[str, Any] = {}
    for raw_key, value in record.items():
        key = sanitise_key(raw_key)
        out[FIELD_ALIASES.get(key, key)] = value
    return out


def _to_float(value: Any) -> float | None:
    """Parse a numeric field, treating the feed's placeholders as missing."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "NA", "N/A", "na", "null", "None"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    # The feed uses 0 for "not reported" on price columns.
    return number if number > 0 else None


def _to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    logger.warning("Unparseable AGMARKNET arrival date %r", value)
    return None


def parse_record(record: Mapping[str, Any]) -> MandiQuote | None:
    """Turn one raw feed record into a :class:`MandiQuote`.

    Returns ``None`` when the record lacks the fields that make it meaningful
    (commodity, district, date) or names a commodity outside our crop set.
    """
    clean = sanitise_record(record)

    commodity = str(clean.get("commodity") or "").strip()
    district = str(clean.get("district") or "").strip()
    arrival_date = _to_date(clean.get("arrival_date"))
    if not commodity or not district or arrival_date is None:
        return None

    crop = COMMODITY_TO_CROP.get(commodity.lower())
    if crop is None:
        return None

    # Arrivals arrive either in tonnes or in quintals depending on the export.
    arrival_volume = _to_float(clean.get("arrival_volume"))
    if arrival_volume is None:
        quintals = _to_float(clean.get("arrival_volume_qtl"))
        arrival_volume = quintals / _QUINTALS_PER_TONNE if quintals is not None else None

    return MandiQuote(
        district=district,
        market=str(clean.get("market") or "").strip() or "Unknown",
        crop=crop,
        commodity=commodity,
        variety=str(clean.get("variety") or "").strip(),
        arrival_date=arrival_date,
        min_price=_to_float(clean.get("min_price")),
        max_price=_to_float(clean.get("max_price")),
        modal_price=_to_float(clean.get("modal_price")),
        arrival_volume=arrival_volume,
    )


def parse_payload(payload: Mapping[str, Any]) -> list[MandiQuote]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise AgmarknetUnavailable(
            f"Unexpected payload shape: expected a 'records' list, got "
            f"{type(records).__name__}"
        )
    quotes = [q for q in (parse_record(r) for r in records) if q is not None]
    logger.info("AGMARKNET: parsed %d/%d record(s)", len(quotes), len(records))
    return quotes


# --------------------------------------------------------------------------
# Live fetch
# --------------------------------------------------------------------------


async def fetch_live(
    district: str,
    crop: str | None = None,
    limit: int = 1000,
) -> list[MandiQuote]:
    """Query the live data.gov.in resource.

    Raises:
        AgmarknetUnavailable: on a missing API key, a transport error, or an
            unusable payload. The caller falls back to the cache and flags it.
    """
    if not settings.agmarknet_configured:
        raise AgmarknetUnavailable(
            "AGMARKNET_API_KEY is not set; register at data.gov.in for a key."
        )

    import httpx

    params: dict[str, Any] = {
        "api-key": settings.agmarknet_api_key,
        "format": "json",
        "limit": limit,
        "filters[state]": settings.agmarknet_state,
        "filters[district]": district,
    }
    if crop:
        commodities = CROP_TO_COMMODITIES.get(crop)
        if not commodities:
            raise AgmarknetUnavailable(f"No AGMARKNET commodity mapping for {crop!r}")
        # The API filters on a single value; the first commodity is the primary
        # one for the class and the rest are covered by the unfiltered sweep.
        params["filters[commodity]"] = commodities[0]

    url = f"{settings.agmarknet_base_url}/{settings.agmarknet_resource_id}"

    last_error: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    settings.agmarknet_timeout_seconds, connect=CONNECT_TIMEOUT
                ),
                headers={"User-Agent": REQUEST_USER_AGENT},
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            # A 4xx will not fix itself on retry; a 5xx might.
            if 400 <= exc.response.status_code < 500:
                raise AgmarknetUnavailable(
                    f"AGMARKNET returned HTTP {exc.response.status_code}"
                ) from exc
            last_error = exc
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
        else:
            if attempt > 1:
                logger.info("AGMARKNET answered on attempt %d", attempt)
            return parse_payload(payload)

        if attempt < FETCH_ATTEMPTS:
            delay = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            logger.debug(
                "AGMARKNET attempt %d/%d failed (%s); retrying in %ss",
                attempt,
                FETCH_ATTEMPTS,
                type(last_error).__name__,
                delay,
            )
            await asyncio.sleep(delay)

    raise AgmarknetUnavailable(
        f"AGMARKNET did not answer in {FETCH_ATTEMPTS} attempts "
        f"({type(last_error).__name__ if last_error else 'unknown'}). The feed "
        "is intermittently unreachable; the scheduled poller keeps trying."
    )


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


async def cache_quotes(quotes: Sequence[MandiQuote]) -> int:
    """Persist live quotes so the fallback has something to serve."""
    if not quotes:
        return 0
    rows = [
        (
            q.district,
            q.market,
            q.crop,
            q.variety,
            q.arrival_date,
            q.min_price,
            q.max_price,
            q.modal_price,
            q.arrival_volume,
        )
        for q in quotes
    ]
    async with db.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO mandi_prices_cache
                (district, market, crop, variety, arrival_date,
                 min_price, max_price, modal_price, arrival_volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (district, market, crop, variety, arrival_date)
            DO UPDATE SET
                min_price      = EXCLUDED.min_price,
                max_price      = EXCLUDED.max_price,
                modal_price    = EXCLUDED.modal_price,
                -- Never overwrite a real arrival figure with a NULL from a
                -- later fetch that omitted the column.
                arrival_volume = COALESCE(EXCLUDED.arrival_volume,
                                          mandi_prices_cache.arrival_volume),
                fetched_at     = now()
            """,
            rows,
        )
    return len(rows)


async def cached_quotes(
    district: str, crop: str | None = None, days: int | None = None
) -> list[MandiQuote]:
    """Read back cached quotes within the fallback window."""
    days = days or settings.market_cache_max_age_days
    since = datetime.now(tz=timezone.utc).date() - timedelta(days=days)

    clauses = ["district = %s", "arrival_date >= %s"]
    params: list[Any] = [district, since]
    if crop:
        clauses.append("crop = %s")
        params.append(crop)

    rows = await db.fetch_all(
        f"""
        SELECT district, market, crop, variety, arrival_date,
               min_price, max_price, modal_price, arrival_volume
        FROM mandi_prices_cache
        WHERE {' AND '.join(clauses)}
        ORDER BY arrival_date DESC, market
        """,
        params,
    )
    return [
        MandiQuote(
            district=r[0],
            market=r[1],
            crop=r[2],
            commodity=r[2],
            variety=r[3],
            arrival_date=r[4],
            min_price=float(r[5]) if r[5] is not None else None,
            max_price=float(r[6]) if r[6] is not None else None,
            modal_price=float(r[7]) if r[7] is not None else None,
            arrival_volume=float(r[8]) if r[8] is not None else None,
        )
        for r in rows
    ]


async def moving_average(
    district: str, crop: str, days: int | None = None
) -> dict | None:
    """30-day moving average of the modal price -- the documented fallback."""
    days = days or settings.market_cache_max_age_days
    since = datetime.now(tz=timezone.utc).date() - timedelta(days=days)

    row = await db.fetch_one(
        """
        SELECT AVG(modal_price)::float,
               MIN(min_price)::float,
               MAX(max_price)::float,
               SUM(arrival_volume)::float,
               COUNT(*) FILTER (WHERE modal_price IS NOT NULL),
               COUNT(*) FILTER (WHERE arrival_volume IS NOT NULL),
               MAX(arrival_date)
        FROM mandi_prices_cache
        WHERE district = %s AND crop = %s AND arrival_date >= %s
        """,
        (district, crop, since),
    )
    if not row or row[4] in (None, 0):
        return None

    return {
        "district": district,
        "crop": crop,
        "window_days": days,
        "modal_price_avg": row[0],
        "min_price": row[1],
        "max_price": row[2],
        # NULL, not 0, when no row in the window reported arrivals.
        "arrival_volume_mt": row[3] if row[5] else None,
        "quote_count": row[4],
        "arrival_report_count": row[5],
        "latest_arrival_date": row[6],
    }


async def total_arrivals_mt(
    district: str, crop: str, window_days: int
) -> float | None:
    """Observed arrival tonnage over a window, or ``None`` if unpublished."""
    since = datetime.now(tz=timezone.utc).date() - timedelta(days=window_days)
    row = await db.fetch_one(
        """
        SELECT SUM(arrival_volume)::float,
               COUNT(*) FILTER (WHERE arrival_volume IS NOT NULL)
        FROM mandi_prices_cache
        WHERE district = %s AND crop = %s AND arrival_date >= %s
        """,
        (district, crop, since),
    )
    if not row or not row[1]:
        return None
    return row[0]


# --------------------------------------------------------------------------
# Orchestration: live primary, cache fallback, badge either way
# --------------------------------------------------------------------------


async def get_prices(
    district: str, crop: str | None = None
) -> tuple[list[MandiQuote], status.StatusBadge]:
    """Live prices if possible, cached ones if not -- and say which."""
    try:
        quotes = await fetch_live(district, crop)
        if quotes:
            try:
                await cache_quotes(quotes)
            except db.DatabaseUnavailable as exc:
                logger.warning("Fetched live prices but could not cache them: %s", exc)
            newest = max(q.arrival_date for q in quotes)
            return quotes, status.market_live(newest)
        reason = "AGMARKNET returned no records for this district and crop."
    except AgmarknetUnavailable as exc:
        logger.warning("AGMARKNET live fetch failed, falling back to cache: %s", exc)
        reason = str(exc)

    try:
        cached = await cached_quotes(district, crop)
    except db.DatabaseUnavailable as exc:
        return [], status.market_unavailable(
            f"{reason} The price cache is also unreachable: {exc}"
        )

    if not cached:
        return [], status.market_unavailable(reason)

    newest = max(q.arrival_date for q in cached)
    return cached, status.market_cached(newest, reason=reason)

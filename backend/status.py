"""Data-source status badges.

Every response that carries data a user might act on also carries a badge
saying where that data came from and how old it is. The badge is constructed
here, server-side, from the same facts the query used -- the frontend renders
it but never decides it, so there is no way for the UI to show "live" over
cached numbers.

Badge vocabulary (matching the product spec):

===================== ==================================================
Situation             Badge
===================== ==================================================
Live Sentinel-2       🟢 LIVE SATELLITE (YYYY-MM-DD)
Cached composite      🟡 CACHED SATELLITE TILE (YYYY-MM-DD)
No imagery at all     🔴 SATELLITE DATA UNAVAILABLE
Live AGMARKNET        🟢 LIVE MARKET DATA
Cached prices         🟡 MARKET DATA CACHED
No price data         🔴 MARKET DATA UNAVAILABLE
Verified ground truth 🟢 VALIDATED DISTRICT
No verified labels    🔴 UNVALIDATED DISTRICT (No Verified Labels)
===================== ==================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Iterable

from backend.config import settings


class SourceKind(str, Enum):
    SATELLITE = "satellite"
    MARKET = "market"
    GROUND_TRUTH = "ground_truth"
    MODEL = "model"
    ALERTS = "alerts"


class SourceStatus(str, Enum):
    LIVE = "LIVE"
    CACHED = "CACHED"
    UNAVAILABLE = "UNAVAILABLE"
    UNVALIDATED = "UNVALIDATED"
    QUEUED = "QUEUED"


class Severity(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


_SEVERITY_ICON = {Severity.OK: "🟢", Severity.WARN: "🟡", Severity.ERROR: "🔴"}


@dataclass
class StatusBadge:
    """One data source's provenance, ready to render."""

    source: SourceKind
    status: SourceStatus
    label: str
    severity: Severity
    detail: str = ""
    as_of: date | None = None
    age_days: int | None = None
    is_fallback: bool = False

    @property
    def icon(self) -> str:
        return _SEVERITY_ICON[self.severity]

    def to_dict(self) -> dict:
        return {
            "source": self.source.value,
            "status": self.status.value,
            "label": self.label,
            "severity": self.severity.value,
            "icon": self.icon,
            "detail": self.detail,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "age_days": self.age_days,
            "is_fallback": self.is_fallback,
        }


@dataclass
class StatusSet:
    """The badges attached to one response."""

    badges: list[StatusBadge] = field(default_factory=list)

    def add(self, badge: StatusBadge) -> "StatusSet":
        self.badges.append(badge)
        return self

    def extend(self, badges: Iterable[StatusBadge]) -> "StatusSet":
        self.badges.extend(badges)
        return self

    @property
    def degraded(self) -> bool:
        """True when any source is on a fallback or missing entirely."""
        return any(b.is_fallback or b.severity is not Severity.OK for b in self.badges)

    @property
    def worst_severity(self) -> Severity:
        if any(b.severity is Severity.ERROR for b in self.badges):
            return Severity.ERROR
        if any(b.severity is Severity.WARN for b in self.badges):
            return Severity.WARN
        return Severity.OK

    def to_dict(self) -> dict:
        return {
            "degraded": self.degraded,
            "worst_severity": self.worst_severity.value,
            "badges": [b.to_dict() for b in self.badges],
        }


def _age_days(as_of: date | None) -> int | None:
    if as_of is None:
        return None
    return (datetime.now(tz=timezone.utc).date() - as_of).days


# --------------------------------------------------------------------------
# Satellite
# --------------------------------------------------------------------------


def satellite_live(observed_on: date) -> StatusBadge:
    return StatusBadge(
        source=SourceKind.SATELLITE,
        status=SourceStatus.LIVE,
        severity=Severity.OK,
        label=f"🟢 LIVE SATELLITE ({observed_on.isoformat()})",
        detail="Composite built from Sentinel-2 L2A imagery fetched just now.",
        as_of=observed_on,
        age_days=_age_days(observed_on),
        is_fallback=False,
    )


def satellite_cached(observed_on: date, reason: str = "") -> StatusBadge:
    """The 🟡 cached-tile badge, dated with the composite it is serving.

    Beyond ``SATELLITE_CACHE_MAX_AGE_DAYS`` the cache is considered stale and
    the badge escalates to red -- an old composite is not a substitute for a
    current one.
    """
    age = _age_days(observed_on) or 0
    stale = age > settings.satellite_cache_max_age_days

    if stale:
        return StatusBadge(
            source=SourceKind.SATELLITE,
            status=SourceStatus.UNAVAILABLE,
            severity=Severity.ERROR,
            label=f"🔴 SATELLITE DATA STALE ({observed_on.isoformat()})",
            detail=(
                f"Newest cached composite is {age} days old, beyond the "
                f"{settings.satellite_cache_max_age_days}-day limit. "
                + (reason or "Earth Engine is unreachable.")
            ),
            as_of=observed_on,
            age_days=age,
            is_fallback=True,
        )

    return StatusBadge(
        source=SourceKind.SATELLITE,
        status=SourceStatus.CACHED,
        severity=Severity.WARN,
        label=f"🟡 CACHED SATELLITE TILE ({observed_on.isoformat()})",
        detail=(
            reason
            or "Serving the last stored 16-day median composite from PostGIS; "
            "Earth Engine was unreachable."
        ),
        as_of=observed_on,
        age_days=age,
        is_fallback=True,
    )


def satellite_unavailable(reason: str = "") -> StatusBadge:
    return StatusBadge(
        source=SourceKind.SATELLITE,
        status=SourceStatus.UNAVAILABLE,
        severity=Severity.ERROR,
        label="🔴 SATELLITE DATA UNAVAILABLE",
        detail=(
            reason
            or "Earth Engine is unreachable and the PostGIS composite cache is "
            "empty. Run the 60-day seed ingestion to populate it."
        ),
        is_fallback=True,
    )


# --------------------------------------------------------------------------
# Market prices
# --------------------------------------------------------------------------


def market_live(as_of: date | None = None) -> StatusBadge:
    return StatusBadge(
        source=SourceKind.MARKET,
        status=SourceStatus.LIVE,
        severity=Severity.OK,
        label="🟢 LIVE MARKET DATA",
        detail="Prices fetched from the AGMARKNET feed on data.gov.in.",
        as_of=as_of,
        age_days=_age_days(as_of),
        is_fallback=False,
    )


def market_cached(as_of: date | None, reason: str = "") -> StatusBadge:
    """The 🟡 cached-market badge, backed by the 30-day moving average."""
    age = _age_days(as_of)
    stale = age is not None and age > settings.market_cache_max_age_days

    if stale:
        return StatusBadge(
            source=SourceKind.MARKET,
            status=SourceStatus.UNAVAILABLE,
            severity=Severity.ERROR,
            label="🔴 MARKET DATA STALE",
            detail=(
                f"Newest cached quote is {age} days old, beyond the "
                f"{settings.market_cache_max_age_days}-day window."
            ),
            as_of=as_of,
            age_days=age,
            is_fallback=True,
        )

    return StatusBadge(
        source=SourceKind.MARKET,
        status=SourceStatus.CACHED,
        severity=Severity.WARN,
        label="🟡 MARKET DATA CACHED",
        detail=(
            reason
            or "AGMARKNET was unreachable; showing the 30-day moving average "
            "from the PostGIS price cache."
        ),
        as_of=as_of,
        age_days=age,
        is_fallback=True,
    )


def market_unavailable(reason: str = "") -> StatusBadge:
    return StatusBadge(
        source=SourceKind.MARKET,
        status=SourceStatus.UNAVAILABLE,
        severity=Severity.ERROR,
        label="🔴 MARKET DATA UNAVAILABLE",
        detail=(
            reason
            or "AGMARKNET is unreachable and no cached quotes exist for this "
            "district and crop."
        ),
        is_fallback=True,
    )


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------


def district_validated(verified_count: int, last_verified: date | None = None) -> StatusBadge:
    return StatusBadge(
        source=SourceKind.GROUND_TRUTH,
        status=SourceStatus.LIVE,
        severity=Severity.OK,
        label="🟢 VALIDATED DISTRICT",
        detail=(
            f"{verified_count} field-verified parcel(s) back the crop "
            "classification for this district."
        ),
        as_of=last_verified,
        age_days=_age_days(last_verified),
        is_fallback=False,
    )


def district_unvalidated(district: str, parcel_count: int = 0) -> StatusBadge:
    """The 🔴 badge that accompanies an NDVI-basemap-only response.

    This is the visible half of the rule that unvalidated districts are never
    classified. It is not an error state -- it is an accurate description of
    what is and is not known.
    """
    return StatusBadge(
        source=SourceKind.GROUND_TRUTH,
        status=SourceStatus.UNVALIDATED,
        severity=Severity.ERROR,
        label="🔴 UNVALIDATED DISTRICT (No Verified Labels)",
        detail=(
            f"{district} has no field-verified parcels"
            + (f" ({parcel_count} unverified boundaries loaded)" if parcel_count else "")
            + ". Showing the raw Sentinel-2 NDVI basemap only -- no crop "
            "classification is produced without verified ground truth."
        ),
        is_fallback=False,
    )


# --------------------------------------------------------------------------
# Model and alerts
# --------------------------------------------------------------------------


def model_active(model_version: str, kappa: float | None = None) -> StatusBadge:
    detail = f"Active classifier: {model_version}."
    if kappa is not None:
        detail += f" Hold-out Cohen's kappa {kappa:.3f}."
    return StatusBadge(
        source=SourceKind.MODEL,
        status=SourceStatus.LIVE,
        severity=Severity.OK,
        label=f"🟢 MODEL {model_version}",
        detail=detail,
    )


def model_unavailable(reason: str = "") -> StatusBadge:
    return StatusBadge(
        source=SourceKind.MODEL,
        status=SourceStatus.UNAVAILABLE,
        severity=Severity.ERROR,
        label="🔴 NO TRAINED MODEL",
        detail=(
            reason
            or "No active classifier is registered. Districts render as raw "
            "spectral indices only."
        ),
        is_fallback=True,
    )


def alerts_live() -> StatusBadge:
    return StatusBadge(
        source=SourceKind.ALERTS,
        status=SourceStatus.LIVE,
        severity=Severity.OK,
        label="🟢 WHATSAPP ALERTS LIVE",
        detail="Twilio WhatsApp delivery is configured and responding.",
    )


def alerts_queued(pending: int, reason: str = "") -> StatusBadge:
    return StatusBadge(
        source=SourceKind.ALERTS,
        status=SourceStatus.QUEUED,
        severity=Severity.WARN,
        label=f"🟡 ALERTS QUEUED ({pending})",
        detail=(
            reason
            or f"{pending} advisory message(s) awaiting retry on the Celery "
            "queue with exponential backoff."
        ),
        is_fallback=True,
    )

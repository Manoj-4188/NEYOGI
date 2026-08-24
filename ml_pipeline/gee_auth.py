"""Earth Engine authentication.

Two paths are supported:

* **Service account** (required for containers, Celery workers and CI). Set
  ``GEE_SERVICE_ACCOUNT_EMAIL`` and ``GEE_SERVICE_ACCOUNT_KEY_FILE``.
* **Interactive user credentials** for local development, i.e. the token that
  ``earthengine authenticate`` writes to the developer's home directory.

``initialize()`` is idempotent and caches its result, so it is safe to call at
the top of every entry point.
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_INITIALISED = False


class EarthEngineUnavailable(RuntimeError):
    """Raised when Earth Engine cannot be reached or authenticated.

    Callers must translate this into a cached-data fallback plus a UI status
    badge -- never into fabricated imagery.
    """


def initialize(force: bool = False) -> None:
    """Initialise the Earth Engine client library.

    Raises:
        EarthEngineUnavailable: if the ``earthengine-api`` package is missing or
            the credentials are absent or rejected.
    """
    global _INITIALISED
    with _LOCK:
        if _INITIALISED and not force:
            return

        try:
            import ee
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise EarthEngineUnavailable(
                "earthengine-api is not installed; "
                "install ml_pipeline/requirements.txt"
            ) from exc

        project = os.getenv("GEE_PROJECT_ID") or None
        sa_email = os.getenv("GEE_SERVICE_ACCOUNT_EMAIL", "").strip()
        key_file = os.getenv("GEE_SERVICE_ACCOUNT_KEY_FILE", "").strip()

        try:
            if sa_email and key_file and os.path.exists(key_file):
                logger.info(
                    "Initialising Earth Engine with service account %s", sa_email
                )
                credentials = ee.ServiceAccountCredentials(sa_email, key_file)
                ee.Initialize(credentials, project=project)
            else:
                if sa_email or key_file:
                    logger.warning(
                        "Service-account variables are set but key file %r is not "
                        "readable; falling back to stored user credentials.",
                        key_file,
                    )
                logger.info("Initialising Earth Engine with stored user credentials")
                ee.Initialize(project=project)
        except Exception as exc:  # noqa: BLE001 - ee raises many concrete types
            raise EarthEngineUnavailable(
                f"Earth Engine initialisation failed: {exc}"
            ) from exc

        _INITIALISED = True
        logger.info("Earth Engine initialised (project=%s)", project or "<default>")


def is_initialised() -> bool:
    return _INITIALISED


def health_check() -> dict:
    """Cheap round trip used by the officer telemetry endpoint.

    Returns a structured dict rather than raising, because telemetry must be
    able to *report* an outage without becoming one.
    """
    try:
        initialize()
        import ee

        # Smallest possible server round trip.
        value = ee.Number(1).getInfo()
        healthy = value == 1
        return {
            "service": "google_earth_engine",
            "healthy": bool(healthy),
            "detail": "round-trip ok" if healthy else f"unexpected response: {value!r}",
        }
    except EarthEngineUnavailable as exc:
        return {"service": "google_earth_engine", "healthy": False, "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"service": "google_earth_engine", "healthy": False, "detail": repr(exc)}

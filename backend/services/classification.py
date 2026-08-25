"""District crop classification, served from the cache with live fallback.

Reads the newest stored classification for a district. When none exists the
caller can ask for one to be computed on the spot — the sampling run takes
tens of seconds, so it is not done implicitly on every page load.

Every payload carries the spectral model's caveat. The UI shows crop names and
confidences, and is required to show that caveat next to them: these are
indicative estimates from spectral signatures, not field-verified observations.
"""

from __future__ import annotations

import logging
from datetime import date

from backend import db, status

logger = logging.getLogger(__name__)

MODEL_NOTE = "Field verification pending — accuracy improves with ground truth"
MODEL_SOURCE = "spectral_index_threshold_model"


async def latest_for_district(district: str) -> dict | None:
    """Newest stored classification, or None if the district has never run."""
    rows = await db.fetch_all(
        """
        SELECT crop, area_ha, mean_confidence, sample_count, share,
               share_stderr, composite_start, samples_classified,
               cropland_area_ha, scene_count, classified_at
        FROM district_classification_latest
        WHERE district = %s
        ORDER BY area_ha DESC
        """,
        (district,),
    )
    if not rows:
        return None

    first = rows[0]
    return {
        "district": district,
        "composite_start": first[6].isoformat(),
        "samples_classified": int(first[7]),
        "cropland_area_ha": round(float(first[8]), 1),
        "scene_count": int(first[9]),
        "classified_at": first[10].isoformat(),
        "source": MODEL_SOURCE,
        "note": MODEL_NOTE,
        "crops": [
            {
                "crop": r[0],
                "area_ha": round(float(r[1]), 1),
                "confidence": round(float(r[2]), 3),
                "sample_count": int(r[3]),
                "share": round(float(r[4]), 4),
                "share_stderr": round(float(r[5]), 4),
            }
            for r in rows
        ],
    }


def _badge(has_results: bool, composite_start: date | None = None):
    """Amber when showing model output; red when there is nothing to show.

    Never green. A spectral estimate without field verification does not get
    the same visual weight as a measured observation.
    """
    if has_results:
        return status.StatusBadge(
            source=status.SourceKind.MODEL,
            status=status.SourceStatus.CACHED,
            severity=status.Severity.WARN,
            label="SPECTRAL MODEL",
            detail=(
                "Crop classes estimated from Sentinel-2 spectral signatures"
                + (f" for the composite starting {composite_start}." if composite_start else ".")
                + " Field verification pending."
            ),
            as_of=composite_start,
            is_fallback=True,
        )
    return status.StatusBadge(
        source=status.SourceKind.MODEL,
        status=status.SourceStatus.UNAVAILABLE,
        severity=status.Severity.ERROR,
        label="NO CLASSIFICATION",
        detail=(
            "No classification has been computed for this district yet, or no "
            "cloud-free imagery was available in the last composite window."
        ),
        is_fallback=False,
    )


async def get_classification(district: str) -> dict:
    """Classification payload plus its status badge."""
    try:
        stored = await latest_for_district(district)
    except db.DatabaseUnavailable as exc:
        logger.warning("Classification lookup failed for %s: %s", district, exc)
        stored = None

    if stored is None:
        return {
            "district": district,
            "crops": [],
            "source": MODEL_SOURCE,
            "note": MODEL_NOTE,
            "status": status.StatusSet().add(_badge(False)).to_dict(),
        }

    composite = date.fromisoformat(stored["composite_start"])
    stored["status"] = status.StatusSet().add(_badge(True, composite)).to_dict()
    return stored


def run_classification_sync(district_name: str, sample_size: int = 400) -> dict:
    """Blocking sampling run for one district. Call in a worker thread."""
    from ml_pipeline.district_classification import classify_district, persist
    from ml_pipeline.gee_districts import resolve_districts

    resolution = resolve_districts([district_name])
    district = resolution.get(district_name)
    if district is None:
        return {
            "district": district_name,
            "status": "UNRESOLVED",
            "detail": "No boundary source carries this district.",
        }

    result = classify_district(district, sample_size=sample_size)
    persist(result)
    return result.to_dict()

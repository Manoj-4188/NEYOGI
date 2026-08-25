"""Central configuration for the ML pipeline.

Values are read from the environment so that the same code runs unchanged in a
developer shell, in the Celery worker container and in a CI job.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
MODEL_DIR = DATA_DIR / "models"
EXPORT_DIR = DATA_DIR / "exports"
GROUND_TRUTH_DIR = DATA_DIR / "ground_truth"
REFERENCE_DIR = DATA_DIR / "reference"

MODEL_PATH = MODEL_DIR / "rf_crop_classifier.joblib"
MODEL_METRICS_PATH = MODEL_DIR / "rf_crop_classifier.metrics.json"
BASELINE_YIELD_PATH = REFERENCE_DIR / "baseline_yields.yml"

# Candidate districts for the Karnataka perishable-crop belt. These are
# *candidates only*: gee_districts.resolve_districts() must confirm each one
# against FAO/GAUL/2015/level2 ADM2_NAME at runtime before any query is issued.
CANDIDATE_DISTRICTS: tuple[str, ...] = (
    "Kolar",
    "Chikkaballapur",
    "Bengaluru Rural",
    "Ramanagara",
    "Tumakuru",
    "Hassan",
    "Mandya",
    "Chikkamagaluru",
)

STATE_NAME = os.getenv("GAUL_STATE_NAME", "Karnataka")
COUNTRY_NAME = os.getenv("GAUL_COUNTRY_NAME", "India")

GAUL_LEVEL2 = "FAO/GAUL/2015/level2"
GAUL_LEVEL1 = "FAO/GAUL/2015/level1"
S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

# --------------------------------------------------------------------------
# Boundary sources
#
# GAUL is primary. Its 2015 snapshot predates several Indian district
# reorganisations, though: Karnataka created Chikkaballapura (from Kolar) and
# Ramanagara (from Bangalore Rural) in 2007, and GAUL carries neither -- only
# 27 ADM2 features exist for the state.
#
# geoBoundaries CGAZ is the documented fallback for exactly those cases. It is
# open data (CC-BY 4.0, William & Mary geoLab) and current enough to include
# both districts. It is a *fallback*, not a replacement: a district that
# resolves against GAUL keeps the GAUL polygon, so the primary source stays
# authoritative and any substitution is visible in the resolution report.
# --------------------------------------------------------------------------
GEOBOUNDARIES_ADM2 = "projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM2"

#: Country code used by geoBoundaries' ``shapeGroup`` property (ISO 3166-1 a3).
GEOBOUNDARIES_COUNTRY = os.getenv("GEOBOUNDARIES_COUNTRY", "IND")

#: Set false to disable the fallback and leave post-2007 districts unresolved.
USE_BOUNDARY_FALLBACK = os.getenv("USE_BOUNDARY_FALLBACK", "true").lower() not in {
    "0",
    "false",
    "no",
}

# Sentinel-2 native resolution for the 10 m bands. reduceRegions runs at this
# scale so that parcel statistics are computed from real pixels rather than a
# resampled pyramid level.
NATIVE_SCALE_M = 10

# Sentinel-2 Scene Classification Layer classes to mask out.
#   3  = cloud shadow
#   8  = cloud medium probability
#   9  = cloud high probability
#   10 = thin cirrus
SCL_MASK_CLASSES: tuple[int, ...] = (3, 8, 9, 10)

# Sentinel-2 reflectance is stored as scaled integers; divide by this to get
# surface reflectance in [0, 1].
S2_REFLECTANCE_SCALE = 10_000.0


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class PipelineSettings:
    """Runtime knobs that control freshness policy and composite cadence."""

    composite_period_days: int = field(
        default_factory=lambda: _int_env("COMPOSITE_PERIOD_DAYS", 16)
    )
    seed_lookback_days: int = field(
        default_factory=lambda: _int_env("GEE_SEED_LOOKBACK_DAYS", 60)
    )
    satellite_cache_max_age_days: int = field(
        default_factory=lambda: _int_env("SATELLITE_CACHE_MAX_AGE_DAYS", 30)
    )
    market_cache_max_age_days: int = field(
        default_factory=lambda: _int_env("MARKET_CACHE_MAX_AGE_DAYS", 30)
    )
    # A composite built from fewer than this many cloud-free scenes is flagged
    # low-confidence rather than silently accepted.
    min_scenes_per_composite: int = field(
        default_factory=lambda: _int_env("MIN_SCENES_PER_COMPOSITE", 2)
    )
    max_cloud_cover_pct: int = field(
        default_factory=lambda: _int_env("MAX_CLOUD_COVER_PCT", 60)
    )

    @property
    def database_url(self) -> str:
        return os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://neyogi:neyogi@localhost:5432/neyogi",
        )


SETTINGS = PipelineSettings()

# Crop classes the Random Forest is allowed to emit. "Fallow/Non-Crop" is a
# real, labelled class -- not a fallback bucket for low-confidence predictions.
CROP_CLASSES: tuple[str, ...] = (
    "Tomato",
    "Onion",
    "Potato",
    "Leafy Greens",
    "Fallow/Non-Crop",
)

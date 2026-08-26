"""Spectral crop classifier.

Wraps the pre-trained RandomForest in ``models/`` — 300 trees over 17 features
(the eleven vegetation indices plus six Sentinel-2 bands), emitting one of
``leafy_greens``, ``onion``, ``other``, ``tomato``.

Scope and honesty
-----------------
This model is trained on spectral signatures, not on field-verified parcels
from this belt. It produces an *indicative* crop signal, and every result it
returns carries that caveat in the payload (``source`` and ``note``) so no
caller can present a prediction as a verified observation. The UI is required
to render the caveat alongside the crop name.

This is deliberately a different thing from ``ml_pipeline.inference``, which
runs the ground-truth-trained classifier and stays gated on
``verified_flag = TRUE``. Both can coexist: this one gives coverage today,
that one gives defensibility once a field survey exists. They are never mixed
in a single answer.

Missing features are the one place to be careful. ``predict_crop`` substitutes
0.0 for an absent column because the estimator requires a dense row, but it
also reports which columns were missing, and refuses outright when too few are
present — a vector of mostly zeros would still yield a confident-looking class.
"""

from __future__ import annotations

import logging
import os
import warnings
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "neyogi_crop_model.pkl")
FEATURES_PATH = os.path.join(os.path.dirname(__file__), "models", "feature_columns.pkl")

#: Below this many real features the input is too sparse to classify. The model
#: takes 17 columns; a row padded mostly with zeros produces a confident
#: prediction from essentially no evidence, which is the failure this guards.
MIN_REAL_FEATURES = 10

#: The model was fitted on raw Sentinel-2 digital numbers for its band
#: features -- the training CSV carries B2..B12 in the 40..4,900 range. The
#: ingestion pipeline divides bands by 10,000 to get surface reflectance, so
#: without this the band features arrive four orders of magnitude below
#: anything the model saw while fitting.
#:
#: The index features are ratios and therefore scale-invariant, which is why
#: this went unnoticed: they dominate the forest's splits, so only about 0.2%
#: of predictions actually flip. It is still wrong, and it silently degrades
#: every band-based split in all 300 trees.
BAND_TRAINING_SCALE = 10_000.0

#: Bands are recognised by name; everything else is an index and is passed
#: through untouched.
_BAND_PREFIX = "B"

SOURCE_LABEL = "spectral_index_threshold_model"
PENDING_NOTE = "Field verification pending — accuracy improves with ground truth"


class ModelUnavailable(RuntimeError):
    """The spectral model artifact could not be loaded."""


class InsufficientFeatures(ValueError):
    """Too few of the model's features were supplied to classify honestly."""


@lru_cache(maxsize=1)
def _load() -> tuple[object, list[str]]:
    """Load and cache the estimator and its feature column order."""
    import joblib

    for path in (MODEL_PATH, FEATURES_PATH):
        if not os.path.exists(path):
            raise ModelUnavailable(f"Model artifact missing: {path}")
    try:
        model = joblib.load(MODEL_PATH)
        columns = list(joblib.load(FEATURES_PATH))
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailable(f"Could not load the spectral model: {exc}") from exc

    expected = getattr(model, "n_features_in_", len(columns))
    if expected != len(columns):
        raise ModelUnavailable(
            f"Feature contract mismatch: estimator expects {expected} columns, "
            f"feature_columns.pkl lists {len(columns)}."
        )
    logger.info(
        "Spectral model loaded: %d features, classes %s",
        len(columns),
        list(getattr(model, "classes_", [])),
    )
    return model, columns


def feature_columns() -> list[str]:
    """The exact column order the estimator was fitted on."""
    return list(_load()[1])


def class_labels() -> list[str]:
    return [str(c) for c in getattr(_load()[0], "classes_", [])]


def predict_crop(feature_dict: dict) -> dict:
    """Classify one feature vector.

    Args:
        feature_dict: mapping of feature name to value. Keys are matched
            case-insensitively against the model's column names.

    Returns:
        ``crop_type``, ``confidence``, ``source``, ``note``, plus
        ``probabilities`` per class and ``missing_features`` naming any column
        that had to be padded.

    Raises:
        InsufficientFeatures: when fewer than ``MIN_REAL_FEATURES`` of the
            model's columns were supplied.
        ModelUnavailable: when the artifact cannot be loaded.
    """
    model, columns = _load()

    # Case-insensitive lookup: GEE band names and index names vary in case
    # between callers, and a silent miss would become a padded zero.
    lookup = {str(k).strip().upper(): v for k, v in (feature_dict or {}).items()}

    values: list[float] = []
    missing: list[str] = []
    for column in columns:
        raw = lookup.get(column.upper())
        if raw is None or (isinstance(raw, float) and np.isnan(raw)):
            missing.append(column)
            values.append(0.0)
            continue

        value = float(raw)
        # Rescale reflectance back to the digital numbers the model was fitted
        # on. A caller that already supplies raw DN (the training CSV, for
        # instance) is left alone: reflectance is bounded by 1.0, so anything
        # above that is already in DN.
        if column.upper().startswith(_BAND_PREFIX) and abs(value) <= 1.0:
            value *= BAND_TRAINING_SCALE
        values.append(value)

    present = len(columns) - len(missing)
    if present < MIN_REAL_FEATURES:
        raise InsufficientFeatures(
            f"Only {present} of {len(columns)} model features were supplied "
            f"(minimum {MIN_REAL_FEATURES}). Missing: {', '.join(missing[:8])}"
            f"{'...' if len(missing) > 8 else ''}"
        )

    X = np.array(values, dtype=np.float64).reshape(1, -1)

    # The estimator was fitted with feature names, so a bare ndarray makes
    # sklearn warn that it cannot check them. The column order here is built
    # from feature_columns.pkl -- the same list the model was fitted on, and
    # _load() asserts the two agree -- so the check is already satisfied by
    # construction. Silencing only this warning keeps real ones visible.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="X does not have valid feature names",
            category=UserWarning,
        )
        prediction = model.predict(X)[0]
        probabilities = model.predict_proba(X)[0]

    return {
        "crop_type": str(prediction),
        "confidence": round(float(max(probabilities)), 3),
        "source": SOURCE_LABEL,
        "note": PENDING_NOTE,
        "probabilities": {
            str(cls): round(float(p), 3)
            for cls, p in zip(model.classes_, probabilities)
        },
        "missing_features": missing,
        "features_used": present,
    }


def predict_batch(rows: list[dict]) -> list[dict | None]:
    """Classify many vectors, returning ``None`` where a row was too sparse.

    Used by the district sampler, where individual sample points are routinely
    cloud-masked and dropping them is correct.
    """
    model, columns = _load()
    out: list[dict | None] = []
    for row in rows:
        try:
            out.append(predict_crop(row))
        except InsufficientFeatures:
            out.append(None)
    return out


def health_check() -> dict:
    """Structured status for the officer telemetry endpoint."""
    try:
        model, columns = _load()
        return {
            "service": "spectral_classifier",
            "healthy": True,
            "detail": (
                f"{type(model).__name__} loaded: {len(columns)} features, "
                f"classes {', '.join(class_labels())}. Indicative only — "
                "not trained on local field-verified parcels."
            ),
        }
    except ModelUnavailable as exc:
        return {"service": "spectral_classifier", "healthy": False, "detail": str(exc)}

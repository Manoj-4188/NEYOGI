"""Crop classification inference.

The rule this module exists to enforce: **the model runs only on parcels with
``verified_flag = TRUE``.**

A district with no verified parcels is *unvalidated*. For it, this module
returns no predictions at all, and the API serves the raw Sentinel-2 NDVI
basemap behind a red "UNVALIDATED DISTRICT" badge. Nothing here will invent a
label for an unlabelled region, and there is no code path that turns a spectral
index into a crop name without a trained, ground-truth-backed model behind it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np

from ml_pipeline import config, db

logger = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    """No trained model artifact could be loaded."""


class DistrictUnvalidated(RuntimeError):
    """The district has no verified ground truth, so it must not be classified."""


@dataclass(frozen=True)
class Prediction:
    parcel_id: int
    predicted_class: str
    probability: float
    feature_date: date
    model_version: str

    def as_dict(self) -> dict:
        return {
            "parcel_id": self.parcel_id,
            "predicted_class": self.predicted_class,
            "probability": round(self.probability, 4),
            "feature_date": self.feature_date.isoformat()
            if isinstance(self.feature_date, date)
            else str(self.feature_date),
            "model_version": self.model_version,
        }


@lru_cache(maxsize=2)
def load_model(path: str | None = None) -> dict:
    """Load and cache the joblib artifact.

    Raises:
        ModelUnavailable: when the artifact is missing or unreadable. Callers
            degrade to "indices only" rather than guessing.
    """
    artifact_path = Path(path) if path else config.MODEL_PATH
    if not artifact_path.exists():
        raise ModelUnavailable(
            f"No model artifact at {artifact_path}. Train one with "
            "`python -m ml_pipeline.train_classifier`."
        )
    try:
        import joblib

        artifact = joblib.load(artifact_path)
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailable(f"Could not load {artifact_path}: {exc}") from exc

    required = {"pipeline", "feature_names", "class_labels", "model_version"}
    missing = required - set(artifact)
    if missing:
        raise ModelUnavailable(
            f"{artifact_path} is not a NEYOGI model artifact (missing {sorted(missing)})"
        )
    logger.info(
        "Loaded model %s (%d features, %d classes)",
        artifact["model_version"],
        len(artifact["feature_names"]),
        len(artifact["class_labels"]),
    )
    return artifact


def build_matrix(rows: Sequence[dict], feature_names: Sequence[str]) -> np.ndarray:
    """Assemble the feature matrix in the artifact's recorded column order.

    Column order comes from the artifact, never from the current value of
    ``INDEX_NAMES`` -- otherwise adding an index later would silently permute
    the inputs of an already-trained model.
    """
    return np.vstack(
        [
            np.array(
                [
                    float(r["features"][name])
                    if r.get("features", {}).get(name) is not None
                    else np.nan
                    for name in feature_names
                ],
                dtype=np.float64,
            )
            for r in rows
        ]
    )


def classify_district(
    district: str,
    on_or_after: date | None = None,
    model_path: str | None = None,
    min_probability: float = 0.0,
) -> list[Prediction]:
    """Classify a district's verified parcels.

    Raises:
        DistrictUnvalidated: when the district has no verified parcels with
            features. This is a normal, expected outcome -- the API turns it
            into the red unvalidated badge.
        ModelUnavailable: when no trained artifact exists.
    """
    artifact = load_model(model_path)

    # fetch_inference_frame filters on verified_flag = TRUE in SQL, so an
    # unvalidated district can only ever come back empty here.
    rows = db.fetch_inference_frame(district=district, on_or_after=on_or_after)
    if not rows:
        raise DistrictUnvalidated(
            f"{district} has no verified parcels with spectral features. "
            "It is rendered as raw NDVI basemap; no crop classes are produced."
        )

    pipeline = artifact["pipeline"]
    feature_names = list(artifact["feature_names"])
    matrix = build_matrix(rows, feature_names)

    probabilities = pipeline.predict_proba(matrix)
    classes = list(pipeline.classes_)
    best = np.argmax(probabilities, axis=1)

    predictions: list[Prediction] = []
    for row, index, prob_row in zip(rows, best, probabilities):
        probability = float(prob_row[index])
        if probability < min_probability:
            continue
        predictions.append(
            Prediction(
                parcel_id=int(row["parcel_id"]),
                predicted_class=str(classes[index]),
                probability=probability,
                feature_date=row["date"],
                model_version=artifact["model_version"],
            )
        )

    logger.info(
        "Classified %d/%d verified parcel(s) in %s with model %s",
        len(predictions),
        len(rows),
        district,
        artifact["model_version"],
    )
    return predictions


def persist(predictions: Sequence[Prediction]) -> int:
    return db.upsert_predictions(
        [
            {
                "parcel_id": p.parcel_id,
                "model_version": p.model_version,
                "predicted_class": p.predicted_class,
                "probability": p.probability,
                "feature_date": p.feature_date,
            }
            for p in predictions
        ]
    )


def classified_area_by_crop(predictions: Sequence[Prediction]) -> dict[str, float]:
    """Hectares per predicted class, from the parcels' measured areas.

    Area comes from ``parcels.area_ha``, computed in an equal-area projection at
    ingest. Parcels with no computed area are excluded rather than assigned a
    typical size.
    """
    if not predictions:
        return {}
    by_id = {p.parcel_id: p for p in predictions}
    areas: dict[str, float] = {}
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, area_ha FROM parcels WHERE id = ANY(%s) AND area_ha IS NOT NULL",
            (list(by_id),),
        )
        for parcel_id, area_ha in cur.fetchall():
            prediction = by_id[parcel_id]
            areas[prediction.predicted_class] = areas.get(
                prediction.predicted_class, 0.0
            ) + float(area_ha)
    return areas


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Classify verified parcels")
    parser.add_argument("--district", required=True)
    parser.add_argument("--since", type=date.fromisoformat, default=None)
    parser.add_argument("--min-probability", type=float, default=0.0)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        predictions = classify_district(
            args.district, on_or_after=args.since, min_probability=args.min_probability
        )
    except DistrictUnvalidated as exc:
        print(json.dumps({"status": "UNVALIDATED_DISTRICT", "detail": str(exc)}, indent=2))
        return 0
    except ModelUnavailable as exc:
        print(json.dumps({"status": "MODEL_UNAVAILABLE", "detail": str(exc)}, indent=2))
        return 4

    written = persist(predictions) if args.persist else 0
    print(
        json.dumps(
            {
                "status": "OK",
                "district": args.district,
                "predictions": len(predictions),
                "persisted": written,
                "area_ha_by_crop": classified_area_by_crop(predictions),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

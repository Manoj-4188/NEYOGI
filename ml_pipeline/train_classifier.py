"""Phase 4 -- Random Forest crop classifier.

Training protocol
-----------------
* 80/20 stratified split, **grouped by parcel**. One parcel contributes several
  rows (one per composite date), and those rows are near-duplicates of each
  other. A plain stratified split would scatter a parcel's own observations
  across train and test, and the reported accuracy would mostly measure
  memorisation. ``StratifiedGroupKFold`` keeps every parcel wholly on one side.
* 5-fold cross-validation, likewise grouped by parcel.
* Reported metrics: per-class precision / recall / F1, macro and weighted
  averages, and Cohen's kappa (which discounts the agreement expected by chance
  and is the honest headline number for an imbalanced label set).

Refusals
--------
Training aborts with :class:`InsufficientGroundTruth` when the labelled set is
too small or too thin per class to support a defensible model. A model fitted
on a handful of parcels would produce confident-looking predictions with no
evidential basis, which is exactly what this system must not ship.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ml_pipeline import config, db
from ml_pipeline.feature_engineering import INDEX_NAMES

logger = logging.getLogger(__name__)

#: A class with fewer than this many distinct verified parcels is not modelled.
MIN_PARCELS_PER_CLASS = 5
#: Below this many labelled parcels overall, training refuses outright.
MIN_TOTAL_PARCELS = 30
#: At least two classes are needed for a classification problem to exist.
MIN_CLASSES = 2

RANDOM_STATE = 42
N_SPLITS = 5
TEST_FRACTION = 0.2


class InsufficientGroundTruth(RuntimeError):
    """The verified label set cannot support a defensible model."""


@dataclass
class TrainingData:
    """Assembled feature matrix and its provenance."""

    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray  # parcel_id per row
    feature_names: tuple[str, ...]
    districts: np.ndarray
    dates: np.ndarray

    @property
    def n_samples(self) -> int:
        return int(self.X.shape[0])

    @property
    def n_parcels(self) -> int:
        return int(np.unique(self.groups).size)

    def class_parcel_counts(self) -> dict[str, int]:
        """Distinct parcels per class -- the number that actually constrains fit."""
        counts: dict[str, int] = {}
        for label in np.unique(self.y):
            counts[str(label)] = int(np.unique(self.groups[self.y == label]).size)
        return counts

    def class_row_counts(self) -> dict[str, int]:
        labels, counts = np.unique(self.y, return_counts=True)
        return {str(k): int(v) for k, v in zip(labels, counts)}


@dataclass
class TrainingResult:
    model_version: str
    artifact_path: Path
    class_labels: list[str]
    metrics: dict
    confusion_matrix: list[list[int]]
    n_training_samples: int
    n_parcels: int
    feature_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model_version": self.model_version,
            "artifact_path": str(self.artifact_path),
            "class_labels": self.class_labels,
            "metrics": self.metrics,
            "confusion_matrix": self.confusion_matrix,
            "n_training_samples": self.n_training_samples,
            "n_parcels": self.n_parcels,
            "feature_names": self.feature_names,
        }


# --------------------------------------------------------------------------
# Data assembly
# --------------------------------------------------------------------------


def build_training_data(
    rows: Sequence[dict],
    feature_names: Sequence[str] | None = None,
    min_features_present: int = 6,
) -> TrainingData:
    """Turn ``db.fetch_training_frame()`` rows into arrays.

    Rows with fewer than ``min_features_present`` observed indices are dropped:
    a composite where most of the parcel was cloud-masked carries too little
    signal, and imputing eight of eleven features would be inventing data.
    """
    feature_names = tuple(feature_names or INDEX_NAMES)
    if not rows:
        raise InsufficientGroundTruth(
            "No labelled parcel/date observations were returned. Load ground "
            "truth with ml_pipeline.load_ground_truth and run the Sentinel-2 "
            "ingestion before training."
        )

    features: list[np.ndarray] = []
    labels: list[str] = []
    groups: list[int] = []
    districts: list[str] = []
    dates: list[Any] = []
    skipped_sparse = 0

    for row in rows:
        values = row.get("features") or {}
        vector = np.array(
            [
                float(values[name]) if values.get(name) is not None else np.nan
                for name in feature_names
            ],
            dtype=np.float64,
        )
        if int(np.count_nonzero(~np.isnan(vector))) < min_features_present:
            skipped_sparse += 1
            continue
        features.append(vector)
        labels.append(str(row["crop_label"]))
        groups.append(int(row["parcel_id"]))
        districts.append(str(row.get("district") or ""))
        dates.append(row.get("date"))

    if skipped_sparse:
        logger.info(
            "Dropped %d observation(s) with fewer than %d usable indices "
            "(heavy cloud masking).",
            skipped_sparse,
            min_features_present,
        )

    if not features:
        raise InsufficientGroundTruth(
            "Every labelled observation was too sparsely observed to use. "
            "Extend the ingestion window or relax --min-features."
        )

    return TrainingData(
        X=np.vstack(features),
        y=np.array(labels, dtype=object),
        groups=np.array(groups, dtype=int),
        feature_names=feature_names,
        districts=np.array(districts, dtype=object),
        dates=np.array(dates, dtype=object),
    )


def validate_sufficiency(data: TrainingData) -> None:
    """Refuse to train on a label set that cannot support the claim."""
    parcel_counts = data.class_parcel_counts()

    if data.n_parcels < MIN_TOTAL_PARCELS:
        raise InsufficientGroundTruth(
            f"Only {data.n_parcels} verified parcel(s) available; at least "
            f"{MIN_TOTAL_PARCELS} are required. Districts remain unvalidated "
            "and will render as raw NDVI basemap."
        )

    thin = {k: v for k, v in parcel_counts.items() if v < MIN_PARCELS_PER_CLASS}
    if thin:
        raise InsufficientGroundTruth(
            "These classes have too few distinct verified parcels to model "
            f"(minimum {MIN_PARCELS_PER_CLASS}): "
            + ", ".join(f"{k}={v}" for k, v in sorted(thin.items()))
            + ". Collect more ground truth, or drop the class from this run "
            "with --classes."
        )

    if len(parcel_counts) < MIN_CLASSES:
        raise InsufficientGroundTruth(
            f"Only {len(parcel_counts)} class present; a classifier needs at "
            f"least {MIN_CLASSES}."
        )

    unexpected = set(parcel_counts) - set(config.CROP_CLASSES)
    if unexpected:
        raise InsufficientGroundTruth(
            f"Labels outside the declared class set: {sorted(unexpected)}. "
            f"Declared classes are {list(config.CROP_CLASSES)}."
        )


# --------------------------------------------------------------------------
# Splitting
# --------------------------------------------------------------------------


def grouped_stratified_split(
    data: TrainingData, test_fraction: float = TEST_FRACTION
) -> tuple[np.ndarray, np.ndarray]:
    """80/20 split that is stratified by class *and* grouped by parcel.

    Implemented as one fold of ``StratifiedGroupKFold`` with
    ``n_splits = round(1 / test_fraction)``, which is the scikit-learn idiom for
    a grouped hold-out.
    """
    from sklearn.model_selection import StratifiedGroupKFold

    n_splits = max(2, round(1.0 / test_fraction))
    splitter = StratifiedGroupKFold(
        n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE
    )
    train_idx, test_idx = next(splitter.split(data.X, data.y, groups=data.groups))

    overlap = set(data.groups[train_idx]) & set(data.groups[test_idx])
    if overlap:  # pragma: no cover - defensive; StratifiedGroupKFold guarantees this
        raise RuntimeError(f"Parcel leakage between splits: {sorted(overlap)[:5]}")
    return train_idx, test_idx


def build_pipeline(n_estimators: int = 400, max_depth: int | None = None):
    """Median-imputer + Random Forest.

    The imputer handles the NaNs that mark genuinely unobserved indices. Median
    imputation is recorded in the artifact so the same transform is replayed at
    inference; it is a modelling choice, not a data substitution -- the raw NaN
    stays in the database.
    """
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    return Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            (
                "rf",
                RandomForestClassifier(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    min_samples_leaf=2,
                    # Counteracts the natural imbalance between fallow land and
                    # the individual vegetable classes.
                    class_weight="balanced_subsample",
                    n_jobs=-1,
                    random_state=RANDOM_STATE,
                    oob_score=True,
                    bootstrap=True,
                ),
            ),
        ]
    )


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def cross_validate(data: TrainingData, pipeline, n_splits: int = N_SPLITS) -> dict:
    """Grouped, stratified k-fold cross-validation."""
    from sklearn.base import clone
    from sklearn.metrics import cohen_kappa_score, f1_score
    from sklearn.model_selection import StratifiedGroupKFold

    splitter = StratifiedGroupKFold(
        n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE
    )
    accuracies: list[float] = []
    macro_f1s: list[float] = []
    kappas: list[float] = []

    for fold, (train_idx, test_idx) in enumerate(
        splitter.split(data.X, data.y, groups=data.groups), start=1
    ):
        estimator = clone(pipeline)
        estimator.fit(data.X[train_idx], data.y[train_idx])
        predicted = estimator.predict(data.X[test_idx])
        truth = data.y[test_idx]

        accuracies.append(float(np.mean(predicted == truth)))
        macro_f1s.append(float(f1_score(truth, predicted, average="macro", zero_division=0)))
        kappas.append(float(cohen_kappa_score(truth, predicted)))
        logger.info(
            "CV fold %d/%d: accuracy=%.3f macro-F1=%.3f kappa=%.3f",
            fold,
            n_splits,
            accuracies[-1],
            macro_f1s[-1],
            kappas[-1],
        )

    return {
        "n_splits": n_splits,
        "accuracy_mean": float(np.mean(accuracies)),
        "accuracy_std": float(np.std(accuracies)),
        "macro_f1_mean": float(np.mean(macro_f1s)),
        "macro_f1_std": float(np.std(macro_f1s)),
        "kappa_mean": float(np.mean(kappas)),
        "kappa_std": float(np.std(kappas)),
        "per_fold": {
            "accuracy": accuracies,
            "macro_f1": macro_f1s,
            "kappa": kappas,
        },
    }


def evaluate_holdout(pipeline, data: TrainingData, test_idx: np.ndarray) -> dict:
    """Per-class precision/recall/F1, kappa and the confusion matrix."""
    from sklearn.metrics import (
        classification_report,
        cohen_kappa_score,
        confusion_matrix,
    )

    truth = data.y[test_idx]
    predicted = pipeline.predict(data.X[test_idx])
    labels = sorted(set(map(str, data.y)))

    report = classification_report(
        truth, predicted, labels=labels, output_dict=True, zero_division=0
    )
    matrix = confusion_matrix(truth, predicted, labels=labels)

    return {
        "labels": labels,
        "accuracy": float(np.mean(predicted == truth)),
        "cohen_kappa": float(cohen_kappa_score(truth, predicted, labels=labels)),
        "per_class": {
            label: {
                "precision": float(report[label]["precision"]),
                "recall": float(report[label]["recall"]),
                "f1": float(report[label]["f1-score"]),
                "support": int(report[label]["support"]),
            }
            for label in labels
            if label in report
        },
        "macro_avg": {
            "precision": float(report["macro avg"]["precision"]),
            "recall": float(report["macro avg"]["recall"]),
            "f1": float(report["macro avg"]["f1-score"]),
        },
        "weighted_avg": {
            "precision": float(report["weighted avg"]["precision"]),
            "recall": float(report["weighted avg"]["recall"]),
            "f1": float(report["weighted avg"]["f1-score"]),
        },
        "confusion_matrix": matrix.tolist(),
        "n_test_samples": int(len(test_idx)),
        "n_test_parcels": int(np.unique(data.groups[test_idx]).size),
    }


def feature_importances(pipeline, feature_names: Sequence[str]) -> dict[str, float]:
    forest = pipeline.named_steps["rf"]
    return {
        name: float(value)
        for name, value in sorted(
            zip(feature_names, forest.feature_importances_),
            key=lambda pair: pair[1],
            reverse=True,
        )
    }


# --------------------------------------------------------------------------
# Training entry point
# --------------------------------------------------------------------------


def train(
    data: TrainingData,
    output_path: Path | None = None,
    n_estimators: int = 400,
    max_depth: int | None = None,
    n_splits: int = N_SPLITS,
) -> TrainingResult:
    """Fit, evaluate and persist the classifier."""
    import joblib

    validate_sufficiency(data)

    logger.info(
        "Training on %d observation(s) from %d verified parcel(s); parcels per class: %s",
        data.n_samples,
        data.n_parcels,
        data.class_parcel_counts(),
    )

    pipeline = build_pipeline(n_estimators=n_estimators, max_depth=max_depth)
    cv_metrics = cross_validate(data, pipeline, n_splits=n_splits)

    train_idx, test_idx = grouped_stratified_split(data)
    pipeline.fit(data.X[train_idx], data.y[train_idx])
    holdout = evaluate_holdout(pipeline, data, test_idx)

    logger.info(
        "Hold-out: accuracy=%.3f macro-F1=%.3f kappa=%.3f on %d parcel(s)",
        holdout["accuracy"],
        holdout["macro_avg"]["f1"],
        holdout["cohen_kappa"],
        holdout["n_test_parcels"],
    )

    forest = pipeline.named_steps["rf"]
    oob = float(getattr(forest, "oob_score_", float("nan")))

    trained_at = datetime.now(tz=timezone.utc)
    model_version = f"rf-{trained_at:%Y%m%d%H%M%S}"

    metrics = {
        "holdout": holdout,
        "cross_validation": cv_metrics,
        "oob_score": None if np.isnan(oob) else oob,
        "feature_importances": feature_importances(pipeline, data.feature_names),
        "class_parcel_counts": data.class_parcel_counts(),
        "class_row_counts": data.class_row_counts(),
        "trained_at": trained_at.isoformat(),
        "protocol": {
            "split": f"{int((1 - TEST_FRACTION) * 100)}/{int(TEST_FRACTION * 100)} "
            "stratified, grouped by parcel",
            "cross_validation": f"{n_splits}-fold StratifiedGroupKFold",
            "random_state": RANDOM_STATE,
        },
    }

    output_path = output_path or config.MODEL_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # The artifact carries everything inference needs to reproduce the exact
    # feature contract -- order included. Inference refuses a mismatch.
    artifact = {
        "pipeline": pipeline,
        "feature_names": list(data.feature_names),
        "class_labels": sorted(set(map(str, data.y))),
        "model_version": model_version,
        "trained_at": trained_at.isoformat(),
        "n_training_samples": data.n_samples,
        "n_parcels": data.n_parcels,
        "metrics": metrics,
    }
    joblib.dump(artifact, output_path)
    logger.info("Saved model artifact to %s", output_path)

    config.MODEL_METRICS_PATH.write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8"
    )

    return TrainingResult(
        model_version=model_version,
        artifact_path=output_path,
        class_labels=sorted(set(map(str, data.y))),
        metrics=metrics,
        confusion_matrix=holdout["confusion_matrix"],
        n_training_samples=data.n_samples,
        n_parcels=data.n_parcels,
        feature_names=list(data.feature_names),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="train_classifier",
        description="Train the NEYOGI Random Forest crop classifier.",
    )
    parser.add_argument("--districts", nargs="*", default=None)
    parser.add_argument(
        "--classes",
        nargs="*",
        default=None,
        help="Restrict training to these crop classes.",
    )
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--n-splits", type=int, default=N_SPLITS)
    parser.add_argument("--min-features", type=int, default=6)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--no-register",
        action="store_true",
        help="Skip writing the model to the PostGIS model registry.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        rows = db.fetch_training_frame(districts=args.districts, index_names=INDEX_NAMES)
    except db.DatabaseUnavailable as exc:
        logger.error("%s", exc)
        return 3

    if args.classes:
        allowed = set(args.classes)
        rows = [r for r in rows if r["crop_label"] in allowed]

    try:
        data = build_training_data(rows, min_features_present=args.min_features)
        result = train(
            data,
            output_path=args.output,
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            n_splits=args.n_splits,
        )
    except InsufficientGroundTruth as exc:
        logger.error("Refusing to train: %s", exc)
        db.record_pipeline_run(
            stage="train_classifier",
            district=None,
            payload={"refused": str(exc)},
            ok=False,
        )
        return 4

    if not args.no_register:
        db.register_model(
            model_version=result.model_version,
            artifact_path=str(result.artifact_path),
            class_labels=result.class_labels,
            n_training_samples=result.n_training_samples,
            metrics=result.metrics,
            confusion_matrix=result.confusion_matrix,
            activate=True,
        )
    db.record_pipeline_run(
        stage="train_classifier",
        district=None,
        payload={
            "model_version": result.model_version,
            "kappa": result.metrics["holdout"]["cohen_kappa"],
            "macro_f1": result.metrics["holdout"]["macro_avg"]["f1"],
            "n_parcels": result.n_parcels,
        },
        ok=True,
    )

    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

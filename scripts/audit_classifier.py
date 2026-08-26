"""Audit what the shipped spectral classifier actually learned.

Two questions this answers, both checkable rather than argued:

1. Does the model reproduce the threshold rules its labels were generated
   from? If agreement is near-total, the "classifier" is a Random Forest
   fitted to three if-statements, and its accuracy measures how well a forest
   can approximate a rule -- not whether a pixel is really that crop.

2. Are the band features on the same scale at training and inference? The
   training CSV holds raw Sentinel-2 integers; the ingestion pipeline divides
   by 10000 to get surface reflectance. Six of the seventeen features are raw
   bands, so a mismatch there is fed silently into every prediction.

    python scripts/audit_classifier.py
"""

from __future__ import annotations

import pathlib
import sys

import joblib
import numpy as np
import pandas as pd

CSV = pathlib.Path(
    r"C:\Users\pavan\OneDrive\Desktop\NEYOGI\neyogi-ml\neyogi_features.csv"
)
MODEL = pathlib.Path("ml_pipeline/models/neyogi_crop_model.pkl")
FEATURES = pathlib.Path("ml_pipeline/models/feature_columns.pkl")

LINE = "=" * 70


def synthetic_labels(df: pd.DataFrame) -> pd.Series:
    """The exact rule set from the original train_model.py."""
    labels = np.full(len(df), "other", dtype=object)
    tomato = (df["NDVI"] > 0.5) & (df["NDRE"] > 0.3)
    onion = (df["NDVI"] > 0.3) & (df["NDVI"] <= 0.5) & (df["NDMI"] > 0.1)
    leafy = (df["NDVI"] > 0.4) & (df["EVI"] > 0.2) & (df["GNDVI"] > 0.3)
    labels[tomato] = "tomato"
    labels[onion] = "onion"
    labels[leafy & ~tomato & ~onion] = "leafy_greens"
    return pd.Series(labels, index=df.index)


def main() -> int:
    if not CSV.exists():
        print(f"Training CSV not found at {CSV}")
        return 1

    df = pd.read_csv(CSV)
    model = joblib.load(MODEL)
    columns = list(joblib.load(FEATURES))

    print(LINE)
    print("1. IS THE MODEL JUST THE THRESHOLD RULES?")
    print(LINE)

    rules = synthetic_labels(df)
    X = df[columns].to_numpy(dtype=float)
    predicted = model.predict(X)

    agreement = float((predicted == rules.to_numpy()).mean())
    print(f"  training rows                     : {len(df)}")
    print(f"  model agrees with the rule set on : {agreement:.1%} of them")
    print()
    print("  label distribution produced by the rules:")
    for name, count in rules.value_counts().items():
        print(f"    {name:<14} {count:>4}  ({count / len(df):.0%})")

    print()
    print("  The labels are generated from NDVI/NDRE/NDMI/EVI/GNDVI thresholds")
    print("  and those same indices are then handed back as features. No field")
    print("  observation enters anywhere. 'tomato' means NDVI>0.5 & NDRE>0.3 --")
    print("  a vigour class, not a crop.")

    print()
    print(LINE)
    print("2. FEATURE SCALE: TRAINING vs INFERENCE")
    print(LINE)

    bands = [c for c in columns if c.startswith("B")]
    print("  band ranges in the training CSV:")
    for b in bands:
        print(f"    {b:<4} {df[b].min():>10,.1f} .. {df[b].max():>10,.1f}")

    print()
    print("  The ingestion pipeline divides bands by 10,000 to get surface")
    print("  reflectance, so at inference these same features arrive in 0..1.")
    print(f"  {len(bands)} of {len(columns)} features are affected.")

    # Show the effect directly: same pixel, both scales.
    row = df.iloc[[0]][columns].to_numpy(dtype=float)
    scaled = row.copy()
    for i, c in enumerate(columns):
        if c.startswith("B"):
            scaled[0, i] = scaled[0, i] / 10_000.0

    p_raw = model.predict_proba(row)[0]
    p_scaled = model.predict_proba(scaled)[0]
    classes = list(model.classes_)

    print()
    print("  Same pixel, both scales:")
    print(f"    {'class':<14} {'raw bands':>10} {'scaled bands':>14}")
    for cls, a, b in zip(classes, p_raw, p_scaled):
        print(f"    {cls:<14} {a:>10.3f} {b:>14.3f}")
    print(f"    {'-> predicted':<14} {classes[int(np.argmax(p_raw))]:>10} "
          f"{classes[int(np.argmax(p_scaled))]:>14}")

    # How often does the scale change the answer, across the whole set?
    X_scaled = X.copy()
    for i, c in enumerate(columns):
        if c.startswith("B"):
            X_scaled[:, i] = X_scaled[:, i] / 10_000.0
    flipped = float((model.predict(X_scaled) != predicted).mean())
    conf_raw = model.predict_proba(X).max(axis=1).mean()
    conf_scaled = model.predict_proba(X_scaled).max(axis=1).mean()

    print()
    print(f"  predictions that change with the rescale : {flipped:.1%}")
    print(f"  mean confidence, raw bands               : {conf_raw:.3f}")
    print(f"  mean confidence, scaled bands            : {conf_scaled:.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""District-scale crop classification from Sentinel-2 spectra.

The ground-truth pipeline classifies *parcels*, and needs digitised field
boundaries to exist. This module answers the same question without them, by
sampling the district itself.

Method
------
1. Build the district's 16-day cloud-masked median composite (the same one the
   basemap renders), carrying the eleven indices plus the six raw bands the
   model consumes.
2. Draw a stratified random sample of points inside the district, restricted to
   pixels that look like cropland at all — a minimum NDVI, and NDWI below zero
   to drop open water. Classifying rooftops and reservoirs would otherwise
   inflate every crop's area.
3. Classify each sampled point with the spectral model.
4. Aggregate: a crop's share of classified samples, multiplied by the sampled
   cropland area, gives its area estimate.

What the area figure is, and is not
-----------------------------------
It is an extrapolation from a sample, not a census of fields. The sampling
error is real and is reported alongside it (``sample_count`` and the standard
error on each share), so the number can be read with its uncertainty rather
than as a measured quantity. It is not a substitute for field survey, and
every record carries ``source='spectral_index_threshold_model'`` to keep that
distinction visible downstream.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ml_pipeline import config
from ml_pipeline.classifier import (
    InsufficientFeatures,
    ModelUnavailable,
    feature_columns,
    predict_crop,
)
from ml_pipeline.gee_auth import EarthEngineUnavailable, initialize
from ml_pipeline.gee_districts import ResolvedDistrict, district_geometry

logger = logging.getLogger(__name__)

#: Sample points per district. Enough for a stable share estimate without
#: making the getInfo() payload unwieldy.
DEFAULT_SAMPLE_SIZE = 400

#: Cropland screen. Below this NDVI the pixel is bare, built or water, and the
#: model has no business assigning it a crop.
MIN_CROPLAND_NDVI = 0.25

#: NDWI above this is standing water (McFeeters 1996).
MAX_CROPLAND_NDWI = 0.0

#: Below this many successfully classified points, the class shares are too
#: noisy to extrapolate to a district. Monsoon cloud can leave a district
#: with a handful of usable pixels, and one sample scaled to 300,000 ha is
#: a fabricated number wearing a real one's clothes. The run reports the
#: shortfall instead of publishing an area.
MIN_CLASSIFIED_SAMPLES = 30

#: Sampling scale. Coarser than the 10 m native grid on purpose: a 20 m sample
#: point averages a small neighbourhood, which suppresses single-pixel noise
#: without materially blurring field-scale boundaries.
SAMPLE_SCALE_M = 20


@dataclass
class CropAreaEstimate:
    crop: str
    sample_count: int
    share: float
    area_ha: float
    mean_confidence: float
    #: Standard error on `share`, from the binomial sampling distribution.
    share_stderr: float

    def to_dict(self) -> dict:
        return {
            "crop": self.crop,
            "sample_count": self.sample_count,
            "share": round(self.share, 4),
            "share_stderr": round(self.share_stderr, 4),
            "area_ha": round(self.area_ha, 1),
            "mean_confidence": round(self.mean_confidence, 3),
        }


@dataclass
class DistrictClassification:
    district: str
    composite_start: date
    composite_end: date
    scene_count: int
    samples_requested: int
    samples_classified: int
    cropland_area_ha: float
    district_area_ha: float
    crops: list[CropAreaEstimate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "district": self.district,
            "composite_start": self.composite_start.isoformat(),
            "composite_end": self.composite_end.isoformat(),
            "scene_count": self.scene_count,
            "samples_requested": self.samples_requested,
            "samples_classified": self.samples_classified,
            "cropland_area_ha": round(self.cropland_area_ha, 1),
            "district_area_ha": round(self.district_area_ha, 1),
            "crops": [c.to_dict() for c in self.crops],
            "source": "spectral_index_threshold_model",
            "note": "Field verification pending — accuracy improves with ground truth",
            "method": (
                f"Stratified random sample of {self.samples_requested} points over "
                f"cropland pixels (NDVI ≥ {MIN_CROPLAND_NDVI}, NDWI ≤ "
                f"{MAX_CROPLAND_NDWI}) at {SAMPLE_SCALE_M} m; area extrapolated "
                "from class shares."
            ),
            "notes": self.notes,
        }


def _sample_district(geometry, composite, sample_size: int) -> list[dict]:
    """Draw cropland sample points and return their feature dictionaries."""
    import ee

    # Cropland screen, applied as a mask so sampling only lands on plausible
    # agricultural pixels.
    ndvi = composite.select("NDVI")
    ndwi = composite.select("NDWI")
    cropland = ndvi.gte(MIN_CROPLAND_NDVI).And(ndwi.lte(MAX_CROPLAND_NDWI))
    masked = composite.updateMask(cropland)

    wanted = [c for c in feature_columns() if c in composite.bandNames().getInfo()]

    samples = masked.select(wanted).sample(
        region=geometry,
        scale=SAMPLE_SCALE_M,
        numPixels=sample_size,
        seed=42,
        geometries=False,
        dropNulls=True,
    )
    try:
        payload = samples.getInfo()
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(f"District sampling failed: {exc}") from exc

    return [f.get("properties", {}) for f in payload.get("features", [])]


def _cropland_area_ha(geometry, composite) -> float:
    """Area of pixels passing the cropland screen, in hectares."""
    import ee

    ndvi = composite.select("NDVI")
    ndwi = composite.select("NDWI")
    cropland = ndvi.gte(MIN_CROPLAND_NDVI).And(ndwi.lte(MAX_CROPLAND_NDWI))

    area = (
        cropland.multiply(ee.Image.pixelArea())
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=geometry,
            scale=SAMPLE_SCALE_M,
            maxPixels=1e10,
            bestEffort=True,
        )
        .get("NDVI")
    )
    try:
        value = area.getInfo()
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(f"Cropland area reduction failed: {exc}") from exc
    return float(value or 0.0) / 10_000.0


def classify_district(
    district: ResolvedDistrict,
    window_days: int | None = None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> DistrictClassification:
    """Sample and classify one district's cropland.

    Raises:
        EarthEngineUnavailable: imagery or reductions could not be computed.
        ModelUnavailable: the spectral model artifact is missing.
    """
    from ml_pipeline.feature_engineering import add_index_bands
    from ml_pipeline.gee_ingestion import (
        SOURCE_BANDS,
        CompositeWindow,
        NoImageryAvailable,
        sentinel2_collection,
    )

    initialize()
    import ee

    window_days = window_days or config.SETTINGS.composite_period_days
    end = datetime.now(tz=timezone.utc).date()
    start = end - timedelta(days=window_days)

    geometry = district_geometry(district)
    collection = sentinel2_collection(geometry, start, end)
    scene_count = int(collection.size().getInfo())
    if scene_count == 0:
        raise NoImageryAvailable(
            f"No cloud-free Sentinel-2 scenes for {district.gaul_name} in "
            f"{start}..{end}"
        )

    composite = add_index_bands(
        collection.median().clip(geometry), available_bands=SOURCE_BANDS
    )

    district_area_ha = float(
        geometry.area(maxError=100).divide(10_000).getInfo() or 0.0
    )
    cropland_ha = _cropland_area_ha(geometry, composite)
    rows = _sample_district(geometry, composite, sample_size)

    result = DistrictClassification(
        # The platform's own name for the district, not the boundary dataset's.
        # Every other table -- parcels, cold storage, mandi prices -- is keyed
        # on the requested name, and the dashboard queries with it. Persisting
        # the GAUL spelling here made three districts' classifications
        # invisible to the UI: stored as "Belgaum", queried as "Belagavi".
        district=district.requested_name,
        composite_start=start,
        composite_end=end,
        scene_count=scene_count,
        samples_requested=sample_size,
        samples_classified=0,
        cropland_area_ha=cropland_ha,
        district_area_ha=district_area_ha,
    )

    if not rows:
        result.notes.append(
            "No pixel passed the cropland screen in this composite — the "
            "district is either fully cloud-masked or genuinely non-cropped "
            "in this window."
        )
        return result

    tally: dict[str, list[float]] = {}
    for row in rows:
        try:
            prediction = predict_crop(row)
        except InsufficientFeatures:
            continue
        tally.setdefault(prediction["crop_type"], []).append(prediction["confidence"])

    classified = sum(len(v) for v in tally.values())
    result.samples_classified = classified
    if classified == 0:
        result.notes.append(
            "Every sample was too sparsely observed to classify; no crop areas "
            "are reported for this window."
        )
        return result

    for crop, confidences in sorted(tally.items(), key=lambda kv: -len(kv[1])):
        n = len(confidences)
        share = n / classified
        # Binomial standard error on the share, scaled to the same units.
        stderr = math.sqrt(max(share * (1.0 - share), 0.0) / classified)
        result.crops.append(
            CropAreaEstimate(
                crop=crop,
                sample_count=n,
                share=share,
                area_ha=share * cropland_ha,
                mean_confidence=sum(confidences) / n,
                share_stderr=stderr,
            )
        )

    if classified < MIN_CLASSIFIED_SAMPLES:
        # Keep the sample count visible, but publish no areas: extrapolating a
        # district from a handful of points would look like a measurement.
        result.crops = []
        result.notes.append(
            f"Only {classified} sample point(s) could be classified, below the "
            f"{MIN_CLASSIFIED_SAMPLES} needed to extrapolate district areas. "
            "This usually means heavy cloud cover in the composite window. No "
            "crop areas are reported."
        )
        return result

    dropped = len(rows) - classified
    if dropped:
        result.notes.append(
            f"{dropped} of {len(rows)} sampled points were dropped as too "
            "sparsely observed to classify."
        )
    return result


def persist(result: DistrictClassification) -> int:
    """Store a district classification, replacing any for the same composite."""
    from ml_pipeline import db

    rows = [
        (
            result.district,
            c.crop,
            result.composite_start,
            c.sample_count,
            c.share,
            c.share_stderr,
            c.area_ha,
            c.mean_confidence,
            result.samples_classified,
            result.cropland_area_ha,
            result.scene_count,
        )
        for c in result.crops
    ]
    if not rows:
        return 0

    with db.connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO district_classifications
                (district, crop, composite_start, sample_count, share,
                 share_stderr, area_ha, mean_confidence, samples_classified,
                 cropland_area_ha, scene_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (district, crop, composite_start) DO UPDATE SET
                sample_count       = EXCLUDED.sample_count,
                share              = EXCLUDED.share,
                share_stderr       = EXCLUDED.share_stderr,
                area_ha            = EXCLUDED.area_ha,
                mean_confidence    = EXCLUDED.mean_confidence,
                samples_classified = EXCLUDED.samples_classified,
                cropland_area_ha   = EXCLUDED.cropland_area_ha,
                scene_count        = EXCLUDED.scene_count,
                classified_at      = now()
            """,
            rows,
        )
    return len(rows)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse
    import json

    from ml_pipeline import db
    from ml_pipeline.gee_districts import resolve_districts
    from ml_pipeline.gee_ingestion import NoImageryAvailable

    parser = argparse.ArgumentParser(
        description="Classify district cropland with the spectral model."
    )
    parser.add_argument("--districts", nargs="*", default=None)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--window-days", type=int, default=None)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    resolution = resolve_districts(args.districts)
    out = []
    for district in resolution.resolved:
        try:
            result = classify_district(
                district, window_days=args.window_days, sample_size=args.samples
            )
        except NoImageryAvailable as exc:
            out.append({"district": district.gaul_name, "status": "NO_IMAGERY", "detail": str(exc)})
            continue
        except (EarthEngineUnavailable, ModelUnavailable) as exc:
            out.append({"district": district.gaul_name, "status": "ERROR", "detail": str(exc)})
            continue

        if not args.no_persist:
            persist(result)
            db.record_pipeline_run(
                "district_classification",
                district.gaul_name,
                {"crops": len(result.crops), "samples": result.samples_classified},
                ok=True,
            )
        out.append(result.to_dict())

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

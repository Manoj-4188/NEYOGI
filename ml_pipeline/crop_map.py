"""Per-pixel crop classification raster.

The district classifier samples a few hundred points and reports areas. This
renders the same question across every pixel, producing the kind of map where
you can see field boundaries and cropping patterns directly.

How it works, and why it is built this way
------------------------------------------
The platform's classifier is a scikit-learn Random Forest, which cannot run
inside Earth Engine. Pulling every pixel down to classify locally is not an
option either -- a district is tens of millions of pixels.

So the work is split. Sample points are pulled down and labelled by the
sklearn model, exactly as the district classifier does. Those labelled points
then train an ``ee.Classifier.smileRandomForest`` server-side, which is
applied to the whole composite. The Earth Engine forest is a stand-in for the
sklearn one, fitted to reproduce its decisions.

That indirection is worth stating plainly: the raster shows what the sklearn
model *would* say, as approximated by a second forest. The agreement between
the two is measured on a held-out slice of the sampled points and returned
with the layer, so a map that approximates badly can be recognised as such
rather than trusted by default.

Everything the district classifier says about its own limits applies here too.
The labels behind it come from threshold rules over spectral indices, not from
field observation, so a pixel painted "tomato" means "spectrally resembles
what the rules call tomato" -- see ml_pipeline/classifier.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ml_pipeline import config
from ml_pipeline.classifier import class_labels, feature_columns, predict_crop
from ml_pipeline.classifier import InsufficientFeatures
from ml_pipeline.district_classification import (
    MAX_CROPLAND_NDWI,
    MIN_CROPLAND_NDVI,
    SAMPLE_SCALE_M,
)
from ml_pipeline.gee_auth import EarthEngineUnavailable, initialize
from ml_pipeline.gee_districts import ResolvedDistrict, district_geometry

logger = logging.getLogger(__name__)

#: Training points for the server-side forest. More than the district
#: classifier uses, because this fits a model rather than estimating a share.
DEFAULT_TRAINING_SAMPLES = 3000

#: Held back from fitting, to measure how well the Earth Engine forest
#: reproduces the sklearn one.
HOLDOUT_FRACTION = 0.25

#: Trees in the server-side forest. Matches the sklearn model's 300.
EE_TREES = 300

#: Below this agreement the raster is not a faithful stand-in for the sklearn
#: model, and is returned flagged rather than presented as equivalent.
MIN_AGREEMENT = 0.80

#: Palette, in the order of ``class_labels()``. Chosen to stay distinguishable
#: for the most common forms of colour blindness: the tomato/leafy pair is
#: separated by lightness as well as hue.
CLASS_COLOURS: dict[str, str] = {
    "tomato": "#c0392b",
    "onion": "#d4882a",
    "leafy_greens": "#1a5c2a",
    "other": "#9ca3af",
}


@dataclass
class CropMapLayer:
    """A rendered per-pixel classification, ready for the map."""

    district: str
    composite_start: date
    composite_end: date
    scene_count: int
    tile_url_template: str
    #: Class name -> hex colour, in the order the palette was built.
    legend: dict
    training_points: int
    #: Agreement between the Earth Engine forest and the sklearn model on
    #: points held out of fitting.
    agreement: float
    #: True when agreement cleared MIN_AGREEMENT.
    faithful: bool
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "district": self.district,
            "composite_start": self.composite_start.isoformat(),
            "composite_end": self.composite_end.isoformat(),
            "scene_count": self.scene_count,
            "tile_url_template": self.tile_url_template,
            "legend": self.legend,
            "training_points": self.training_points,
            "agreement": round(self.agreement, 4),
            "faithful": self.faithful,
            "scale_m": SAMPLE_SCALE_M,
            "source": "spectral_index_threshold_model",
            "note": (
                "Per-pixel classes from an Earth Engine forest fitted to "
                "reproduce the platform's classifier. Field verification "
                "pending; classes reflect spectral rules, not field survey."
            ),
            "notes": self.notes,
        }


def _label_samples(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Label sampled points with the sklearn model.

    Returns the rows that classified and their labels; points too sparsely
    observed to classify are dropped rather than assigned a fallback class.
    """
    kept: list[dict] = []
    labels: list[str] = []
    for row in rows:
        try:
            labels.append(predict_crop(row)["crop_type"])
        except InsufficientFeatures:
            continue
        kept.append(row)
    return kept, labels


def build_crop_map(
    district: ResolvedDistrict,
    window_days: int | None = None,
    training_samples: int = DEFAULT_TRAINING_SAMPLES,
) -> CropMapLayer:
    """Classify every cropland pixel in a district and return a tile layer.

    Raises:
        NoImageryAvailable: no cloud-free scene in the window.
        EarthEngineUnavailable: Earth Engine could not complete the work.
        ValueError: too few points classified to fit a server-side model.
    """
    from ml_pipeline.feature_engineering import add_index_bands
    from ml_pipeline.gee_ingestion import (
        SOURCE_BANDS,
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

    columns = feature_columns()
    available = [c for c in columns if c in composite.bandNames().getInfo()]

    # Cropland screen, matching the district classifier so the two agree about
    # what counts as farmland.
    cropland = composite.select("NDVI").gte(MIN_CROPLAND_NDVI).And(
        composite.select("NDWI").lte(MAX_CROPLAND_NDWI)
    )
    masked = composite.updateMask(cropland)

    # ---- sample and label locally -------------------------------------
    samples = masked.select(available).sample(
        region=geometry,
        scale=SAMPLE_SCALE_M,
        numPixels=training_samples,
        seed=42,
        geometries=True,
        dropNulls=True,
    )
    try:
        payload = samples.getInfo()
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(f"Sampling failed for the crop map: {exc}") from exc

    features = payload.get("features", [])
    rows = [f.get("properties", {}) for f in features]
    kept, labels = _label_samples(rows)

    if len(kept) < 50:
        raise ValueError(
            f"Only {len(kept)} sample point(s) could be classified, too few to "
            "fit a per-pixel model. This usually means heavy cloud cover."
        )

    # ---- rebuild as a labelled FeatureCollection for Earth Engine ------
    classes = class_labels()
    class_index = {name: i for i, name in enumerate(classes)}

    labelled = []
    for feature, row, label in zip(features, kept, labels):
        props = {c: float(row[c]) for c in available if row.get(c) is not None}
        props["class"] = class_index[label]
        labelled.append(ee.Feature(ee.Geometry(feature["geometry"]), props))

    fc = ee.FeatureCollection(labelled).randomColumn("split", 42)
    train = fc.filter(ee.Filter.gte("split", HOLDOUT_FRACTION))
    test = fc.filter(ee.Filter.lt("split", HOLDOUT_FRACTION))

    classifier = ee.Classifier.smileRandomForest(numberOfTrees=EE_TREES, seed=42).train(
        features=train, classProperty="class", inputProperties=available
    )

    # ---- how faithfully does the EE forest copy the sklearn one? -------
    try:
        matrix = test.classify(classifier).errorMatrix("class", "classification")
        agreement = float(matrix.accuracy().getInfo())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not measure crop-map agreement: %s", exc)
        agreement = 0.0

    classified = masked.select(available).classify(classifier).clip(geometry)

    palette = [CLASS_COLOURS.get(name, "#9ca3af") for name in classes]
    map_id = classified.getMapId(
        {"min": 0, "max": len(classes) - 1, "palette": palette}
    )

    notes: list[str] = []
    faithful = agreement >= MIN_AGREEMENT
    if not faithful:
        notes.append(
            f"The Earth Engine forest reproduces the platform classifier on only "
            f"{agreement:.0%} of held-out points, below the {MIN_AGREEMENT:.0%} "
            "needed to treat this raster as a faithful stand-in. Read it as "
            "indicative of pattern, not of class."
        )
    if len(kept) < len(rows):
        notes.append(
            f"{len(rows) - len(kept)} of {len(rows)} sampled points were too "
            "sparsely observed to label and were dropped."
        )

    return CropMapLayer(
        district=district.requested_name,
        composite_start=start,
        composite_end=end,
        scene_count=scene_count,
        tile_url_template=map_id["tile_fetcher"].url_format,
        legend={name: CLASS_COLOURS.get(name, "#9ca3af") for name in classes},
        training_points=len(kept),
        agreement=agreement,
        faithful=faithful,
        notes=notes,
    )

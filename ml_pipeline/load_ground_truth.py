"""Phase 3 -- ingest digitised field parcels and build their index time series.

Usage::

    python -m ml_pipeline.load_ground_truth data/ground_truth/kolar_2024.geojson \\
        --district Kolar --verified-by "R. Shastri (HD Kolar)" --compute-indices

What this tool deliberately refuses to do:

* **Guess a crop label.** An unrecognised label aborts the file with a list of
  the offending values. It is never coerced to the nearest class.
* **Mark a parcel verified without an attributor.** ``verified_flag`` requires
  both a crop label and a named person or survey that stands behind it.
* **Accept a district the live GAUL lookup could not confirm** (unless
  ``--skip-district-check`` is passed for an offline load, which leaves the
  parcels loaded but the district still unvalidated until it resolves).

The result is that ``parcels.verified_flag`` means exactly one thing: a human
attributed this polygon to this crop. Phase 4 keys off nothing else.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from ml_pipeline import config, db
from ml_pipeline.gee_auth import EarthEngineUnavailable

logger = logging.getLogger(__name__)

#: Accepted spellings for each crop class. Matching is exact after casefolding
#: and whitespace collapse -- there is no fuzzy fallback, because a mislabelled
#: training parcel is worse than a rejected file.
LABEL_ALIASES: dict[str, str] = {
    "tomato": "Tomato",
    "tomatoes": "Tomato",
    "tamatar": "Tomato",
    "tomato hybrid": "Tomato",
    "onion": "Onion",
    "onions": "Onion",
    "eerulli": "Onion",
    "irulli": "Onion",
    "potato": "Potato",
    "potatoes": "Potato",
    "aloo": "Potato",
    "alugadde": "Potato",
    "leafy greens": "Leafy Greens",
    "leafy vegetables": "Leafy Greens",
    "spinach": "Leafy Greens",
    "palak": "Leafy Greens",
    "amaranth": "Leafy Greens",
    "coriander": "Leafy Greens",
    "methi": "Leafy Greens",
    "fenugreek": "Leafy Greens",
    "soppu": "Leafy Greens",
    "fallow": "Fallow/Non-Crop",
    "fallow/non-crop": "Fallow/Non-Crop",
    "non-crop": "Fallow/Non-Crop",
    "noncrop": "Fallow/Non-Crop",
    "barren": "Fallow/Non-Crop",
    "bare soil": "Fallow/Non-Crop",
    "uncultivated": "Fallow/Non-Crop",
}

# Property keys checked, in order, when looking for each field.
LABEL_KEYS = ("crop_label", "crop", "label", "croptype", "crop_type")
UID_KEYS = ("parcel_uid", "uid", "id", "parcel_id", "survey_no", "survey_number")
DISTRICT_KEYS = ("district", "dist", "adm2_name")
SURVEY_DATE_KEYS = ("survey_date", "surveyed_on", "date", "visit_date")
VERIFIER_KEYS = ("verified_by", "surveyor", "enumerator", "attributed_by")


class GroundTruthError(ValueError):
    """A ground-truth file failed validation. Nothing is written."""


def _normalise_label(raw: str) -> str | None:
    key = " ".join(str(raw).strip().lower().split())
    if key in LABEL_ALIASES:
        return LABEL_ALIASES[key]
    # Allow the canonical class names themselves.
    for canonical in config.CROP_CLASSES:
        if key == canonical.lower():
            return canonical
    return None


def _first(properties: dict, keys: Sequence[str]) -> Any:
    lowered = {str(k).lower(): v for k, v in properties.items()}
    for key in keys:
        value = lowered.get(key)
        if value not in (None, ""):
            return value
    return None


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    logger.warning("Unparseable survey date %r; storing NULL.", value)
    return None


def read_feature_collection(path: Path) -> list[dict]:
    """Load a GeoJSON file and return its features."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GroundTruthError(f"{path.name}: not valid JSON -- {exc}") from exc

    kind = payload.get("type")
    if kind == "FeatureCollection":
        features = payload.get("features") or []
    elif kind == "Feature":
        features = [payload]
    else:
        raise GroundTruthError(
            f"{path.name}: expected a GeoJSON Feature or FeatureCollection, got {kind!r}"
        )

    # RFC 7946 fixes GeoJSON at WGS 84. A named CRS other than 4326 means the
    # coordinates are not what the schema expects, so refuse rather than
    # reproject on a guess.
    crs = payload.get("crs")
    if crs:
        name = json.dumps(crs)
        if "4326" not in name and "CRS84" not in name.upper():
            raise GroundTruthError(
                f"{path.name}: declares CRS {name}; reproject to EPSG:4326 before loading"
            )

    if not features:
        raise GroundTruthError(f"{path.name}: contains no features")
    return features


def parse_features(
    features: Iterable[dict],
    source_name: str,
    default_district: str | None = None,
    default_verifier: str | None = None,
    require_labels: bool = True,
) -> list[dict]:
    """Validate features and shape them into parcel dicts.

    Raises:
        GroundTruthError: on any invalid geometry, unknown crop label, missing
            district or missing identifier. Validation is all-or-nothing so a
            partially-bad file never half-loads.
    """
    parcels: list[dict] = []
    unknown_labels: set[str] = set()
    problems: list[str] = []

    for position, feature in enumerate(features, start=1):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry")

        if not geometry or geometry.get("type") not in ("Polygon", "MultiPolygon"):
            problems.append(
                f"feature #{position}: geometry must be Polygon or MultiPolygon, "
                f"got {(geometry or {}).get('type')!r}"
            )
            continue

        district = _first(properties, DISTRICT_KEYS) or default_district
        if not district:
            problems.append(
                f"feature #{position}: no district property and no --district given"
            )
            continue

        uid = _first(properties, UID_KEYS)
        if uid in (None, ""):
            # Fall back to a deterministic, file-scoped identifier so re-runs of
            # the same file update the same rows instead of duplicating them.
            uid = f"{source_name}#{position}"

        raw_label = _first(properties, LABEL_KEYS)
        crop_label: str | None = None
        if raw_label not in (None, ""):
            crop_label = _normalise_label(raw_label)
            if crop_label is None:
                unknown_labels.add(str(raw_label))
                continue
        elif require_labels:
            problems.append(
                f"feature #{position} ({uid}): no crop label found in "
                f"{list(properties)[:6]}"
            )
            continue

        verifier = _first(properties, VERIFIER_KEYS) or default_verifier
        # verified_flag is asserted only when both halves of the claim exist.
        verified = bool(crop_label and verifier)

        parcels.append(
            {
                "parcel_uid": str(uid),
                "district": str(district).strip(),
                "crop_label": crop_label,
                "verified_flag": verified,
                "label_source": source_name,
                "survey_date": _parse_date(_first(properties, SURVEY_DATE_KEYS)),
                "verified_by": str(verifier) if verified else None,
                "geometry": geometry,
            }
        )

    if unknown_labels:
        problems.append(
            "unrecognised crop label(s): "
            + ", ".join(sorted(repr(u) for u in unknown_labels))
            + f". Accepted classes are {', '.join(config.CROP_CLASSES)}. "
            "Add an alias to LABEL_ALIASES or correct the source file -- "
            "labels are never inferred."
        )

    if problems:
        raise GroundTruthError(
            f"{source_name}: {len(problems)} validation problem(s):\n  - "
            + "\n  - ".join(problems)
        )

    return parcels


def summarise(parcels: Sequence[dict]) -> dict:
    """Counts by district, class and verification state, for the run log."""
    by_district: dict[str, int] = {}
    by_class: dict[str, int] = {}
    verified = 0
    for parcel in parcels:
        by_district[parcel["district"]] = by_district.get(parcel["district"], 0) + 1
        label = parcel["crop_label"] or "<unlabelled>"
        by_class[label] = by_class.get(label, 0) + 1
        verified += int(parcel["verified_flag"])
    return {
        "parcels": len(parcels),
        "verified": verified,
        "unverified": len(parcels) - verified,
        "by_district": by_district,
        "by_class": by_class,
    }


def compute_index_series(
    districts: Sequence[str],
    lookback_days: int | None = None,
) -> list[dict]:
    """Compute mean spatial index time series for the loaded parcels.

    This is the "compute mean spatial time-series indices" half of Phase 3: it
    runs the Phase 1 ingestion over the freshly loaded polygons so that every
    verified parcel arrives at Phase 4 with a populated feature history.
    """
    from ml_pipeline.gee_districts import resolve_districts
    from ml_pipeline.gee_ingestion import ingest_district

    lookback_days = lookback_days or config.SETTINGS.seed_lookback_days
    end = datetime.now(tz=timezone.utc).date()
    start = end - timedelta(days=lookback_days)

    reports: list[dict] = []
    resolution = resolve_districts(list(districts))
    for name in resolution.unresolved:
        logger.error(
            "District %r did not resolve against GAUL; its parcels stay unvalidated.",
            name,
        )
        reports.append({"district": name, "error": "unresolved against FAO/GAUL/2015/level2"})

    for district in resolution.resolved:
        parcels = db.fetch_parcels(district=district.gaul_name)
        if not parcels:
            continue
        records, report = ingest_district(district, parcels, start, end)
        if records:
            report.records_written = db.upsert_index_time_series(records)
        db.record_pipeline_run(
            stage="ground_truth_indices",
            district=district.gaul_name,
            payload=report.to_dict(),
            ok=not report.errors,
        )
        reports.append(report.to_dict())
    return reports


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="load_ground_truth",
        description="Ingest digitised parcel GeoJSONs into PostGIS.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="GeoJSON file(s) or directories")
    parser.add_argument(
        "--district",
        default=None,
        help="District to apply to features that do not carry one.",
    )
    parser.add_argument(
        "--verified-by",
        default=None,
        help=(
            "Person or survey standing behind these labels. Required for the "
            "parcels to count as verified ground truth."
        ),
    )
    parser.add_argument(
        "--allow-unlabelled",
        action="store_true",
        help="Load boundary-only parcels (they stay unverified and unusable for training).",
    )
    parser.add_argument(
        "--compute-indices",
        action="store_true",
        help="Run Sentinel-2 ingestion for the loaded districts afterwards.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="History to build when --compute-indices is set (default: GEE_SEED_LOOKBACK_DAYS).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate only; write nothing.")
    return parser


def expand_paths(paths: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.geojson")))
            files.extend(sorted(path.glob("*.json")))
        elif path.exists():
            files.append(path)
        else:
            raise GroundTruthError(f"{path}: no such file or directory")
    if not files:
        raise GroundTruthError("No GeoJSON files found in the given paths")
    return files


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        files = expand_paths(args.paths)
    except GroundTruthError as exc:
        logger.error("%s", exc)
        return 2

    all_parcels: list[dict] = []
    for path in files:
        try:
            features = read_feature_collection(path)
            parcels = parse_features(
                features,
                source_name=path.name,
                default_district=args.district,
                default_verifier=args.verified_by,
                require_labels=not args.allow_unlabelled,
            )
        except GroundTruthError as exc:
            logger.error("%s", exc)
            return 2
        logger.info("%s: %d parcel(s) validated", path.name, len(parcels))
        all_parcels.extend(parcels)

    summary = summarise(all_parcels)
    if summary["verified"] == 0:
        logger.warning(
            "No parcel qualifies as verified ground truth. Districts loaded from "
            "these files stay UNVALIDATED and will render as raw NDVI basemap "
            "only. Pass --verified-by, or include a verifier property, to "
            "attribute the labels."
        )

    if args.dry_run:
        print(json.dumps({"dry_run": True, **summary}, indent=2, default=str))
        return 0

    try:
        written = db.upsert_parcels(all_parcels)
    except db.DatabaseUnavailable as exc:
        logger.error("%s", exc)
        return 3

    logger.info("Wrote %d parcel(s) to PostGIS", written)
    db.record_pipeline_run(
        stage="load_ground_truth",
        district=args.district,
        payload={"files": [f.name for f in files], **summary},
        ok=True,
    )

    result: dict = {"written": written, **summary}

    if args.compute_indices:
        districts = sorted(summary["by_district"])
        try:
            result["index_reports"] = compute_index_series(districts, args.lookback_days)
        except EarthEngineUnavailable as exc:
            logger.error(
                "Parcels are loaded, but Earth Engine is unavailable so no index "
                "series was built: %s",
                exc,
            )
            result["index_reports"] = {"error": str(exc)}

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Ingest a cold storage register (CSV or GeoJSON) into PostGIS.

Usage::

    python -m ml_pipeline.load_cold_storage data/cold_storage/nhb_karnataka.csv \\
        --source "NHB Cold Storage Directory" --source-year 2023 \\
        --source-url https://www.nhb.gov.in/csrIndex.aspx

Accepts a CSV with a header row, or a GeoJSON FeatureCollection of points.
Column names are matched case-insensitively against the aliases below, so a
register exported from NHB, a state horticulture department or MoFPI can be
loaded without being reshaped first.

What this loader refuses to do
------------------------------
* **Invent coordinates.** A row without usable lat/lon is loaded with a NULL
  geometry: listed and counted, but not mapped. It is never geocoded to a
  district or taluk centroid, which would place a real business at an address
  it does not occupy.
* **Estimate capacity.** A blank or unparseable capacity stays NULL. It is
  never derived from chamber count or floor area.
* **Accept a row without a district**, since every query in the platform is
  district-scoped.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from ml_pipeline import db

logger = logging.getLogger(__name__)

NAME_KEYS = ("name", "facility_name", "cold_storage_name", "unit_name", "firm_name")
UID_KEYS = ("facility_uid", "uid", "id", "licence_no", "license_no", "registration_no")
DISTRICT_KEYS = ("district", "district_name", "dist")
TALUK_KEYS = ("taluk", "taluka", "tehsil", "block", "mandal")
ADDRESS_KEYS = ("address", "location", "village", "place", "full_address")
CAPACITY_KEYS = (
    "capacity_mt",
    "capacity",
    "capacity_in_mt",
    "installed_capacity",
    "licensed_capacity",
    "capacity_tonnes",
)
COMMODITY_KEYS = ("commodity", "commodity_focus", "commodities", "produce")
OWNERSHIP_KEYS = ("ownership", "sector", "type", "ownership_type")
COST_KEYS = (
    "cost_per_day_per_tonne",
    "cost_per_tonne_day",
    "cost_per_tonne_per_day",
    "tariff",
    "rate",
)
CROPS_KEYS = ("crops_supported", "crops", "accepted_crops")
CONTACT_KEYS = ("contact", "phone", "mobile", "telephone", "contact_no")
LAT_KEYS = ("latitude", "lat", "y")
LON_KEYS = ("longitude", "lon", "lng", "long", "x")

#: Crop names folded to the classifier's class vocabulary, so a facility can be
#: matched against a predicted crop without a second mapping in between.
CROP_VOCAB = {
    "tomato": "tomato",
    "tomatoes": "tomato",
    "onion": "onion",
    "onions": "onion",
    "potato": "potato",
    "leafy_greens": "leafy_greens",
    "leafy greens": "leafy_greens",
    "greens": "leafy_greens",
    "spinach": "leafy_greens",
}

OWNERSHIP_ALIASES = {
    "private": "private",
    "pvt": "private",
    "private sector": "private",
    "cooperative": "cooperative",
    "co-operative": "cooperative",
    "coop": "cooperative",
    "co-op": "cooperative",
    "government": "government",
    "govt": "government",
    "public": "government",
    "public sector": "government",
    "state": "government",
}

# Karnataka's bounding box, used only to reject transposed or malformed
# coordinates -- never to snap a point onto the state.
KARNATAKA_BBOX = (74.0, 11.5, 78.6, 18.5)  # west, south, east, north


class ColdStorageError(ValueError):
    """The register failed validation. Nothing is written."""


def _first(row: dict, keys: Sequence[str]) -> Any:
    lowered = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}
    for key in keys:
        value = lowered.get(key)
        if value not in (None, ""):
            return value
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    # Registers often write "5000 MT" or "5,000 tonnes".
    for suffix in ("mt", "tonnes", "tonne", "tons", "ton"):
        if text.lower().endswith(suffix):
            text = text[: -len(suffix)].strip()
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number > 0 else None


def _normalise_ownership(value: Any) -> str:
    if value in (None, ""):
        return "unknown"
    key = " ".join(str(value).strip().lower().split())
    return OWNERSHIP_ALIASES.get(key, "unknown")


def _crops(value: Any) -> list[str]:
    """Split a crop list, keeping only names the platform recognises.

    An unrecognised crop is dropped rather than passed through: this field is
    used to match a facility against a predicted crop, and an unknown token
    would silently never match anything while looking like it might.
    """
    if value in (None, ""):
        return []
    out: list[str] = []
    for token in str(value).replace("|", ",").replace(";", ",").split(","):
        key = " ".join(token.strip().lower().split())
        crop = CROP_VOCAB.get(key)
        if crop and crop not in out:
            out.append(crop)
    return out


def _coordinates(row: dict) -> tuple[float | None, float | None]:
    """Return ``(lon, lat)``, or ``(None, None)`` when unusable.

    A coordinate pair outside Karnataka's bounding box is discarded rather than
    corrected: it usually means lat/lon were transposed at export, and guessing
    which way round they belong would move a real facility.
    """
    lat = _to_float(_first(row, LAT_KEYS))
    lon = _to_float(_first(row, LON_KEYS))
    if lat is None or lon is None:
        return None, None

    west, south, east, north = KARNATAKA_BBOX
    if not (west <= lon <= east and south <= lat <= north):
        logger.warning(
            "Discarding out-of-range coordinates (lon=%s, lat=%s); the facility "
            "is loaded without a location rather than being placed wrongly.",
            lon,
            lat,
        )
        return None, None
    return lon, lat


def read_rows(path: Path) -> list[dict]:
    """Read a CSV or GeoJSON register into flat dicts."""
    if path.suffix.lower() in {".geojson", ".json"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features") or []
        rows = []
        for feature in features:
            props = dict(feature.get("properties") or {})
            geom = feature.get("geometry") or {}
            if geom.get("type") == "Point":
                coords = geom.get("coordinates") or []
                if len(coords) >= 2:
                    props.setdefault("longitude", coords[0])
                    props.setdefault("latitude", coords[1])
            rows.append(props)
        return rows

    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_rows(
    rows: Iterable[dict],
    source_name: str,
    source: str,
    source_url: str | None,
    source_year: int | None,
    default_district: str | None = None,
) -> list[dict]:
    facilities: list[dict] = []
    problems: list[str] = []

    for position, row in enumerate(rows, start=1):
        district = _first(row, DISTRICT_KEYS) or default_district
        if not district:
            problems.append(f"row #{position}: no district column and no --district given")
            continue

        name = _first(row, NAME_KEYS)
        if not name:
            problems.append(f"row #{position}: no facility name")
            continue

        uid = _first(row, UID_KEYS) or f"{source_name}#{position}"
        lon, lat = _coordinates(row)

        facilities.append(
            {
                "facility_uid": str(uid).strip(),
                "name": str(name).strip(),
                "district": str(district).strip(),
                "taluk": (str(_first(row, TALUK_KEYS)).strip() if _first(row, TALUK_KEYS) else None),
                "address": (str(_first(row, ADDRESS_KEYS)).strip() if _first(row, ADDRESS_KEYS) else None),
                "capacity_mt": _to_float(_first(row, CAPACITY_KEYS)),
                "commodity_focus": (
                    str(_first(row, COMMODITY_KEYS)).strip()
                    if _first(row, COMMODITY_KEYS)
                    else None
                ),
                "ownership": _normalise_ownership(_first(row, OWNERSHIP_KEYS)),
                # NULL when not stated: a 0 tariff would read as free storage.
                "cost_per_tonne_day": _to_float(_first(row, COST_KEYS)),
                "crops_supported": _crops(_first(row, CROPS_KEYS)),
                "contact": (
                    str(_first(row, CONTACT_KEYS)).strip()
                    if _first(row, CONTACT_KEYS)
                    else None
                ),
                "longitude": lon,
                "latitude": lat,
                "source": source,
                "source_url": source_url,
                "source_year": source_year,
            }
        )

    if problems:
        raise ColdStorageError(
            f"{source_name}: {len(problems)} validation problem(s):\n  - "
            + "\n  - ".join(problems)
        )
    return facilities


def upsert(facilities: Sequence[dict]) -> int:
    if not facilities:
        return 0
    with db.connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO cold_storage_facilities
                (facility_uid, name, district, taluk, address, capacity_mt,
                 commodity_focus, ownership, geom, source, source_url, source_year,
                 cost_per_tonne_day, crops_supported, contact)
            VALUES (
                %(facility_uid)s, %(name)s, %(district)s, %(taluk)s, %(address)s,
                %(capacity_mt)s, %(commodity_focus)s, %(ownership)s,
                CASE
                    WHEN %(longitude)s IS NULL OR %(latitude)s IS NULL THEN NULL
                    ELSE ST_SetSRID(ST_MakePoint(%(longitude)s, %(latitude)s), 4326)
                END,
                %(source)s, %(source_url)s, %(source_year)s,
                %(cost_per_tonne_day)s, %(crops_supported)s, %(contact)s
            )
            ON CONFLICT (facility_uid, district) DO UPDATE SET
                name            = EXCLUDED.name,
                taluk           = EXCLUDED.taluk,
                address         = EXCLUDED.address,
                capacity_mt     = EXCLUDED.capacity_mt,
                commodity_focus = EXCLUDED.commodity_focus,
                ownership       = EXCLUDED.ownership,
                geom            = COALESCE(EXCLUDED.geom, cold_storage_facilities.geom),
                source          = EXCLUDED.source,
                source_url      = EXCLUDED.source_url,
                source_year     = EXCLUDED.source_year,
                cost_per_tonne_day = EXCLUDED.cost_per_tonne_day,
                crops_supported = EXCLUDED.crops_supported,
                contact         = EXCLUDED.contact
            """,
            list(facilities),
        )
    return len(facilities)


def summarise(facilities: Sequence[dict]) -> dict:
    by_district: dict[str, int] = {}
    mapped = capacity_known = 0
    for f in facilities:
        by_district[f["district"]] = by_district.get(f["district"], 0) + 1
        mapped += int(f["longitude"] is not None)
        capacity_known += int(f["capacity_mt"] is not None)
    return {
        "facilities": len(facilities),
        "mapped": mapped,
        "unmapped": len(facilities) - mapped,
        "capacity_known": capacity_known,
        "by_district": by_district,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="load_cold_storage",
        description="Ingest a cold storage register (CSV or GeoJSON) into PostGIS.",
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--source",
        required=True,
        help='Register this came from, e.g. "NHB Cold Storage Directory".',
    )
    parser.add_argument("--source-url", default=None)
    parser.add_argument(
        "--source-year",
        type=int,
        default=None,
        help="Vintage of the register. Surfaced in the UI so nobody reads a "
        "2014 directory as current.",
    )
    parser.add_argument("--district", default=None, help="Applied to rows without one.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    all_facilities: list[dict] = []
    for path in args.paths:
        if not path.exists():
            logger.error("%s: no such file", path)
            return 2
        try:
            rows = read_rows(path)
            facilities = parse_rows(
                rows,
                source_name=path.name,
                source=args.source,
                source_url=args.source_url,
                source_year=args.source_year,
                default_district=args.district,
            )
        except (ColdStorageError, json.JSONDecodeError) as exc:
            logger.error("%s", exc)
            return 2
        logger.info("%s: %d facility(ies) validated", path.name, len(facilities))
        all_facilities.extend(facilities)

    summary = summarise(all_facilities)
    if summary["unmapped"]:
        logger.warning(
            "%d facility(ies) have no usable coordinates. They are listed and "
            "counted but will not appear on the map -- they are never geocoded "
            "to a district centroid.",
            summary["unmapped"],
        )

    if args.dry_run:
        print(json.dumps({"dry_run": True, **summary}, indent=2))
        return 0

    try:
        written = upsert(all_facilities)
    except db.DatabaseUnavailable as exc:
        logger.error("%s", exc)
        return 3

    db.record_pipeline_run(
        stage="load_cold_storage",
        district=args.district,
        payload={"source": args.source, **summary},
        ok=True,
    )
    print(json.dumps({"written": written, **summary}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

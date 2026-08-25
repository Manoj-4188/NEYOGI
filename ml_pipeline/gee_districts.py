"""Dynamic district-boundary resolution.

The candidate district names in ``config.CANDIDATE_DISTRICTS`` are the names
used by the Karnataka administration today. Two problems stand between those
names and a polygon:

**Spelling.** GAUL spells several of them the old way — "Bangalore Rural" for
Bengaluru Rural, "Tumkur" for Tumakuru, "Chikmagalur" for Chikkamagaluru.
Hard-coding a mapping would silently query the wrong polygon the day GAUL is
republished, so the live ``ADM2_NAME`` list is fetched at runtime and matched
against.

**Vintage.** GAUL's 2015 snapshot predates the 2007 Karnataka reorganisation.
It carries 27 ADM2 features for the state, and neither Chikkaballapura (split
from Kolar) nor Ramanagara (split from Bangalore Rural) is among them. Querying
the parent district instead would silently return the wrong ground — Kolar's
polygon still contains Chikkaballapura's territory, so the request would
succeed and the numbers would be wrong.

So resolution runs in two passes:

1. **GAUL** — the primary, authoritative source.
2. **geoBoundaries CGAZ ADM2** — consulted only for candidates GAUL could not
   resolve. Open data (CC-BY 4.0, William & Mary geoLab), current enough to
   carry both post-2007 districts.

Every resolved district records which source it came from, and that provenance
travels through the API into the UI. A candidate neither source can place is
returned in ``unresolved`` and skipped — never approximated to a neighbour.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from ml_pipeline import config
from ml_pipeline.gee_auth import EarthEngineUnavailable, initialize

logger = logging.getLogger(__name__)

# Minimum similarity for an automatic fuzzy match. Below this the candidate is
# reported unresolved so that a human decides -- we never guess a boundary.
FUZZY_MATCH_THRESHOLD = 0.82

#: Source identifiers recorded on each resolved district.
SOURCE_GAUL = "FAO/GAUL/2015/level2"
SOURCE_GEOBOUNDARIES = "geoBoundaries/CGAZ_ADM2"

# Known transliteration equivalences. These are aliases used *during matching*,
# not a substitute for the live lookup: a candidate still has to appear in the
# response under one of these spellings before it resolves.
TRANSLITERATION_ALIASES: dict[str, tuple[str, ...]] = {
    "bengaluru rural": ("bangalore rural",),
    "bengaluru urban": ("bangalore urban",),
    "chikkaballapur": ("chikballapur", "chikkaballapura", "chikballapura"),
    "chikkamagaluru": ("chikmagalur", "chikkamagalur", "chickmagalur"),
    "tumakuru": ("tumkur",),
    "mysuru": ("mysore",),
    "belagavi": ("belgaum",),
    "kalaburagi": ("gulbarga",),
    "vijayapura": ("bijapur",),
    "ballari": ("bellary",),
    "shivamogga": ("shimoga",),
}


def normalise(name: str) -> str:
    """Fold a district name to a comparable key.

    Strips accents and punctuation, collapses whitespace and lowercases.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9]+", " ", stripped.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _candidate_keys(name: str) -> list[str]:
    key = normalise(name)
    return [key, *TRANSLITERATION_ALIASES.get(key, ())]


@dataclass(frozen=True)
class ResolvedDistrict:
    """A district candidate successfully matched to a real boundary feature."""

    requested_name: str
    gaul_name: str
    adm1_name: str
    adm0_name: str
    #: GAUL ADM2_CODE, or -1 for a district resolved from the fallback source.
    adm2_code: int
    match_kind: str  # "exact" | "alias" | "fuzzy"
    match_score: float
    #: Which dataset supplied the polygon. See SOURCE_* above.
    source: str = SOURCE_GAUL
    #: geoBoundaries shapeName, when source is the fallback. Used to re-select
    #: the geometry without relying on a numeric code the dataset lacks.
    source_key: str = ""

    @property
    def is_exact(self) -> bool:
        return self.match_kind == "exact"

    @property
    def is_fallback_source(self) -> bool:
        return self.source != SOURCE_GAUL


@dataclass(frozen=True)
class DistrictResolution:
    """Outcome of resolving every candidate against the live datasets."""

    resolved: tuple[ResolvedDistrict, ...]
    unresolved: tuple[str, ...]
    available_names: tuple[str, ...]
    state: str
    country: str

    @property
    def resolved_names(self) -> tuple[str, ...]:
        return tuple(d.gaul_name for d in self.resolved)

    @property
    def fallback_names(self) -> tuple[str, ...]:
        """Districts that needed the secondary boundary source."""
        return tuple(d.requested_name for d in self.resolved if d.is_fallback_source)

    def get(self, requested_name: str) -> ResolvedDistrict | None:
        key = normalise(requested_name)
        for district in self.resolved:
            if key in {normalise(district.requested_name), normalise(district.gaul_name)}:
                return district
        return None

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "country": self.country,
            "resolved": [
                {
                    "requested_name": d.requested_name,
                    "gaul_name": d.gaul_name,
                    "adm2_code": d.adm2_code,
                    "match_kind": d.match_kind,
                    "match_score": round(d.match_score, 4),
                    "source": d.source,
                }
                for d in self.resolved
            ],
            "unresolved": list(self.unresolved),
            "fallback_used": list(self.fallback_names),
            "available_count": len(self.available_names),
        }


# --------------------------------------------------------------------------
# Primary source: FAO GAUL
# --------------------------------------------------------------------------


def _state_filter(ee, state: str, country: str):
    """Build the GAUL filter for a state, tolerating ADM1 spelling drift."""
    aliases = {normalise(state), *TRANSLITERATION_ALIASES.get(normalise(state), ())}
    name_filters = [ee.Filter.eq("ADM1_NAME", alias.title()) for alias in aliases]
    name_filters.append(ee.Filter.eq("ADM1_NAME", state))
    return ee.Filter.And(
        ee.Filter.eq("ADM0_NAME", country),
        ee.Filter.Or(*name_filters),
    )


@lru_cache(maxsize=8)
def fetch_state_districts(state: str, country: str) -> tuple[dict, ...]:
    """Return every GAUL ADM2 feature's descriptive properties for a state.

    Cached per process: the GAUL collection is static within a run, and this is
    the only unavoidable ``getInfo()`` round trip in the resolution path.
    """
    initialize()
    import ee

    collection = ee.FeatureCollection(config.GAUL_LEVEL2).filter(
        _state_filter(ee, state, country)
    )
    try:
        rows = collection.reduceColumns(
            ee.Reducer.toList(3),
            ["ADM2_NAME", "ADM2_CODE", "ADM1_NAME"],
        ).getInfo()
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(f"GAUL district lookup failed: {exc}") from exc

    rendered = rows.get("list") or []
    districts = [
        {"adm2_name": row[0], "adm2_code": int(row[1]), "adm1_name": row[2]}
        for row in rendered
        if row and row[0]
    ]
    if not districts:
        raise EarthEngineUnavailable(
            f"GAUL returned no ADM2 features for {state}, {country}. "
            "Check the ADM1_NAME spelling in the current GAUL release."
        )
    logger.info("GAUL: %d districts found for %s", len(districts), state)
    return tuple(districts)


# --------------------------------------------------------------------------
# Fallback source: geoBoundaries CGAZ
# --------------------------------------------------------------------------


def _state_geometry(ee, state: str, country: str):
    """The state's GAUL ADM1 polygon, used to scope the fallback spatially.

    geoBoundaries has no state-name property on its ADM2 features, so the
    candidate set is narrowed by intersecting with the state boundary rather
    than by attribute -- which also guarantees a fallback district cannot be
    matched to a same-named district in another state.
    """
    aliases = {normalise(state), *TRANSLITERATION_ALIASES.get(normalise(state), ())}
    name_filters = [ee.Filter.eq("ADM1_NAME", alias.title()) for alias in aliases]
    name_filters.append(ee.Filter.eq("ADM1_NAME", state))
    return (
        ee.FeatureCollection(config.GAUL_LEVEL1)
        .filter(ee.Filter.And(ee.Filter.eq("ADM0_NAME", country), ee.Filter.Or(*name_filters)))
        .geometry()
    )


@lru_cache(maxsize=8)
def fetch_fallback_districts(state: str, country: str) -> tuple[dict, ...]:
    """ADM2 names from geoBoundaries that fall inside the state.

    Returns an empty tuple rather than raising when the dataset is unreachable:
    the fallback is best-effort, and its absence must degrade to "unresolved",
    not to a failed run.
    """
    if not config.USE_BOUNDARY_FALLBACK:
        return ()

    initialize()
    import ee

    try:
        state_geom = _state_geometry(ee, state, country)
        collection = (
            ee.FeatureCollection(config.GEOBOUNDARIES_ADM2)
            .filter(ee.Filter.eq("shapeGroup", config.GEOBOUNDARIES_COUNTRY))
            .filterBounds(state_geom)
        )
        names = collection.aggregate_array("shapeName").getInfo() or []
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "geoBoundaries fallback unavailable (%s). Districts missing from "
            "GAUL will be reported unresolved.",
            exc,
        )
        return ()

    districts = [{"adm2_name": n, "adm1_name": state} for n in sorted(set(names)) if n]
    logger.info("geoBoundaries: %d ADM2 names inside %s", len(districts), state)
    return tuple(districts)


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def _match(candidate: str, by_key: dict[str, dict]) -> tuple[dict | None, str, float]:
    """Exact key, then transliteration alias, then fuzzy above threshold."""
    for idx, key in enumerate(_candidate_keys(candidate)):
        if key in by_key:
            return by_key[key], ("exact" if idx == 0 else "alias"), 1.0

    close = difflib.get_close_matches(
        normalise(candidate), list(by_key), n=1, cutoff=FUZZY_MATCH_THRESHOLD
    )
    if close:
        score = difflib.SequenceMatcher(None, normalise(candidate), close[0]).ratio()
        return by_key[close[0]], "fuzzy", score
    return None, "", 0.0


def resolve_districts(
    candidates: list[str] | tuple[str, ...] | None = None,
    state: str | None = None,
    country: str | None = None,
) -> DistrictResolution:
    """Match candidate district names to real boundary features.

    GAUL is tried first. Anything it cannot place is retried against
    geoBoundaries, which carries the post-2007 districts GAUL predates. A
    candidate neither source resolves is returned in ``unresolved`` and must be
    skipped by the caller -- never substituted with a neighbouring polygon.
    """
    candidates = tuple(candidates or config.CANDIDATE_DISTRICTS)
    state = state or config.STATE_NAME
    country = country or config.COUNTRY_NAME

    available = fetch_state_districts(state, country)
    by_key: dict[str, dict] = {normalise(d["adm2_name"]): d for d in available}

    resolved: list[ResolvedDistrict] = []
    needs_fallback: list[str] = []

    for candidate in candidates:
        match, kind, score = _match(candidate, by_key)
        if match is None:
            needs_fallback.append(candidate)
            continue

        if kind != "exact":
            logger.info(
                "District %r resolved to GAUL ADM2_NAME %r (%s match, score=%.2f)",
                candidate,
                match["adm2_name"],
                kind,
                score,
            )
        resolved.append(
            ResolvedDistrict(
                requested_name=candidate,
                gaul_name=match["adm2_name"],
                adm1_name=match["adm1_name"],
                adm0_name=country,
                adm2_code=match["adm2_code"],
                match_kind=kind,
                match_score=score,
                source=SOURCE_GAUL,
            )
        )

    # Second pass: only for candidates GAUL could not place.
    unresolved: list[str] = []
    if needs_fallback:
        fallback = fetch_fallback_districts(state, country)
        fallback_by_key = {normalise(d["adm2_name"]): d for d in fallback}

        for candidate in needs_fallback:
            match, kind, score = _match(candidate, fallback_by_key)
            if match is None:
                logger.warning(
                    "District %r has no counterpart in GAUL or geoBoundaries for "
                    "%s; it will be skipped.",
                    candidate,
                    state,
                )
                unresolved.append(candidate)
                continue

            logger.info(
                "District %r not in GAUL (2015 snapshot predates it); resolved "
                "to geoBoundaries %r (%s match).",
                candidate,
                match["adm2_name"],
                kind,
            )
            resolved.append(
                ResolvedDistrict(
                    requested_name=candidate,
                    gaul_name=match["adm2_name"],
                    adm1_name=state,
                    adm0_name=country,
                    adm2_code=-1,  # geoBoundaries has no ADM2_CODE
                    match_kind=kind,
                    match_score=score,
                    source=SOURCE_GEOBOUNDARIES,
                    source_key=match["adm2_name"],
                )
            )

    return DistrictResolution(
        resolved=tuple(resolved),
        unresolved=tuple(unresolved),
        available_names=tuple(d["adm2_name"] for d in available),
        state=state,
        country=country,
    )


def district_geometry(district: ResolvedDistrict):
    """Return the ``ee.Geometry`` for a resolved district.

    GAUL features are selected by ``ADM2_CODE`` rather than name, so the
    geometry cannot drift from the feature the resolver validated. geoBoundaries
    has no such code, so its features are selected by ``shapeName`` and
    additionally clipped to the state to rule out a same-named district
    elsewhere in the country.
    """
    initialize()
    import ee

    if district.source == SOURCE_GAUL:
        return (
            ee.FeatureCollection(config.GAUL_LEVEL2)
            .filter(ee.Filter.eq("ADM2_CODE", district.adm2_code))
            .geometry()
        )

    state_geom = _state_geometry(ee, district.adm1_name, district.adm0_name)
    return (
        ee.FeatureCollection(config.GEOBOUNDARIES_ADM2)
        .filter(
            ee.Filter.And(
                ee.Filter.eq("shapeGroup", config.GEOBOUNDARIES_COUNTRY),
                ee.Filter.eq("shapeName", district.source_key or district.gaul_name),
            )
        )
        .filterBounds(state_geom)
        .geometry()
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: print the resolution report so an operator can audit the mapping."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Resolve districts against FAO/GAUL/2015/level2, with a "
        "geoBoundaries fallback for districts GAUL predates."
    )
    parser.add_argument("--districts", nargs="*", default=None)
    parser.add_argument("--state", default=None)
    parser.add_argument("--list-available", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    resolution = resolve_districts(args.districts, state=args.state)
    payload = resolution.to_dict()
    if args.list_available:
        payload["available_names"] = sorted(resolution.available_names)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 1 if resolution.unresolved else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Dynamic district-boundary resolution against FAO/GAUL/2015/level2.

The candidate district names in ``config.CANDIDATE_DISTRICTS`` are the names
used by the Karnataka administration. GAUL spells several of them differently
(older transliterations such as "Bangalore Rural" for "Bengaluru Rural"), and
the GAUL snapshot predates some district reorganisations.

Hard-coding a mapping would silently query the wrong polygon the day GAUL is
updated. Instead this module pulls the real ``ADM2_NAME`` list for the state at
runtime and matches against it, and it reports any candidate it could not
resolve rather than substituting a neighbouring district.
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

# Known transliteration equivalences. These are aliases used *during matching*,
# not a substitute for the live lookup: a candidate still has to appear in the
# GAUL response under one of these spellings before it resolves.
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
    """A district candidate successfully matched to a real GAUL feature."""

    requested_name: str
    gaul_name: str
    adm1_name: str
    adm0_name: str
    adm2_code: int
    match_kind: str  # "exact" | "alias" | "fuzzy"
    match_score: float

    @property
    def is_exact(self) -> bool:
        return self.match_kind == "exact"


@dataclass(frozen=True)
class DistrictResolution:
    """Outcome of resolving every candidate against the live GAUL collection."""

    resolved: tuple[ResolvedDistrict, ...]
    unresolved: tuple[str, ...]
    available_names: tuple[str, ...]
    state: str
    country: str

    @property
    def resolved_names(self) -> tuple[str, ...]:
        return tuple(d.gaul_name for d in self.resolved)

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
                }
                for d in self.resolved
            ],
            "unresolved": list(self.unresolved),
            "available_count": len(self.available_names),
        }


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
    """Return every ADM2 feature's descriptive properties for a state.

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


def resolve_districts(
    candidates: list[str] | tuple[str, ...] | None = None,
    state: str | None = None,
    country: str | None = None,
) -> DistrictResolution:
    """Match candidate district names against the live GAUL ADM2 name list.

    Each candidate is resolved by exact key, then by known transliteration
    alias, then by fuzzy ratio above ``FUZZY_MATCH_THRESHOLD``. Anything still
    unmatched is returned in ``unresolved`` -- callers must skip those districts
    and surface them, never fall back to a nearby polygon.
    """
    candidates = tuple(candidates or config.CANDIDATE_DISTRICTS)
    state = state or config.STATE_NAME
    country = country or config.COUNTRY_NAME

    available = fetch_state_districts(state, country)
    by_key: dict[str, dict] = {normalise(d["adm2_name"]): d for d in available}
    available_keys = list(by_key)

    resolved: list[ResolvedDistrict] = []
    unresolved: list[str] = []

    for candidate in candidates:
        match: dict | None = None
        kind = ""
        score = 0.0

        for idx, key in enumerate(_candidate_keys(candidate)):
            if key in by_key:
                match = by_key[key]
                kind = "exact" if idx == 0 else "alias"
                score = 1.0
                break

        if match is None:
            close = difflib.get_close_matches(
                normalise(candidate), available_keys, n=1, cutoff=FUZZY_MATCH_THRESHOLD
            )
            if close:
                score = difflib.SequenceMatcher(
                    None, normalise(candidate), close[0]
                ).ratio()
                match, kind = by_key[close[0]], "fuzzy"

        if match is None:
            logger.warning(
                "District %r has no GAUL ADM2 counterpart in %s; it will be skipped.",
                candidate,
                state,
            )
            unresolved.append(candidate)
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
    """Return the ``ee.Geometry`` for a resolved district, selected by code.

    Selection is by ``ADM2_CODE`` rather than name so that the geometry cannot
    drift away from the feature the resolver actually validated.
    """
    initialize()
    import ee

    return ee.FeatureCollection(config.GAUL_LEVEL2).filter(
        ee.Filter.eq("ADM2_CODE", district.adm2_code)
    ).geometry()


def main(argv: list[str] | None = None) -> int:
    """CLI: print the resolution report so an operator can audit the mapping."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Resolve districts against FAO/GAUL/2015/level2"
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

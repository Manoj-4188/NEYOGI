"""District resolution against GAUL, with the geoBoundaries fallback.

Both live lookups are replaced with fixtures that mimic the real datasets —
including the fact that GAUL's 2015 snapshot genuinely lacks Chikkaballapura
and Ramanagara, which were created in 2007. What is under test is the matching
and fallback policy, not Earth Engine.
"""

from __future__ import annotations

import pytest

from ml_pipeline import gee_districts as gd

# Names as GAUL spells them, which is not how Karnataka spells them today.
# Chikkaballapura and Ramanagara are absent, exactly as in the real dataset.
FAKE_GAUL_DISTRICTS = (
    {"adm2_name": "Kolar", "adm2_code": 17690, "adm1_name": "Karnataka"},
    {"adm2_name": "Bangalore Rural", "adm2_code": 70158, "adm1_name": "Karnataka"},
    {"adm2_name": "Tumkur", "adm2_code": 17695, "adm1_name": "Karnataka"},
    {"adm2_name": "Hassan", "adm2_code": 17688, "adm1_name": "Karnataka"},
    {"adm2_name": "Mandya", "adm2_code": 17691, "adm1_name": "Karnataka"},
    {"adm2_name": "Chikmagalur", "adm2_code": 17683, "adm1_name": "Karnataka"},
    # GAUL uses the pre-rename spellings for these two as well.
    {"adm2_name": "Mysore", "adm2_code": 17692, "adm1_name": "Karnataka"},
    {"adm2_name": "Belgaum", "adm2_code": 17681, "adm1_name": "Karnataka"},
)

# geoBoundaries is current enough to carry the two post-2007 districts.
FAKE_GEOBOUNDARIES = (
    {"adm2_name": "Chikkaballapura", "adm1_name": "Karnataka"},
    {"adm2_name": "Ramanagara", "adm1_name": "Karnataka"},
    {"adm2_name": "Kolar", "adm1_name": "Karnataka"},
    {"adm2_name": "Bangalore Rural", "adm1_name": "Karnataka"},
)


@pytest.fixture
def fake_sources(monkeypatch):
    """Both boundary datasets available."""
    monkeypatch.setattr(gd, "fetch_state_districts", lambda s, c: FAKE_GAUL_DISTRICTS)
    monkeypatch.setattr(gd, "fetch_fallback_districts", lambda s, c: FAKE_GEOBOUNDARIES)
    return FAKE_GAUL_DISTRICTS


@pytest.fixture
def gaul_only(monkeypatch):
    """GAUL available, fallback unreachable (its documented degraded mode)."""
    monkeypatch.setattr(gd, "fetch_state_districts", lambda s, c: FAKE_GAUL_DISTRICTS)
    monkeypatch.setattr(gd, "fetch_fallback_districts", lambda s, c: ())
    return FAKE_GAUL_DISTRICTS


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Kolar", "kolar"),
        ("  KOLAR  ", "kolar"),
        ("Bengaluru Rural", "bengaluru rural"),
        ("Bengaluru-Rural", "bengaluru rural"),
        ("Chikkaballapur.", "chikkaballapur"),
        ("Tumakuru\t", "tumakuru"),
    ],
)
def test_normalise_folds_case_punctuation_and_space(raw: str, expected: str) -> None:
    assert gd.normalise(raw) == expected


def test_normalise_strips_diacritics() -> None:
    assert gd.normalise("Bengalūru Rural") == "bengaluru rural"


# --------------------------------------------------------------------------
# Primary source
# --------------------------------------------------------------------------


def test_exact_name_resolves_as_exact(fake_sources) -> None:
    resolution = gd.resolve_districts(["Kolar"])
    match = resolution.get("Kolar")
    assert match is not None
    assert match.gaul_name == "Kolar"
    assert match.match_kind == "exact"
    assert match.adm2_code == 17690
    assert match.source == gd.SOURCE_GAUL
    assert not resolution.unresolved


def test_modern_name_resolves_to_legacy_gaul_spelling_via_alias(fake_sources) -> None:
    """GAUL still says "Bangalore Rural", "Tumkur", "Chikmagalur"."""
    resolution = gd.resolve_districts(["Bengaluru Rural", "Tumakuru", "Chikkamagaluru"])
    assert resolution.get("Bengaluru Rural").gaul_name == "Bangalore Rural"
    assert resolution.get("Tumakuru").gaul_name == "Tumkur"
    assert resolution.get("Chikkamagaluru").gaul_name == "Chikmagalur"
    for name in ("Bengaluru Rural", "Tumakuru", "Chikkamagaluru"):
        assert resolution.get(name).match_kind == "alias"
        assert resolution.get(name).source == gd.SOURCE_GAUL
    assert not resolution.unresolved


def test_close_misspelling_resolves_as_fuzzy(fake_sources) -> None:
    resolution = gd.resolve_districts(["Mandyaa"])
    match = resolution.get("Mandyaa")
    assert match is not None
    assert match.gaul_name == "Mandya"
    assert match.match_kind == "fuzzy"
    assert match.match_score >= gd.FUZZY_MATCH_THRESHOLD


# --------------------------------------------------------------------------
# Fallback source -- the 2007 district reorganisation
# --------------------------------------------------------------------------


def test_post_2007_districts_resolve_via_the_fallback(fake_sources) -> None:
    """GAUL 2015 predates both; geoBoundaries carries them."""
    resolution = gd.resolve_districts(["Chikkaballapur", "Ramanagara"])
    assert not resolution.unresolved

    chikka = resolution.get("Chikkaballapur")
    assert chikka is not None
    assert chikka.gaul_name == "Chikkaballapura"
    assert chikka.source == gd.SOURCE_GEOBOUNDARIES
    assert chikka.is_fallback_source

    rama = resolution.get("Ramanagara")
    assert rama is not None
    assert rama.gaul_name == "Ramanagara"
    assert rama.source == gd.SOURCE_GEOBOUNDARIES


def test_fallback_districts_carry_no_gaul_code(fake_sources) -> None:
    """geoBoundaries has no ADM2_CODE; -1 marks that, and db stores NULL."""
    resolution = gd.resolve_districts(["Chikkaballapur"])
    assert resolution.get("Chikkaballapur").adm2_code == -1


def test_fallback_records_the_key_needed_to_reselect_the_geometry(fake_sources) -> None:
    """geoBoundaries is selected by shapeName, so that name must be stored."""
    match = gd.resolve_districts(["Ramanagara"]).get("Ramanagara")
    assert match.source_key == "Ramanagara"


def test_gaul_is_preferred_when_both_sources_have_the_district(fake_sources) -> None:
    """Kolar exists in both fixtures; the primary source must win."""
    match = gd.resolve_districts(["Kolar"]).get("Kolar")
    assert match.source == gd.SOURCE_GAUL
    assert match.adm2_code == 17690


def test_fallback_names_are_reported_for_audit(fake_sources) -> None:
    resolution = gd.resolve_districts(["Kolar", "Chikkaballapur", "Ramanagara"])
    assert set(resolution.fallback_names) == {"Chikkaballapur", "Ramanagara"}


def test_all_eight_candidate_districts_resolve(fake_sources) -> None:
    from ml_pipeline import config

    resolution = gd.resolve_districts(config.CANDIDATE_DISTRICTS)
    assert not resolution.unresolved
    assert len(resolution.resolved) == len(config.CANDIDATE_DISTRICTS)
    # Real GAUL codes must still be distinct; fallbacks share the -1 sentinel.
    codes = [d.adm2_code for d in resolution.resolved if d.adm2_code > 0]
    assert len(set(codes)) == len(codes)


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_unknown_district_is_reported_not_guessed(fake_sources) -> None:
    """Absent from both sources: skipped, never approximated."""
    resolution = gd.resolve_districts(["Atlantis", "Kolar"])
    assert "Atlantis" in resolution.unresolved
    assert resolution.get("Atlantis") is None
    assert resolution.resolved_names == ("Kolar",)


def test_a_district_from_another_state_does_not_resolve(fake_sources) -> None:
    resolution = gd.resolve_districts(["Coimbatore"])
    assert resolution.unresolved == ("Coimbatore",)
    assert resolution.resolved == ()


def test_unreachable_fallback_degrades_to_unresolved_not_to_an_error(gaul_only) -> None:
    """A missing fallback must not fail the run, only narrow what resolves."""
    resolution = gd.resolve_districts(["Kolar", "Chikkaballapur"])
    assert resolution.resolved_names == ("Kolar",)
    assert resolution.unresolved == ("Chikkaballapur",)


def test_empty_gaul_response_is_an_error_not_an_empty_result(monkeypatch) -> None:
    from ml_pipeline.gee_auth import EarthEngineUnavailable

    def _empty(state: str, country: str):
        raise EarthEngineUnavailable("GAUL returned no ADM2 features")

    monkeypatch.setattr(gd, "fetch_state_districts", _empty)
    with pytest.raises(EarthEngineUnavailable):
        gd.resolve_districts(["Kolar"])


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def test_resolution_dict_is_serialisable_audit_output(fake_sources) -> None:
    import json

    resolution = gd.resolve_districts(["Kolar", "Chikkaballapur", "Atlantis"])
    payload = resolution.to_dict()
    json.dumps(payload)  # must not raise
    assert payload["unresolved"] == ["Atlantis"]
    assert payload["fallback_used"] == ["Chikkaballapur"]
    sources = {r["gaul_name"]: r["source"] for r in payload["resolved"]}
    assert sources["Kolar"] == gd.SOURCE_GAUL
    assert sources["Chikkaballapura"] == gd.SOURCE_GEOBOUNDARIES


def test_get_accepts_either_the_requested_or_the_resolved_name(fake_sources) -> None:
    resolution = gd.resolve_districts(["Bengaluru Rural"])
    assert resolution.get("Bengaluru Rural") is not None
    assert resolution.get("Bangalore Rural") is not None

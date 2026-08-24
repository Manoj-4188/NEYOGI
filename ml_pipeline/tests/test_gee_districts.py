"""District resolution against the GAUL ADM2 name list.

The live Earth Engine lookup is replaced with a fixture that mimics the real
FAO/GAUL/2015/level2 spellings for Karnataka -- including the older
transliterations GAUL actually carries ("Bangalore Rural", "Tumkur",
"Chikmagalur"). What is under test is the matching policy, not Earth Engine.
"""

from __future__ import annotations

import pytest

from ml_pipeline import gee_districts as gd

# Names as GAUL spells them, which is not how Karnataka spells them today.
FAKE_GAUL_DISTRICTS = (
    {"adm2_name": "Kolar", "adm2_code": 10001, "adm1_name": "Karnataka"},
    {"adm2_name": "Chikballapur", "adm2_code": 10002, "adm1_name": "Karnataka"},
    {"adm2_name": "Bangalore Rural", "adm2_code": 10003, "adm1_name": "Karnataka"},
    {"adm2_name": "Ramanagara", "adm2_code": 10004, "adm1_name": "Karnataka"},
    {"adm2_name": "Tumkur", "adm2_code": 10005, "adm1_name": "Karnataka"},
    {"adm2_name": "Hassan", "adm2_code": 10006, "adm1_name": "Karnataka"},
    {"adm2_name": "Mandya", "adm2_code": 10007, "adm1_name": "Karnataka"},
    {"adm2_name": "Chikmagalur", "adm2_code": 10008, "adm1_name": "Karnataka"},
    {"adm2_name": "Mysore", "adm2_code": 10009, "adm1_name": "Karnataka"},
)


@pytest.fixture
def fake_gaul(monkeypatch):
    def _fetch(state: str, country: str):
        assert state and country
        return FAKE_GAUL_DISTRICTS

    monkeypatch.setattr(gd, "fetch_state_districts", _fetch)
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
# Resolution policy
# --------------------------------------------------------------------------


def test_exact_name_resolves_as_exact(fake_gaul) -> None:
    resolution = gd.resolve_districts(["Kolar"])
    match = resolution.get("Kolar")
    assert match is not None
    assert match.gaul_name == "Kolar"
    assert match.match_kind == "exact"
    assert match.adm2_code == 10001
    assert not resolution.unresolved


def test_modern_name_resolves_to_legacy_gaul_spelling_via_alias(fake_gaul) -> None:
    """The whole reason this module exists: GAUL still says "Bangalore Rural"."""
    resolution = gd.resolve_districts(["Bengaluru Rural", "Tumakuru", "Chikkamagaluru"])
    assert resolution.get("Bengaluru Rural").gaul_name == "Bangalore Rural"
    assert resolution.get("Tumakuru").gaul_name == "Tumkur"
    assert resolution.get("Chikkamagaluru").gaul_name == "Chikmagalur"
    for name in ("Bengaluru Rural", "Tumakuru", "Chikkamagaluru"):
        assert resolution.get(name).match_kind == "alias"
    assert not resolution.unresolved


def test_all_eight_candidate_districts_resolve(fake_gaul) -> None:
    from ml_pipeline import config

    resolution = gd.resolve_districts(config.CANDIDATE_DISTRICTS)
    assert not resolution.unresolved
    assert len(resolution.resolved) == len(config.CANDIDATE_DISTRICTS)
    # Codes must be distinct: no two candidates may collapse onto one polygon.
    codes = [d.adm2_code for d in resolution.resolved]
    assert len(set(codes)) == len(codes)


def test_close_misspelling_resolves_as_fuzzy(fake_gaul) -> None:
    resolution = gd.resolve_districts(["Ramanagar"])
    match = resolution.get("Ramanagar")
    assert match is not None
    assert match.gaul_name == "Ramanagara"
    assert match.match_kind == "fuzzy"
    assert match.match_score >= gd.FUZZY_MATCH_THRESHOLD


def test_unknown_district_is_reported_not_guessed(fake_gaul) -> None:
    """A district GAUL does not carry must be skipped, never approximated."""
    resolution = gd.resolve_districts(["Atlantis", "Kolar"])
    assert "Atlantis" in resolution.unresolved
    assert resolution.get("Atlantis") is None
    assert resolution.resolved_names == ("Kolar",)


def test_a_district_from_another_state_does_not_resolve(fake_gaul) -> None:
    resolution = gd.resolve_districts(["Coimbatore"])
    assert resolution.unresolved == ("Coimbatore",)
    assert resolution.resolved == ()


def test_resolution_dict_is_serialisable_audit_output(fake_gaul) -> None:
    import json

    resolution = gd.resolve_districts(["Kolar", "Bengaluru Rural", "Atlantis"])
    payload = resolution.to_dict()
    json.dumps(payload)  # must not raise
    assert payload["unresolved"] == ["Atlantis"]
    assert {r["gaul_name"] for r in payload["resolved"]} == {"Kolar", "Bangalore Rural"}
    assert payload["available_count"] == len(FAKE_GAUL_DISTRICTS)


def test_get_accepts_either_the_requested_or_the_gaul_name(fake_gaul) -> None:
    resolution = gd.resolve_districts(["Bengaluru Rural"])
    assert resolution.get("Bengaluru Rural") is not None
    assert resolution.get("Bangalore Rural") is not None


def test_empty_gaul_response_is_an_error_not_an_empty_result(monkeypatch) -> None:
    from ml_pipeline.gee_auth import EarthEngineUnavailable

    def _empty(state: str, country: str):
        raise EarthEngineUnavailable("GAUL returned no ADM2 features")

    monkeypatch.setattr(gd, "fetch_state_districts", _empty)
    with pytest.raises(EarthEngineUnavailable):
        gd.resolve_districts(["Kolar"])

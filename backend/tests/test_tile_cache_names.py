"""District spelling variants in the tile cache lookup.

Tiles are stored under the GAUL boundary dataset's spelling while the UI asks
by the district's current name. Four of eight districts had no fallback tile
because of that difference alone, which presented as missing imagery.
"""

from __future__ import annotations

from backend.services.satellite import _name_variants


def test_current_name_matches_the_gaul_spelling() -> None:
    assert "tumkur" in _name_variants("Tumakuru")
    assert "mysore" in _name_variants("Mysuru")
    assert "belgaum" in _name_variants("Belagavi")
    assert "bangalore rural" in _name_variants("Bengaluru Rural")
    assert "chikkaballapura" in _name_variants("Chikkaballapur")


def test_lookup_works_from_the_gaul_spelling_too() -> None:
    """The cache may be queried with either name, so the map runs both ways."""
    assert "tumakuru" in _name_variants("Tumkur")
    assert "mysuru" in _name_variants("Mysore")
    assert "belagavi" in _name_variants("Belgaum")


def test_the_name_itself_is_always_included() -> None:
    assert "kolar" in _name_variants("Kolar")
    assert "hassan" in _name_variants("Hassan")


def test_an_unknown_district_still_returns_its_own_name() -> None:
    assert _name_variants("Nowhere") == ["nowhere"]


def test_variants_are_lower_cased_for_a_case_insensitive_match() -> None:
    assert all(v == v.lower() for v in _name_variants("Bengaluru Rural"))

"""Supply estimation: the arithmetic, and the refusals.

The refusal tests matter as much as the arithmetic ones. A yield constant that
nobody has verified must produce a status, not a number.
"""

from __future__ import annotations

from datetime import date

import pytest

from ml_pipeline import supply_estimation as se

VERIFIED_DOC = {
    "schema_version": 1,
    "defaults": {
        "Tomato": {
            "value_mt_ha": 24.0,
            "verified": True,
            "source": "Test fixture",
            "source_url": "https://example.invalid/fixture",
            "reference_year": 2023,
        },
        "Onion": {
            "value_mt_ha": None,
            "verified": False,
            "source": "",
            "source_url": "",
            "reference_year": None,
        },
        "Fallow/Non-Crop": {
            "value_mt_ha": 0.0,
            "verified": True,
            "source": "Definitional",
            "source_url": "",
            "reference_year": None,
        },
    },
    "districts": {
        "Kolar": {
            "Tomato": {
                "value_mt_ha": 31.5,
                "verified": True,
                "source": "Test fixture (district override)",
                "source_url": "https://example.invalid/kolar",
                "reference_year": 2023,
            }
        },
        "Hassan": {},
    },
}


# --------------------------------------------------------------------------
# Deterministic arithmetic
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("area_ha", "yield_mt_ha", "expected_mt"),
    [
        (100.0, 24.0, 2400.0),
        (0.0, 24.0, 0.0),
        (12.5, 31.5, 393.75),
        (1.0, 0.0, 0.0),
    ],
)
def test_projected_volume_is_area_times_yield(area_ha, yield_mt_ha, expected_mt) -> None:
    assert se.projected_volume_mt(area_ha, yield_mt_ha) == pytest.approx(expected_mt)


def test_projected_volume_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        se.projected_volume_mt(-1.0, 24.0)
    with pytest.raises(ValueError):
        se.projected_volume_mt(1.0, -24.0)


@pytest.mark.parametrize(
    ("projected", "arrivals", "expected"),
    [
        (2400.0, 1200.0, 2.0),
        (600.0, 1200.0, 0.5),
        (1000.0, 1000.0, 1.0),
    ],
)
def test_oversupply_ratio(projected, arrivals, expected) -> None:
    assert se.oversupply_ratio(projected, arrivals) == pytest.approx(expected)


def test_oversupply_ratio_is_undefined_without_arrivals() -> None:
    """Zero arrivals means "not published", not "infinite oversupply"."""
    assert se.oversupply_ratio(2400.0, None) is None
    assert se.oversupply_ratio(2400.0, 0.0) is None
    assert se.oversupply_ratio(2400.0, -5.0) is None


def test_quintals_convert_to_tonnes() -> None:
    assert se.quintals_to_tonnes(1000.0) == pytest.approx(100.0)
    assert se.quintals_to_tonnes(None) is None


# --------------------------------------------------------------------------
# Baseline resolution
# --------------------------------------------------------------------------


def test_district_override_beats_the_default() -> None:
    baseline = se.get_yield_baseline("Tomato", district="Kolar", document=VERIFIED_DOC)
    assert baseline.value_mt_ha == pytest.approx(31.5)
    assert baseline.scope == "district"


def test_default_applies_when_district_has_no_override() -> None:
    baseline = se.get_yield_baseline("Tomato", district="Hassan", document=VERIFIED_DOC)
    assert baseline.value_mt_ha == pytest.approx(24.0)
    assert baseline.scope == "default"


def test_unverified_baseline_raises_rather_than_returning_a_number() -> None:
    with pytest.raises(se.YieldBaselineUnavailable, match="Onion"):
        se.get_yield_baseline("Onion", district="Kolar", document=VERIFIED_DOC)


def test_unknown_crop_raises() -> None:
    with pytest.raises(se.YieldBaselineUnavailable):
        se.get_yield_baseline("Dragonfruit", document=VERIFIED_DOC)


def test_a_value_present_but_flagged_unverified_is_still_refused() -> None:
    """`verified: false` overrides a populated number -- reviewer gate, not a typo check."""
    doc = {
        "defaults": {
            "Potato": {"value_mt_ha": 22.0, "verified": False, "source": "draft"}
        }
    }
    with pytest.raises(se.YieldBaselineUnavailable):
        se.get_yield_baseline("Potato", document=doc)


def test_non_numeric_baseline_is_treated_as_unverified() -> None:
    doc = {"defaults": {"Potato": {"value_mt_ha": "about twenty", "verified": True}}}
    with pytest.raises(se.YieldBaselineUnavailable):
        se.get_yield_baseline("Potato", document=doc)


# --------------------------------------------------------------------------
# The file that actually ships
# --------------------------------------------------------------------------


def test_shipped_baseline_file_parses() -> None:
    document = se.load_baseline_document()
    assert document["schema_version"] == 1
    assert "defaults" in document and "districts" in document


def test_shipped_file_ships_unverified_so_volumes_are_withheld() -> None:
    """The repository must not carry invented yield constants."""
    document = se.load_baseline_document()
    for crop in ("Tomato", "Onion", "Potato", "Leafy Greens"):
        with pytest.raises(se.YieldBaselineUnavailable):
            se.get_yield_baseline(crop, document=document)


def test_fallow_is_the_only_verified_entry_and_it_is_zero() -> None:
    document = se.load_baseline_document()
    baseline = se.get_yield_baseline("Fallow/Non-Crop", document=document)
    assert baseline.value_mt_ha == 0.0


def test_baseline_coverage_reports_the_gap() -> None:
    coverage = se.baseline_coverage(VERIFIED_DOC)
    assert "Tomato" in coverage["verified"]
    assert "Onion" in coverage["unverified"]
    assert coverage["districts"]["Kolar"] == ["Tomato"]


# --------------------------------------------------------------------------
# Estimate assembly and statuses
# --------------------------------------------------------------------------

WINDOW = (date(2024, 6, 1), date(2024, 6, 22))


def _estimate(crop: str, area: float, arrivals: float | None, district: str = "Kolar"):
    return se.estimate_crop_supply(
        district=district,
        crop=crop,
        classified_area_ha=area,
        parcel_count=10,
        observed_arrivals_mt=arrivals,
        window_start=WINDOW[0],
        window_end=WINDOW[1],
        document=VERIFIED_DOC,
    )


def test_full_path_reports_ok_with_volume_and_ratio() -> None:
    estimate = _estimate("Tomato", area=100.0, arrivals=1575.0)
    assert estimate.status == "OK"
    # 100 ha x 31.5 MT/ha (Kolar override) = 3150 MT; 3150/1575 = 2.0
    assert estimate.projected_volume_mt == pytest.approx(3150.0)
    assert estimate.oversupply_ratio == pytest.approx(2.0)
    assert estimate.yield_baseline.scope == "district"


def test_missing_yield_withholds_volume_but_keeps_measured_area() -> None:
    estimate = _estimate("Onion", area=42.0, arrivals=500.0)
    assert estimate.status == "YIELD_BASELINE_UNAVAILABLE"
    assert estimate.projected_volume_mt is None
    assert estimate.oversupply_ratio is None
    # Area is measured, so it is still reported.
    assert estimate.classified_area_ha == pytest.approx(42.0)


def test_missing_arrivals_keeps_volume_but_withholds_the_ratio() -> None:
    estimate = _estimate("Tomato", area=100.0, arrivals=None)
    assert estimate.status == "INSUFFICIENT_ARRIVAL_DATA"
    assert estimate.projected_volume_mt == pytest.approx(3150.0)
    assert estimate.oversupply_ratio is None


def test_no_classified_area_is_its_own_status() -> None:
    estimate = _estimate("Tomato", area=0.0, arrivals=1000.0)
    assert estimate.status == "NO_CLASSIFIED_AREA"
    assert estimate.projected_volume_mt is None


def test_every_estimate_serialises_to_json() -> None:
    import json

    for estimate in (
        _estimate("Tomato", 100.0, 1575.0),
        _estimate("Onion", 42.0, 500.0),
        _estimate("Tomato", 100.0, None),
        _estimate("Tomato", 0.0, 10.0),
    ):
        json.dumps(estimate.to_dict())


# --------------------------------------------------------------------------
# District forecast
# --------------------------------------------------------------------------


def test_forecast_excludes_fallow_from_marketable_supply() -> None:
    forecast = se.forecast_district(
        "Kolar",
        area_by_crop={"Tomato": 100.0, "Fallow/Non-Crop": 500.0},
        arrivals_by_crop={"Tomato": 1575.0},
        as_of=WINDOW[1],
        document=VERIFIED_DOC,
    )
    assert [c.crop for c in forecast.crops] == ["Tomato"]


def test_forecast_notes_explain_each_withheld_number() -> None:
    forecast = se.forecast_district(
        "Kolar",
        area_by_crop={"Tomato": 100.0, "Onion": 40.0},
        arrivals_by_crop={"Onion": 200.0},  # Tomato arrivals absent
        as_of=WINDOW[1],
        document=VERIFIED_DOC,
    )
    joined = " ".join(forecast.notes)
    assert "Onion" in joined and "baseline yield" in joined
    assert "Tomato" in joined and "arrival" in joined


def test_forecast_on_unvalidated_district_returns_a_note_not_an_empty_success() -> None:
    forecast = se.forecast_district(
        "Chikkaballapur", area_by_crop={}, as_of=WINDOW[1], document=VERIFIED_DOC
    )
    assert forecast.crops == []
    assert forecast.notes
    assert "unvalidated" in forecast.notes[0].lower()


def test_forecast_window_spans_the_requested_days() -> None:
    forecast = se.forecast_district(
        "Kolar",
        area_by_crop={"Tomato": 1.0},
        window_days=21,
        as_of=date(2024, 6, 22),
        document=VERIFIED_DOC,
    )
    assert forecast.window_start == date(2024, 6, 1)
    assert forecast.window_end == date(2024, 6, 22)
    assert (forecast.window_end - forecast.window_start).days == 21

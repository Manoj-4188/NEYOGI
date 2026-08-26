"""Supply estimation: the arithmetic, and the refusals.

The refusal tests matter as much as the arithmetic ones. A yield constant that
nobody has verified must produce a status, not a number.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ml_pipeline import supply_estimation as se

VERIFIED_DOC = {
    "schema_version": 3,
    "defaults": {
        "Tomato": {
            "value_mt_ha": 24.0,
            "verified": True,
            "source": "Test fixture",
            "source_url": "https://example.invalid/fixture",
            "reference_year": 2023,
            "harvest_spread_weeks": 8.0,
            "harvest_spread_verified": True,
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
                "harvest_spread_weeks": 8.0,
                "harvest_spread_verified": True,
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
    assert document["schema_version"] == 3
    assert "defaults" in document and "districts" in document


def test_shipped_constants_are_verified_and_cited() -> None:
    """Operator-supplied constants are in force, and each names its source.

    This file previously shipped every value unverified. It now carries the
    Karnataka Horticulture Department figures the operator supplied, so the
    guarantee under test changes: a constant may be in force, but only with a
    citation attached. An unsourced number is the thing that must not exist.
    """
    document = se.load_baseline_document()
    for crop in ("Tomato", "Onion", "Potato", "Leafy Greens"):
        baseline = se.get_yield_baseline(crop, document=document)
        assert baseline.value_mt_ha > 0, crop
        assert baseline.source.strip(), f"{crop} has no cited source"
        assert baseline.reference_year, f"{crop} has no reference year"


def test_an_unverified_entry_is_still_refused() -> None:
    """The verification gate itself must keep working."""
    doc = {
        "defaults": {
            "Tomato": {"value_mt_ha": 25.0, "verified": False, "source": "draft"}
        }
    }
    with pytest.raises(se.YieldBaselineUnavailable):
        se.get_yield_baseline("Tomato", document=doc)


def test_shipped_absorption_is_district_scoped_not_crop_scoped() -> None:
    """Market throughput belongs to a mandi, so no crop-level default exists.

    A single state-wide absorption figure would be wrong nearly everywhere it
    applied -- Kolar clears roughly forty times the tomato of a district with
    no major yard -- so a district without a sourced figure must withhold the
    ratio rather than borrow one.
    """
    document = se.load_baseline_document()
    for crop in ("Tomato", "Onion", "Potato", "Leafy Greens"):
        default = se.get_yield_baseline(crop, document=document)
        assert default.absorption_t_per_week is None, crop

    kolar = se.get_yield_baseline("Tomato", district="Kolar", document=document)
    assert kolar.absorption_t_per_week == pytest.approx(19231.0)
    assert kolar.scope == "district"


def test_shipped_harvest_spreads_are_verified() -> None:
    """Without a spread the ratio compares a stock against a flow."""
    document = se.load_baseline_document()
    for crop, weeks in (
        ("Tomato", 8.0),
        ("Onion", 3.0),
        ("Potato", 3.0),
        ("Leafy Greens", 2.0),
    ):
        baseline = se.get_yield_baseline(crop, document=document)
        assert baseline.harvest_spread_weeks == pytest.approx(weeks), crop


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
    # 100 ha x 31.5 MT/ha (Kolar override) = 3,150 MT of harvest, which over
    # an 8-week spread arrives at 393.75 MT/week. The 1,575 MT observed over
    # the 21-day window is 525 MT/week. Both sides are flows: 393.75 / 525.
    assert estimate.projected_volume_mt == pytest.approx(3150.0)
    assert estimate.weekly_arrival_mt == pytest.approx(393.75)
    assert estimate.weekly_absorption_mt == pytest.approx(525.0)
    assert estimate.oversupply_ratio == pytest.approx(0.75)
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


# --------------------------------------------------------------------------
# Plausibility guard
# --------------------------------------------------------------------------

ABSORPTION_DOC = {
    "schema_version": 3,
    "defaults": {
        "Tomato": {
            "value_mt_ha": 25.0,
            "verified": True,
            "source": "Test fixture",
            "reference_year": 2023,
            # No crop-level absorption: it belongs to a district's mandi.
            "absorption_t_per_week": None,
            "absorption_verified": False,
            "harvest_spread_weeks": 8.0,
            "harvest_spread_verified": True,
        },
    },
    "districts": {
        "Kolar": {
            "Tomato": {
                "value_mt_ha": 25.0,
                "verified": True,
                "source": "Test fixture",
                "reference_year": 2023,
                "absorption_t_per_week": 19231.0,
                "absorption_verified": True,
                "harvest_spread_weeks": 8.0,
                "harvest_spread_verified": True,
            }
        },
        # A district with a yield but no sourced market throughput.
        "Hassan": {},
    },
}


def _est(area_ha, arrivals=None, days=21, district="Kolar"):
    return se.estimate_crop_supply(
        district=district,
        crop="Tomato",
        classified_area_ha=area_ha,
        parcel_count=1,
        observed_arrivals_mt=arrivals,
        window_start=date(2024, 6, 1),
        window_end=date(2024, 6, 1) + timedelta(days=days),
        document=ABSORPTION_DOC,
    )


# --------------------------------------------------------------------------
# Flow-to-flow comparison
# --------------------------------------------------------------------------


def test_projected_volume_is_converted_to_a_weekly_arrival_rate() -> None:
    """A whole harvest divided by its spread is what actually reaches market."""
    # 1,000 ha x 25 = 25,000 MT over 8 weeks -> 3,125 MT/week.
    e = _est(1_000.0)
    assert e.projected_volume_mt == pytest.approx(25_000.0)
    assert e.weekly_arrival_mt == pytest.approx(3_125.0)


def test_district_absorption_backs_the_ratio_when_arrivals_are_absent() -> None:
    e = _est(1_000.0)
    assert e.status == "OK_DISTRICT_ABSORPTION"
    assert e.demand_basis == "district_absorption"
    assert e.weekly_absorption_mt == pytest.approx(19_231.0)
    assert e.oversupply_ratio == pytest.approx(3_125.0 / 19_231.0, rel=1e-6)


def test_observed_arrivals_take_precedence_and_are_rated_weekly() -> None:
    """A measurement beats the reference figure, converted to matching units."""
    # 21 days is 3 weeks, so 30,000 MT observed is 10,000 MT/week.
    e = _est(1_000.0, arrivals=30_000.0)
    assert e.status == "OK"
    assert e.demand_basis == "observed_arrivals"
    assert e.weekly_absorption_mt == pytest.approx(10_000.0)
    assert e.oversupply_ratio == pytest.approx(3_125.0 / 10_000.0, rel=1e-6)


def test_a_district_without_sourced_absorption_withholds_the_ratio() -> None:
    """No crop-level default is borrowed for a district that has no figure."""
    e = _est(1_000.0, district="Hassan")
    assert e.status == "INSUFFICIENT_ARRIVAL_DATA"
    assert e.oversupply_ratio is None
    # The measured area and its tonnage still stand.
    assert e.projected_volume_mt == pytest.approx(25_000.0)


def test_missing_harvest_spread_blocks_the_ratio() -> None:
    """Without a spread a stock cannot honestly meet a flow."""
    doc = {
        "defaults": {
            "Tomato": {
                "value_mt_ha": 25.0,
                "verified": True,
                "source": "fixture",
                "absorption_t_per_week": 19231.0,
                "absorption_verified": True,
                "harvest_spread_weeks": 8.0,
                "harvest_spread_verified": False,  # not yet sourced
            }
        },
        "districts": {},
    }
    e = se.estimate_crop_supply(
        district="Kolar",
        crop="Tomato",
        classified_area_ha=1_000.0,
        parcel_count=1,
        observed_arrivals_mt=None,
        window_start=date(2024, 6, 1),
        window_end=date(2024, 6, 22),
        document=doc,
    )
    assert e.status == "HARVEST_SPREAD_UNKNOWN"
    assert e.oversupply_ratio is None


# --------------------------------------------------------------------------
# Plausibility guard
# --------------------------------------------------------------------------


def test_the_ratio_bound_catches_a_wildly_wrong_numerator() -> None:
    """Anything past the bound is a modelling error, not a market condition."""
    # 500,000 ha x 25 / 8 weeks = 1.56M MT/week against 19,231 -> ~81x.
    e = _est(500_000.0)
    assert e.status == "IMPLAUSIBLE_RATIO"
    assert e.oversupply_ratio is None
    # The measured area survives; only the derived ratio is withheld.
    assert e.classified_area_ha == pytest.approx(500_000.0)
    assert "withheld" in e.detail


def test_a_moderately_wrong_area_slips_past_the_ratio_bound() -> None:
    """Documents why the ratio bound is not the only defence needed.

    78,334 ha was what the spectral model actually assigned to tomato in
    Kolar -- 20% of the district, and more than Karnataka's entire tomato
    area. Under the flow model that produces about 12.7x, which is extreme
    but not absurd enough for the ratio bound to reject.

    So the bound alone would let a badly wrong area through wearing a
    plausible number. What stops it is the confidence floor in
    backend.services.supply, which bars a class from feeding a tonnage claim
    at all when the classifier is barely better than chance -- and that area
    carried a mean confidence of 0.43 against a 0.25 chance baseline.
    """
    e = _est(78_334.0)
    assert e.status == "OK_DISTRICT_ABSORPTION"
    assert 10 < e.oversupply_ratio < 20
    from backend.services.supply import MIN_AREA_CONFIDENCE

    assert MIN_AREA_CONFIDENCE > 0.43


def test_a_genuine_glut_still_reports_normally() -> None:
    """The guard must not swallow the signal the platform exists to give."""
    # 15,000 ha x 25 / 8 weeks = 46,875 MT/week against 19,231 -> 2.44x.
    e = _est(15_000.0)
    assert e.status == "OK_DISTRICT_ABSORPTION"
    assert e.oversupply_ratio == pytest.approx(2.437, rel=1e-2)


def test_a_balanced_market_reports_near_one() -> None:
    # 6,154 ha x 25 / 8 weeks is about 19,231 MT/week, matching absorption.
    e = _est(6_154.0)
    assert e.oversupply_ratio == pytest.approx(1.0, rel=1e-3)


def test_a_district_override_inherits_what_it_does_not_restate() -> None:
    """An override naming only absorption must keep the default's other fields.

    Kolar's entry states its market throughput and nothing else. If the
    override replaced the default outright it would silently lose the harvest
    spread, and the ratio would be withheld for the one district that has a
    sourced absorption figure -- a gap that looks like missing data but is
    really a merge bug.
    """
    document = se.load_baseline_document()
    kolar = se.get_yield_baseline("Tomato", district="Kolar", document=document)
    assert kolar.scope == "district"
    assert kolar.absorption_t_per_week == pytest.approx(19231.0)
    # Inherited from the crop default, not restated in the override.
    assert kolar.harvest_spread_weeks == pytest.approx(8.0)
    assert kolar.value_mt_ha == pytest.approx(25.0)


def test_kolar_tomato_projects_end_to_end_at_a_realistic_area() -> None:
    """The whole chain, on the one district with a sourced absorption figure."""
    document = se.load_baseline_document()
    e = se.estimate_crop_supply(
        district="Kolar",
        crop="Tomato",
        classified_area_ha=15_000.0,
        parcel_count=0,
        observed_arrivals_mt=None,
        window_start=date(2026, 8, 5),
        window_end=date(2026, 8, 26),
        document=document,
    )
    assert e.status == "OK_DISTRICT_ABSORPTION"
    # 15,000 ha x 25 = 375,000 MT over 8 weeks = 46,875 MT/week.
    assert e.weekly_arrival_mt == pytest.approx(46_875.0)
    assert e.weekly_absorption_mt == pytest.approx(19_231.0)
    assert e.oversupply_ratio == pytest.approx(2.44, rel=1e-2)

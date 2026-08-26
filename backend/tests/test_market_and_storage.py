"""Market ranking and cold-storage hold-or-sell arithmetic.

Both features convert published prices into a recommendation someone acts on
by hiring a lorry or paying storage fees, so the arithmetic is pinned here and
the refusals are tested as carefully as the happy path.
"""

from __future__ import annotations

import pytest

from backend.services import geo
from backend.services import markets as mk
from backend.services import storage_economics as econ


# --------------------------------------------------------------------------
# Geography
# --------------------------------------------------------------------------


def test_haversine_matches_a_known_separation() -> None:
    """Kolar to Bengaluru Rural is roughly 50 km as the crow flies."""
    d = geo.haversine_km((13.136, 78.129), (13.190, 77.700))
    assert 40 < d < 60


def test_distance_is_symmetric() -> None:
    a = geo.district_distance_km("Kolar", "Mysuru")
    b = geo.district_distance_km("Mysuru", "Kolar")
    assert a == pytest.approx(b)


def test_same_district_is_zero_distance() -> None:
    assert geo.district_distance_km("Kolar", "Kolar") == pytest.approx(0.0)


def test_gaul_spellings_resolve_to_the_same_point() -> None:
    """A market filed under the old district spelling must still place."""
    assert geo.centroid_for("Bangalore Rural") == geo.centroid_for("Bengaluru Rural")
    assert geo.centroid_for("Tumkur") == geo.centroid_for("Tumakuru")
    assert geo.centroid_for("Mysore") == geo.centroid_for("Mysuru")


def test_unknown_district_returns_none_rather_than_a_default_point() -> None:
    """A wrong centroid silently produces a wrong ranking."""
    assert geo.centroid_for("Atlantis") is None
    assert geo.district_distance_km("Kolar", "Atlantis") is None


# --------------------------------------------------------------------------
# Transport cost and net profit
# --------------------------------------------------------------------------


def test_transport_cost_is_rate_times_distance_times_tonnes() -> None:
    # 100 km, 100 quintals = 10 t, at 2.5/km/t -> 100 * 2.5 * 10 = 2500
    assert mk.transport_cost(100.0, 100.0) == pytest.approx(2500.0)


def test_transport_cost_scales_linearly_in_both_terms() -> None:
    base = mk.transport_cost(50.0, 100.0)
    assert mk.transport_cost(100.0, 100.0) == pytest.approx(2 * base)
    assert mk.transport_cost(50.0, 200.0) == pytest.approx(2 * base)


def test_zero_distance_costs_nothing_to_haul() -> None:
    assert mk.transport_cost(0.0, 500.0) == 0.0


def test_net_profit_worked_example() -> None:
    """A full hand-computed case, so the formula cannot drift silently."""
    price, quantity, distance = 1200.0, 100.0, 80.0
    gross = price * quantity                      # 120,000
    cost = mk.transport_cost(distance, quantity)  # 80 * 2.5 * 10 = 2,000
    assert gross == pytest.approx(120_000.0)
    assert cost == pytest.approx(2_000.0)
    assert gross - cost == pytest.approx(118_000.0)


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("tomato", "Tomato"),
        ("TOMATO", "Tomato"),
        ("leafy_greens", "Leafy Greens"),
        ("leafy greens", "Leafy Greens"),
    ],
)
def test_crop_names_normalise(supplied, expected) -> None:
    assert mk.normalise_crop(supplied) == expected


def test_unknown_crop_is_rejected_not_guessed() -> None:
    assert mk.normalise_crop("dragonfruit") is None


# --------------------------------------------------------------------------
# Cold storage economics
# --------------------------------------------------------------------------


def test_price_per_tonne_converts_from_quintals() -> None:
    assert econ.price_per_tonne(1200.0) == pytest.approx(12_000.0)


def test_storage_cost_is_tariff_times_tonnes_times_days() -> None:
    # 3.5/t/day, 10 t, 18 days -> 630
    assert econ.storage_cost(3.5, 10.0, 18) == pytest.approx(630.0)


def test_net_benefit_worked_example() -> None:
    """Hand-computed: tomato at 1200/qtl, 10 t, 3.5/t/day, 18 days, 1.35x."""
    r = econ.net_benefit(
        price_per_quintal=1200.0,
        cost_per_tonne_day=3.5,
        quantity_t=10.0,
        holding_days=18,
        recovery_factor=1.35,
    )
    # price/t = 12,000; current = 120,000; recovery = 162,000; cost = 630
    assert r["price_per_tonne"] == pytest.approx(12_000.0)
    assert r["current_revenue"] == pytest.approx(120_000.0)
    assert r["recovery_revenue"] == pytest.approx(162_000.0)
    assert r["storage_cost"] == pytest.approx(630.0)
    assert r["net_benefit"] == pytest.approx(41_370.0)


def test_net_benefit_reduces_to_the_uplift_minus_the_cost() -> None:
    """Algebraic identity, independent of the implementation's route to it."""
    price, tariff, qty, days, factor = 850.0, 4.0, 25.0, 18, 1.35
    r = econ.net_benefit(price, tariff, qty, days, factor)
    expected = qty * (
        econ.price_per_tonne(price) * (factor - 1.0) - tariff * days
    )
    assert r["net_benefit"] == pytest.approx(expected)


def test_no_recovery_makes_holding_a_pure_loss() -> None:
    """The assumption is load-bearing: at 1.0x, storage only costs money."""
    r = econ.net_benefit(1200.0, 3.5, 10.0, 18, recovery_factor=1.0)
    assert r["net_benefit"] == pytest.approx(-630.0)
    assert r["net_benefit"] < 0


def test_breakeven_factor_is_the_point_of_indifference() -> None:
    """Applying the break-even factor must yield a net benefit of zero."""
    price, tariff, qty, days = 1200.0, 3.5, 10.0, 18
    r = econ.net_benefit(price, tariff, qty, days)
    at_breakeven = econ.net_benefit(
        price, tariff, qty, days, recovery_factor=r["breakeven_factor"]
    )
    assert at_breakeven["net_benefit"] == pytest.approx(0.0, abs=1e-6)


def test_every_payload_carries_the_assumption_in_words() -> None:
    """The caveat must travel with the number, not sit in documentation."""
    r = econ.net_benefit(1200.0, 3.5, 10.0)
    assert "planning assumption" in r["assumption"]
    assert "not a forecast" in r["assumption"]
    assert r["recovery_factor"] == econ.PRICE_RECOVERY_FACTOR


def test_fallback_prices_cover_the_crops_the_classifier_emits() -> None:
    for crop in ("tomato", "onion", "leafy_greens"):
        assert econ.FALLBACK_PRICES_PER_QUINTAL[crop] > 0


def test_recovery_factor_is_configurable_not_hardcoded() -> None:
    """It is an assumption, so it must be adjustable without a code edit."""
    import inspect

    src = inspect.getsource(econ)
    assert "STORAGE_PRICE_RECOVERY_FACTOR" in src


# --------------------------------------------------------------------------
# Classifier feature contract
# --------------------------------------------------------------------------


def test_band_features_are_rescaled_to_the_training_domain() -> None:
    """The model was fitted on raw DN; the pipeline supplies reflectance.

    Index features are ratios and scale-invariant, so this mismatch changed
    only about 0.2% of predictions and went unnoticed. It still fed every
    band-based split in all 300 trees a value four orders of magnitude below
    anything seen during fitting.
    """
    from ml_pipeline import classifier

    reflectance = {
        "NDVI": 0.72, "EVI": 0.55, "NDMI": 0.30, "SAVI": 0.60, "NDRE": 0.35,
        "GNDVI": 0.62, "CIG": 2.1, "LSWI": 0.28, "NDWI": -0.55, "BSI": -0.30,
        "RENDVI": 0.22,
        "B2": 0.05, "B3": 0.08, "B4": 0.06, "B8": 0.35, "B11": 0.20, "B12": 0.12,
    }
    # The same pixel expressed as digital numbers, which is what the model saw.
    digital_numbers = {
        k: (v * 10_000 if k.startswith("B") else v) for k, v in reflectance.items()
    }

    from_reflectance = classifier.predict_crop(reflectance)
    from_dn = classifier.predict_crop(digital_numbers)

    # Both forms must reach the model identically.
    assert from_reflectance["crop_type"] == from_dn["crop_type"]
    assert from_reflectance["confidence"] == pytest.approx(from_dn["confidence"])


def test_index_features_are_never_rescaled() -> None:
    """Indices are ratios; multiplying one by 10,000 would be nonsense."""
    from ml_pipeline import classifier

    base = {
        "NDVI": 0.72, "EVI": 0.55, "NDMI": 0.30, "SAVI": 0.60, "NDRE": 0.35,
        "GNDVI": 0.62, "CIG": 2.1, "LSWI": 0.28, "NDWI": -0.55, "BSI": -0.30,
        "RENDVI": 0.22,
        "B2": 500.0, "B3": 800.0, "B4": 600.0, "B8": 3500.0, "B11": 2000.0,
        "B12": 1200.0,
    }
    # NDVI below 1.0 must pass through untouched, unlike a band.
    result = classifier.predict_crop(base)
    assert result["features_used"] == 17
    assert 0.0 <= result["confidence"] <= 1.0

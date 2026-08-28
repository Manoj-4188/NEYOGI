"""Radar index arithmetic.

The decibel conversion shipped wrong once -- written as ``(dB / 10) ** 10``
instead of ``10 ** (dB / 10)`` -- and nothing caught it, because the wrong form
raises no error and returns a positive number for every input. It reached the
database and put an RVI of 3.96 on eleven windows of Kolar's series, which is
above the index's ceiling for any real surface.

These cover the arithmetic directly, which is why the conversion was pulled out
of the Earth Engine call and into a plain function.
"""

from __future__ import annotations

import pytest

from ml_pipeline import sentinel1 as s1


# --------------------------------------------------------------------------
# Decibel conversion
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("db", "expected"),
    [
        (0.0, 1.0),
        (-10.0, 0.1),
        (-20.0, 0.01),
        (-3.0, 0.5011872336),
        (-18.0, 0.0158489319),
    ],
)
def test_decibels_convert_to_linear_power(db: float, expected: float) -> None:
    assert s1.db_to_linear(db) == pytest.approx(expected)


def test_conversion_is_not_the_transposed_form_that_shipped() -> None:
    """The specific bug: exponent and base swapped.

    Both forms return a float, so only the value distinguishes them.
    """
    for db in (-10.0, -12.0, -18.0, -22.0):
        assert s1.db_to_linear(db) != pytest.approx((db / 10.0) ** 10)


def test_more_negative_decibels_mean_less_power() -> None:
    """Ordering the broken form inverted for the bands that matter."""
    assert s1.db_to_linear(-18.0) < s1.db_to_linear(-10.0) < s1.db_to_linear(-6.0)


# --------------------------------------------------------------------------
# RVI
# --------------------------------------------------------------------------


def test_rvi_over_typical_cropland_backscatter() -> None:
    """VV -10 dB, VH -18 dB is an ordinary vegetated field."""
    vv = s1.db_to_linear(-10.0)
    vh = s1.db_to_linear(-18.0)
    assert 0.4 < s1.rvi_from_linear(vv, vh) < 0.7


def test_rvi_stays_below_the_plausible_bound_across_the_real_range() -> None:
    """Sweep the backscatter combinations Sentinel-1 actually returns."""
    for vv_db in range(-20, -4):
        for vh_db in range(-30, -10):
            if vh_db >= vv_db:  # cross-pol is always the weaker return
                continue
            rvi = s1.rvi_from_linear(s1.db_to_linear(vv_db), s1.db_to_linear(vh_db))
            assert 0.0 < rvi < s1.MAX_PLAUSIBLE_RVI


def test_bare_ground_scores_lower_than_dense_canopy() -> None:
    """RVI rises with volume scattering; that ordering is the whole signal."""
    bare = s1.rvi_from_linear(s1.db_to_linear(-8.0), s1.db_to_linear(-22.0))
    canopy = s1.rvi_from_linear(s1.db_to_linear(-8.0), s1.db_to_linear(-13.0))
    assert bare < canopy


def test_the_broken_conversion_produces_the_value_we_stored() -> None:
    """Reproduces the 3.96 that reached the database; the bound catches it."""
    bad = s1.rvi_from_linear((-10.0 / 10.0) ** 10, (-18.0 / 10.0) ** 10)
    assert bad > s1.MAX_PLAUSIBLE_RVI
    assert bad == pytest.approx(3.99, abs=0.02)


def test_zero_total_power_is_an_error_not_an_infinity() -> None:
    with pytest.raises(ValueError):
        s1.rvi_from_linear(0.0, 0.0)


def test_plausible_bound_excludes_vh_exceeding_vv() -> None:
    """RVI reaches 2 only when cross-pol equals co-pol, which does not occur."""
    assert s1.rvi_from_linear(0.1, 0.1) == pytest.approx(2.0)
    assert s1.MAX_PLAUSIBLE_RVI <= 2.0

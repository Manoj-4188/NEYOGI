"""Verify every vegetation index against hand-computed reference matrices.

The expected arrays below are literal decimals worked out by hand from the
published formula for each index -- they are deliberately *not* re-derived in
code, because a test that recomputes the implementation's own expression only
proves the code equals itself.

Reference reflectance block (2x2, surface reflectance in [0, 1])::

    B2  blue      [[0.10, 0.20], [0.05, 0.15]]
    B3  green     [[0.20, 0.30], [0.10, 0.25]]
    B4  red       [[0.10, 0.40], [0.20, 0.30]]
    B5  rededge1  [[0.30, 0.35], [0.25, 0.40]]
    B6  rededge2  [[0.50, 0.45], [0.35, 0.50]]
    B8  nir       [[0.50, 0.60], [0.40, 0.20]]
    B8A nir_n     [[0.55, 0.65], [0.45, 0.25]]
    B11 swir1     [[0.25, 0.15], [0.30, 0.35]]
"""

from __future__ import annotations

import numpy as np
import pytest

from ml_pipeline import feature_engineering as fe

TOLERANCE = {"rtol": 1e-11, "atol": 1e-12}

BANDS: dict[str, np.ndarray] = {
    "B2": np.array([[0.10, 0.20], [0.05, 0.15]]),
    "B3": np.array([[0.20, 0.30], [0.10, 0.25]]),
    "B4": np.array([[0.10, 0.40], [0.20, 0.30]]),
    "B5": np.array([[0.30, 0.35], [0.25, 0.40]]),
    "B6": np.array([[0.50, 0.45], [0.35, 0.50]]),
    "B8": np.array([[0.50, 0.60], [0.40, 0.20]]),
    "B8A": np.array([[0.55, 0.65], [0.45, 0.25]]),
    "B11": np.array([[0.25, 0.15], [0.30, 0.35]]),
}

# Hand-computed expectations, 12 significant digits.
EXPECTED: dict[str, np.ndarray] = {
    "NDVI": np.array(
        [[0.666666666667, 0.200000000000], [0.333333333333, -0.200000000000]]
    ),
    "EVI": np.array(
        [[0.740740740741, 0.200000000000], [0.224719101124, -0.133333333333]]
    ),
    "NDMI": np.array(
        [[0.333333333333, 0.600000000000], [0.142857142857, -0.272727272727]]
    ),
    "SAVI": np.array(
        [[0.545454545455, 0.200000000000], [0.272727272727, -0.150000000000]]
    ),
    "NDRE": np.array(
        [[0.250000000000, 0.263157894737], [0.230769230769, -0.333333333333]]
    ),
    "GNDVI": np.array(
        [[0.428571428571, 0.333333333333], [0.600000000000, -0.111111111111]]
    ),
    "CIG": np.array(
        [[1.500000000000, 1.000000000000], [3.000000000000, -0.200000000000]]
    ),
    "LSWI": np.array(
        [[0.375000000000, 0.625000000000], [0.200000000000, -0.166666666667]]
    ),
    "NDWI": np.array(
        [[-0.428571428571, -0.333333333333], [-0.600000000000, 0.111111111111]]
    ),
    "BSI": np.array(
        [[-0.263157894737, -0.185185185185], [0.052631578947, 0.300000000000]]
    ),
    "RENDVI": np.array(
        [[0.250000000000, 0.125000000000], [0.166666666667, 0.111111111111]]
    ),
}


# --------------------------------------------------------------------------
# Formula correctness
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_index_matches_hand_computed_matrix(name: str) -> None:
    spec = fe.INDEX_BY_NAME[name]
    result = spec.compute(BANDS)
    np.testing.assert_allclose(result, EXPECTED[name], **TOLERANCE)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_direct_function_matches_registry(name: str) -> None:
    """Calling the module-level function directly gives the same answer."""
    spec = fe.INDEX_BY_NAME[name]
    direct = spec.fn(*(BANDS[b] for b in spec.bands))
    np.testing.assert_allclose(direct, EXPECTED[name], **TOLERANCE)


def test_compute_all_returns_every_index() -> None:
    computed = fe.compute_all(BANDS)
    assert set(computed) == set(fe.INDEX_NAMES)
    assert len(computed) == 11


def test_compute_all_skips_indices_with_missing_bands() -> None:
    """A missing band drops the index; it must never be back-filled."""
    partial = {k: v for k, v in BANDS.items() if k != "B11"}
    computed = fe.compute_all(partial)
    # NDMI, LSWI and BSI all need SWIR1.
    assert "NDMI" not in computed
    assert "LSWI" not in computed
    assert "BSI" not in computed
    assert "NDVI" in computed


def test_compute_raises_on_missing_band() -> None:
    with pytest.raises(KeyError, match="B11"):
        fe.INDEX_BY_NAME["NDMI"].compute({"B8": 0.5})


# --------------------------------------------------------------------------
# Analytic properties that must hold for any correct implementation
# --------------------------------------------------------------------------


def test_ndwi_is_the_negation_of_gndvi() -> None:
    """Both are normalised Green/NIR differences with the terms transposed."""
    np.testing.assert_allclose(
        fe.ndwi(BANDS["B3"], BANDS["B8"]),
        -fe.gndvi(BANDS["B8"], BANDS["B3"]),
        **TOLERANCE,
    )


def test_ndvi_is_zero_when_nir_equals_red() -> None:
    equal = np.array([0.05, 0.3, 0.9])
    np.testing.assert_allclose(fe.ndvi(equal, equal), np.zeros(3), **TOLERANCE)


def test_savi_reduces_to_ndvi_when_l_is_zero() -> None:
    """SAVI with L=0 is NDVI by definition -- a structural check on the form."""
    np.testing.assert_allclose(
        fe.savi(BANDS["B8"], BANDS["B4"], L=0.0),
        fe.ndvi(BANDS["B8"], BANDS["B4"]),
        **TOLERANCE,
    )


def test_normalised_indices_stay_within_minus_one_and_one() -> None:
    bounded = ["NDVI", "NDMI", "NDRE", "GNDVI", "LSWI", "NDWI", "BSI", "RENDVI"]
    rng = np.random.default_rng(20240824)
    sample = {band: rng.uniform(0.001, 1.0, size=512) for band in fe.REQUIRED_BANDS}
    for name in bounded:
        values = fe.INDEX_BY_NAME[name].compute(sample)
        assert np.nanmin(values) >= -1.0 - 1e-12, name
        assert np.nanmax(values) <= 1.0 + 1e-12, name


def test_bsi_is_positive_over_bare_soil_signature() -> None:
    """High SWIR/red against low NIR/blue is the bare-soil signature."""
    soil = {"B11": 0.38, "B4": 0.30, "B8": 0.22, "B2": 0.12}
    assert float(fe.INDEX_BY_NAME["BSI"].compute(soil)) > 0.0


def test_bsi_is_negative_over_dense_canopy_signature() -> None:
    canopy = {"B11": 0.18, "B4": 0.04, "B8": 0.45, "B2": 0.03}
    assert float(fe.INDEX_BY_NAME["BSI"].compute(canopy)) < 0.0


def test_ndmi_and_lswi_differ_only_by_nir_band() -> None:
    """They share a formula; the distinction is B8 versus B8A, nothing else."""
    same_nir = dict(BANDS, B8A=BANDS["B8"])
    np.testing.assert_allclose(
        fe.INDEX_BY_NAME["LSWI"].compute(same_nir),
        fe.INDEX_BY_NAME["NDMI"].compute(same_nir),
        **TOLERANCE,
    )
    # With the real, different narrow-NIR band they must not coincide.
    assert not np.allclose(
        fe.INDEX_BY_NAME["LSWI"].compute(BANDS),
        fe.INDEX_BY_NAME["NDMI"].compute(BANDS),
    )


# --------------------------------------------------------------------------
# Undefined values stay undefined
# --------------------------------------------------------------------------


def test_safe_divide_yields_nan_not_zero_on_zero_denominator() -> None:
    result = fe.safe_divide(np.array([1.0, 0.0, -2.0]), np.array([0.0, 0.0, 4.0]))
    assert np.isnan(result[0])
    assert np.isnan(result[1])
    assert result[2] == pytest.approx(-0.5)


def test_ndvi_of_fully_masked_pixel_is_nan() -> None:
    """A pixel where every band reads zero is *no observation*, not bare soil."""
    assert np.isnan(float(fe.ndvi(0.0, 0.0)))


def test_scalar_inputs_are_supported() -> None:
    assert float(fe.ndvi(0.5, 0.1)) == pytest.approx(0.666666666667, rel=1e-11)


# --------------------------------------------------------------------------
# Registry integrity
# --------------------------------------------------------------------------


def test_registry_has_exactly_eleven_unique_indices() -> None:
    assert len(fe.INDEX_SPECS) == 11
    assert len(set(fe.INDEX_NAMES)) == 11


def test_required_bands_is_the_union_of_all_specs() -> None:
    union = {band for spec in fe.INDEX_SPECS for band in spec.bands}
    assert set(fe.REQUIRED_BANDS) == union
    assert set(fe.REQUIRED_BANDS) == {
        "B2",
        "B3",
        "B4",
        "B5",
        "B6",
        "B8",
        "B8A",
        "B11",
    }


def test_every_spec_declares_the_bands_its_function_consumes() -> None:
    """The declared band tuple must match the function signature order."""
    import inspect

    for spec in fe.INDEX_SPECS:
        params = [
            name
            for name, p in inspect.signature(spec.fn).parameters.items()
            if p.default is inspect.Parameter.empty
        ]
        assert tuple(params) == spec.bands, spec.name


def test_gee_expression_references_only_declared_bands() -> None:
    """Guards against the Earth Engine mirror drifting from the NumPy form."""
    import re

    for spec in fe.INDEX_SPECS:
        tokens = set(re.findall(r"\bB[0-9]+A?\b", spec.expression))
        assert tokens == set(spec.bands), spec.name


def test_indices_available_for_reports_the_computable_subset() -> None:
    assert set(fe.indices_available_for(fe.REQUIRED_BANDS)) == set(fe.INDEX_NAMES)
    assert set(fe.indices_available_for(("B8", "B4"))) == {"NDVI", "SAVI"}
    assert fe.indices_available_for(()) == ()


# --------------------------------------------------------------------------
# Feature vector assembly
# --------------------------------------------------------------------------


def test_feature_vector_follows_registry_order() -> None:
    values = {name: float(i) for i, name in enumerate(fe.INDEX_NAMES)}
    vector = fe.feature_vector(values)
    np.testing.assert_allclose(vector, np.arange(11, dtype=float))


def test_feature_vector_marks_missing_indices_as_nan() -> None:
    vector = fe.feature_vector({"NDVI": 0.7})
    assert vector[fe.INDEX_NAMES.index("NDVI")] == pytest.approx(0.7)
    assert np.isnan(vector).sum() == 10

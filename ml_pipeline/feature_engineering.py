"""Phase 2 -- the eleven vegetation indices, as pure functions.

Every index is defined exactly once, in :data:`INDEX_SPECS`, as a triple of
(required Sentinel-2 bands, NumPy implementation, Earth Engine expression). The
NumPy function is what the unit tests verify against hand-computed matrices;
the Earth Engine expression is what runs server-side. Keeping both in one
registry is deliberate -- a formula can not drift between the tested path and
the production path without the drift being visible on a single line.

Band conventions (Sentinel-2 L2A, surface reflectance scaled to [0, 1]):

===== ============ ==================================================
Band  Centre (nm)  Role
===== ============ ==================================================
B2    492          Blue
B3    560          Green
B4    665          Red
B5    704          Red edge 1
B6    740          Red edge 2
B8    833          NIR (broad, 10 m)
B8A   864          NIR (narrow, 20 m)
B11   1610         SWIR 1
===== ============ ==================================================

A note on NDMI and LSWI: both are normalised NIR/SWIR differences and are
structurally the same formula. They are kept separate because the literature
uses different NIR bands -- NDMI (Gao 1996) uses the broad NIR, while LSWI as
used in the rice/flooding literature (Xiao et al. 2005) uses the narrow NIR
band matched to MODIS band 2. Over a wet canopy the two diverge slightly. They
are not duplicated by accident, and neither is invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np

# Soil-adjustment factor for SAVI. L = 0.5 is Huete's (1988) recommendation for
# intermediate vegetation density, which is the regime for these crops.
SAVI_L = 0.5

ArrayLike = np.ndarray | float | int


def _as_array(value: ArrayLike) -> np.ndarray:
    """Coerce input to a float array without copying when already float64."""
    return np.asarray(value, dtype=np.float64)


def safe_divide(numerator: ArrayLike, denominator: ArrayLike) -> np.ndarray:
    """Element-wise division that yields NaN where the denominator is zero.

    A zero denominator means the index is genuinely undefined for that pixel
    (for example NDVI where NIR and Red are both zero over deep water or a
    fully masked pixel). Returning NaN keeps that undefined-ness visible all
    the way to the database, instead of silently substituting 0.0 -- which
    would read downstream as "bare soil" rather than "no observation".
    """
    num = _as_array(numerator)
    den = _as_array(denominator)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.true_divide(num, den)
        result = np.where(den == 0, np.nan, result)
    return result


# --------------------------------------------------------------------------
# Index implementations
# --------------------------------------------------------------------------


def ndvi(B8: ArrayLike, B4: ArrayLike) -> np.ndarray:
    """Normalised Difference Vegetation Index (Rouse et al. 1974).

    ``(NIR - Red) / (NIR + Red)``. General canopy greenness and the backbone of
    the crop phenology signal.
    """
    return safe_divide(_as_array(B8) - _as_array(B4), _as_array(B8) + _as_array(B4))


def evi(B8: ArrayLike, B4: ArrayLike, B2: ArrayLike) -> np.ndarray:
    """Enhanced Vegetation Index (Huete et al. 2002).

    ``2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)``. Resists the
    saturation NDVI shows over dense canopy, which matters for peak-stage
    tomato and leafy greens.
    """
    nir, red, blue = _as_array(B8), _as_array(B4), _as_array(B2)
    return 2.5 * safe_divide(nir - red, nir + 6.0 * red - 7.5 * blue + 1.0)


def ndmi(B8: ArrayLike, B11: ArrayLike) -> np.ndarray:
    """Normalised Difference Moisture Index (Gao 1996).

    ``(NIR - SWIR1) / (NIR + SWIR1)`` using the broad NIR band. Tracks canopy
    water content and irrigation state.
    """
    nir, swir = _as_array(B8), _as_array(B11)
    return safe_divide(nir - swir, nir + swir)


def savi(B8: ArrayLike, B4: ArrayLike, L: float = SAVI_L) -> np.ndarray:
    """Soil-Adjusted Vegetation Index (Huete 1988).

    ``((NIR - Red) / (NIR + Red + L)) * (1 + L)``. Suppresses the soil
    background that dominates early-season imagery of row crops.
    """
    nir, red = _as_array(B8), _as_array(B4)
    return safe_divide(nir - red, nir + red + L) * (1.0 + L)


def ndre(B8: ArrayLike, B5: ArrayLike) -> np.ndarray:
    """Normalised Difference Red Edge (Gitelson & Merzlyak 1994).

    ``(NIR - RedEdge1) / (NIR + RedEdge1)``. Sensitive to canopy nitrogen and
    holds its dynamic range after NDVI saturates.
    """
    nir, rededge = _as_array(B8), _as_array(B5)
    return safe_divide(nir - rededge, nir + rededge)


def gndvi(B8: ArrayLike, B3: ArrayLike) -> np.ndarray:
    """Green NDVI (Gitelson et al. 1996).

    ``(NIR - Green) / (NIR + Green)``. More responsive to chlorophyll
    concentration than NDVI.
    """
    nir, green = _as_array(B8), _as_array(B3)
    return safe_divide(nir - green, nir + green)


def cig(B8: ArrayLike, B3: ArrayLike) -> np.ndarray:
    """Chlorophyll Index -- Green (Gitelson et al. 2003).

    ``(NIR / Green) - 1``. Unbounded above, so it separates the very dense
    canopies where the normalised indices compress.
    """
    return safe_divide(_as_array(B8), _as_array(B3)) - 1.0


def lswi(B8A: ArrayLike, B11: ArrayLike) -> np.ndarray:
    """Land Surface Water Index (Xiao et al. 2005).

    ``(NIR_narrow - SWIR1) / (NIR_narrow + SWIR1)``. Same structure as NDMI but
    computed on the narrow NIR band (B8A), matching the MODIS-derived
    definition used for flooding and transplanting detection.
    """
    nir, swir = _as_array(B8A), _as_array(B11)
    return safe_divide(nir - swir, nir + swir)


def ndwi(B3: ArrayLike, B8: ArrayLike) -> np.ndarray:
    """Normalised Difference Water Index (McFeeters 1996).

    ``(Green - NIR) / (Green + NIR)``. Delineates open water -- farm ponds and
    tanks -- which must be excluded from cultivated-area totals.
    """
    green, nir = _as_array(B3), _as_array(B8)
    return safe_divide(green - nir, green + nir)


def bsi(
    B11: ArrayLike, B4: ArrayLike, B8: ArrayLike, B2: ArrayLike
) -> np.ndarray:
    """Bare Soil Index (Rikimaru et al. 2002).

    ``((SWIR1 + Red) - (NIR + Blue)) / ((SWIR1 + Red) + (NIR + Blue))``. The
    primary discriminator for the Fallow/Non-Crop class.
    """
    swir, red, nir, blue = (
        _as_array(B11),
        _as_array(B4),
        _as_array(B8),
        _as_array(B2),
    )
    upper = (swir + red) - (nir + blue)
    lower = (swir + red) + (nir + blue)
    return safe_divide(upper, lower)


def rendvi(B6: ArrayLike, B5: ArrayLike) -> np.ndarray:
    """Red Edge NDVI (Sims & Gamon 2002).

    ``(RedEdge2 - RedEdge1) / (RedEdge2 + RedEdge1)``, the Sentinel-2 analogue
    of the 750/705 nm formulation. Distinct from NDRE, which contrasts the red
    edge against the NIR plateau rather than against a second red-edge band.
    """
    far, near = _as_array(B6), _as_array(B5)
    return safe_divide(far - near, far + near)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexSpec:
    """One vegetation index: its bands, NumPy form and Earth Engine form."""

    name: str
    bands: tuple[str, ...]
    fn: Callable[..., np.ndarray]
    expression: str
    description: str
    #: Physically meaningful output range, used only for reporting/QA.
    valid_range: tuple[float, float]

    def compute(self, bands: Mapping[str, ArrayLike]) -> np.ndarray:
        """Evaluate this index from a mapping of band name -> reflectance."""
        missing = [b for b in self.bands if b not in bands]
        if missing:
            raise KeyError(
                f"{self.name} requires band(s) {', '.join(missing)} which were not supplied"
            )
        return self.fn(*(bands[b] for b in self.bands))


INDEX_SPECS: tuple[IndexSpec, ...] = (
    IndexSpec(
        name="NDVI",
        bands=("B8", "B4"),
        fn=ndvi,
        expression="(B8 - B4) / (B8 + B4)",
        description="Canopy greenness (Rouse et al. 1974)",
        valid_range=(-1.0, 1.0),
    ),
    IndexSpec(
        name="EVI",
        bands=("B8", "B4", "B2"),
        fn=evi,
        expression="2.5 * ((B8 - B4) / (B8 + 6 * B4 - 7.5 * B2 + 1))",
        description="Saturation-resistant greenness (Huete et al. 2002)",
        valid_range=(-1.0, 1.0),
    ),
    IndexSpec(
        name="NDMI",
        bands=("B8", "B11"),
        fn=ndmi,
        expression="(B8 - B11) / (B8 + B11)",
        description="Canopy moisture, broad NIR (Gao 1996)",
        valid_range=(-1.0, 1.0),
    ),
    IndexSpec(
        name="SAVI",
        bands=("B8", "B4"),
        fn=savi,
        expression=f"((B8 - B4) / (B8 + B4 + {SAVI_L})) * {1.0 + SAVI_L}",
        description="Soil-adjusted greenness (Huete 1988)",
        valid_range=(-1.5, 1.5),
    ),
    IndexSpec(
        name="NDRE",
        bands=("B8", "B5"),
        fn=ndre,
        expression="(B8 - B5) / (B8 + B5)",
        description="Red-edge nitrogen proxy (Gitelson & Merzlyak 1994)",
        valid_range=(-1.0, 1.0),
    ),
    IndexSpec(
        name="GNDVI",
        bands=("B8", "B3"),
        fn=gndvi,
        expression="(B8 - B3) / (B8 + B3)",
        description="Green NDVI, chlorophyll sensitive (Gitelson et al. 1996)",
        valid_range=(-1.0, 1.0),
    ),
    IndexSpec(
        name="CIG",
        bands=("B8", "B3"),
        fn=cig,
        expression="(B8 / B3) - 1",
        description="Chlorophyll index, green (Gitelson et al. 2003)",
        valid_range=(-1.0, 20.0),
    ),
    IndexSpec(
        name="LSWI",
        bands=("B8A", "B11"),
        fn=lswi,
        expression="(B8A - B11) / (B8A + B11)",
        description="Surface water/flooding, narrow NIR (Xiao et al. 2005)",
        valid_range=(-1.0, 1.0),
    ),
    IndexSpec(
        name="NDWI",
        bands=("B3", "B8"),
        fn=ndwi,
        expression="(B3 - B8) / (B3 + B8)",
        description="Open-water delineation (McFeeters 1996)",
        valid_range=(-1.0, 1.0),
    ),
    IndexSpec(
        name="BSI",
        bands=("B11", "B4", "B8", "B2"),
        fn=bsi,
        expression="((B11 + B4) - (B8 + B2)) / ((B11 + B4) + (B8 + B2))",
        description="Bare soil / fallow discriminator (Rikimaru et al. 2002)",
        valid_range=(-1.0, 1.0),
    ),
    IndexSpec(
        name="RENDVI",
        bands=("B6", "B5"),
        fn=rendvi,
        expression="(B6 - B5) / (B6 + B5)",
        description="Red-edge NDVI, 740/704 nm (Sims & Gamon 2002)",
        valid_range=(-1.0, 1.0),
    ),
)

INDEX_BY_NAME: dict[str, IndexSpec] = {spec.name: spec for spec in INDEX_SPECS}
INDEX_NAMES: tuple[str, ...] = tuple(spec.name for spec in INDEX_SPECS)

#: Every Sentinel-2 band any index depends on. gee_ingestion selects these.
REQUIRED_BANDS: tuple[str, ...] = tuple(
    sorted({band for spec in INDEX_SPECS for band in spec.bands})
)

#: Bands the spectral classifier consumes directly, on top of the indices.
#: B12 (SWIR 2, 2190 nm) feeds no index here but is one of the model's 17
#: features, so it has to be fetched even though nothing else uses it.
CLASSIFIER_BANDS: tuple[str, ...] = ("B2", "B3", "B4", "B8", "B11", "B12")

#: Union of everything downstream needs from a Sentinel-2 scene.
ALL_BANDS: tuple[str, ...] = tuple(sorted(set(REQUIRED_BANDS) | set(CLASSIFIER_BANDS)))


def compute_all(bands: Mapping[str, ArrayLike]) -> dict[str, np.ndarray]:
    """Compute every index whose bands are present in ``bands``.

    Indices with missing bands are omitted rather than filled -- an absent band
    is a real gap and the caller has to see it as one.
    """
    out: dict[str, np.ndarray] = {}
    for spec in INDEX_SPECS:
        if all(band in bands for band in spec.bands):
            out[spec.name] = spec.compute(bands)
    return out


def feature_vector(
    values: Mapping[str, float], order: Sequence[str] | None = None
) -> np.ndarray:
    """Order index values into the classifier's feature vector.

    Missing indices become NaN so the model pipeline's imputer handles them
    explicitly, rather than being coerced to a plausible-looking zero.
    """
    order = tuple(order or INDEX_NAMES)
    return np.array(
        [float(values.get(name, np.nan)) for name in order], dtype=np.float64
    )


# --------------------------------------------------------------------------
# Earth Engine mirror
# --------------------------------------------------------------------------


def add_index_bands(image, available_bands: Sequence[str] | None = None):
    """Attach the index bands to an Earth Engine image.

    Uses the same expressions recorded in :data:`INDEX_SPECS`, so the
    server-side computation cannot diverge from the unit-tested NumPy form.
    Indices whose source bands are absent are skipped rather than approximated.

    Args:
        image: the ``ee.Image`` to augment.
        available_bands: the bands known to be present. Pass this from the
            caller (which already selected them) to avoid an extra
            ``bandNames().getInfo()`` round trip per composite. When omitted the
            band list is fetched from the server.
    """
    if available_bands is None:
        band_names = set(image.bandNames().getInfo() or [])
    else:
        band_names = set(available_bands)

    for spec in INDEX_SPECS:
        if not set(spec.bands).issubset(band_names):
            continue
        band_map = {band: image.select(band) for band in spec.bands}
        computed = image.expression(spec.expression, band_map).rename(spec.name)
        image = image.addBands(computed)
    return image


def indices_available_for(available_bands: Sequence[str]) -> tuple[str, ...]:
    """Names of the indices computable from ``available_bands``."""
    present = set(available_bands)
    return tuple(
        spec.name for spec in INDEX_SPECS if set(spec.bands).issubset(present)
    )

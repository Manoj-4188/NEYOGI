"""Sentinel-1 radar, for the weeks when optical imagery sees nothing.

Sentinel-2 is blind through cloud, and Karnataka's monsoon can close it for
weeks -- Kolar went from five clear passes to none in a fortnight, which
stalled every downstream figure. Sentinel-1 is C-band SAR: it supplies its own
illumination and passes through cloud, so it keeps returning data through the
season that matters most.

What radar is not
-----------------
It is not a substitute for NDVI, and nothing here treats it as one.

NDVI measures reflected light and responds to chlorophyll: how *green* a
canopy is. Radar backscatter responds to structure and water content: how the
canopy is *built* and how wet it is. The two correlate over a growing season
because a crop gets greener and bulkier together, but they are separate
physical measurements and diverge exactly where it matters -- a senescing crop
loses greenness long before it loses structure.

So RVI is stored in its own column, plotted as its own series, and never
back-fills an NDVI gap. A reader comparing the two is comparing two
measurements, which is honest. Substituting one for the other would be
inventing a greenness reading from a radar echo.

The spectral classifier is not fed radar either: it was fitted on seventeen
optical features and has never seen a backscatter value.

Processing notes
----------------
* **GRD, IW mode.** Interferometric Wide is the standard land acquisition.
* **One orbit direction at a time.** Ascending and descending passes view a
  field from opposite sides, and the backscatter differs enough that mixing
  them adds a step change to the series that looks like a real event.
* **Speckle filtering.** SAR is inherently grainy; a focal median over a small
  neighbourhood removes most of it without smearing field edges.
* **dB to linear power before arithmetic.** The bands ship in decibels, which
  are logarithmic, so summing or ratioing them directly is meaningless. The
  conversion is ``10 ** (dB / 10)``; writing it as ``(dB / 10) ** 10`` fails
  silently and pins RVI near 4, so the arithmetic is isolated in
  :func:`db_to_linear` where a test can reach it.
* **A refusal, not a clamp.** RVI above :data:`MAX_PLAUSIBLE_RVI` is physically
  impossible and means the chain is broken. Such a reading is dropped rather
  than stored or clipped into range, since a clipped value still reads as a
  measurement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from ml_pipeline.gee_auth import EarthEngineUnavailable, initialize

logger = logging.getLogger(__name__)

S1_COLLECTION = "COPERNICUS/S1_GRD"

#: Speckle filter radius, in metres. Wide enough to suppress grain, narrow
#: enough to leave a field boundary intact.
SPECKLE_RADIUS_M = 30

#: Sentinel-1 GRD IW pixel spacing.
S1_SCALE_M = 10

#: Orbit direction. Fixed rather than mixed: a field looks different from
#: ascending and descending passes, and alternating between them puts a step
#: in the time series that reads as a real change in the crop.
DEFAULT_ORBIT = "DESCENDING"

#: Cross-polarised return is weaker than co-polarised for every natural
#: surface, so VH < VV and RVI = 4*VH/(VV+VH) stays below 2. Real vegetation
#: sits between roughly 0.2 and 1.0. Anything above this bound is not an
#: unusual field; it is a unit or conversion error upstream, and it is refused
#: rather than stored, because a stored 3.96 is indistinguishable from a
#: measurement once it reaches a chart.
MAX_PLAUSIBLE_RVI = 2.0


@dataclass
class RadarObservation:
    """One district-mean radar reading for a composite window."""

    observed_on: date
    rvi: float
    vv_db: float
    vh_db: float
    scene_count: int
    orbit: str

    def to_dict(self) -> dict:
        return {
            "observed_on": self.observed_on.isoformat(),
            "rvi": round(self.rvi, 4),
            "vv_db": round(self.vv_db, 2),
            "vh_db": round(self.vh_db, 2),
            "scene_count": self.scene_count,
            "orbit": self.orbit,
        }


def db_to_linear(db: float) -> float:
    """Linear power from decibels: ``10 ** (dB / 10)``.

    Plain arithmetic, so it can be tested without Earth Engine. The Earth
    Engine form below must mirror it exactly.

    The order is easy to get backwards, and getting it backwards is quiet.
    ``(dB / 10) ** 10`` is a different function that returns a positive number
    for every input, so nothing raises and nothing looks obviously wrong: at
    VV = -10 dB it gives 1.0 instead of 0.1, and at VH = -18 dB it gives 357
    instead of 0.016. VH is the more negative band, so the error inflates it
    far above VV and pins RVI near its ceiling of 4 whatever is on the ground.
    """
    return 10.0 ** (db / 10.0)


def rvi_from_linear(vv: float, vh: float) -> float:
    """Dual-polarisation Radar Vegetation Index from linear powers.

    ``RVI = 4 * VH / (VV + VH)``. Both arguments must already be linear power;
    passing decibels gives a number rather than an error, which is why the
    conversion lives in its own function above.
    """
    total = vv + vh
    if total <= 0:
        raise ValueError("backscatter powers must be positive linear values")
    return 4.0 * vh / total


def _to_linear(image, band: str):
    """Earth Engine form of :func:`db_to_linear`.

    ``ee.Image.pow`` raises the image to a constant exponent. Here the image
    is the *exponent*, so the base has to be the constant 10 and the call
    reads the other way round.
    """
    import ee

    return ee.Image(10.0).pow(image.select(band).divide(10.0))


def add_radar_indices(image):
    """Attach RVI and the VH/VV ratio to a Sentinel-1 image.

    RVI, the dual-polarisation Radar Vegetation Index::

        RVI = 4 * VH / (VV + VH)      (linear power, not dB)

    Near zero over bare or smooth ground, rising towards one as a canopy
    develops volume scattering. Structurally analogous to NDVI's role, but a
    different measurement -- see the module docstring.
    """
    import ee

    vv = _to_linear(image, "VV")
    vh = _to_linear(image, "VH")

    rvi = vh.multiply(4).divide(vv.add(vh)).rename("RVI")
    ratio = vh.divide(vv).rename("VH_VV")

    return image.addBands(rvi).addBands(ratio)


def sentinel1_collection(geometry, start: date, end: date, orbit: str = DEFAULT_ORBIT):
    """Speckle-filtered Sentinel-1 GRD for a geometry, date range and orbit."""
    initialize()
    import ee

    collection = (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(geometry)
        .filterDate(start.isoformat(), end.isoformat())
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.eq("orbitProperties_pass", orbit))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    )

    def prepare(image):
        smoothed = image.select(["VV", "VH"]).focal_median(
            SPECKLE_RADIUS_M, "circle", "meters"
        )
        return add_radar_indices(smoothed).copyProperties(
            image, ["system:time_start", "orbitProperties_pass"]
        )

    return collection.map(prepare)


def scene_count(geometry, start: date, end: date, orbit: str = DEFAULT_ORBIT) -> int:
    """How many radar passes cover this geometry in the window."""
    try:
        return int(sentinel1_collection(geometry, start, end, orbit).size().getInfo())
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(f"Sentinel-1 scene count failed: {exc}") from exc


def best_orbit(geometry, start: date, end: date) -> tuple[str, int]:
    """Pick whichever orbit direction has more passes over this district.

    Returns ``(orbit, count)``. Coverage is uneven across India, and a district
    on the edge of one orbit's swath may be well inside the other's.
    """
    counts = {}
    for orbit in ("DESCENDING", "ASCENDING"):
        try:
            counts[orbit] = scene_count(geometry, start, end, orbit)
        except EarthEngineUnavailable:
            counts[orbit] = 0
    orbit = max(counts, key=counts.get)
    return orbit, counts[orbit]


def district_radar(
    geometry,
    start: date,
    end: date,
    orbit: str | None = None,
    cropland_mask=None,
    scale: int = 100,
) -> RadarObservation | None:
    """Mean RVI and backscatter for one district and window.

    ``cropland_mask`` restricts the average to farmland when supplied. Radar
    responds strongly to built-up areas and open water, so an unmasked district
    mean is dominated by whatever is not a field.

    Returns None when no pass covered the district -- rare, since radar is not
    blocked by cloud, but possible at a swath edge.
    """
    initialize()
    import ee

    if orbit is None:
        orbit, count = best_orbit(geometry, start, end)
        if count == 0:
            return None

    collection = sentinel1_collection(geometry, start, end, orbit)
    try:
        n = int(collection.size().getInfo())
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(f"Sentinel-1 query failed: {exc}") from exc
    if n == 0:
        return None

    composite = collection.median().clip(geometry)
    if cropland_mask is not None:
        composite = composite.updateMask(cropland_mask)

    try:
        stats = composite.select(["RVI", "VV", "VH"]).reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=scale,
            maxPixels=1e10,
            bestEffort=True,
        ).getInfo()
    except Exception as exc:  # noqa: BLE001
        raise EarthEngineUnavailable(f"Sentinel-1 reduction failed: {exc}") from exc

    rvi = stats.get("RVI")
    if rvi is None:
        return None

    # A reading outside the physical range means the processing chain is
    # wrong, not that the field is unusual. Refuse it: an impossible number
    # that reaches the series is plotted next to NDVI and read as a
    # measurement by anyone looking at the chart.
    rvi = float(rvi)
    if not 0.0 < rvi < MAX_PLAUSIBLE_RVI:
        logger.warning(
            "Sentinel-1 RVI %.3f for %s (%s) is outside the physical range "
            "(0, %.1f); discarding the reading rather than storing it.",
            rvi,
            start.isoformat(),
            orbit,
            MAX_PLAUSIBLE_RVI,
        )
        return None

    return RadarObservation(
        observed_on=start,
        rvi=rvi,
        vv_db=float(stats.get("VV") or 0.0),
        vh_db=float(stats.get("VH") or 0.0),
        scene_count=n,
        orbit=orbit,
    )

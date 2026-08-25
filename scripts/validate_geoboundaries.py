"""Validate the geoBoundaries polygons for the two districts GAUL lacks.

Checks that the candidate replacement is actually the right piece of ground
before it is wired in: correct state, plausible area, and located inside the
GAUL parent district it was carved from.
"""

import logging
logging.basicConfig(level=logging.ERROR)

from ml_pipeline.gee_auth import initialize
initialize()
import ee

GB = "projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM2"

# Published district areas (km2), for a sanity comparison only.
EXPECTED_KM2 = {"Chikkaballapura": 4208, "Ramanagara": 3556}
# GAUL parent each was carved out of in 2007.
PARENT = {"Chikkaballapura": "Kolar", "Ramanagara": "Bangalore Rural"}

karnataka = (
    ee.FeatureCollection("FAO/GAUL/2015/level1")
    .filter(ee.Filter.And(
        ee.Filter.eq("ADM0_NAME", "India"),
        ee.Filter.eq("ADM1_NAME", "Karnataka"),
    ))
    .geometry()
)

gb = ee.FeatureCollection(GB).filter(ee.Filter.eq("shapeGroup", "IND"))

print("geoBoundaries ADM2 features intersecting Karnataka:")
in_state = gb.filterBounds(karnataka)
names = sorted(set(in_state.aggregate_array("shapeName").getInfo()))
print(f"  {len(names)} names")
print()

for target in ("Chikkaballapura", "Ramanagara"):
    print("=" * 66)
    print(target)
    feat = gb.filter(ee.Filter.eq("shapeName", target))
    n = feat.size().getInfo()
    print(f"  features named exactly this : {n}")
    if n == 0:
        print("  NOT FOUND")
        continue

    geom = feat.geometry()
    area_km2 = geom.area(maxError=100).divide(1e6).getInfo()
    centroid = geom.centroid(maxError=100).coordinates().getInfo()
    within_state = geom.intersects(karnataka, ee.ErrorMargin(100)).getInfo()

    # How much of it falls inside the GAUL parent it was split from.
    parent = (
        ee.FeatureCollection("FAO/GAUL/2015/level2")
        .filter(ee.Filter.And(
            ee.Filter.eq("ADM1_NAME", "Karnataka"),
            ee.Filter.eq("ADM2_NAME", PARENT[target]),
        ))
        .geometry()
    )
    overlap = geom.intersection(parent, ee.ErrorMargin(100)).area(maxError=100).divide(1e6).getInfo()

    exp = EXPECTED_KM2[target]
    print(f"  area              : {area_km2:,.0f} km2  (published ~{exp:,} km2)")
    print(f"  ratio to published: {area_km2/exp:.2f}")
    print(f"  centroid lon/lat  : {centroid[0]:.4f}, {centroid[1]:.4f}")
    print(f"  intersects Karnataka: {within_state}")
    print(f"  overlap with GAUL {PARENT[target]}: {overlap:,.0f} km2 ({overlap/area_km2*100:.0f}% of it)")

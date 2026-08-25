"""Probe candidate admin-boundary datasets for the two post-2007 districts.

GAUL 2015 predates Chikkaballapur (split from Kolar, 2007) and Ramanagara
(split from Bangalore Rural, 2007), so neither exists in it. This finds a
published source that does carry them -- we substitute a real boundary or
none at all, never a hand-drawn one.
"""

import logging
logging.basicConfig(level=logging.ERROR)

from ml_pipeline.gee_auth import initialize

initialize()
import ee

TARGETS = ("Chikkaballapur", "Ramanagara")

# (asset id, is_table, state-name property, district-name property)
CANDIDATES = [
    ("FAO/GAUL/2015/level2", True, "ADM1_NAME", "ADM2_NAME"),
    ("FAO/GAUL_SIMPLIFIED_500m/2015/level2", True, "ADM1_NAME", "ADM2_NAME"),
    ("projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM2", True, "shapeGroup", "shapeName"),
    ("projects/sat-io/open-datasets/geoboundaries/HPSCGS_ADM2", True, "shapeGroup", "shapeName"),
    ("USDOS/LSIB_SIMPLE/2017", True, "wld_rgn", "country_na"),
]


def probe(asset, state_prop, name_prop):
    try:
        fc = ee.FeatureCollection(asset)
        # Sample property names first so a schema mismatch is obvious.
        first = fc.first().propertyNames().getInfo()
        has_props = state_prop in first and name_prop in first
        info = {"asset": asset, "reachable": True, "props_ok": has_props,
                "sample_props": [p for p in first if not p.startswith("system:")][:8]}
        if not has_props:
            return info

        # Pull district names for anything mentioning Karnataka / IND.
        filt = ee.Filter.Or(
            ee.Filter.eq(state_prop, "Karnataka"),
            ee.Filter.eq(state_prop, "IND"),
            ee.Filter.eq(state_prop, "India"),
        )
        sub = fc.filter(filt)
        n = sub.size().getInfo()
        info["matched_features"] = n
        if n:
            names = sub.aggregate_array(name_prop).getInfo()
            info["count_names"] = len(names)
            found = {}
            for t in TARGETS:
                hits = [x for x in names if x and t.lower()[:8] in str(x).lower()]
                found[t] = hits[:3]
            info["targets"] = found
        return info
    except Exception as exc:
        return {"asset": asset, "reachable": False, "error": f"{type(exc).__name__}: {str(exc)[:150]}"}


for asset, _, sp, np_ in CANDIDATES:
    print("=" * 70)
    print(asset)
    r = probe(asset, sp, np_)
    for k, v in r.items():
        if k != "asset":
            print(f"  {k}: {v}")

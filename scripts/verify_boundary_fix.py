"""End-to-end check of the boundary fallback against the live datasets.

Confirms that the two districts GAUL 2015 predates now resolve, that their
polygons are the right size and in the right place, and that Sentinel-2
imagery can actually be queried over them.

    docker compose exec backend python scripts/verify_boundary_fix.py
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

logging.basicConfig(level=logging.ERROR)

from ml_pipeline.gee_districts import (  # noqa: E402
    SOURCE_GAUL,
    district_geometry,
    resolve_districts,
)
from ml_pipeline.gee_ingestion import sentinel2_collection  # noqa: E402

LINE = "=" * 74

# Published district areas (km2) for a sanity comparison only -- never used
# to correct or scale a geometry.
EXPECTED_KM2 = {"Chikkaballapur": 4208, "Ramanagara": 3556}


def main() -> int:
    resolution = resolve_districts()

    print(LINE)
    print("RESOLUTION")
    print(LINE)
    for d in resolution.resolved:
        tag = "GAUL" if d.source == SOURCE_GAUL else "geoBoundaries"
        code = d.adm2_code if d.adm2_code > 0 else "-"
        print(
            "  {:<18} -> {:<18} [{:<13}] code={:<6} ({})".format(
                d.requested_name, d.gaul_name, tag, code, d.match_kind
            )
        )
    print("  unresolved    :", list(resolution.unresolved) or "none")
    print("  fallback used :", list(resolution.fallback_names) or "none")

    print()
    print(LINE)
    print("GEOMETRY AND IMAGERY for the districts GAUL could not place")
    print(LINE)

    end = date.today()
    start = end - timedelta(days=16)
    ok = True

    for name, expected in EXPECTED_KM2.items():
        district = resolution.get(name)
        if district is None:
            print("  {:<18} STILL UNRESOLVED".format(name))
            ok = False
            continue

        geometry = district_geometry(district)
        area = geometry.area(maxError=100).divide(1e6).getInfo()
        centroid = geometry.centroid(maxError=100).coordinates().getInfo()
        scenes = int(sentinel2_collection(geometry, start, end).size().getInfo())
        ratio = area / expected

        print(
            "  {:<18} area={:>7,.0f} km2 (published ~{:,}, ratio {:.2f})".format(
                name, area, expected, ratio
            )
        )
        print(
            "  {:<18} centroid={:.3f}, {:.3f}   scenes in last 16d: {}".format(
                "", centroid[0], centroid[1], scenes
            )
        )

        # A polygon more than 15% off the published area is the wrong feature.
        if not 0.85 <= ratio <= 1.15:
            print("  {:<18} AREA OUT OF RANGE -- wrong feature?".format(""))
            ok = False

    print()
    print("All boundary checks passed." if ok else "Boundary checks FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

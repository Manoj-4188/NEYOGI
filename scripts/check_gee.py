"""Verify the Earth Engine service account end to end.

Run inside the backend container:

    docker compose exec backend python scripts/check_gee.py

Checks run in order, so a failure names the step that broke:

1. Credentials load and Earth Engine initialises.
2. A trivial server round trip returns.
3. FAO/GAUL/2015/level2 resolves the candidate districts -- proves dataset
   read access, not merely authentication.
4. Sentinel-2 L2A returns a real scene count -- proves the collection this
   platform actually depends on is readable.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta

logging.basicConfig(level=logging.ERROR)

LINE = "=" * 62


def main() -> int:
    from ml_pipeline.gee_auth import health_check

    print(LINE)
    print("1. Authentication and round trip")
    print(LINE)
    result = health_check()
    print("  healthy :", result["healthy"])
    print("  detail  :", result["detail"][:400])
    if not result["healthy"]:
        print()
        print("STOPPED: authentication failed, so nothing below could run.")
        return 1

    print()
    print(LINE)
    print("2. FAO/GAUL/2015/level2 district resolution (live)")
    print(LINE)
    try:
        from ml_pipeline.gee_districts import resolve_districts

        resolution = resolve_districts()
        for d in resolution.resolved:
            print(
                "  {:<18} -> {:<18} ({}, ADM2_CODE={})".format(
                    d.requested_name, d.gaul_name, d.match_kind, d.adm2_code
                )
            )
        if resolution.unresolved:
            print("  UNRESOLVED (skipped):", list(resolution.unresolved))
        print(" ", len(resolution.available_names), "districts available in the state")
    except Exception as exc:
        print("  FAILED:", type(exc).__name__, exc)
        return 2

    print()
    print(LINE)
    print("3. Sentinel-2 L2A availability (live)")
    print(LINE)
    try:
        from ml_pipeline.gee_districts import district_geometry
        from ml_pipeline.gee_ingestion import sentinel2_collection

        end = date.today()
        start = end - timedelta(days=16)
        for name in ("Kolar", "Hassan"):
            district = resolution.get(name)
            if district is None:
                print(" ", name, "not resolved, skipping")
                continue
            geometry = district_geometry(district)
            count = int(sentinel2_collection(geometry, start, end).size().getInfo())
            print("  {:<10} {} .. {}: {} cloud-screened scene(s)".format(
                name, start, end, count))
    except Exception as exc:
        print("  FAILED:", type(exc).__name__, exc)
        return 3

    print()
    print("All Earth Engine checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

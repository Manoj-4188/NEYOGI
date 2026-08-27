"""Count cloud-free Sentinel-2 scenes per district for the current window.

Cheap compared with a classification run, so it is worth doing first: a
district with no scenes cannot be classified at all, and running the sampler
against one only to have it fail wastes a minute of Earth Engine time.
"""

import logging
from datetime import date, timedelta

logging.basicConfig(level=logging.ERROR)

from ml_pipeline import config
from ml_pipeline.gee_districts import district_geometry, resolve_districts
from ml_pipeline.gee_ingestion import sentinel2_collection

end = date.today()
start = end - timedelta(days=config.SETTINGS.composite_period_days)
print("window:", start, "..", end)
print()

resolution = resolve_districts()
if resolution.unresolved:
    print("unresolved:", list(resolution.unresolved))
    print()

results = []
for d in resolution.resolved:
    try:
        geom = district_geometry(d)
        n = int(sentinel2_collection(geom, start, end).size().getInfo())
    except Exception as exc:
        print("  {:<18} ERROR {}".format(d.requested_name, type(exc).__name__))
        continue
    results.append((d.requested_name, n))
    print("  {:<18} {:>3} scene(s)".format(d.requested_name, n))

print()
withscenes = [name for name, n in results if n > 0]
print("districts with imagery:", len(withscenes), "of", len(results))
print(" ", ", ".join(withscenes) if withscenes else "none")

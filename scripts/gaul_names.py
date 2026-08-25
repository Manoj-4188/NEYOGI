"""List every ADM2 name GAUL carries for the state, to audit unresolved districts."""
import logging
logging.basicConfig(level=logging.ERROR)
from ml_pipeline.gee_districts import fetch_state_districts, normalise

names = sorted(d["adm2_name"] for d in fetch_state_districts("Karnataka", "India"))
print(len(names), "ADM2 names in GAUL for Karnataka:")
for n in names:
    print("   ", n)

print()
print("Looking for anything resembling the two unresolved candidates:")
for target in ("Chikkaballapur", "Ramanagara"):
    key = normalise(target)
    hits = [n for n in names if key[:5] in normalise(n) or normalise(n)[:5] in key]
    print("  {:<18} -> {}".format(target, hits or "no similar name present"))

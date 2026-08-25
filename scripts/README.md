# Operational scripts

Diagnostics that run inside the backend container, where the credentials and
the `ml_pipeline` package are on the path:

```bash
docker compose exec backend python scripts/check_gee.py
docker compose exec backend python scripts/gaul_names.py
```

| Script | Purpose |
| --- | --- |
| `check_gee.py` | Verifies the Earth Engine service account in four ordered steps — auth, round trip, GAUL district resolution, live Sentinel-2 scene count — so a failure names the step that broke rather than just "GEE is down". |
| `gaul_names.py` | Lists every ADM2 name FAO/GAUL/2015/level2 carries for the state. Use it when a district resolves unexpectedly, or not at all. |

## Earth Engine IAM roles

A service account needs all three of these on the project. Fewer produces
failures that look unrelated to permissions:

| Role | Without it |
| --- | --- |
| `roles/serviceusage.serviceUsageConsumer` | `ee.Initialize()` fails outright — the account cannot call project APIs. |
| Earth Engine Resource **Writer** | Auth and collection reads succeed, but `getMapId` returns `earthengine.maps.create denied`, so no basemap tiles. Viewer is **not** sufficient. |
| Earth Engine API enabled | 403s that read like permission errors. |

The service account must also be registered at
<https://signup.earthengine.google.com/#!/service_accounts>, which is separate
from Cloud IAM.

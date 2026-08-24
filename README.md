# NEYOGI

**Enterprise GIS platform for perishable-crop market intelligence** — Sentinel-2
crop mapping and AGMARKNET price signals for Karnataka's vegetable belt.

NEYOGI answers one question for a tomato, onion, potato or leafy-greens grower:
*is the belt about to produce more than the mandi can absorb?* It answers it
from measured satellite imagery, field-verified crop labels and published market
data — and it declines to answer where any of those are missing.

---

## The core directive

> Build fewer, fully defensible features backed strictly by real data.

Three rules follow from that, and they are enforced in code rather than in
convention:

**1. Unsupervised structure is never presented as a crop label.**
Classification runs only on parcels with `verified_flag = TRUE` — polygons a
named person attributed to a named crop. `ml_pipeline/inference.py` reads the
labelled set through one SQL query that filters on that flag, so there is no
call path that produces a crop class for an unlabelled region. A district with
no verified parcels renders as a raw NDVI basemap behind a red badge.

**2. Yield constants are cited or withheld.**
`data/reference/baseline_yields.yml` ships with every value `null` and
`verified: false`. Until an operator fills one in from a citable source and a
second person checks it, `supply_estimation` refuses to compute a tonnage for
that crop and the API returns `YIELD_BASELINE_UNAVAILABLE`. Classified *area* is
still reported — it is measured. Only the derived tonnage is withheld.

**3. Missing data is a status, not a zero.**
A cloud-masked parcel produces no row, not a 0.0 NDVI. An unpublished mandi
arrival is `NULL`, not zero arrivals — so the oversupply ratio reports
`INSUFFICIENT_ARRIVAL_DATA` rather than dividing by zero and claiming infinite
oversupply. `safe_divide` returns `NaN` where an index is genuinely undefined.

---

## Transparent contingency

Every response carries a `status` object. The UI renders it and never overrides
it, so cached data cannot be displayed as live.

| Source | Primary | Fallback | Badge |
| ------ | ------- | -------- | ----- |
| Satellite | Live Sentinel-2 L2A via Earth Engine | PostGIS 16-day median composite cache (≤30 days) | `🟡 CACHED SATELLITE TILE (YYYY-MM-DD)` |
| Market | Live AGMARKNET (data.gov.in) | PostGIS 30-day moving average | `🟡 MARKET DATA CACHED` |
| Ground truth | Digitised parcel GeoJSONs | **Do not classify** — NDVI basemap only | `🔴 UNVALIDATED DISTRICT (No Verified Labels)` |
| Alerts | Twilio WhatsApp | Celery/Redis retry queue, exponential backoff | `🟡 ALERTS QUEUED (n)` |

A cached badge escalates from amber to red once the data passes its policy age
(`SATELLITE_CACHE_MAX_AGE_DAYS`, `MARKET_CACHE_MAX_AGE_DAYS`). A 60-day
historical seed (`make seed`) populates the cache on a fresh deployment so the
dashboard never opens on an empty state.

---

## Layout

```
neyogi/
├── ml_pipeline/          GEE ingestion, feature engineering, RF classifier
│   ├── gee_districts.py    Dynamic FAO/GAUL ADM2 name resolution
│   ├── gee_ingestion.py    SCL cloud masking, 16-day composites, reduceRegions
│   ├── feature_engineering.py  The 11 indices (NumPy + Earth Engine, one registry)
│   ├── load_ground_truth.py    Parcel GeoJSON ingestion CLI
│   ├── train_classifier.py     Random Forest, parcel-grouped splits
│   ├── inference.py            Verified-parcels-only classification
│   ├── supply_estimation.py    Deterministic volume and oversupply ratio
│   └── tests/                  109 tests
├── backend/              FastAPI, PostGIS schema, AGMARKNET, Twilio, Celery
│   ├── api/v1/             The five REST endpoints, plus auth and webhooks
│   ├── services/           agmarknet, satellite, parcels, supply, twilio, i18n
│   ├── workers/            Celery app, beat schedule, retry tasks
│   ├── sql/001_schema.sql  PostGIS schema (idempotent)
│   └── tests/              83 tests
├── frontend/             React + Leaflet + Tailwind
├── data/
│   ├── ground_truth/       Parcel GeoJSONs (none ship — see its README)
│   ├── reference/          baseline_yields.yml (ships unverified, by design)
│   ├── models/             rf_crop_classifier.joblib
│   └── cache/, exports/
└── docker-compose.yml
```

---

## Quick start

```bash
cp .env.example .env          # fill in secrets — at minimum JWT_SECRET
mkdir -p secrets              # drop the GEE service-account JSON here
docker compose up -d --build
```

- Dashboard → <http://localhost:8080>
- API docs → <http://localhost:8000/docs>
- Health → <http://localhost:8000/health>

Create an officer account:

```bash
make officer PASS=your-password
# paste the hash into OFFICER_ACCOUNTS as  username:$2b$12$...
docker compose restart backend
```

On a fresh install every district shows `🔴 UNVALIDATED DISTRICT`. That is
correct: no ground truth has been loaded yet.

### Local development

```bash
make install
make env
make migrate      # apply the PostGIS schema
make api          # FastAPI on :8000
make web          # Vite on :5173 (proxies /api to :8000)
```

---

## Bringing a district online

```bash
# 1. Confirm the district exists in the live GAUL collection.
make districts

# 2. Load field-verified parcels (see data/ground_truth/README.md).
python -m ml_pipeline.load_ground_truth data/ground_truth/kolar_2024.geojson \
    --district Kolar --verified-by "R. Shastri, Horticulture Dept (Kolar)" \
    --compute-indices

# 3. Seed 60 days of composites so the cache is warm.
make seed

# 4. Train, once there are ≥30 verified parcels and ≥5 per class.
make train

# 5. Fill in the yield baselines, or projected tonnage stays withheld.
make yields       # shows which crops are still unverified
```

Steps 2 and 5 are the ones that cannot be automated: they are where a human
takes responsibility for a claim.

---

## Design notes

### Dynamic district resolution

GAUL 2015 still spells several Karnataka districts the old way — *Bangalore
Rural*, *Tumkur*, *Chikmagalur*. Hard-coding a mapping would silently query the
wrong polygon the day GAUL is republished. `gee_districts.resolve_districts()`
pulls the live `ADM2_NAME` list at runtime and matches by exact key, then known
transliteration alias, then fuzzy ratio above 0.82. Anything below that is
returned as **unresolved** and skipped — never matched to a neighbouring
district. The mapping is auditable with `make districts`.

### Native-resolution aggregation

`reduceRegions` always runs at `scale=10`. Aggregating coarser would let Earth
Engine serve a resampled pyramid level, which changes the statistics for the
sub-hectare parcels that dominate this belt. Parcels are reduced in batches of
250 and composite windows are iterated one at a time in Python rather than
through a server-side `ee.List.map`, which is what keeps district-wide runs
under the Earth Engine memory ceiling.

### The eleven indices

NDVI, EVI, NDMI, SAVI, NDRE, GNDVI, CIG, LSWI, NDWI, BSI, RENDVI — each defined
once in `INDEX_SPECS` as a triple of (bands, NumPy function, Earth Engine
expression). The NumPy form is verified against hand-computed 2×2 matrices; the
Earth Engine expression is what runs server-side. A test asserts the expression
references exactly the declared bands, so the two forms cannot drift apart.

NDMI and LSWI are the same formula on different NIR bands (B8 vs B8A), which is
how the literature defines them. That is documented rather than deduplicated.

### Parcel-grouped splits

One parcel contributes a row per composite date, and those rows are near
duplicates. A plain stratified split would scatter a parcel across train and
test, and the reported accuracy would mostly measure memorisation. Training uses
`StratifiedGroupKFold` throughout — for the 80/20 hold-out and the 5-fold CV —
so a parcel lands wholly on one side. Cohen's kappa is the headline metric
because raw accuracy flatters a fallow-dominated label set.

Training refuses outright below 30 verified parcels or 5 per class.

### The AGMARKNET key sanitiser

The data.gov.in feed has shipped `Modal_Price`, `modal_price` and
`Modal_x0020_Price` at different times. `sanitise_key` folds all three onto one
canonical snake_case name, handles camelCase, and preserves unrecognised keys
instead of dropping them so a new upstream column shows up in logs. Every
spelling is pinned by a test.

The daily price resource does not reliably publish arrival tonnage. When it is
absent, `arrival_volume` stays `NULL` and the oversupply ratio is reported as
undefined. It is never inferred from price movement.

---

## API

| Endpoint | Purpose |
| -------- | ------- |
| `GET /api/v1/map/crops` | Parcel GeoJSON, filtered by district/date, with verification status and badges |
| `GET /api/v1/forecast/supply` | Projected supply and the mandi arrival ratio |
| `GET /api/v1/prices/mandi` | Live AGMARKNET with the 30-day cached fallback |
| `GET /api/v1/parcel/{id}/ndvi` | One parcel's index history |
| `GET /api/v1/officer/telemetry` | Role-gated pipeline status, GEE tile health, ground-truth audit |

Plus `POST /api/v1/auth/login`, `GET /api/v1/officer/model` (confusion matrix),
`POST /api/v1/officer/parcels/{id}/verify`, and the Twilio webhooks.

The public dashboard is unauthenticated by design — price transparency is the
point. The officer console requires a bearer token with the `officer` role.

---

## WhatsApp advisory bot

Farmers register over WhatsApp (district → crops), then use `PRICE`, `SUPPLY`,
`KANNADA`/`ENGLISH`, `STOP`. Every farmer-facing string exists in English and
Kannada, and Kannada input is accepted (`ಟೊಮಾಟೊ`, `ಕೋಲಾರ`). A weekly briefing
goes out Monday morning.

Outbound messages are written to `outbound_messages` in PostGIS *before* the
send is attempted, so a crash mid-send leaves the advisory queued rather than
lost. Twilio failures retry with exponential backoff (1→32 min, then abandoned),
and a 15-minute sweeper re-arms anything whose retry task died with the broker —
the queue lives in PostGIS, so nothing depends on Redis surviving.

Webhook signatures are validated against `PUBLIC_BASE_URL`, not the incoming
request, because behind a proxy the request's own host is the proxy's.

---

## Tests

```bash
make test          # 192 tests
make test-indices  # just the index math, verbose
```

Coverage is concentrated where correctness is checkable without a live
dependency: the index formulas (against hand-computed matrices), the district
matching policy, compositing windows, the supply arithmetic and its refusals,
the AGMARKNET sanitiser, the status-badge vocabulary and the bilingual
catalogue. Earth Engine and Twilio calls are not mocked into fake data — they
are simply out of scope for the suite.

---

## Scheduled jobs

| Task | Schedule (IST) |
| ---- | -------------- |
| Sentinel-2 ingestion | daily 02:30 |
| Classification | daily 04:00 |
| AGMARKNET refresh | daily 19:00 |
| Weekly farmer briefings | Monday 07:00 |
| Outbound queue sweep | every 15 min |

---

## Known limits

- **Yield baselines ship unfilled.** Projected tonnage is unavailable until an
  operator fills and verifies `data/reference/baseline_yields.yml`. This is the
  designed behaviour, but it does mean a fresh deployment reports area without
  volume.
- **`Leafy Greens` is an aggregate class** (amaranth, spinach, coriander,
  fenugreek) with multiple harvests per season. Any single yield constant for it
  is coarse; the config asks the operator to state the basis explicitly.
- **Season is not modelled.** Kharif and rabi onion have materially different
  yields and the classifier does not currently split by season.
- **AGMARKNET commodity filtering** queries one commodity per request, so the
  `Leafy Greens` aggregate is covered primarily by the unfiltered district
  sweep.
- **GAUL 2015 predates some district reorganisations.** Districts created after
  that snapshot will not resolve and are reported as unresolved rather than
  approximated.

---

## Data sources

- **Sentinel-2 L2A** — `COPERNICUS/S2_SR_HARMONIZED` via Google Earth Engine (ESA Copernicus)
- **District boundaries** — `FAO/GAUL/2015/level2`
- **Mandi prices** — AGMARKNET, republished on [data.gov.in](https://data.gov.in)
- **Yield baselines** — operator-supplied, from Karnataka Dept of Horticulture / DES / NHB

# Running NEYOGI

Everything below runs from the project folder:

```
C:\Users\pavan\OneDrive\Desktop\neyogi final\neyogi
```

Open PowerShell there, or `cd` into it first.

---

## The short version

The stack is already built. To use it day to day you only need three commands.

```powershell
docker compose up -d      # start everything
docker compose ps         # check it is healthy
docker compose down       # stop everything
```

Then open **<http://localhost:8080/dashboard>**.

That is the whole loop. The rest of this file is for when something needs
more than that.

---

## What is running

`docker compose up -d` starts six containers. They talk to each other by name
on a private network; only three are reachable from your browser.

| Service | What it is | Where you reach it |
| --- | --- | --- |
| **frontend** | The React dashboard, served by nginx | <http://localhost:8080> |
| **backend** | The FastAPI service | <http://localhost:8000> |
| **postgis** | PostgreSQL + PostGIS, all the data | `localhost:5433` |
| worker | Celery — ingestion, prices, classification | not exposed |
| beat | Celery scheduler | not exposed |
| redis | Queue behind worker and beat | not exposed |

Postgres is on **5433**, not the usual 5432, because you already have
PostgreSQL 18 running on 5432. Both can run at once.

### Pages

| Page | URL |
| --- | --- |
| Dashboard (public) | <http://localhost:8080/dashboard> |
| Officer console | <http://localhost:8080/officer> |
| API docs, interactive | <http://localhost:8000/docs> |
| Health check | <http://localhost:8000/health> |

**Officer login:** `pavan` / `6Q8mEicLRzw45zLVndaN`

---

## Everyday commands

### Start, stop, restart

```powershell
docker compose up -d              # start (or resume) everything
docker compose stop               # stop, keep the containers
docker compose start              # start them again
docker compose down               # stop and remove containers (data survives)
docker compose restart backend    # bounce one service
```

`docker compose down` is safe. Your database lives in a Docker volume that
outlives the containers, so parcels, prices and classifications are all still
there next time you bring it up.

### After you change code

```powershell
docker compose up -d --build              # rebuild everything that changed
docker compose up -d --build backend      # rebuild just one service
```

### After you edit `.env`

Environment variables are read when a container starts, so a plain `restart`
will not pick them up. You need a recreate:

```powershell
docker compose up -d --force-recreate backend worker beat
```

### Watch what is happening

```powershell
docker compose logs -f              # all services, live
docker compose logs -f backend      # just the backend
docker compose logs --tail 50 backend
```

`Ctrl+C` stops following; it does not stop the service.

---

## Running without Docker

Useful when you want to change Python or React code and see it immediately,
without a rebuild each time. You still need the database, so leave that
container running.

**Terminal 1 — database only**

```powershell
docker compose up -d postgis redis
```

**Terminal 2 — backend with auto-reload**

```powershell
python -m pip install -r backend/requirements.txt
$env:DATABASE_URL = "postgresql://neyogi:<password from .env>@localhost:5433/neyogi"
uvicorn backend.main:app --reload --port 8000
```

The password is the `POSTGRES_PASSWORD` line in `.env`. Note **5433** — you are
reaching the container from outside now, not from another container.

**Terminal 3 — frontend with hot reload**

```powershell
cd frontend
npm install        # first time only
npm run dev
```

That serves on <http://localhost:5173> and proxies `/api` through to
whatever is on port 8000, so the two halves find each other.

Edit a `.jsx` file and the browser updates on save. Edit a `.py` file and
uvicorn restarts itself.

---

## Checking things are healthy

```powershell
docker compose ps
```

You want six lines all saying `healthy`. If one says `unhealthy` or
`restarting`, read its log:

```powershell
docker compose logs --tail 40 backend
```

A quick end-to-end check:

```powershell
curl http://localhost:8000/health
```

The `configured` block in the reply tells you which external services have
credentials:

```json
"configured": { "agmarknet": true, "twilio": false, "earth_engine": true }
```

### Tests

```powershell
docker compose exec backend python -m pytest ml_pipeline/tests backend/tests -q
```

237 tests, a couple of seconds. Or without Docker: `python -m pytest ml_pipeline/tests backend/tests -q`

### Diagnostics

```powershell
docker compose exec backend python scripts/check_gee.py           # Earth Engine, four ordered checks
docker compose exec backend python scripts/verify_boundary_fix.py # district boundaries
docker compose exec backend python scripts/gaul_names.py          # what GAUL calls each district
```

---

## Pipeline tasks

These are the jobs that put data into the system. `beat` runs them on a
schedule; these commands run one now.

```powershell
# Classify a district's cropland from satellite imagery (~1-2 min)
curl -X POST "http://localhost:8000/api/v1/classification/run?district=Kolar&samples=400"

# Pull the latest mandi prices from AGMARKNET
docker compose exec worker python -c "from backend.workers.tasks import refresh_prices; print(refresh_prices())"

# Backfill 60 days of Sentinel-2 composites
docker compose exec backend python -m ml_pipeline.gee_ingestion --seed

# Load field-verified parcels (see data/ground_truth/README.md)
docker compose exec backend python -m ml_pipeline.load_ground_truth `
    data/ground_truth/<file>.geojson --district Kolar `
    --verified-by "Name, Dept" --compute-indices

# Load a cold storage register (see data/cold_storage/README.md)
docker compose exec backend python -m ml_pipeline.load_cold_storage `
    data/cold_storage/<file>.csv --source "NHB Directory" --source-year 2023
```

---

## Looking at the database

```powershell
docker compose exec postgis psql -U neyogi -d neyogi
```

Then at the `neyogi=#` prompt: `\dt` lists tables, `\q` quits.

Or a single query without the prompt:

```powershell
docker compose exec postgis psql -U neyogi -d neyogi -c "SELECT district, crop, area_ha FROM district_classification_latest;"
```

Useful ones:

```sql
SELECT district, crop, round(area_ha::numeric) AS ha, mean_confidence
FROM district_classification_latest ORDER BY district;

SELECT name, district, capacity_mt, cost_per_tonne_day
FROM cold_storage_facilities ORDER BY district;

SELECT count(*) FROM mandi_prices_cache;

SELECT stage, district, ok, created_at
FROM pipeline_runs ORDER BY created_at DESC LIMIT 10;
```

---

## When something looks wrong

**Every panel is empty and the sidebar dots are red.**
The backend is probably down or restarting. `docker compose ps`, then
`docker compose logs --tail 40 backend`.

**502 from the dashboard, but `localhost:8000` works.**
nginx lost the backend. `docker compose restart frontend`.

**The dashboard looks stale after a rebuild.**
Browser cache. Hard refresh with `Ctrl+Shift+R`.

**Docker says the port is in use.**
Something else holds 8080, 8000 or 5433. Find it:
`Get-NetTCPConnection -LocalPort 8080 | Select-Object OwningProcess`

**Start fresh, keeping the data:**

```powershell
docker compose down
docker compose up -d --build
```

**Start completely fresh, deleting the data** — this erases parcels, prices
and classifications, and the schema is recreated on next start:

```powershell
docker compose down -v
docker compose up -d --build
```

---

## Where things live

```
neyogi/
├── .env                      secrets and settings — not in git
├── secrets/                  Earth Engine service-account key — not in git
├── docker-compose.yml        what runs, and how
├── backend/                  FastAPI service
│   ├── api/v1/               the endpoints
│   ├── services/             the logic behind them
│   └── sql/                  database schema, applied on start-up
├── ml_pipeline/              satellite ingestion and the classifier
│   └── models/               the trained model file
├── frontend/src/             React dashboard
│   ├── pages/                Dashboard, OfficerConsole, Login
│   └── components/           the cards
├── data/
│   ├── reference/            yield and market constants
│   ├── ground_truth/         field parcels (none loaded yet)
│   └── cold_storage/         facility register
└── scripts/                  diagnostics
```

The two files most worth knowing:

- **`.env`** — every credential and setting. Editing it needs a
  `--force-recreate`, not a restart.
- **`data/reference/baseline_yields.yml`** — the yield and market-absorption
  constants. Its header explains what each one does and why it must be
  sourced rather than guessed.

---

## What is and is not working today

Working: the dashboard, the map with live Sentinel-2 NDVI, crop
classification, cold storage with hold-or-sell figures, the officer console.

Not showing data yet, and why:

- **Mandi prices and Best Markets** — AGMARKNET (data.gov.in) has been
  unreachable for several days. The key is configured; the feed is down. It
  will populate on its own when they come back.
- **Supply Pressure** — withheld for Kolar. The crop areas behind it come
  from a model whose confidence is below the floor required to turn an area
  into a tonnage claim. The card explains this where it appears.

Neither is a fault in the app. Both are cases of it declining to show a number
it cannot stand behind, which is the behaviour it was built for.

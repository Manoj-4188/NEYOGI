# Cold storage registers

Cold storage is the practical answer to an oversupply warning. If NEYOGI
projects that the belt will out-produce recent mandi arrivals, a grower's
alternative to selling into a falling market is to hold — and holding needs a
facility within reach.

This directory holds the register files that populate that layer. **No register
ships with the repository**; the files below have to be obtained and placed
here, for the same reason no sample parcels ship: a plausible-looking invented
facility list would send someone to an address that does not exist.

---

## What NEYOGI stores, and what it refuses to

| Field | Stored? | Notes |
| --- | --- | --- |
| Name, district, taluk, address | Yes | As published. |
| **Licensed capacity (MT)** | Yes | Nameplate figure from the register. |
| Coordinates | Yes, when published | A row without them is listed but **not mapped**. |
| Ownership, commodity focus | Yes, when published | Normalised to a small set. |
| **Available / free space** | **No** | See below. |

### Why there is no "space available"

India has no public feed of real-time cold storage utilisation. The Ministry of
Agriculture has stated that capacity utilisation is not centrally maintained and
that no real-time monitoring system exists. Any availability figure this
platform displayed would therefore be invented — and a farmer who loaded a
truck on it could arrive at a full facility, having spent fuel and lost a day
during the few days a perishable crop stays saleable.

So the API returns `utilisation_available: false`, every capacity is labelled
*licensed*, and the UI tells the reader to call ahead. If a state ever publishes
a live utilisation feed, it belongs in a new column with its own status badge —
not as an estimate derived from these numbers.

### Why unmapped facilities are not geocoded

A register row without coordinates is loaded with a `NULL` geometry: counted in
the district total, listed in the panel, absent from the map. It would be easy
to drop a pin on the district or taluk centroid, and that pin would be wrong —
it would show a real, findable business at a location it does not occupy. The
loader also discards coordinate pairs that fall outside Karnataka's bounding
box, since those are almost always lat/lon transposed at export, and guessing
which way round they belong would move the facility rather than fix it.

---

## Where to get a register

1. **NHB National Cold Storage Database** — <https://www.nhb.gov.in/csrIndex.aspx>
   The primary national directory. Note that the underlying survey dates from
   2012–13, so record `--source-year` accurately; the UI surfaces it.
2. **NHB Integrated Cold Chain Availability Platform (ICAP)** —
   <https://nhb.gov.in/IcapMap/ICAPMap_rpt.aspx>
   Newer, with a map view. It is an ASP.NET postback report rather than an API,
   so export from the UI rather than scripting against it.
3. **Karnataka State Department of Horticulture** —
   <https://horticulture.karnataka.gov.in> — often has the most current
   district-level list, including facilities aided under state schemes.
4. **Ministry of Food Processing Industries** — scheme-wise lists of cold chain
   projects sanctioned under PMKSY.
5. **data.gov.in** — search "cold storage"; several state-wise capacity
   resources are published, though most are aggregate rather than facility-level.

Prefer a facility-level list with coordinates. A state-level aggregate cannot
populate this layer, because the question the panel answers is *which* facility,
not how many tonnes exist statewide.

---

## File format

CSV with a header row, or a GeoJSON `FeatureCollection` of points. Column names
are matched case-insensitively against a set of aliases, so most registers load
without reshaping. Recognised names include:

| Field | Accepted column names |
| --- | --- |
| Name | `name`, `facility_name`, `cold_storage_name`, `unit_name`, `firm_name` |
| Identifier | `facility_uid`, `licence_no`, `license_no`, `registration_no`, `id` |
| District | `district`, `district_name`, `dist` |
| Taluk | `taluk`, `taluka`, `tehsil`, `block`, `mandal` |
| Capacity | `capacity_mt`, `capacity`, `installed_capacity`, `licensed_capacity` |
| Coordinates | `latitude`/`longitude`, `lat`/`lon`, `lat`/`lng` |
| Ownership | `ownership`, `sector`, `type` |
| Commodity | `commodity`, `commodity_focus`, `produce` |

Capacity values may carry a unit suffix (`5000 MT`, `5,000 tonnes`) — the loader
strips it. A blank or unparseable capacity is stored as `NULL`, never estimated.

### Minimal CSV example

```csv
name,district,taluk,capacity_mt,latitude,longitude,ownership
Sri Venkateshwara Cold Storage,Kolar,Malur,5000,13.0034,77.9385,private
KAPPEC Cold Unit,Kolar,Kolar,3200,13.1367,78.1291,government
```

---

## Loading

Validate without writing:

```bash
python -m ml_pipeline.load_cold_storage data/cold_storage/<file>.csv \
    --source "NHB Cold Storage Directory" --source-year 2023 --dry-run
```

Load for real:

```bash
python -m ml_pipeline.load_cold_storage data/cold_storage/<file>.csv \
    --source "NHB Cold Storage Directory" \
    --source-url https://www.nhb.gov.in/csrIndex.aspx \
    --source-year 2023
```

Inside Docker, prefix with `docker compose exec backend`.

`--source` and `--source-year` are not decoration: they are shown in the UI
badge so nobody reads a decade-old directory as a current one. Record the
vintage of the document you actually used, not the year you loaded it.

Re-running the same file updates rather than duplicates, keyed on
`(facility_uid, district)`. A re-import that omits coordinates will not erase
coordinates already stored.

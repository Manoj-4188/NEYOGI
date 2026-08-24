# Ground truth — digitised field parcels

This directory holds the GeoJSON files that are the evidential foundation of
NEYOGI. Everything the platform claims about crops traces back to a polygon
here that a named person attributed to a named crop.

**No sample or example parcel file ships in this repository.** That is
deliberate. A plausible-looking synthetic parcel set would train a model, fill
a dashboard and produce oversupply warnings that look exactly like real ones.
The schema and a worked example are documented below instead; the data itself
has to come from the field.

Until real parcels are loaded, every district reports
`🔴 UNVALIDATED DISTRICT (No Verified Labels)` and renders as a raw Sentinel-2
NDVI basemap. That is the correct behaviour, not a broken state.

---

## File format

A GeoJSON `FeatureCollection` in **EPSG:4326** (RFC 7946 requires it; a file
declaring another CRS is rejected rather than reprojected on a guess).

Each feature needs a `Polygon` or `MultiPolygon` geometry and these properties:

| Property        | Required | Notes |
| --------------- | -------- | ----- |
| `parcel_uid`    | Recommended | Stable identifier — survey number, or the source system's feature id. If absent, a deterministic `<filename>#<n>` is generated so re-running the same file updates rather than duplicates rows. |
| `district`      | Yes\*    | May be supplied per-feature or once via `--district`. |
| `crop_label`    | Yes\*\*  | Must resolve to one of the five classes (see below). |
| `verified_by`   | Yes\*\*\* | The person or survey standing behind the label. |
| `survey_date`   | Optional | `YYYY-MM-DD`, `DD-MM-YYYY` or `DD/MM/YYYY`. |

\* Per-feature `district` wins over the `--district` flag.
\*\* Omit only with `--allow-unlabelled`, which loads boundaries that stay
unverified and unusable for training.
\*\*\* Per-feature `verified_by` wins over `--verified-by`. **A parcel is marked
`verified_flag = TRUE` only when it has both a crop label and an attributor** —
the database enforces this with a `CHECK` constraint, and the classifier reads
nothing else.

### Crop classes

`Tomato`, `Onion`, `Potato`, `Leafy Greens`, `Fallow/Non-Crop`.

Common spellings and Kannada/Hindi names are accepted (`tamatar`, `eerulli`,
`alugadde`, `soppu`, `palak`, …); see `LABEL_ALIASES` in
`ml_pipeline/load_ground_truth.py`. **An unrecognised label aborts the whole
file** with a list of the offending values. It is never coerced to the nearest
class — a mislabelled training parcel is worse than a rejected file.

`Fallow/Non-Crop` is a real, surveyed class. It is not a bucket for parcels
nobody was sure about; leave those out.

---

## Worked example

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[78.1301, 13.1364], [78.1318, 13.1364],
                         [78.1318, 13.1349], [78.1301, 13.1349],
                         [78.1301, 13.1364]]]
      },
      "properties": {
        "parcel_uid": "KLR-MLB-114/2",
        "district": "Kolar",
        "crop_label": "Tomato",
        "verified_by": "R. Shastri, Horticulture Dept (Kolar)",
        "survey_date": "2024-06-18"
      }
    }
  ]
}
```

`data/ground_truth/schema.json` is a JSON Schema for the same structure; run it
through any validator before loading a large survey.

---

## Loading

Validate without writing anything:

```bash
python -m ml_pipeline.load_ground_truth data/ground_truth/kolar_2024.geojson \
    --district Kolar --dry-run
```

Load, and build the spectral time series for the loaded parcels:

```bash
python -m ml_pipeline.load_ground_truth data/ground_truth/kolar_2024.geojson \
    --district Kolar \
    --verified-by "R. Shastri, Horticulture Dept (Kolar)" \
    --compute-indices
```

Validation is all-or-nothing per file, so a partially bad survey never
half-loads.

Areas are **not** taken from the source file. They are recomputed server-side in
an equal-area projection (EPSG:6933) at ingest, because hectare figures feed
directly into projected tonnage.

---

## How much is enough?

`ml_pipeline/train_classifier.py` refuses to train below:

- **30 verified parcels** overall (`MIN_TOTAL_PARCELS`), and
- **5 distinct verified parcels per class** (`MIN_PARCELS_PER_CLASS`).

These are floors, not targets. A parcel contributes one row per 16-day
composite, so a modest survey yields a lot of rows — but the splits are
*grouped by parcel*, so it is the parcel count, not the row count, that
constrains what the model can honestly claim.

The officer console's ground-truth audit shows the current count against these
floors per class.

---

## Collection notes

- **Digitise the cultivated extent**, not the revenue boundary. Bunds, channels
  and access paths inside a survey number dilute the spectral signature.
- **Record the survey date.** A parcel labelled in June says nothing about the
  same field in November; the model consumes composites near the survey window.
- **Sub-hectare parcels are fine.** Aggregation runs at Sentinel-2's native 10 m,
  so a 0.4 ha plot still contributes ~40 pixels.
- **Include fallow deliberately.** Without surveyed `Fallow/Non-Crop` parcels the
  classifier has no negative class and will over-assign crops to bare soil.

/**
 * Data-source readiness checklist.
 *
 * A fresh NEYOGI deployment is legitimately empty: it will not show a crop, a
 * price or a tonnage it cannot evidence. Left unexplained that reads as a
 * broken app, so this panel states exactly which inputs are present, which are
 * missing, and the command or credential that supplies each one.
 *
 * Every row is derived from a live server response -- /health for credentials,
 * /api/v1/map/districts for ground truth. Nothing is assumed or hard-coded.
 */

import { Icon } from './EmptyState.jsx';

function Row({ ready, label, detail, action, unlocks }) {
  return (
    <li className="flex gap-3 px-4 py-3">
      <span
        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold
                    ${ready ? 'bg-sage text-white' : 'border border-dashed border-terracotta-200 bg-terracotta-100 text-terracotta-600'}`}
        aria-hidden="true"
      >
        {ready ? '✓' : ''}
      </span>

      <div className="min-w-0 flex-1">
        <p
          className={`text-sm font-medium ${ready ? 'text-forest' : 'text-forest-900'}`}
        >
          {label}
        </p>
        <p className="mt-0.5 text-xs leading-relaxed text-forest-900/60">{detail}</p>

        {!ready && action ? (
          <code
            className="mt-1.5 block max-w-full overflow-x-auto whitespace-pre rounded border border-parchment-300
                       bg-parchment px-2 py-1.5 font-mono text-[11px] text-forest-900/75"
          >
            {action}
          </code>
        ) : null}

        {!ready && unlocks ? (
          <p className="mt-1 text-[11px] text-sage-600">Unlocks: {unlocks}</p>
        ) : null}
      </div>
    </li>
  );
}

export default function SetupProgress({ health, districts }) {
  const configured = health?.configured || {};
  const validated = (districts || []).filter((d) => d.is_validated).length;
  const parcels = (districts || []).reduce((n, d) => n + (d.parcel_count || 0), 0);

  const steps = [
    {
      key: 'db',
      ready: Boolean(health?.dependencies?.[0]?.healthy),
      label: 'PostGIS database',
      detail: health?.dependencies?.[0]?.detail || 'Spatial store for parcels, indices and the price cache.',
    },
    {
      key: 'agmarknet',
      ready: Boolean(configured.agmarknet),
      label: 'AGMARKNET market feed',
      detail: configured.agmarknet
        ? 'API key configured. Live mandi prices are fetched, with a 30-day cached fallback.'
        : 'No API key. Mandi prices and the arrivals side of the supply ratio are unavailable.',
      action: 'AGMARKNET_API_KEY=…   # free key from data.gov.in',
      unlocks: 'live prices, price history, oversupply denominator',
    },
    {
      key: 'gee',
      ready: Boolean(configured.earth_engine),
      label: 'Google Earth Engine',
      detail: configured.earth_engine
        ? 'Service account configured. Sentinel-2 composites can be ingested.'
        : 'No service account. Satellite imagery, NDVI basemaps and all 11 spectral indices are unavailable.',
      action: 'secrets/gee_service_account.json + GEE_PROJECT_ID',
      unlocks: 'NDVI basemap, vegetation indices, crop classification inputs',
    },
    {
      key: 'groundtruth',
      ready: validated > 0,
      label: 'Field-verified ground truth',
      detail:
        validated > 0
          ? `${validated} district(s) validated from ${parcels} loaded parcel(s).`
          : `No district has field-verified parcels${parcels ? ` (${parcels} boundaries loaded, none verified)` : ''}. Crop classification stays off — no label is ever inferred without one.`,
      action:
        'python -m ml_pipeline.load_ground_truth data/ground_truth/<file>.geojson \\n  --district Kolar --verified-by "Name, Dept" --compute-indices',
      unlocks: 'crop classes on the map, classified area, supply projections',
    },
    {
      key: 'twilio',
      ready: Boolean(configured.twilio),
      label: 'Twilio WhatsApp (optional)',
      detail: configured.twilio
        ? 'Credentials configured. Farmer advisories can be delivered.'
        : 'Not configured. The advisory bot and weekly briefings are inactive.',
      action: 'TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN',
      unlocks: 'farmer registration, price lookups, weekly briefings',
    },
  ];

  const ready = steps.filter((s) => s.ready).length;
  const pct = Math.round((ready / steps.length) * 100);

  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Icon name="seedling" className="h-4 w-4 text-sage-600" />
          <h2 className="panel-title">Data sources</h2>
        </div>
        <span className="font-mono text-xs tabular-nums text-forest-900/60">
          {ready}/{steps.length}
        </span>
      </header>

      <div className="px-4 pt-3">
        <div
          className="h-1.5 w-full overflow-hidden rounded-full bg-parchment-200"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Data sources configured"
        >
          <div
            className="h-full rounded-full bg-sage transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <ul className="divide-y divide-parchment-200">
        {steps.map((s) => (
          <Row key={s.key} {...s} />
        ))}
      </ul>

      <p className="border-t border-parchment-200 px-4 py-2.5 text-[11px] leading-relaxed text-forest-900/50">
        NEYOGI shows nothing it cannot evidence. Panels stay empty until the
        source behind them is supplied — that is the intended behaviour, not a
        fault. After editing <code className="font-mono">.env</code>, run{' '}
        <code className="font-mono">docker compose up -d --force-recreate backend worker beat</code>.
      </p>
    </section>
  );
}

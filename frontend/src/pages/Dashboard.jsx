/**
 * Public dashboard.
 *
 * Layout: district picker, a system-wide fallback banner, the parcel map, the
 * 21-day supply-versus-arrivals chart, and the mandi price table.
 *
 * The banner and every badge are driven by the `status` objects the API
 * attaches to each response, so the page cannot show stale data without saying
 * so. Where a panel has nothing to show it explains which input is missing,
 * rather than rendering blank — see components/EmptyState.jsx.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import api from '../api/client.js';
import ColdStoragePanel from '../components/ColdStoragePanel.jsx';
import CropMap from '../components/CropMap.jsx';
import EmptyState, { Icon, SkeletonPanel } from '../components/EmptyState.jsx';
import ParcelDetails from '../components/ParcelPopup.jsx';
import PriceTable from '../components/PriceTable.jsx';
import SetupProgress from '../components/SetupProgress.jsx';
import SupplyChart, { SupplySummary } from '../components/SupplyChart.jsx';
import { FallbackBanner, StatusBadgeRow } from '../components/StatusBadge.jsx';

const CROPS = ['Tomato', 'Onion', 'Potato', 'Leafy Greens'];

function useAsync(loader, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    loader()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((error) => {
        if (!cancelled) setState({ data: null, error, loading: false });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}

function DistrictPicker({ districts, value, onChange }) {
  return (
    <label className="flex items-center gap-2">
      <span className="sr-only">District</span>
      <select
        className="field w-auto min-w-[13rem]"
        value={value || ''}
        onChange={(event) => onChange(event.target.value)}
      >
        {districts.map((entry) => (
          <option key={entry.district} value={entry.district}>
            {entry.district}
            {entry.is_validated ? '' : ' — unvalidated'}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function Dashboard() {
  const [district, setDistrict] = useState(null);
  const [crop, setCrop] = useState('Tomato');
  const [selectedParcel, setSelectedParcel] = useState(null);

  const healthState = useAsync(() => api.health().catch(() => null), []);
  const districtsState = useAsync(() => api.districts(), []);

  // Memoised: a fresh `[]` on every render would re-fire the default-district
  // effect below on every render.
  const districts = useMemo(
    () => districtsState.data?.districts || [],
    [districtsState.data],
  );

  // Default to the first validated district so the map opens on something
  // meaningful; fall back to the first district if none are validated yet.
  useEffect(() => {
    if (district || !districts.length) return;
    const validated = districts.find((d) => d.is_validated);
    setDistrict((validated || districts[0]).district);
  }, [districts, district]);

  const cropsState = useAsync(
    () => (district ? api.crops({ district }) : Promise.resolve(null)),
    [district],
  );
  const forecastState = useAsync(
    () => (district ? api.supplyForecast({ district }) : Promise.resolve(null)),
    [district],
  );
  const pricesState = useAsync(
    () => (district ? api.mandiPrices({ district, crop }) : Promise.resolve(null)),
    [district, crop],
  );
  const coldStorageState = useAsync(
    () => (district ? api.coldStorage({ district }) : Promise.resolve(null)),
    [district],
  );

  const collection = cropsState.data;
  const forecast = forecastState.data;
  const prices = pricesState.data;
  const health = healthState.data;

  // Merge every response's badges into one banner so the user sees the whole
  // system's state, not one endpoint's.
  const combinedStatus = useMemo(() => {
    const badges = [];
    const seen = new Set();
    [collection?.properties?.status, forecast?.status, prices?.status].forEach((status) => {
      (status?.badges || []).forEach((badge) => {
        const key = `${badge.source}-${badge.status}-${badge.as_of}`;
        if (!seen.has(key)) {
          seen.add(key);
          badges.push(badge);
        }
      });
    });
    const worst = badges.some((b) => b.severity === 'error')
      ? 'error'
      : badges.some((b) => b.severity === 'warn')
        ? 'warn'
        : 'ok';
    return {
      badges,
      degraded: badges.some((b) => b.is_fallback || b.severity !== 'ok'),
      worst_severity: worst,
    };
  }, [collection, forecast, prices]);

  const handleSelectParcel = useCallback((props) => setSelectedParcel(props), []);

  const validation = collection?.properties?.validation;
  const isValidated = Boolean(validation?.is_validated);
  const anyValidated = districts.some((d) => d.is_validated);
  const hasPrices = (prices?.quote_count || 0) > 0;
  const agmarknetReady = Boolean(health?.configured?.agmarknet);
  const setupIncomplete =
    !anyValidated || !agmarknetReady || !health?.configured?.earth_engine;

  const loadCommand = [
    'python -m ml_pipeline.load_ground_truth \\',
    `  data/ground_truth/<file>.geojson --district ${district || 'Kolar'} \\`,
    '  --verified-by "Name, Dept" --compute-indices',
  ].join('\n');

  const refreshCommand = [
    'docker compose exec worker python -c \\',
    '  "from backend.workers.tasks import refresh_prices; print(refresh_prices())"',
  ].join('\n');

  const errors = [
    districtsState.error,
    cropsState.error,
    forecastState.error,
    pricesState.error,
  ].filter(Boolean);

  return (
    <div className="mx-auto max-w-[100rem] px-4 py-6 lg:px-8">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-forest">
            Perishable Crop Market Intelligence
          </h1>
          <p className="mt-1 text-sm text-forest-900/70">
            Sentinel-2 crop mapping and AGMARKNET price signals for Karnataka&rsquo;s
            vegetable belt.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <DistrictPicker districts={districts} value={district} onChange={setDistrict} />
          <div className="flex rounded-lg border border-parchment-300 bg-white p-0.5">
            {CROPS.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => setCrop(name)}
                className={
                  crop === name
                    ? 'rounded-md bg-forest px-3 py-1.5 text-sm font-medium text-parchment shadow-sm transition'
                    : 'rounded-md px-3 py-1.5 text-sm font-medium text-forest-900/70 transition hover:bg-parchment'
                }
              >
                {name}
              </button>
            ))}
          </div>
        </div>
      </header>

      {errors.length ? (
        <div className="mb-4 rounded-xl border border-terracotta-200 bg-terracotta-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-terracotta-600">
            Some data could not be loaded
          </h2>
          <ul className="mt-1.5 space-y-1 text-sm text-forest-900/80">
            {errors.map((error, index) => (
              // eslint-disable-next-line react/no-array-index-key
              <li key={index}>{error.message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <FallbackBanner status={combinedStatus} className="mb-4" />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section className="panel overflow-hidden">
          <header className="panel-header">
            <div>
              <h2 className="panel-title">{district || 'Select a district'}</h2>
              {validation ? (
                <p className="mt-0.5 text-xs text-forest-900/60">
                  {validation.verified_count} verified of {validation.parcel_count} parcels
                  {validation.verified_area_ha
                    ? ` · ${validation.verified_area_ha.toLocaleString()} ha verified`
                    : ''}
                </p>
              ) : null}
            </div>
            <StatusBadgeRow status={collection?.properties?.status} />
          </header>

          <div className="h-[30rem]">
            {cropsState.loading ? (
              <SkeletonPanel label="Loading parcels…" />
            ) : collection?.features?.length ? (
              <CropMap
                collection={collection}
                basemapTile={collection?.properties?.basemap_tile}
                coldStores={coldStorageState.data?.facilities}
                onSelectParcel={handleSelectParcel}
              />
            ) : (
              <div className="flex h-full items-center justify-center px-6">
                <EmptyState
                  icon="map"
                  tone="blocked"
                  title={`No parcels loaded for ${district || 'this district'}`}
                  body="The map draws digitised field boundaries. None have been ingested for this district yet, so there is nothing to render — NEYOGI will not synthesise plots to fill the view."
                  command={loadCommand}
                  footnote="Format and a worked example: data/ground_truth/README.md"
                />
              </div>
            )}
          </div>
        </section>

        <div className="space-y-5">
          {selectedParcel ? (
            <ParcelDetails parcel={selectedParcel} onClose={() => setSelectedParcel(null)} />
          ) : null}

          {setupIncomplete ? (
            <SetupProgress health={health} districts={districts} />
          ) : null}

          <ColdStoragePanel
            payload={coldStorageState.data}
            loading={coldStorageState.loading}
            district={district}
          />

          {forecast?.crops?.length ? (
            <div className="space-y-3">
              <h2 className="panel-title">Supply outlook</h2>
              {forecast.crops.map((entry) => (
                <SupplySummary key={entry.crop} crop={entry} />
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <section className="panel mt-5">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Icon name="chart" className="h-4 w-4 shrink-0 text-sage-600" />
            <div>
              <h2 className="panel-title">
                {crop} — supply vs mandi arrivals ({forecast?.window_days || 21} days)
              </h2>
              {forecast?.notes?.length ? (
                <p className="mt-0.5 max-w-3xl text-xs text-forest-900/60">
                  {forecast.notes.join(' ')}
                </p>
              ) : null}
            </div>
          </div>
        </header>

        <div className="px-4 py-4">
          {forecastState.loading ? (
            <SkeletonPanel label="Loading forecast…" />
          ) : !isValidated ? (
            <EmptyState
              icon="seedling"
              tone="blocked"
              title="Supply projection needs verified ground truth"
              body={`${district || 'This district'} has no field-verified parcels, so there is no classified area to project from. A crop label is never inferred from spectral data alone — that is the rule this system is built around.`}
              footnote="Load parcels, then run the classifier to populate this chart."
            />
          ) : !forecast?.daily_series?.[crop]?.length ? (
            <EmptyState
              icon="rupee"
              tone={agmarknetReady ? 'info' : 'blocked'}
              title={`No mandi arrivals recorded for ${crop}`}
              body={
                agmarknetReady
                  ? 'AGMARKNET published no arrival tonnage for this district and crop in the window. Days without a quote are left as gaps rather than drawn as zero arrivals.'
                  : 'No AGMARKNET API key is configured, so no price or arrival data can be fetched.'
              }
              command={agmarknetReady ? undefined : 'AGMARKNET_API_KEY=your_key_here'}
            />
          ) : (
            <SupplyChart
              series={forecast?.daily_series?.[crop]}
              crop={crop}
              windowDays={forecast?.window_days || 21}
            />
          )}
        </div>
      </section>

      <div className="mt-5">
        {pricesState.loading ? (
          <section className="panel">
            <header className="panel-header">
              <h2 className="panel-title">Mandi prices</h2>
            </header>
            <SkeletonPanel label="Loading prices…" />
          </section>
        ) : hasPrices ? (
          <PriceTable payload={prices} crop={crop} />
        ) : (
          <section className="panel">
            <header className="panel-header">
              <div className="flex items-center gap-2">
                <Icon name="rupee" className="h-4 w-4 shrink-0 text-sage-600" />
                <h2 className="panel-title">Mandi prices</h2>
              </div>
              <StatusBadgeRow status={prices?.status} />
            </header>
            <div className="px-4 py-4">
              <EmptyState
                icon="rupee"
                tone="blocked"
                title={`No quotes cached for ${crop} in ${district || 'this district'}`}
                body={
                  agmarknetReady
                    ? 'The AGMARKNET feed was queried and returned nothing usable, and the local cache is empty. Prices appear here as soon as the feed responds — the daily resource is published irregularly and is sometimes unreachable for hours at a time.'
                    : 'No AGMARKNET API key is configured. Register free at data.gov.in, set AGMARKNET_API_KEY, then recreate the backend.'
                }
                command={agmarknetReady ? refreshCommand : 'AGMARKNET_API_KEY=your_key_here'}
                footnote={
                  agmarknetReady
                    ? 'A key is configured — this is an upstream availability gap, not a setup problem.'
                    : undefined
                }
              />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

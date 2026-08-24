/**
 * Public dashboard.
 *
 * Layout: district picker, a system-wide fallback banner, the parcel map, the
 * 21-day supply-versus-arrivals chart, and the mandi price table.
 *
 * The banner is driven entirely by the `status` objects the API attaches to
 * each response, so the page cannot show stale data without saying so.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import api from '../api/client.js';
import CropMap from '../components/CropMap.jsx';
import ParcelDetails from '../components/ParcelPopup.jsx';
import PriceTable from '../components/PriceTable.jsx';
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

  const collection = cropsState.data;
  const forecast = forecastState.data;
  const prices = pricesState.data;

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
  const errors = [districtsState.error, cropsState.error, forecastState.error, pricesState.error]
    .filter(Boolean);

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
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                  crop === name
                    ? 'bg-forest text-parchment'
                    : 'text-forest-900/70 hover:bg-parchment'
                }`}
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
              <div className="flex h-full items-center justify-center text-sm text-sage-600">
                Loading parcels…
              </div>
            ) : (
              <CropMap
                collection={collection}
                basemapTile={collection?.properties?.basemap_tile}
                onSelectParcel={handleSelectParcel}
              />
            )}
          </div>
        </section>

        <div className="space-y-5">
          {selectedParcel ? (
            <ParcelDetails
              parcel={selectedParcel}
              onClose={() => setSelectedParcel(null)}
            />
          ) : (
            <section className="panel px-4 py-6">
              <h2 className="panel-title mb-2">Parcel detail</h2>
              <p className="text-sm text-sage-600">
                Select a parcel on the map to see its crop attribution, measured
                spectral indices and NDVI history.
              </p>
            </section>
          )}

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
        </header>
        <div className="px-4 py-4">
          {forecastState.loading ? (
            <div className="flex h-64 items-center justify-center text-sm text-sage-600">
              Loading forecast…
            </div>
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
        <PriceTable payload={prices} crop={crop} />
      </div>
    </div>
  );
}

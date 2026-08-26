/**
 * Public dashboard.
 *
 * Sidebar selects a district; everything to the right is that district. The
 * top bar carries one status word — LIVE SATELLITE or SPECTRAL MODEL — because
 * the single most important thing a reader needs to know is what kind of
 * evidence they are looking at.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import api from '../api/client.js';
import BestMarketsCard from '../components/BestMarketsCard.jsx';
import ColdStorageCard from '../components/ColdStorageCard.jsx';
import CropClassificationCard from '../components/CropClassificationCard.jsx';
import DistrictMap from '../components/DistrictMap.jsx';
import PriceChartCard from '../components/PriceChartCard.jsx';
import Sidebar from '../components/Sidebar.jsx';
import SupplyPressureCard from '../components/SupplyPressureCard.jsx';

/** District centroids, used to centre the map and measure facility distance. */
const CENTROIDS = {
  Kolar: { lat: 13.136, lon: 78.129 },
  Chikkaballapur: { lat: 13.579, lon: 77.836 },
  'Bengaluru Rural': { lat: 13.19, lon: 77.7 },
  Tumakuru: { lat: 13.34, lon: 77.1 },
  Hassan: { lat: 13.0, lon: 76.1 },
  Mandya: { lat: 12.52, lon: 76.89 },
  Mysuru: { lat: 12.29, lon: 76.64 },
  Belagavi: { lat: 15.85, lon: 74.5 },
};

function useAsync(loader, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    let cancelled = false;
    setState((p) => ({ ...p, loading: true, error: null }));
    loader()
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error) => !cancelled && setState({ data: null, error, loading: false }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export default function Dashboard() {
  const [district, setDistrict] = useState(null);

  const healthState = useAsync(() => api.health().catch(() => null), []);
  const districtsState = useAsync(() => api.districts(), []);

  const districts = useMemo(
    () => districtsState.data?.districts || [],
    [districtsState.data],
  );

  useEffect(() => {
    if (!district && districts.length) setDistrict(districts[0].district);
  }, [districts, district]);

  const mapState = useAsync(
    () => (district ? api.crops({ district }) : Promise.resolve(null)),
    [district],
  );
  const classState = useAsync(
    () => (district ? api.classification({ district }) : Promise.resolve(null)),
    [district],
  );
  const coldState = useAsync(
    () =>
      district
        ? api.coldStorage({ district, crop: 'tomato', quantityT: quintals / 10 })
        : Promise.resolve(null),
    [district, quintals],
  );
  const marketsState = useAsync(
    () =>
      district
        ? api.bestMarkets({
            district,
            cropType: 'tomato',
            quantityQuintals: quintals,
          })
        : Promise.resolve(null),
    [district, quintals],
  );
  const priceState = useAsync(
    () => (district ? api.priceHistory({ district, days: 90 }) : Promise.resolve(null)),
    [district],
  );
  const supplyState = useAsync(
    () => (district ? api.supplyForecast({ district }) : Promise.resolve(null)),
    [district],
  );

  const tile = mapState.data?.properties?.basemap_tile;
  const hasLiveSatellite = Boolean(tile);
  const hasClassification = (classState.data?.crops?.length || 0) > 0;

  // Districts carry a dot in the sidebar; enrich the list with what we know.
  const districtRows = useMemo(
    () =>
      districts.map((d) => ({
        ...d,
        has_classification:
          d.district === district ? hasClassification : Boolean(d.is_validated),
      })),
    [districts, district, hasClassification],
  );

  const lastSynced = useMemo(() => {
    const stamp = classState.data?.classified_at || healthState.data?.time;
    if (!stamp) return null;
    return new Date(stamp).toISOString().slice(0, 16).replace('T', ' ');
  }, [classState.data, healthState.data]);

  const handleSelect = useCallback((name) => setDistrict(name), []);
  const centroid = district ? CENTROIDS[district] : null;

  return (
    <div className="flex h-full">
      <Sidebar
        districts={districtRows}
        selected={district}
        onSelect={handleSelect}
        health={healthState.data}
        satelliteState={hasLiveSatellite ? 'ok' : 'degraded'}
      />

      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <header className="flex h-topbar shrink-0 items-center justify-between border-b border-line px-5">
          <h1 className="text-lg font-semibold text-ink">{district || '—'}</h1>

          <span
            className="caps"
            style={{ color: hasLiveSatellite ? '#1a5c2a' : '#d4882a' }}
          >
            {hasLiveSatellite ? 'Live satellite' : 'Spectral model'}
          </span>

          <span className="text-xs text-muted">
            {lastSynced ? `Last synced ${lastSynced}` : '—'}
          </span>
        </header>

        <div className="h-[420px] shrink-0 border-b border-line">
          <DistrictMap
            center={centroid ? [centroid.lat, centroid.lon] : null}
            basemapTile={tile}
            coldStores={coldState.data?.facilities}
            parcels={mapState.data}
          />
        </div>

        <div className="flex h-6 shrink-0 items-center border-b border-line px-4">
          <span className="text-xs text-muted">
            {tile
              ? `${tile.scene_count} Sentinel-2 scene${tile.scene_count === 1 ? '' : 's'} · Last composite ${tile.composite_start}`
              : 'No cloud-free Sentinel-2 imagery in the current composite window'}
          </span>
        </div>

        <div className="grid flex-1 grid-cols-1 lg:grid-cols-2 lg:divide-x lg:divide-line">
          <div className="flex flex-col">
            <CropClassificationCard
              payload={classState.data}
              loading={classState.loading}
              error={classState.error?.message}
              district={district}
            />
            <ColdStorageCard
              payload={coldState.data}
              loading={coldState.loading}
              district={district}
              origin={centroid}
            />
            <BestMarketsCard
              payload={marketsState.data}
              loading={marketsState.loading}
              district={district}
              onQuantityChange={setQuintals}
            />
          </div>

          <div className="flex flex-col">
            <PriceChartCard
              series={priceState.data?.series}
              loading={priceState.loading}
              windowDays={priceState.data?.window_days || 90}
            />
            <SupplyPressureCard
              payload={supplyState.data}
              loading={supplyState.loading}
              district={district}
            />
          </div>
        </div>
      </main>
    </div>
  );
}

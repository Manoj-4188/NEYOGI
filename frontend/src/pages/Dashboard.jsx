/**
 * Public dashboard.
 *
 * The sidebar picks a district; tabs split the district's information into
 * four questions rather than stacking everything on one screen:
 *
 *   Overview  — what is growing and where can it be stored
 *   Crop map  — every pixel classified
 *   Timing    — when the crop comes off
 *   Market    — prices, where to sell, and how this year compares
 *
 * Each tab loads only what it shows, so opening the dashboard does not fire
 * six requests the reader may never look at.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import api from '../api/client.js';
import BestMarketsCard from '../components/BestMarketsCard.jsx';
import ColdStorageCard from '../components/ColdStorageCard.jsx';
import CropClassificationCard from '../components/CropClassificationCard.jsx';
import CropMapPanel from '../components/CropMapPanel.jsx';
import DistrictMap from '../components/DistrictMap.jsx';
import HarvestPanel from '../components/HarvestPanel.jsx';
import PriceChartCard from '../components/PriceChartCard.jsx';
import Sidebar from '../components/Sidebar.jsx';
import SupplyPressureCard from '../components/SupplyPressureCard.jsx';
import Tabs from '../components/Tabs.jsx';
import YearComparisonPanel from '../components/YearComparisonPanel.jsx';

const CENTROIDS = {
  Kolar: { lat: 13.136, lon: 78.129 },
  Chikkaballapur: { lat: 13.435, lon: 77.727 },
  'Bengaluru Rural': { lat: 13.19, lon: 77.7 },
  Tumakuru: { lat: 13.341, lon: 77.101 },
  Hassan: { lat: 13.005, lon: 76.099 },
  Mandya: { lat: 12.523, lon: 76.895 },
  Mysuru: { lat: 12.295, lon: 76.639 },
  Belagavi: { lat: 15.849, lon: 74.498 },
};

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'map', label: 'Crop map' },
  { id: 'timing', label: 'Harvest timing' },
  { id: 'market', label: 'Market' },
];

function useAsync(loader, deps, enabled = true) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled });
  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    setState((p) => ({ ...p, loading: true, error: null }));
    loader()
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error) => !cancelled && setState({ data: null, error, loading: false }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled]);
  return state;
}

export default function Dashboard() {
  const [district, setDistrict] = useState(null);
  const [tab, setTab] = useState('overview');
  const [quintals, setQuintals] = useState(100);
  const [harvestNonce, setHarvestNonce] = useState(0);

  const healthState = useAsync(() => api.health().catch(() => null), []);
  const districtsState = useAsync(() => api.districts(), []);

  const districts = useMemo(
    () => districtsState.data?.districts || [],
    [districtsState.data],
  );

  useEffect(() => {
    if (!district && districts.length) setDistrict(districts[0].district);
  }, [districts, district]);

  // Always loaded: the top bar and the overview both need these.
  const mapState = useAsync(
    () => (district ? api.crops({ district }) : Promise.resolve(null)),
    [district],
  );
  const classState = useAsync(
    () => (district ? api.classification({ district }) : Promise.resolve(null)),
    [district],
  );

  // Tab-scoped, so a reader who never opens Market never fetches prices.
  const coldState = useAsync(
    () =>
      district
        ? api.coldStorage({ district, crop: 'tomato', quantityT: quintals / 10 })
        : Promise.resolve(null),
    [district, quintals],
    tab === 'overview',
  );
  const supplyState = useAsync(
    () => (district ? api.supplyForecast({ district }) : Promise.resolve(null)),
    [district],
    tab === 'overview',
  );
  const harvestState = useAsync(
    () => (district ? api.harvest({ district, crop: 'tomato' }) : Promise.resolve(null)),
    [district, harvestNonce],
    tab === 'timing',
  );
  const priceState = useAsync(
    () => (district ? api.priceHistory({ district, days: 90 }) : Promise.resolve(null)),
    [district],
    tab === 'market',
  );
  const marketsState = useAsync(
    () =>
      district
        ? api.bestMarkets({ district, cropType: 'tomato', quantityQuintals: quintals })
        : Promise.resolve(null),
    [district, quintals],
    tab === 'market',
  );
  const yearState = useAsync(
    () => (district ? api.yearOnYear({ district }) : Promise.resolve(null)),
    [district],
    tab === 'market',
  );

  const tile = mapState.data?.properties?.basemap_tile;
  const hasClass = (classState.data?.crops?.length || 0) > 0;

  // The satellite badge is decided server-side and carries the composite's
  // real age. The header used to show a bare yes/no, which called a fortnight
  // -old picture "recent" whenever a tile existed at all.
  const satBadge = useMemo(
    () =>
      (mapState.data?.properties?.status?.badges || []).find(
        (b) => b.source === 'satellite',
      ) || null,
    [mapState.data],
  );
  const imageryAge = satBadge?.age_days ?? null;
  const hasLive = Boolean(tile);
  const imageryOk = satBadge?.severity === 'ok';

  const imageryLabel = (() => {
    if (!satBadge) return hasLive ? 'Imagery loaded' : 'No imagery';
    if (imageryOk) return 'Recent imagery';
    if (imageryAge === null) return 'No imagery available';
    return `Imagery ${imageryAge} days old`;
  })();

  const districtRows = useMemo(
    () =>
      districts.map((d) =>
        d.district === district
          ? { ...d, has_classification: hasClass || d.has_classification }
          : d,
      ),
    [districts, district, hasClass],
  );

  const lastSynced = useMemo(() => {
    const stamp = classState.data?.classified_at || healthState.data?.time;
    return stamp ? new Date(stamp).toISOString().slice(0, 16).replace('T', ' ') : null;
  }, [classState.data, healthState.data]);

  const centroid = district ? CENTROIDS[district] : null;
  const refreshHarvest = useCallback(() => setHarvestNonce((n) => n + 1), []);

  return (
    <div className="flex h-full">
      <Sidebar
        districts={districtRows}
        selected={district}
        onSelect={setDistrict}
        health={healthState.data}
        satelliteState={imageryOk ? 'ok' : 'degraded'}
      />

      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <header className="flex h-topbar shrink-0 items-center justify-between border-b border-line px-5">
          <h1 className="text-lg font-semibold text-ink">{district || '—'}</h1>
          <span className="caps" style={{ color: imageryOk ? '#1a5c2a' : '#d4882a' }}>
            {imageryLabel}
          </span>
          <span className="text-xs text-muted">
            {lastSynced ? `Updated ${lastSynced}` : '—'}
          </span>
        </header>

        <Tabs tabs={TABS} active={tab} onChange={setTab} />

        {tab === 'overview' ? (
          <>
            <div className="h-[360px] shrink-0 border-b border-line">
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
                  ? `${tile.scene_count} clear satellite pass${tile.scene_count === 1 ? '' : 'es'} · newest ${tile.composite_start}${
                      imageryAge && imageryAge > 16
                        ? ` · ${imageryAge} days ago, cloud has blocked every pass since`
                        : ''
                    }`
                  : satBadge?.detail || 'No clear satellite view of this district'}
              </span>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 lg:divide-x lg:divide-line">
              <div className="flex flex-col divide-y divide-line">
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
              </div>
              <div className="flex flex-col divide-y divide-line">
                <SupplyPressureCard
                  payload={supplyState.data}
                  loading={supplyState.loading}
                  district={district}
                />
              </div>
            </div>
          </>
        ) : null}

        {tab === 'map' ? <CropMapPanel district={district} center={centroid} /> : null}

        {tab === 'timing' ? (
          <HarvestPanel
            district={district}
            payload={harvestState.data}
            loading={harvestState.loading}
            onRefresh={refreshHarvest}
          />
        ) : null}

        {tab === 'market' ? (
          <div className="divide-y divide-line">
            <PriceChartCard
              series={priceState.data?.series}
              loading={priceState.loading}
              windowDays={priceState.data?.window_days || 90}
            />
            <BestMarketsCard
              payload={marketsState.data}
              loading={marketsState.loading}
              district={district}
              onQuantityChange={setQuintals}
            />
            <YearComparisonPanel
              payload={yearState.data}
              loading={yearState.loading}
              district={district}
            />
          </div>
        ) : null}
      </main>
    </div>
  );
}

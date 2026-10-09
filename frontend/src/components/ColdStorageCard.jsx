/**
 * Nearby cold storage, with the hold-or-sell comparison for each facility.
 *
 * Distance is computed here from the facility's coordinates and the district
 * centroid, so it is only shown for facilities the register actually placed.
 * A facility with no coordinates shows a dash rather than a plausible number,
 * and tariff is likewise blank when unstated — ₹0/t/day would read as free
 * storage.
 *
 * The net-gain line rests on an assumed price recovery, which the card states
 * under the list rather than leaving implicit. Anyone acting on it is paying
 * real storage fees against a return nothing here has observed.
 */

const EARTH_RADIUS_KM = 6371;

function haversineKm(a, b) {
  if (!a || !b) return null;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(h));
}

function rupees(v) {
  if (v == null) return '—';
  const n = Math.round(v);
  return `${n < 0 ? '−' : ''}₹${Math.abs(n).toLocaleString('en-IN')}`;
}

import { useLanguage } from '../i18n/LanguageContext.jsx';

export default function ColdStorageCard({ payload, loading, district, origin }) {
  const { t } = useLanguage();
  const facilities = payload?.facilities || [];
  const econ = payload?.economics;

  const withDistance = facilities.map((f) => ({
    ...f,
    distanceKm:
      f.mapped && origin
        ? haversineKm(origin, { lat: f.latitude, lon: f.longitude })
        : null,
  }));
  withDistance.sort((a, b) => {
    if (a.distanceKm == null) return 1;
    if (b.distanceKm == null) return -1;
    return a.distanceKm - b.distanceKm;
  });

  return (
    <section className="card">
      <h2 className="card-title">{t.storage.title}</h2>
      <p className="card-sub">
        {t.districts?.[district] || district || '—'} · {t.storage.facilityCount(facilities.length)}
      </p>

      {loading ? (
        <p className="mt-4 text-base text-muted">{t.status.loading}</p>
      ) : facilities.length === 0 ? (
        <p className="mt-4 text-base text-muted">
          No cold storage registered for {district || 'this district'}.
        </p>
      ) : (
        <>
          <ul className="mt-3">
            {withDistance.map((f) => {
              const e = f.economics;
              const gain = e?.net_benefit;
              return (
                <li key={f.id} className="border-b border-line py-2">
                  <div className="flex items-center justify-between gap-4">
                    <span className="truncate text-base text-ink font-medium" title={f.name}>
                      {f.name}
                    </span>
                    <span className="shrink-0 whitespace-nowrap text-xs text-muted tnum">
                      {f.distanceKm != null ? `${f.distanceKm.toFixed(0)} km` : '—'}
                      {' · '}
                      {f.licensed_capacity_mt != null
                        ? `${Math.round(f.licensed_capacity_mt).toLocaleString()} t`
                        : '—'}
                      {' · '}
                      {f.cost_per_tonne_day != null
                        ? `₹${f.cost_per_tonne_day}/t/day`
                        : '—'}
                    </span>
                  </div>

                  {e ? (
                    <p
                      className="mt-1 text-xs tnum"
                      style={{ color: gain > 0 ? '#1a5c2a' : '#c0392b' }}
                      title={e.assumption}
                    >
                      {t.storage.storeFor} {e.holding_days} {t.storage.days} → {rupees(Math.abs(gain))} {t.storage.netGain}
                      <span className="ml-1.5 text-muted">
                        ({t.storage.neededRecovery(((e.breakeven_factor - 1) * 100).toFixed(1))})
                      </span>
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>

          <p className="mt-3 text-xs text-muted">
            {t.storage.disclaimer}
          </p>
        </>
      )}
    </section>
  );
}

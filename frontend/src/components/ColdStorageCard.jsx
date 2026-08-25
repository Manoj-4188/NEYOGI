/**
 * Nearby cold storage.
 *
 * The distance figure is computed here from the facility's coordinates and the
 * district centroid, so it is only shown for facilities the register actually
 * placed. A facility with no coordinates shows a dash rather than a plausible
 * number, and tariff is likewise blank when unstated — 0/t/day would read as
 * free storage.
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

export default function ColdStorageCard({ payload, loading, district, origin }) {
  const facilities = payload?.facilities || [];

  const withDistance = facilities.map((f) => ({
    ...f,
    distanceKm:
      f.mapped && origin
        ? haversineKm(origin, { lat: f.latitude, lon: f.longitude })
        : null,
  }));
  // Nearest first; unplaced facilities sink to the bottom rather than
  // pretending to a position they do not have.
  withDistance.sort((a, b) => {
    if (a.distanceKm == null) return 1;
    if (b.distanceKm == null) return -1;
    return a.distanceKm - b.distanceKm;
  });

  return (
    <section className="p-5">
      <h2 className="card-title">Nearby Facilities</h2>
      <p className="card-sub">
        {district || '—'} · {facilities.length} facilit
        {facilities.length === 1 ? 'y' : 'ies'}
      </p>

      {loading ? (
        <p className="mt-4 text-base text-muted">Loading…</p>
      ) : facilities.length === 0 ? (
        <p className="mt-4 text-base text-muted">
          No cold storage registered for {district || 'this district'}.
        </p>
      ) : (
        <>
          <ul className="mt-3">
            {withDistance.map((f) => (
              <li
                key={f.id}
                className="flex h-9 items-center justify-between gap-4 border-b border-line"
              >
                <span className="truncate text-base text-ink" title={f.name}>
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
              </li>
            ))}
          </ul>

          <p className="mt-3 text-xs text-muted">
            Licensed capacity, not currently available space. Call ahead.
          </p>
        </>
      )}
    </section>
  );
}

/**
 * Officer telemetry panels: dependency health, tile freshness, ground-truth
 * coverage and yield-baseline coverage.
 *
 * The ground-truth panel is the one that decides what the platform is allowed
 * to claim from its verified model, so it shows each class against the
 * training floor the pipeline enforces rather than a bare count.
 */

function dot(color) {
  return <span className="dot" style={{ backgroundColor: color }} />;
}

export function ServiceHealth({ services }) {
  return (
    <section className="card">
      <h2 className="card-title">Service Health</h2>
      <p className="card-sub">Live dependency checks</p>
      <ul className="mt-3">
        {(services || []).map((s) => (
          <li key={s.service} className="flex gap-3 border-b border-line py-2.5">
            <span className="mt-1.5">{dot(s.healthy ? '#2ea84a' : '#c0392b')}</span>
            <div className="min-w-0">
              <p className="text-base text-ink">{s.service.replace(/_/g, ' ')}</p>
              <p className="mt-0.5 break-words text-xs text-muted">{s.detail}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function TileHealth({ tiles }) {
  return (
    <section className="card">
      <h2 className="card-title">Earth Engine Coverage</h2>
      <p className="card-sub">Composite freshness and boundary source per district</p>
      <div className="mt-3 overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>District</th>
              <th>Boundary</th>
              <th>Newest composite</th>
              <th className="num">Age</th>
              <th className="num">Composites</th>
              <th>Tile cache</th>
            </tr>
          </thead>
          <tbody>
            {(tiles || []).map((t) => (
              <tr key={t.district}>
                <td>{t.district}</td>
                <td>
                  {t.boundary?.is_fallback_source ? (
                    <span
                      className="text-xs"
                      style={{ color: '#d4882a' }}
                      title={`GAUL 2015 predates this district; boundary from ${t.boundary.source}`}
                    >
                      geoBoundaries
                    </span>
                  ) : (
                    <span className="text-xs text-muted">GAUL</span>
                  )}
                </td>
                <td className="text-muted">{t.newest_composite || '—'}</td>
                <td className="num">
                  {t.composite_age_days == null ? (
                    <span className="text-high">—</span>
                  ) : (
                    `${t.composite_age_days}d`
                  )}
                </td>
                <td className="num text-muted">{t.composite_count}</td>
                <td className="text-xs text-muted">
                  {t.tile_cached ? `cached · ${t.tile_scene_count ?? '?'} scenes` : 'none'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function GroundTruthAudit({ audit }) {
  if (!audit) return null;
  const {
    totals,
    by_class: byClass = [],
    by_district: byDistrict = [],
    missing_classes: missing = [],
  } = audit;
  const canTrain = totals.verified >= totals.min_parcels_to_train;

  return (
    <section className="card">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="card-title">Ground-Truth Audit</h2>
          <p className="card-sub">
            Gates the field-verified model, not the spectral one
          </p>
        </div>
        <span
          className="caps"
          style={{ color: canTrain ? '#1a5c2a' : '#c0392b' }}
        >
          {canTrain ? 'Sufficient' : 'Below floor'}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-4">
        <div>
          <p className="text-xs text-muted">Verified parcels</p>
          <p className="mt-0.5 text-xl font-semibold text-ink tnum">
            {totals.verified.toLocaleString()}
          </p>
          <p className="text-xs text-muted">of {totals.parcels.toLocaleString()}</p>
        </div>
        <div>
          <p className="text-xs text-muted">Training floor</p>
          <p className="mt-0.5 text-xl font-semibold text-ink tnum">
            {totals.min_parcels_to_train}
          </p>
          <p className="text-xs text-muted">parcels</p>
        </div>
        <div>
          <p className="text-xs text-muted">Per class</p>
          <p className="mt-0.5 text-xl font-semibold text-ink tnum">
            {totals.min_parcels_per_class}
          </p>
          <p className="text-xs text-muted">minimum</p>
        </div>
      </div>

      {byClass.length || missing.length ? (
        <ul className="mt-4">
          {byClass.map((e) => (
            <li
              key={e.crop_label}
              className="flex items-center justify-between border-b border-line py-1.5 text-base"
            >
              <span>{e.crop_label}</span>
              <span
                className="tnum"
                style={{ color: e.meets_training_floor ? '#1a5c2a' : '#c0392b' }}
              >
                {e.verified_parcels}
              </span>
            </li>
          ))}
          {missing.map((c) => (
            <li
              key={c}
              className="flex items-center justify-between border-b border-line py-1.5 text-base"
            >
              <span className="text-muted">{c}</span>
              <span className="text-xs text-high">no verified parcels</span>
            </li>
          ))}
        </ul>
      ) : null}

      {byDistrict.length ? (
        <table className="data-table mt-4">
          <thead>
            <tr>
              <th>District</th>
              <th className="num">Parcels</th>
              <th className="num">Verified</th>
              <th className="num">Area</th>
            </tr>
          </thead>
          <tbody>
            {byDistrict.map((e) => (
              <tr key={e.district}>
                <td>{e.district}</td>
                <td className="num text-muted">{e.parcels}</td>
                <td className="num" style={{ color: e.verified ? '#1a5c2a' : '#6b7280' }}>
                  {e.verified}
                </td>
                <td className="num text-muted">{e.verified_area_ha.toLocaleString()} ha</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

export function YieldBaselineCoverage({ coverage }) {
  if (!coverage || coverage.error) {
    return (
      <section className="card">
        <h2 className="card-title">Yield Baselines</h2>
        <p className="mt-2 text-base text-high">
          {coverage?.error || 'Baseline reference file could not be read.'}
        </p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2 className="card-title">Yield Baselines</h2>
      <p className="card-sub">
        Projected tonnage is withheld for any crop without a verified constant
      </p>
      <ul className="mt-3">
        {(coverage.verified || []).map((c) => (
          <li
            key={c}
            className="flex items-center justify-between border-b border-line py-1.5 text-base"
          >
            <span>{c}</span>
            <span className="text-xs" style={{ color: '#1a5c2a' }}>
              verified
            </span>
          </li>
        ))}
        {(coverage.unverified || []).map((c) => (
          <li
            key={c}
            className="flex items-center justify-between border-b border-line py-1.5 text-base"
          >
            <span className="text-muted">{c}</span>
            <span className="text-xs" style={{ color: '#c0392b' }}>
              unverified — tonnage withheld
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

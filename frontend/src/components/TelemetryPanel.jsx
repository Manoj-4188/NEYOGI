/**
 * Officer telemetry: dependency health, per-district tile freshness,
 * ground-truth coverage and yield-baseline coverage.
 *
 * The ground-truth panel is the one that decides what the system is allowed to
 * claim, so it shows each class against the training floor the pipeline
 * enforces rather than just a raw count.
 */

import { StatusBadge } from './StatusBadge.jsx';

function HealthDot({ healthy }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
        healthy ? 'bg-sage' : 'bg-terracotta'
      }`}
      aria-label={healthy ? 'healthy' : 'unhealthy'}
    />
  );
}

export function ServiceHealth({ services }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="panel-title">Service health</h2>
      </header>
      <ul className="divide-y divide-parchment-200">
        {(services || []).map((service) => (
          <li key={service.service} className="flex items-start gap-3 px-4 py-2.5">
            <HealthDot healthy={service.healthy} />
            <div className="min-w-0">
              <p className="text-sm font-medium text-forest-900">
                {service.service.replace(/_/g, ' ')}
              </p>
              <p className="mt-0.5 break-words text-xs text-forest-900/60">
                {service.detail}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function TileHealth({ tiles }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="panel-title">Earth Engine tile health</h2>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-parchment-200 text-left">
              {['District', 'Newest composite', 'Age', 'Composites', 'Tile cache', 'Status'].map(
                (heading) => (
                  <th
                    key={heading}
                    className="whitespace-nowrap px-4 py-2 text-xs uppercase tracking-wide text-sage-600"
                  >
                    {heading}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-parchment-200">
            {(tiles || []).map((tile) => (
              <tr key={tile.district} className="hover:bg-parchment">
                <td className="whitespace-nowrap px-4 py-2 font-medium text-forest-900">
                  {tile.district}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-forest-900/80">
                  {tile.newest_composite || '—'}
                </td>
                <td className="whitespace-nowrap px-4 py-2 font-mono tabular-nums">
                  {tile.composite_age_days == null ? (
                    <span className="text-terracotta">—</span>
                  ) : (
                    `${tile.composite_age_days}d`
                  )}
                </td>
                <td className="px-4 py-2 font-mono tabular-nums text-forest-900/70">
                  {tile.composite_count}
                </td>
                <td className="px-4 py-2">
                  {tile.tile_cached ? (
                    <span className="text-xs text-sage-600">
                      cached · {tile.tile_scene_count ?? '?'} scenes
                    </span>
                  ) : (
                    <span className="text-xs text-forest-900/50">none</span>
                  )}
                </td>
                <td className="px-4 py-2">
                  <StatusBadge badge={tile.status?.badges?.[0] || tile.status} />
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
  const { totals, by_class: byClass = [], by_district: byDistrict = [], missing_classes: missing = [] } =
    audit;
  const canTrain = totals.verified >= totals.min_parcels_to_train;

  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="panel-title">Ground-truth audit</h2>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
            canTrain
              ? 'bg-sage-100 text-forest'
              : 'bg-terracotta-100 text-terracotta-600'
          }`}
        >
          {canTrain ? 'Sufficient to train' : 'Below training floor'}
        </span>
      </header>

      <div className="grid grid-cols-3 gap-4 border-b border-parchment-200 px-4 py-3">
        <div>
          <p className="stat-label">Verified parcels</p>
          <p className="stat-value">{totals.verified.toLocaleString()}</p>
          <p className="text-xs text-sage-600">of {totals.parcels.toLocaleString()} loaded</p>
        </div>
        <div>
          <p className="stat-label">Training floor</p>
          <p className="stat-value">{totals.min_parcels_to_train}</p>
          <p className="text-xs text-sage-600">parcels overall</p>
        </div>
        <div>
          <p className="stat-label">Per class</p>
          <p className="stat-value">{totals.min_parcels_per_class}</p>
          <p className="text-xs text-sage-600">minimum each</p>
        </div>
      </div>

      <div className="px-4 py-3">
        <p className="stat-label mb-2">Verified parcels by class</p>
        <ul className="space-y-1.5">
          {byClass.map((entry) => (
            <li key={entry.crop_label} className="flex items-center gap-3 text-sm">
              <span className="w-32 shrink-0 text-forest-900">{entry.crop_label}</span>
              <span className="h-2 flex-1 overflow-hidden rounded-full bg-parchment-200">
                <span
                  className={`block h-full rounded-full ${
                    entry.meets_training_floor ? 'bg-sage' : 'bg-terracotta'
                  }`}
                  style={{
                    width: `${Math.min(
                      100,
                      (entry.verified_parcels / Math.max(totals.min_parcels_per_class * 4, 1)) * 100,
                    )}%`,
                  }}
                />
              </span>
              <span className="w-10 text-right font-mono tabular-nums text-forest-900/70">
                {entry.verified_parcels}
              </span>
            </li>
          ))}
          {missing.map((crop) => (
            <li key={crop} className="flex items-center gap-3 text-sm">
              <span className="w-32 shrink-0 text-forest-900/50">{crop}</span>
              <span className="flex-1 text-xs text-terracotta">
                no verified parcels — class cannot be modelled
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="overflow-x-auto border-t border-parchment-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-parchment-200 text-left">
              {['District', 'Parcels', 'Verified', 'Verified area', 'Last verified'].map((h) => (
                <th key={h} className="px-4 py-2 text-xs uppercase tracking-wide text-sage-600">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-parchment-200">
            {byDistrict.map((entry) => (
              <tr key={entry.district} className="hover:bg-parchment">
                <td className="px-4 py-2 font-medium text-forest-900">{entry.district}</td>
                <td className="px-4 py-2 font-mono tabular-nums">{entry.parcels}</td>
                <td className="px-4 py-2 font-mono tabular-nums">
                  <span className={entry.verified ? 'text-forest' : 'text-terracotta'}>
                    {entry.verified}
                  </span>
                </td>
                <td className="px-4 py-2 font-mono tabular-nums text-forest-900/70">
                  {entry.verified_area_ha.toLocaleString()} ha
                </td>
                <td className="px-4 py-2 text-xs text-forest-900/60">
                  {entry.last_verified_at?.slice(0, 10) || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function YieldBaselineCoverage({ coverage }) {
  if (!coverage || coverage.error) {
    return (
      <section className="panel px-4 py-4">
        <h2 className="panel-title mb-2">Yield baselines</h2>
        <p className="text-sm text-terracotta">
          {coverage?.error || 'Baseline reference file could not be read.'}
        </p>
      </section>
    );
  }

  return (
    <section className="panel px-4 py-4">
      <h2 className="panel-title mb-2">Yield baselines</h2>
      <p className="mb-3 text-xs text-forest-900/60">
        Projected tonnage is withheld for any crop without an operator-verified
        yield constant. Fill and verify entries in
        <code className="ml-1 font-mono">data/reference/baseline_yields.yml</code>.
      </p>
      <div className="flex flex-wrap gap-2">
        {(coverage.verified || []).map((crop) => (
          <span
            key={crop}
            className="rounded-full bg-sage-100 px-2.5 py-1 text-xs font-semibold text-forest"
          >
            ✓ {crop}
          </span>
        ))}
        {(coverage.unverified || []).map((crop) => (
          <span
            key={crop}
            className="rounded-full bg-terracotta-100 px-2.5 py-1 text-xs font-semibold text-terracotta-600"
          >
            ✗ {crop}
          </span>
        ))}
      </div>
    </section>
  );
}

export function PipelineRuns({ runs }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="panel-title">Recent pipeline runs</h2>
      </header>
      {runs?.length ? (
        <ul className="max-h-80 divide-y divide-parchment-200 overflow-y-auto">
          {runs.map((run, index) => (
            <li
              // eslint-disable-next-line react/no-array-index-key
              key={`${run.stage}-${run.created_at}-${index}`}
              className="flex items-start gap-3 px-4 py-2.5"
            >
              <HealthDot healthy={run.ok} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-forest-900">
                  {run.stage}
                  {run.district ? (
                    <span className="ml-1.5 text-sage-600">· {run.district}</span>
                  ) : null}
                </p>
                <p className="mt-0.5 truncate font-mono text-xs text-forest-900/50">
                  {JSON.stringify(run.payload)}
                </p>
              </div>
              <time className="shrink-0 text-xs text-forest-900/50">
                {new Date(run.created_at).toLocaleString()}
              </time>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 py-6 text-sm text-sage-600">No pipeline runs recorded yet.</p>
      )}
    </section>
  );
}

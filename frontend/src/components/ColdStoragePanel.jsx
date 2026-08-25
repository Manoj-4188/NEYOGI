/**
 * Cold storage registered in the selected district.
 *
 * This is the panel that makes an oversupply warning actionable: if the belt
 * is projected to out-produce the mandi, holding the crop is the alternative
 * to dumping it, and holding needs a facility.
 *
 * The distinction this panel is careful about: it shows **licensed capacity**,
 * never available space. No Indian authority publishes live cold storage
 * utilisation, so "space free" would be a fabrication — and one a farmer might
 * drive 40 km on. Every capacity figure here is labelled as licensed, and the
 * footer says plainly that utilisation is unknown.
 */

import { useState } from 'react';

import EmptyState, { Icon, SkeletonRows } from './EmptyState.jsx';
import { StatusBadge } from './StatusBadge.jsx';

const OWNERSHIP_LABEL = {
  private: 'Private',
  cooperative: 'Co-op',
  government: 'Govt',
  unknown: '—',
};

function formatCapacity(mt) {
  if (mt == null) return null;
  if (mt >= 1000) return `${(mt / 1000).toFixed(1)}k MT`;
  return `${Math.round(mt).toLocaleString()} MT`;
}

function FacilityRow({ facility }) {
  const capacity = formatCapacity(facility.licensed_capacity_mt);

  return (
    <li className="flex items-start gap-3 px-4 py-2.5">
      <span
        className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
          facility.mapped ? 'bg-sage' : 'border border-parchment-300 bg-parchment-200'
        }`}
        title={facility.mapped ? 'Mapped' : 'No coordinates in the source register'}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-forest-900" title={facility.name}>
          {facility.name}
        </p>
        <p className="mt-0.5 truncate text-xs text-forest-900/55">
          {[facility.taluk, facility.commodity_focus].filter(Boolean).join(' · ') ||
            facility.address ||
            facility.district}
        </p>
      </div>
      <div className="shrink-0 text-right">
        {capacity ? (
          <p className="font-mono text-sm font-semibold tabular-nums text-forest">
            {capacity}
          </p>
        ) : (
          <p className="font-mono text-sm text-terracotta" title="Capacity not stated in the source register">
            —
          </p>
        )}
        <p className="text-[10px] uppercase tracking-wide text-sage-600">
          {OWNERSHIP_LABEL[facility.ownership] || '—'}
        </p>
      </div>
    </li>
  );
}

export default function ColdStoragePanel({ payload, loading, district }) {
  const [expanded, setExpanded] = useState(false);

  const facilities = payload?.facilities || [];
  const summary = payload?.summary;
  const badge = payload?.status?.badges?.[0];
  const shown = expanded ? facilities : facilities.slice(0, 5);

  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Icon name="satellite" className="h-4 w-4 shrink-0 text-sage-600" />
          <h2 className="panel-title">Cold storage</h2>
        </div>
        {badge ? <StatusBadge badge={badge} /> : null}
      </header>

      {loading ? (
        <SkeletonRows rows={4} />
      ) : facilities.length === 0 ? (
        <div className="px-4 py-4">
          <EmptyState
            compact
            icon="satellite"
            tone="blocked"
            title={`No cold storage registered for ${district || 'this district'}`}
            body="Holding capacity is the practical answer to a projected glut, but no register has been loaded. NEYOGI will not estimate facilities or their locations."
            command={
              'python -m ml_pipeline.load_cold_storage <register>.csv \\\n' +
              '  --source "NHB Cold Storage Directory" --source-year 2023'
            }
            footnote="Registers: nhb.gov.in/csrIndex.aspx, or the state horticulture department."
          />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3 border-b border-parchment-200 px-4 py-3">
            <div>
              <p className="stat-label">Facilities</p>
              <p className="stat-value">{summary.facility_count}</p>
              {summary.mapped_count < summary.facility_count ? (
                <p className="text-[11px] text-forest-900/50">
                  {summary.mapped_count} mapped
                </p>
              ) : null}
            </div>
            <div className="col-span-2">
              <p className="stat-label">Licensed capacity</p>
              {summary.licensed_capacity_mt != null ? (
                <p className="stat-value">
                  {(summary.licensed_capacity_mt / 1000).toFixed(1)}
                  <span className="ml-1 text-xs font-normal text-sage-600">k MT</span>
                </p>
              ) : (
                <p className="value-withheld" title="No facility in this district published a capacity">
                  —
                </p>
              )}
              <p className="text-[11px] text-forest-900/50">
                {summary.capacity_known_count} of {summary.facility_count} published a figure
              </p>
            </div>
          </div>

          <ul className="divide-y divide-parchment-200">
            {shown.map((f) => (
              <FacilityRow key={f.id} facility={f} />
            ))}
          </ul>

          {facilities.length > 5 ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="w-full border-t border-parchment-200 px-4 py-2 text-xs font-medium
                         text-sage-600 transition hover:bg-parchment"
            >
              {expanded
                ? 'Show fewer'
                : `Show all ${facilities.length} facilities`}
            </button>
          ) : null}

          <p className="border-t border-parchment-200 px-4 py-2.5 text-[11px] leading-relaxed text-forest-900/50">
            Licensed capacity as published in the source register — not space
            currently available. Live utilisation is not published by any Indian
            authority, so NEYOGI does not estimate it. Call ahead before moving
            produce.
          </p>
        </>
      )}
    </section>
  );
}

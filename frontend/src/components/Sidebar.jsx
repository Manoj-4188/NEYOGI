/**
 * Fixed left sidebar: district selection and dependency status.
 *
 * This is the whole navigation surface — there is no top navbar. The status
 * block at the bottom is the one place the operator can see, at a glance,
 * whether what is on screen is backed by live sources or cached ones.
 */

import { NavLink } from 'react-router-dom';

/** Status dot colour by health, using the three-level scale from the system. */
function statusColor(state) {
  if (state === 'ok') return '#2ea84a';
  if (state === 'degraded') return '#d4882a';
  return '#c0392b';
}

function StatusRow({ label, state, title }) {
  return (
    <div className="flex h-5 items-center gap-2" title={title}>
      <span className="dot" style={{ backgroundColor: statusColor(state) }} />
      <span className="text-xs text-muted">{label}</span>
    </div>
  );
}

/**
 * District status dot:
 *   green  — classification available from a current composite
 *   amber  — resolvable, but nothing classified yet
 *   red    — no boundary, or no imagery
 */
function districtState(entry) {
  if (entry?.has_classification) return 'ok';
  if (entry?.boundary === null) return 'error';
  return 'degraded';
}

export default function Sidebar({
  districts,
  selected,
  onSelect,
  health,
  satelliteState,
}) {
  const dbOk = Boolean(health?.dependencies?.[0]?.healthy);
  const agmarknetOk = Boolean(health?.configured?.agmarknet);
  const geeOk = Boolean(health?.configured?.earth_engine);

  return (
    <aside className="flex w-sidebar shrink-0 flex-col border-r border-line bg-white">
      <header className="flex h-header flex-col justify-center border-b border-line px-4">
        <NavLink to="/dashboard" className="text-md font-bold leading-tight text-ink">
          NEYOGI
        </NavLink>
        <span className="text-xs leading-tight text-muted">
          Crop Market Intelligence
        </span>
      </header>

      <nav className="flex-1 overflow-y-auto py-1" aria-label="Districts">
        {districts.length === 0 ? (
          <p className="px-4 py-3 text-xs text-muted">Loading districts…</p>
        ) : (
          districts.map((entry) => {
            const isActive = entry.district === selected;
            return (
              <button
                key={entry.district}
                type="button"
                onClick={() => onSelect(entry.district)}
                aria-current={isActive ? 'true' : undefined}
                className={`flex h-row w-full items-center justify-between px-4 text-left
                            text-base transition-colors ${
                              isActive
                                ? 'border-l-2 border-accent bg-accent-wash pl-[14px] text-ink'
                                : 'border-l-2 border-transparent text-ink hover:bg-wash'
                            }`}
              >
                <span className="truncate">{entry.district}</span>
                <span
                  className="dot"
                  style={{ backgroundColor: statusColor(districtState(entry)) }}
                  title={
                    entry.has_classification
                      ? 'Classification available'
                      : 'No classification for the latest composite'
                  }
                />
              </button>
            );
          })
        )}
      </nav>

      <div className="border-t border-line px-4 py-3">
        <StatusRow
          label="PostGIS"
          state={dbOk ? 'ok' : 'error'}
          title={health?.dependencies?.[0]?.detail || 'Spatial database'}
        />
        <StatusRow
          label="Satellite"
          state={geeOk ? satelliteState || 'ok' : 'error'}
          title={
            geeOk
              ? 'Earth Engine configured'
              : 'No Earth Engine service account configured'
          }
        />
        <StatusRow
          label="Agmarknet"
          state={agmarknetOk ? 'degraded' : 'error'}
          title={
            agmarknetOk
              ? 'API key configured; serving cached quotes when the feed is unreachable'
              : 'No AGMARKNET API key configured'
          }
        />
      </div>

      <div className="border-t border-line px-4 py-2">
        <NavLink
          to="/officer"
          className="text-xs text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          Officer console
        </NavLink>
      </div>
    </aside>
  );
}

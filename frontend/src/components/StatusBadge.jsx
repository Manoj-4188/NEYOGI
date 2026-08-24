/**
 * Data-provenance badges.
 *
 * These render exactly what the API sent. The severity, the wording and the
 * date all come from the server payload, so there is no path by which the UI
 * can present cached data as live — the frontend has no opinion to override.
 */

const SEVERITY_STYLES = {
  ok: 'border-sage-200 bg-sage-100 text-forest',
  warn: 'border-amber-300 bg-amber-50 text-amber-900',
  error: 'border-terracotta-200 bg-terracotta-100 text-terracotta-600',
};

export function StatusBadge({ badge, className = '', showDetail = false }) {
  if (!badge) return null;
  const tone = SEVERITY_STYLES[badge.severity] || SEVERITY_STYLES.warn;

  return (
    <span
      className={`inline-flex max-w-full items-start gap-1.5 rounded-full border px-2.5 py-1
                  text-xs font-semibold leading-tight ${tone} ${className}`}
      title={badge.detail || badge.label}
    >
      <span aria-hidden="true">{badge.icon}</span>
      <span className="truncate">{badge.label.replace(/^[🟢🟡🔴]\s*/u, '')}</span>
      {showDetail && badge.detail ? (
        <span className="ml-1 font-normal opacity-80">{badge.detail}</span>
      ) : null}
    </span>
  );
}

/** Horizontal list of every badge attached to a response. */
export function StatusBadgeRow({ status, className = '' }) {
  if (!status?.badges?.length) return null;
  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      {status.badges.map((badge) => (
        <StatusBadge key={`${badge.source}-${badge.status}`} badge={badge} />
      ))}
    </div>
  );
}

/**
 * Prominent banner shown when any source is on a fallback.
 *
 * Deliberately not dismissible: if the numbers on screen came from a cache or
 * an unvalidated district, that has to stay visible for as long as they do.
 */
export function FallbackBanner({ status, className = '' }) {
  if (!status?.degraded) return null;

  const fallbacks = status.badges.filter((b) => b.is_fallback || b.severity !== 'ok');
  if (!fallbacks.length) return null;

  const isError = status.worst_severity === 'error';
  const frame = isError
    ? 'border-terracotta-200 bg-terracotta-100'
    : 'border-amber-300 bg-amber-50';

  return (
    <section
      role="status"
      aria-live="polite"
      className={`rounded-xl border px-4 py-3 ${frame} ${className}`}
    >
      <h2 className="flex items-center gap-2 text-sm font-semibold text-forest">
        <span aria-hidden="true">{isError ? '🔴' : '🟡'}</span>
        {isError ? 'Some data is unavailable' : 'Showing fallback data'}
      </h2>
      <ul className="mt-2 space-y-1.5">
        {fallbacks.map((badge) => (
          <li key={`${badge.source}-${badge.status}`} className="text-sm text-forest-900/80">
            <span className="font-semibold">{badge.label}</span>
            {badge.detail ? <span className="ml-1.5">{badge.detail}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Placeholder for a number the system is deliberately withholding.
 *
 * Used wherever a value could not be computed from real data — an unverified
 * yield baseline, an unpublished arrival tonnage. It renders an em dash and the
 * reason, never a zero, because a zero here would read as a measurement.
 */
export function WithheldValue({ reason, label }) {
  return (
    <span className="inline-flex flex-col">
      <span className="value-withheld" title={reason}>
        —
      </span>
      {label ? <span className="text-xs text-terracotta-600">{label}</span> : null}
    </span>
  );
}

export default StatusBadge;

/**
 * Empty and loading states.
 *
 * NEYOGI is empty until real data is loaded, and that is by design -- it
 * refuses to invent parcels, prices or yields. But "correct" and "looks
 * broken" are different things, and a blank panel reads as the second. These
 * components make an empty panel say what is missing, why, and what supplies
 * it, so the absence looks deliberate rather than defective.
 *
 * Nothing here fabricates a value. The skeletons animate a layout, not data.
 */

/* ------------------------------------------------------------------ *
 * Icons -- inline SVG, currentColor, no icon dependency.
 * ------------------------------------------------------------------ */

const ICONS = {
  map: (
    <path d="M9 4.5 3.5 6.8v12.7L9 17.2l6 2.3 5.5-2.3V4.5L15 6.8 9 4.5Zm0 0v12.7m6-10.4v12.7" />
  ),
  chart: <path d="M4 19.5h16M7 16V9m5 7V5m5 11v-4" />,
  satellite: (
    <>
      <path d="M12 3v3m0 12v3m9-9h-3M6 12H3" />
      <circle cx="12" cy="12" r="4" />
    </>
  ),
  rupee: <path d="M7 5h10M7 9h10M15 5c0 4-3.5 4-8 4l8 10" />,
  seedling: (
    <>
      <path d="M12 20v-8" />
      <path d="M12 14c0-3.5 2.6-6 6-6 0 3.4-2.6 6-6 6Z" />
      <path d="M12 17c0-2.6-2.2-4.8-4.8-4.8 0 2.6 2.2 4.8 4.8 4.8Z" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10.5" width="14" height="9.5" rx="2" />
      <path d="M8.5 10.5V7.8a3.5 3.5 0 1 1 7 0v2.7" />
    </>
  ),
};

export function Icon({ name, className = 'h-6 w-6' }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {ICONS[name] || ICONS.map}
    </svg>
  );
}

/* ------------------------------------------------------------------ *
 * Empty state
 * ------------------------------------------------------------------ */

const TONES = {
  neutral: {
    ring: 'border-parchment-300',
    wash: 'bg-parchment-200/50 text-forest',
    heading: 'text-forest',
  },
  info: {
    ring: 'border-sage-200',
    wash: 'bg-sage-100 text-sage-600',
    heading: 'text-forest',
  },
  blocked: {
    ring: 'border-terracotta-200',
    wash: 'bg-terracotta-100 text-terracotta-600',
    heading: 'text-terracotta-600',
  },
};

/**
 * @param icon     key into ICONS
 * @param title    what is absent, stated plainly
 * @param body     why it is absent
 * @param command  the shell command that fixes it, if there is one
 * @param tone     neutral | info | blocked
 * @param footnote small print under the command
 */
export default function EmptyState({
  icon = 'map',
  title,
  body,
  command,
  tone = 'neutral',
  footnote,
  compact = false,
  children,
}) {
  const t = TONES[tone] || TONES.neutral;

  return (
    <div
      className={`flex flex-col items-center justify-center rounded-xl border border-dashed text-center
                  ${t.ring} ${compact ? 'gap-2 px-5 py-8' : 'gap-3 px-6 py-12'}`}
    >
      <span
        className={`inline-flex items-center justify-center rounded-full ${t.wash}
                    ${compact ? 'h-10 w-10' : 'h-14 w-14'}`}
      >
        <Icon name={icon} className={compact ? 'h-5 w-5' : 'h-7 w-7'} />
      </span>

      <h3 className={`text-sm font-semibold ${t.heading}`}>{title}</h3>

      {body ? (
        <p className="max-w-md text-sm leading-relaxed text-forest-900/65">{body}</p>
      ) : null}

      {command ? (
        <code
          className="mt-1 max-w-full overflow-x-auto whitespace-pre rounded-lg border border-parchment-300
                     bg-parchment px-3 py-2 text-left font-mono text-xs text-forest-900/80"
        >
          {command}
        </code>
      ) : null}

      {footnote ? (
        <p className="max-w-md text-xs text-forest-900/45">{footnote}</p>
      ) : null}

      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Loading skeletons
 * ------------------------------------------------------------------ */

export function Skeleton({ className = '' }) {
  return (
    <div className={`animate-pulse rounded-md bg-parchment-200 ${className}`} />
  );
}

export function SkeletonRows({ rows = 4 }) {
  return (
    <div className="space-y-3 px-4 py-4">
      {Array.from({ length: rows }).map((_, i) => (
        // eslint-disable-next-line react/no-array-index-key
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-3 w-3 rounded-full" />
          <Skeleton className="h-3 flex-1" />
          <Skeleton className="h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonPanel({ label = 'Loading' }) {
  return (
    <div className="flex h-full min-h-[16rem] flex-col items-center justify-center gap-3">
      <div className="flex gap-1.5" aria-hidden="true">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="h-2 w-2 animate-bounce rounded-full bg-sage"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </div>
      <p className="text-sm text-sage-600">{label}</p>
    </div>
  );
}

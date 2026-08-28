/**
 * Tab bar.
 *
 * Underline-and-weight rather than a pill or a filled box, so the selected tab
 * reads as part of the page instead of a control floating on top of it. Left
 * aligned with the content below, which keeps the eye on one vertical line.
 */

export default function Tabs({ tabs, active, onChange }) {
  return (
    <div className="flex items-stretch gap-1 border-b border-line px-5" role="tablist">
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tab.id)}
            className={`relative -mb-px border-b-2 px-3 py-2.5 text-base transition-colors ${
              selected
                ? 'border-accent font-semibold text-ink'
                : 'border-transparent text-muted hover:text-ink'
            }`}
          >
            {tab.label}
            {tab.badge ? (
              <span className="ml-1.5 text-xs text-muted">{tab.badge}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

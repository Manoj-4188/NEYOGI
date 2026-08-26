/**
 * Oversupply signal.
 *
 * The ratio is projected production over observed mandi arrivals. Both sides
 * have to exist for it to mean anything, and both are frequently missing —
 * projected volume needs a verified yield baseline, and the denominator needs
 * AGMARKNET to have published arrival tonnage. When either is absent this card
 * says which one, rather than showing a number with a silent hole in it.
 */

const LEVELS = [
  { max: 1.0, label: 'BALANCED', color: '#2ea84a' },
  { max: 1.25, label: 'MODERATE', color: '#d4882a' },
  { max: Infinity, label: 'HIGH RISK', color: '#c0392b' },
];

function levelFor(ratio) {
  return LEVELS.find((l) => ratio <= l.max) || LEVELS[LEVELS.length - 1];
}

/** The first crop with a computable ratio; that is the district's headline. */
function headlineCrop(crops) {
  return (crops || []).find((c) => c.oversupply_ratio != null) || null;
}

export default function SupplyPressureCard({ payload, loading, district }) {
  const crops = payload?.crops || [];
  const headline = headlineCrop(crops);

  // Nothing computable: explain which input is missing, using the status the
  // API already assigned rather than guessing at it here.
  const blocked = !headline && crops.length > 0 ? crops[0] : null;

  return (
    <section className="p-5">
      <h2 className="card-title">Supply Pressure</h2>
      <p className="card-sub">
        {district || '—'}
        {payload?.window?.start ? ` · since ${payload.window.start}` : ''}
      </p>

      {loading ? (
        <p className="mt-4 text-base text-muted">Loading…</p>
      ) : headline ? (
        <>
          <p
            className="mt-4 text-4xl font-bold leading-none tnum"
            style={{ color: levelFor(headline.oversupply_ratio).color }}
          >
            {headline.oversupply_ratio.toFixed(2)}×
          </p>
          <p
            className="caps mt-2"
            style={{ color: levelFor(headline.oversupply_ratio).color }}
          >
            {levelFor(headline.oversupply_ratio).label}
          </p>

          <p className="mt-3 text-sm leading-relaxed text-muted">
            {headline.oversupply_ratio > 1
              ? `Regional ${headline.crop.toLowerCase()} supply exceeds recent mandi
                 absorption by ${Math.round((headline.oversupply_ratio - 1) * 100)}%.
                 Harvest coordination recommended.`
              : `Regional ${headline.crop.toLowerCase()} supply is within recent
                 mandi absorption.`}
          </p>

          <p className="mt-3 text-xs text-muted">
            {Math.round(headline.projected_volume_mt).toLocaleString()} MT projected ·{' '}
            {Math.round(headline.demand_mt ?? headline.observed_arrivals_mt ?? 0).toLocaleString()}{' '}
            MT {headline.demand_basis === 'baseline_demand' ? 'baseline demand' : 'arrivals'}
          </p>

          {/* Which denominator produced the ratio changes how much weight it
              carries, so it is stated rather than left to the reader. */}
          {headline.demand_basis === 'baseline_demand' ? (
            <p className="mt-1 text-xs" style={{ color: '#d4882a' }}>
              Measured against the Horticulture Dept baseline absorption, not
              observed mandi arrivals — AGMARKNET published none for this window.
            </p>
          ) : null}
        </>
      ) : (
        <>
          <p className="mt-4 text-4xl font-bold leading-none text-muted tnum">—</p>
          <p className="caps mt-2 text-muted">NOT COMPUTABLE</p>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            {blocked?.detail ||
              payload?.notes?.[0] ||
              `No classified area or mandi arrivals for ${district || 'this district'}, so
               the supply-to-demand ratio has no basis.`}
          </p>
        </>
      )}
    </section>
  );
}

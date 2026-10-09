/**
 * Oversupply signal.
 *
 * The ratio is projected production over observed mandi arrivals. Both sides
 * have to exist for it to mean anything, and both are frequently missing —
 * projected volume needs a verified yield baseline, and the denominator needs
 * AGMARKNET to have published arrival tonnage. When either is absent this card
 * says which one, rather than showing a number with a silent hole in it.
 */

import { useLanguage } from '../i18n/LanguageContext.jsx';

const LEVELS = [
  { max: 1.0, key: 'balanced', color: '#2ea84a' },
  { max: 1.25, key: 'moderate', color: '#d4882a' },
  { max: Infinity, key: 'highRisk', color: '#c0392b' },
];

function levelFor(ratio) {
  return LEVELS.find((l) => ratio <= l.max) || LEVELS[LEVELS.length - 1];
}

/** The first crop with a computable ratio; that is the district's headline. */
function headlineCrop(crops) {
  return (crops || []).find((c) => c.oversupply_ratio != null) || null;
}

export default function SupplyPressureCard({ payload, loading, district }) {
  const { t } = useLanguage();
  const crops = payload?.crops || [];
  const headline = headlineCrop(crops);
  const blocked = !headline && crops.length > 0 ? crops[0] : null;

  const currentLevel = headline ? levelFor(headline.oversupply_ratio) : null;
  const levelLabel = currentLevel ? t.supply[currentLevel.key] : '';

  return (
    <section className="p-5">
      <h2 className="card-title">{t.supply.title}</h2>
      <p className="card-sub">
        {t.districts?.[district] || district || '—'}
        {payload?.window?.start ? ` · since ${payload.window.start}` : ''}
      </p>

      {loading ? (
        <p className="mt-4 text-base text-muted">{t.status.loading}</p>
      ) : headline ? (
        <>
          <p
            className="mt-4 text-4xl font-bold leading-none tnum"
            style={{ color: currentLevel.color }}
          >
            {headline.oversupply_ratio.toFixed(2)}×
          </p>
          <p
            className="caps mt-2 font-bold"
            style={{ color: currentLevel.color }}
          >
            {levelLabel}
          </p>

          <p className="mt-3 text-sm leading-relaxed text-muted">
            {headline.oversupply_ratio > 1
              ? t.supply.excessDesc(
                  t.crops[headline.crop] || headline.crop,
                  Math.round((headline.oversupply_ratio - 1) * 100)
                )
              : t.supply.balancedDesc(t.crops[headline.crop] || headline.crop)}
          </p>

          <p className="mt-3 text-xs text-muted">
            {Math.round(headline.weekly_arrival_mt ?? 0).toLocaleString()} {t.supply.arriving} ·{' '}
            {Math.round(headline.weekly_absorption_mt ?? 0).toLocaleString()} {t.supply.absorbed}
          </p>

          {headline.demand_basis === 'district_absorption' ? (
            <p className="mt-1 text-xs" style={{ color: '#d4882a' }}>
              {t.supply.denominatorNotice}
            </p>
          ) : null}
        </>
      ) : (
        <>
          <p className="mt-4 text-4xl font-bold leading-none text-muted tnum">—</p>
          <p className="caps mt-2 text-muted">{t.supply.notComputable}</p>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            {blocked?.detail || payload?.notes?.[0] || 'No classified area or arrivals'}
          </p>
        </>
      )}
    </section>
  );
}

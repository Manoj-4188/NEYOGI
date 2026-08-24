/**
 * Mandi price table with the 30-day moving average alongside live quotes.
 *
 * Arrival tonnage is frequently absent from the AGMARKNET feed. Those cells
 * render an em dash with a tooltip, never a zero.
 */

import { StatusBadge } from './StatusBadge.jsx';

function formatRupees(value) {
  if (value == null) return '—';
  return `₹${Math.round(value).toLocaleString('en-IN')}`;
}

export default function PriceTable({ payload, crop }) {
  if (!payload) return null;

  const quotes = (payload.quotes || [])
    .filter((q) => (crop ? q.crop === crop : true))
    .slice()
    .sort((a, b) => b.arrival_date.localeCompare(a.arrival_date))
    .slice(0, 12);

  const average = crop ? payload.moving_average_30d?.[crop] : null;
  const badge = payload.status?.badges?.find((b) => b.source === 'market');

  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="panel-title">Mandi prices</h2>
        {badge ? <StatusBadge badge={badge} /> : null}
      </header>

      {average ? (
        <div className="grid grid-cols-2 gap-4 border-b border-parchment-200 px-4 py-3 sm:grid-cols-4">
          <div>
            <p className="stat-label">30-day average</p>
            <p className="stat-value">{formatRupees(average.modal_price_avg)}</p>
            <p className="text-xs text-sage-600">per quintal</p>
          </div>
          <div>
            <p className="stat-label">Range</p>
            <p className="text-sm font-medium text-forest-900">
              {formatRupees(average.min_price)} – {formatRupees(average.max_price)}
            </p>
          </div>
          <div>
            <p className="stat-label">Quotes</p>
            <p className="text-sm font-medium text-forest-900">{average.quote_count}</p>
          </div>
          <div>
            <p className="stat-label">Arrivals reported</p>
            <p className="text-sm font-medium text-forest-900">
              {average.arrival_report_count
                ? `${average.arrival_report_count} day(s)`
                : 'none published'}
            </p>
          </div>
        </div>
      ) : null}

      {quotes.length === 0 ? (
        <p className="px-4 py-6 text-sm text-sage-600">
          No quotes available for {crop || 'these crops'} in this district.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-parchment-200 text-left">
                <th className="px-4 py-2 text-xs uppercase tracking-wide text-sage-600">
                  Date
                </th>
                <th className="px-4 py-2 text-xs uppercase tracking-wide text-sage-600">
                  Market
                </th>
                <th className="px-4 py-2 text-xs uppercase tracking-wide text-sage-600">
                  Crop
                </th>
                <th className="px-4 py-2 text-right text-xs uppercase tracking-wide text-sage-600">
                  Modal
                </th>
                <th className="px-4 py-2 text-right text-xs uppercase tracking-wide text-sage-600">
                  Range
                </th>
                <th className="px-4 py-2 text-right text-xs uppercase tracking-wide text-sage-600">
                  Arrivals
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-parchment-200">
              {quotes.map((quote) => (
                <tr
                  key={`${quote.market}-${quote.crop}-${quote.variety}-${quote.arrival_date}`}
                  className="hover:bg-parchment"
                >
                  <td className="whitespace-nowrap px-4 py-2 text-forest-900/80">
                    {quote.arrival_date}
                  </td>
                  <td className="px-4 py-2 text-forest-900">{quote.market}</td>
                  <td className="px-4 py-2 text-forest-900/80">
                    {quote.crop}
                    {quote.commodity !== quote.crop ? (
                      <span className="ml-1 text-xs text-sage-600">({quote.commodity})</span>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-right font-mono font-semibold tabular-nums text-forest">
                    {formatRupees(quote.modal_price)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-xs tabular-nums text-forest-900/70">
                    {formatRupees(quote.min_price)} – {formatRupees(quote.max_price)}
                  </td>
                  <td
                    className="whitespace-nowrap px-4 py-2 text-right font-mono tabular-nums"
                    title={
                      quote.arrival_volume_mt == null
                        ? 'AGMARKNET did not publish arrival tonnage for this quote.'
                        : undefined
                    }
                  >
                    {quote.arrival_volume_mt == null ? (
                      <span className="text-terracotta">—</span>
                    ) : (
                      `${quote.arrival_volume_mt.toLocaleString()} MT`
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {payload.notes?.length ? (
        <ul className="space-y-1 border-t border-parchment-200 px-4 py-2.5 text-xs text-forest-900/60">
          {payload.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

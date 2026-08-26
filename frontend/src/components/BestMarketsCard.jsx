/**
 * Markets ranked by what a load actually nets after haulage.
 *
 * The ranking is only as good as the prices behind it, so a market with no
 * published quote is never scored — the card comes back empty and says why
 * rather than filling the table with assumed rates. Someone acts on this by
 * hiring a lorry.
 */

import { useState } from 'react';

function rupees(v) {
  if (v == null) return '—';
  return `₹${Math.round(v).toLocaleString('en-IN')}`;
}

export default function BestMarketsCard({ payload, loading, district, onQuantityChange }) {
  const [quantity, setQuantity] = useState(100);
  const markets = payload?.markets || [];

  function commit(next) {
    const q = Math.max(1, Number(next) || 1);
    setQuantity(q);
    onQuantityChange?.(q);
  }

  return (
    <section className="card">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="card-title">Best Markets</h2>
          <p className="card-sub">
            {payload?.crop || 'Tomato'} · net of transport from {district || '—'}
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          Quintals
          <input
            type="number"
            min={1}
            className="field w-24 py-1 text-right"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            onBlur={(e) => commit(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && commit(e.currentTarget.value)}
          />
        </label>
      </div>

      {loading ? (
        <p className="mt-4 text-base text-muted">Ranking markets…</p>
      ) : markets.length === 0 ? (
        <div className="mt-4">
          <p className="text-base text-muted">No market can be ranked right now.</p>
          <p className="mt-1 text-xs text-muted">
            {payload?.error ||
              'AGMARKNET has published no recent quotes for this crop, and a market cannot be ranked on an assumed price — the output is a recommendation to drive somewhere.'}
          </p>
        </div>
      ) : (
        <>
          <table className="data-table mt-4">
            <thead>
              <tr>
                <th>Market</th>
                <th className="num">₹/qtl</th>
                <th className="num">Distance</th>
                <th className="num">Net profit</th>
              </tr>
            </thead>
            <tbody>
              {markets.map((m, i) => (
                <tr key={`${m.market}-${m.district}`}>
                  <td>
                    {m.market}
                    <span className="ml-1.5 text-xs text-muted">{m.district}</span>
                    {i === 0 ? (
                      <span className="ml-2 text-2xs" style={{ color: '#1a5c2a' }}>
                        BEST
                      </span>
                    ) : null}
                  </td>
                  <td className="num">{Math.round(m.modal_price).toLocaleString('en-IN')}</td>
                  <td className="num text-muted">
                    {m.distance_km != null ? `${Math.round(m.distance_km)} km` : '—'}
                  </td>
                  <td
                    className="num"
                    style={{ color: i === 0 ? '#1a5c2a' : '#111111' }}
                  >
                    {rupees(m.net_profit)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-3 text-xs text-muted">
            {payload.considered} market(s) considered · quotes within{' '}
            {payload.price_window_days} days
          </p>
          <p className="mt-1 text-xs text-muted">
            Transport ≈ ₹2.5/km/tonne (planning constant). Distances are
            district-centre to district-centre.
          </p>
        </>
      )}
    </section>
  );
}

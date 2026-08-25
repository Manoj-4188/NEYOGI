/**
 * Oversupply alert log and dispatch control.
 *
 * The dispatch button only exists when something is actually pending at HIGH
 * or CRITICAL. A permanently-visible "Send Alert" invites a click that sends
 * nothing, and trains the officer to ignore it.
 */

import { useCallback, useState } from 'react';

import api from '../api/client.js';

const LEVEL_COLOR = {
  MODERATE: '#d4882a',
  HIGH: '#c0392b',
  CRITICAL: '#c0392b',
};

export default function AlertLog({ payload, loading, onSent }) {
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const alerts = payload?.alerts || [];
  const dispatchable = payload?.dispatchable || 0;

  const send = useCallback(async () => {
    setSending(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.sendAlerts();
      setResult(r.detail);
      onSent?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  }, [onSent]);

  return (
    <section className="card">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="card-title">Alert Log</h2>
          <p className="card-sub">
            {alerts.length} recent · {dispatchable} pending dispatch
          </p>
        </div>

        {dispatchable > 0 ? (
          <button type="button" className="btn-danger" onClick={send} disabled={sending}>
            {sending ? 'Sending…' : 'Send Alert'}
          </button>
        ) : null}
      </div>

      {result ? <p className="mt-3 text-sm text-accent">{result}</p> : null}
      {error ? <p className="mt-3 text-sm text-high">{error}</p> : null}

      {loading ? (
        <p className="mt-4 text-base text-muted">Loading…</p>
      ) : alerts.length === 0 ? (
        <p className="mt-4 text-base text-muted">
          No alerts raised. Alerts appear when a district&rsquo;s projected supply
          exceeds recent mandi absorption.
        </p>
      ) : (
        <table className="data-table mt-4">
          <thead>
            <tr>
              <th>Date</th>
              <th>District</th>
              <th>Crop</th>
              <th className="num">Ratio</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a, i) => (
              // eslint-disable-next-line react/no-array-index-key
              <tr key={`${a.district}-${a.crop}-${a.date}-${i}`}>
                <td className="text-muted">{a.date}</td>
                <td>{a.district}</td>
                <td>{a.crop}</td>
                <td className="num" style={{ color: LEVEL_COLOR[a.level] || '#111111' }}>
                  {a.ratio.toFixed(2)}×
                </td>
                <td className="text-muted">
                  {a.action}
                  {a.recipients ? ` · ${a.recipients}` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

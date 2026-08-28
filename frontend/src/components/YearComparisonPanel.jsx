/**
 * This season's expected production against what the market took last year.
 *
 * Needs a year of collected arrivals to say anything. Until then it reports
 * what is missing and roughly when it will fill, rather than drawing a chart
 * from one side of a comparison.
 */

function pct(v) {
  if (v == null) return null;
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
}

export default function YearComparisonPanel({ payload, loading, district }) {
  const crops = payload?.crops || [];
  const comparable = payload?.comparable || 0;

  return (
    <section className="p-5">
      <h2 className="card-title">Compared with last year</h2>
      <p className="card-sub">
        Expected production now, against what {district || 'the district'} sold in
        the same weeks a year ago
      </p>

      {loading ? (
        <p className="mt-4 text-base text-muted">Loading…</p>
      ) : crops.length === 0 ? (
        <p className="mt-4 max-w-3xl text-base text-muted">
          {payload?.notes?.[0] ||
            'Nothing classified for this district yet, so there is no production to compare.'}
        </p>
      ) : (
        <>
          <table className="data-table mt-4">
            <thead>
              <tr>
                <th>Crop</th>
                <th className="num">Expected now</th>
                <th className="num">Sold last year</th>
                <th className="num">Change</th>
                <th className="num">Price change</th>
              </tr>
            </thead>
            <tbody>
              {crops.map((c) => (
                <tr key={c.crop}>
                  <td>{c.crop}</td>
                  <td className="num">
                    {c.projected_volume_mt != null
                      ? `${Math.round(c.projected_volume_mt).toLocaleString()} t`
                      : '—'}
                  </td>
                  <td className="num">
                    {c.prior_year_arrivals_mt != null
                      ? `${Math.round(c.prior_year_arrivals_mt).toLocaleString()} t`
                      : '—'}
                  </td>
                  <td
                    className="num"
                    style={{
                      color:
                        c.vs_prior_year_ratio == null
                          ? '#6b7280'
                          : c.vs_prior_year_ratio > 1.2
                            ? '#c0392b'
                            : '#111111',
                    }}
                  >
                    {c.vs_prior_year_ratio != null
                      ? `${c.vs_prior_year_ratio.toFixed(2)}×`
                      : '—'}
                  </td>
                  <td
                    className="num"
                    style={{
                      color:
                        c.price_change_pct == null
                          ? '#6b7280'
                          : c.price_change_pct < 0
                            ? '#c0392b'
                            : '#1a5c2a',
                    }}
                  >
                    {pct(c.price_change_pct) ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {comparable === 0 ? (
            <p className="mt-3 max-w-3xl text-sm leading-relaxed text-muted">
              {crops[0]?.detail}
            </p>
          ) : null}

          <p className="mt-3 text-xs text-muted">
            Last year&rsquo;s window: {payload.prior_window?.start} to{' '}
            {payload.prior_window?.end}, widened by {payload.slack_days} days each
            side because sowing shifts with the monsoon.
          </p>
        </>
      )}
    </section>
  );
}

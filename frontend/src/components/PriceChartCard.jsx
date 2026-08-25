/**
 * Mandi price history.
 *
 * Chart conventions follow the design system: horizontal gridlines only, month
 * labels on the x-axis, no dots on the line, no legend box. One colour per
 * crop, matching the risk palette so tomato reads consistently across cards.
 *
 * `connectNulls` stays off. AGMARKNET publishes irregularly and is sometimes
 * unreachable for days; bridging those gaps would draw a price trend across
 * dates where no quote was ever recorded.
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

const SERIES = [
  { key: 'tomato', label: 'Tomato', color: '#c0392b' },
  { key: 'onion', label: 'Onion', color: '#d4882a' },
  { key: 'leafy_greens', label: 'Leafy greens', color: '#1a5c2a' },
];

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function monthTick(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  return MONTHS[d.getMonth()];
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="border border-line bg-white px-3 py-2 shadow-card">
      <p className="text-xs text-muted">{label}</p>
      {payload.map((e) => (
        <p key={e.dataKey} className="mt-1 flex items-center gap-2 text-sm">
          <span className="dot" style={{ backgroundColor: e.color }} />
          <span className="text-ink">{SERIES.find((s) => s.key === e.dataKey)?.label}</span>
          <span className="ml-auto text-ink tnum">
            {e.value == null ? '—' : `₹${Math.round(e.value).toLocaleString('en-IN')}`}
          </span>
        </p>
      ))}
    </div>
  );
}

export default function PriceChartCard({ series, loading, windowDays = 90 }) {
  const data = series || [];
  const hasAny = data.some((d) => SERIES.some((s) => d[s.key] != null));

  return (
    <section className="card">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="card-title">Mandi Prices</h2>
          <p className="card-sub">{windowDays}-day · Karnataka</p>
        </div>
        <div className="flex gap-3">
          {SERIES.map((s) => (
            <span key={s.key} className="flex items-center gap-1.5 text-xs text-muted">
              <span className="dot" style={{ backgroundColor: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      </div>

      {loading ? (
        <p className="mt-4 text-base text-muted">Loading prices…</p>
      ) : !hasAny ? (
        <div className="mt-4">
          <p className="text-base text-muted">No quotes cached for this window.</p>
          <p className="mt-1 text-xs text-muted">
            AGMARKNET publishes irregularly and has been unreachable; prices
            appear here as soon as the feed responds.
          </p>
        </div>
      ) : (
        <div className="mt-4 h-[240px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#e5e7eb" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={monthTick}
                tick={{ fontSize: 11, fill: '#6b7280' }}
                tickLine={false}
                axisLine={{ stroke: '#e5e7eb' }}
                minTickGap={40}
              />
              <YAxis
                tick={{ fontSize: 11, fill: '#6b7280' }}
                tickLine={false}
                axisLine={false}
                width={52}
                label={{
                  value: '₹/quintal',
                  angle: -90,
                  position: 'insideLeft',
                  style: { fontSize: 10, fill: '#6b7280' },
                }}
              />
              <Tooltip content={<ChartTooltip />} />
              {SERIES.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  stroke={s.color}
                  strokeWidth={1.5}
                  dot={false}
                  activeDot={{ r: 3 }}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <p className="mt-2 text-right text-2xs text-muted">Source: Agmarknet</p>
    </section>
  );
}

/**
 * Harvest timing from the greenness curve.
 *
 * The chart is the argument: a reader can see the rise, the peak and the fall
 * and judge for themselves whether the estimate sits where it should. A date
 * on its own would have to be taken on trust.
 */

import { useCallback, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import api from '../api/client.js';

const CROPS = [
  { key: 'tomato', label: 'Tomato' },
  { key: 'onion', label: 'Onion' },
  { key: 'potato', label: 'Potato' },
  { key: 'leafy_greens', label: 'Leafy greens' },
];

/** Plain-language reading of each status. */
const EXPLAIN = {
  INSUFFICIENT_SERIES: 'Not enough greenness readings yet',
  PEAK_NOT_REACHED: 'The crop is still growing',
  NO_SENESCENCE_CONSTANT: 'No ripening interval recorded for this crop',
};

function ChartTip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="border border-line bg-white px-3 py-2 text-xs">
      <p className="text-muted">{label}</p>
      <p className="mt-0.5 text-ink tnum">NDVI {Number(payload[0].value).toFixed(3)}</p>
    </div>
  );
}

export default function HarvestPanel({ district, payload, loading, onRefresh }) {
  const [crop, setCrop] = useState('tomato');
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState(null);

  const buildSeries = useCallback(async () => {
    if (!district) return;
    setBuilding(true);
    setBuildError(null);
    try {
      await api.buildNdviSeries({ district, lookbackDays: 180 });
      onRefresh?.();
    } catch (e) {
      setBuildError(e.message);
    } finally {
      setBuilding(false);
    }
  }, [district, onRefresh]);

  const series = payload?.series || [];
  const ready = payload?.status === 'OK';

  return (
    <section className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="card-title">Harvest timing</h2>
          <p className="card-sub">
            Estimated from how the district&rsquo;s greenness rises and falls
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex border border-line">
            {CROPS.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => setCrop(c.key)}
                className={
                  crop === c.key
                    ? 'bg-ink px-2.5 py-1 text-xs text-white'
                    : 'px-2.5 py-1 text-xs text-muted hover:text-ink'
                }
              >
                {c.label}
              </button>
            ))}
          </div>
          <button type="button" className="btn text-xs" onClick={buildSeries} disabled={building}>
            {building ? 'Reading imagery…' : 'Rebuild series'}
          </button>
        </div>
      </div>

      {buildError ? <p className="mt-3 text-base text-high">{buildError}</p> : null}

      {loading ? (
        <p className="mt-4 text-base text-muted">Loading…</p>
      ) : ready ? (
        <>
          <div className="mt-4 grid grid-cols-3 gap-6">
            <div>
              <p className="text-xs text-muted">Likely harvest</p>
              <p className="mt-0.5 text-xl font-semibold text-ink">
                {payload.estimated_harvest}
              </p>
              <p className="text-xs text-muted">
                {payload.days_from_now >= 0
                  ? `in about ${payload.days_from_now} days`
                  : `about ${Math.abs(payload.days_from_now)} days ago`}
                {payload.uncertainty_days ? ` · give or take ${payload.uncertainty_days}` : ''}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted">Greenest point</p>
              <p className="mt-0.5 text-xl font-semibold text-ink">{payload.peak_date}</p>
              <p className="text-xs text-muted tnum">NDVI {payload.peak_ndvi}</p>
            </div>
            <div>
              <p className="text-xs text-muted">Latest reading</p>
              <p className="mt-0.5 text-xl font-semibold text-ink">{payload.latest_date}</p>
              <p className="text-xs text-muted tnum">NDVI {payload.latest_ndvi}</p>
            </div>
          </div>

          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-muted">{payload.detail}</p>
          <p className="mt-1 text-xs text-muted">Worked out from: {payload.method}</p>
        </>
      ) : (
        <div className="mt-4">
          <p className="text-base text-ink">
            {EXPLAIN[payload?.status] || 'No estimate yet'}
          </p>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted">
            {payload?.detail ||
              'Build the greenness series for this district to get an estimate.'}
          </p>
        </div>
      )}

      {series.length > 1 ? (
        <div className="mt-5">
          <p className="text-xs text-muted">
            Greenness over time · {series.length} readings, one per 16 days
          </p>
          <div className="mt-2 h-[220px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#e5e7eb" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: '#6b7280' }}
                  tickLine={false}
                  axisLine={{ stroke: '#e5e7eb' }}
                  tickFormatter={(v) => String(v).slice(5)}
                  minTickGap={28}
                />
                <YAxis
                  domain={[0, 1]}
                  tick={{ fontSize: 11, fill: '#6b7280' }}
                  tickLine={false}
                  axisLine={false}
                  width={40}
                />
                <Tooltip content={<ChartTip />} />
                {payload?.peak_date ? (
                  <ReferenceLine
                    x={payload.peak_date}
                    stroke="#1a5c2a"
                    strokeDasharray="3 3"
                    label={{ value: 'peak', fontSize: 10, fill: '#1a5c2a', position: 'top' }}
                  />
                ) : null}
                <Line
                  type="monotone"
                  dataKey="ndvi"
                  stroke="#1a5c2a"
                  strokeWidth={1.6}
                  dot={{ r: 2 }}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-1 text-xs text-muted">
            Gaps are fortnights with no clear satellite view. They are left
            empty rather than filled in.
          </p>
        </div>
      ) : null}
    </section>
  );
}

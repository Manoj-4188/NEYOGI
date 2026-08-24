/**
 * 21-day projected supply versus observed mandi arrivals.
 *
 * Days the AGMARKNET feed did not publish arrive as `null` and are left as
 * gaps in the line (`connectNulls` is off) rather than being bridged — a
 * connected line across a silent week would imply observations that were never
 * made.
 */

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { WithheldValue } from './StatusBadge.jsx';

const FOREST = '#1B3B2B';
const SAGE = '#4E8752';
const TERRACOTTA = '#C45A37';
const GRID = '#D6DCCB';

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="panel px-3 py-2 text-xs">
      <p className="font-semibold text-forest">{label}</p>
      {payload.map((entry) => (
        <p key={entry.dataKey} className="mt-1 flex items-center gap-2">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-forest-900/70">{entry.name}</span>
          <span className="ml-auto font-mono tabular-nums text-forest">
            {entry.value == null ? '—' : Number(entry.value).toLocaleString()}
          </span>
        </p>
      ))}
    </div>
  );
}

/**
 * Per-crop summary tile. Renders the oversupply ratio, or an explicit reason
 * the ratio could not be computed.
 */
export function SupplySummary({ crop }) {
  const ok = crop.status === 'OK';
  const ratio = crop.oversupply_ratio;
  const oversupplied = ok && ratio != null && ratio > 1.25;

  return (
    <div className="panel px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-forest">{crop.crop}</h3>
          <p className="stat-label mt-0.5">
            {crop.classified_area_ha.toLocaleString()} ha · {crop.parcel_count} parcels
          </p>
        </div>
        {oversupplied ? (
          <span className="rounded-full bg-terracotta-100 px-2 py-1 text-xs font-semibold text-terracotta-600">
            Oversupply risk
          </span>
        ) : null}
      </div>

      <dl className="mt-3 grid grid-cols-3 gap-3">
        <div>
          <dt className="stat-label">Projected</dt>
          <dd>
            {crop.projected_volume_mt != null ? (
              <span className="stat-value">
                {Math.round(crop.projected_volume_mt).toLocaleString()}
                <span className="ml-1 text-xs font-normal text-sage-600">MT</span>
              </span>
            ) : (
              <WithheldValue reason={crop.detail} label="no verified yield" />
            )}
          </dd>
        </div>
        <div>
          <dt className="stat-label">Arrivals</dt>
          <dd>
            {crop.observed_arrivals_mt != null ? (
              <span className="stat-value">
                {Math.round(crop.observed_arrivals_mt).toLocaleString()}
                <span className="ml-1 text-xs font-normal text-sage-600">MT</span>
              </span>
            ) : (
              <WithheldValue reason={crop.detail} label="not published" />
            )}
          </dd>
        </div>
        <div>
          <dt className="stat-label">Ratio</dt>
          <dd>
            {ratio != null ? (
              <span
                className="stat-value"
                style={{ color: oversupplied ? TERRACOTTA : FOREST }}
              >
                {ratio.toFixed(2)}×
              </span>
            ) : (
              <WithheldValue reason={crop.detail} label="undefined" />
            )}
          </dd>
        </div>
      </dl>

      {crop.detail ? (
        <p className="mt-2 border-t border-parchment-200 pt-2 text-xs text-forest-900/60">
          {crop.detail}
        </p>
      ) : null}

      {crop.yield_baseline ? (
        <p className="mt-1.5 text-xs text-sage-600">
          Yield baseline {crop.yield_baseline.value_mt_ha} MT/ha
          {crop.yield_baseline.source ? ` · ${crop.yield_baseline.source}` : ''}
        </p>
      ) : null}
    </div>
  );
}

export default function SupplyChart({ series, crop, windowDays = 21 }) {
  const data = series || [];

  if (!data.length) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-parchment-300 px-6 text-center">
        <p className="text-sm text-sage-600">
          No mandi quotes cached for {crop} in the last {windowDays} days, so
          there is nothing to chart. Prices are published irregularly; this is a
          gap in the feed, not zero arrivals.
        </p>
      </div>
    );
  }

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: SAGE }}
            tickLine={false}
            axisLine={{ stroke: GRID }}
            tickFormatter={(value) => String(value).slice(5)}
          />
          <YAxis
            yAxisId="volume"
            tick={{ fontSize: 11, fill: SAGE }}
            tickLine={false}
            axisLine={false}
            width={52}
            label={{
              value: 'MT',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: SAGE },
            }}
          />
          <YAxis
            yAxisId="price"
            orientation="right"
            tick={{ fontSize: 11, fill: TERRACOTTA }}
            tickLine={false}
            axisLine={false}
            width={56}
            label={{
              value: '₹/qtl',
              angle: 90,
              position: 'insideRight',
              style: { fontSize: 11, fill: TERRACOTTA },
            }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
            iconType="circle"
            iconSize={8}
          />
          <Bar
            yAxisId="volume"
            dataKey="arrival_volume_mt"
            name="Mandi arrivals (MT)"
            fill={SAGE}
            radius={[3, 3, 0, 0]}
            maxBarSize={22}
          />
          <Line
            yAxisId="price"
            type="monotone"
            dataKey="modal_price"
            name="Modal price (₹/quintal)"
            stroke={TERRACOTTA}
            strokeWidth={2}
            dot={{ r: 2.5, fill: TERRACOTTA }}
            // Gaps stay gaps: no interpolation across days with no quote.
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

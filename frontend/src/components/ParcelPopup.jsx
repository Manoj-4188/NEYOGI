/**
 * Parcel detail rendering — a compact Leaflet popup and a fuller side panel.
 *
 * Both are careful about one thing: they distinguish a *measured* value from a
 * *withheld* one. Spectral indices are measurements and are always shown. A
 * crop class is shown only where the server supplied one; where it did not,
 * the reason is printed instead of a blank or a guess.
 */

import { useEffect, useState } from 'react';

import api from '../api/client.js';

/** Escape untrusted text before it enters the Leaflet popup's innerHTML. */
function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

const KEY_INDICES = ['NDVI', 'EVI', 'NDMI', 'NDRE'];

/**
 * Build the HTML bound to each polygon. Returns a string because Leaflet
 * popups take markup, not React elements.
 */
export function buildPopupHtml(props = {}, renderMode = 'ndvi_basemap') {
  const indices = props.indices || {};
  const indexRows = KEY_INDICES.filter((name) => indices[name] !== undefined)
    .map(
      (name) => `
        <div style="display:flex;justify-content:space-between;gap:12px">
          <span style="color:#4E8752">${escapeHtml(name)}</span>
          <span style="font-variant-numeric:tabular-nums;font-weight:600">
            ${Number(indices[name]).toFixed(3)}
          </span>
        </div>`,
    )
    .join('');

  let cropBlock;
  if (renderMode === 'crop_classes' && (props.crop_label || props.predicted_class)) {
    const verified = Boolean(props.crop_label);
    const label = escapeHtml(props.crop_label || props.predicted_class);
    const confidence =
      !verified && props.probability != null
        ? ` <span style="color:#4E8752">(${(props.probability * 100).toFixed(0)}% confidence)</span>`
        : '';
    cropBlock = `
      <p style="margin:0 0 6px;font-size:15px;font-weight:700;color:#1B3B2B">
        ${label}${confidence}
      </p>
      <p style="margin:0 0 8px;font-size:11px;color:#4E8752">
        ${verified ? '✓ Field-verified label' : 'Model prediction'}
      </p>`;
  } else {
    const reason =
      props.classification_withheld_reason || 'No verified ground truth for this district';
    cropBlock = `
      <p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#C45A37">
        Crop not classified
      </p>
      <p style="margin:0 0 8px;font-size:11px;color:#C45A37">${escapeHtml(reason)}</p>`;
  }

  return `
    <div style="font-family:Inter,system-ui,sans-serif;padding:12px 14px;min-width:200px">
      ${cropBlock}
      <div style="font-size:12px;line-height:1.6">
        <div style="display:flex;justify-content:space-between;gap:12px">
          <span style="color:#4E8752">Parcel</span>
          <span style="font-weight:600">${escapeHtml(props.parcel_uid || props.id)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:12px">
          <span style="color:#4E8752">Area</span>
          <span style="font-variant-numeric:tabular-nums;font-weight:600">
            ${props.area_ha != null ? `${Number(props.area_ha).toFixed(2)} ha` : '—'}
          </span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:12px">
          <span style="color:#4E8752">Observed</span>
          <span style="font-weight:600">${escapeHtml(props.observed_on || 'no imagery')}</span>
        </div>
        ${indexRows}
      </div>
    </div>`;
}

function Row({ label, children }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="text-xs uppercase tracking-wide text-sage-600">{label}</span>
      <span className="text-right text-sm font-medium text-forest-900">{children}</span>
    </div>
  );
}

/**
 * Side panel for the selected parcel, including its full index history.
 */
export default function ParcelDetails({ parcel, onClose }) {
  const [series, setSeries] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!parcel?.id) return undefined;
    let cancelled = false;
    setSeries(null);
    setError(null);

    api
      .parcelSeries({ parcelId: parcel.id, index: 'NDVI' })
      .then((payload) => {
        if (!cancelled) setSeries(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, [parcel?.id]);

  if (!parcel) return null;

  const ndvi = series?.series?.NDVI || [];
  const indices = parcel.indices || {};
  const verified = Boolean(parcel.crop_label);

  return (
    <aside className="panel flex flex-col">
      <header className="panel-header">
        <h2 className="panel-title">Parcel {parcel.parcel_uid || parcel.id}</h2>
        <button type="button" className="btn-secondary px-2 py-1 text-xs" onClick={onClose}>
          Close
        </button>
      </header>

      <div className="divide-y divide-parchment-200 px-4 py-2">
        <Row label="District">{parcel.district}</Row>
        <Row label="Area">
          {parcel.area_ha != null ? `${parcel.area_ha.toFixed(2)} ha` : '—'}
        </Row>
        <Row label="Ground truth">
          {verified ? (
            <span className="text-forest">
              {parcel.crop_label}
              <span className="ml-1.5 text-xs text-sage-600">
                ✓ {parcel.verified_by || 'verified'}
              </span>
            </span>
          ) : (
            <span className="text-terracotta">Not verified</span>
          )}
        </Row>
        <Row label="Model prediction">
          {parcel.predicted_class ? (
            <span>
              {parcel.predicted_class}
              {parcel.probability != null ? (
                <span className="ml-1.5 text-xs text-sage-600">
                  {(parcel.probability * 100).toFixed(0)}%
                </span>
              ) : null}
            </span>
          ) : (
            <span
              className="text-xs text-terracotta"
              title={parcel.classification_withheld_reason}
            >
              {parcel.classification_withheld_reason || 'Not classified'}
            </span>
          )}
        </Row>
        <Row label="Last observed">{parcel.observed_on || 'No cloud-free imagery'}</Row>
        <Row label="Scenes in composite">{parcel.scene_count ?? '—'}</Row>
      </div>

      {Object.keys(indices).length ? (
        <div className="border-t border-parchment-200 px-4 py-3">
          <h3 className="stat-label mb-2">Spectral indices (measured)</h3>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            {Object.entries(indices).map(([name, value]) => (
              <div key={name} className="flex justify-between">
                <dt className="text-sage-600">{name}</dt>
                <dd className="font-mono tabular-nums text-forest-900">
                  {Number(value).toFixed(3)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      <div className="border-t border-parchment-200 px-4 py-3">
        <h3 className="stat-label mb-2">NDVI history</h3>
        {error ? <p className="text-sm text-terracotta">{error}</p> : null}
        {!error && series === null ? (
          <p className="text-sm text-sage-600">Loading…</p>
        ) : null}
        {series && ndvi.length === 0 ? (
          <p className="text-sm text-sage-600">
            No composites recorded for this parcel yet.
          </p>
        ) : null}
        {ndvi.length > 0 ? (
          <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
            {ndvi
              .slice()
              .reverse()
              .map((point) => (
                <li key={point.date} className="flex justify-between">
                  <span className="text-sage-600">{point.date}</span>
                  <span className="font-mono tabular-nums">{point.value.toFixed(3)}</span>
                </li>
              ))}
          </ul>
        ) : null}
      </div>
    </aside>
  );
}

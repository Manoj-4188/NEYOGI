/**
 * Officer console — role-gated.
 *
 * Pipeline telemetry, model diagnostics, the alert log and the manual parcel
 * verification toggle. Verification is the one write on this page and it is
 * the gate on the ground-truth classification path, so the API records who
 * did it.
 */

import { useCallback, useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';

import api from '../api/client.js';
import AlertLog from '../components/AlertLog.jsx';
import ModelCard from '../components/ModelCard.jsx';
import {
  GroundTruthAudit,
  ServiceHealth,
  TileHealth,
  YieldBaselineCoverage,
} from '../components/TelemetryPanel.jsx';
import { useAuth } from '../auth/AuthContext.jsx';

const CROP_CLASSES = ['Tomato', 'Onion', 'Potato', 'Leafy Greens', 'Fallow/Non-Crop'];

function VerificationRow({ parcel, onToggle, busy }) {
  const [cropLabel, setCropLabel] = useState(parcel.crop_label || '');
  const needsLabel = !parcel.verified && !parcel.crop_label && !cropLabel;

  return (
    <tr>
      <td className="font-mono text-xs text-muted">{parcel.parcel_uid}</td>
      <td>
        <select
          className="field py-1 text-sm"
          value={cropLabel}
          onChange={(e) => setCropLabel(e.target.value)}
          disabled={busy}
        >
          <option value="">— no label —</option>
          {CROP_CLASSES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </td>
      <td className="num text-muted">
        {parcel.area_ha != null ? `${parcel.area_ha.toFixed(2)} ha` : '—'}
      </td>
      <td className="text-muted">{parcel.verified_by || '—'}</td>
      <td style={{ color: parcel.verified ? '#1a5c2a' : '#6b7280' }}>
        {parcel.verified ? 'verified' : 'unverified'}
      </td>
      <td className="text-right">
        <button
          type="button"
          className="btn text-xs"
          disabled={busy || (!parcel.verified && needsLabel)}
          title={needsLabel ? 'Choose a crop label first' : undefined}
          onClick={() =>
            onToggle(parcel.id, !parcel.verified, cropLabel || parcel.crop_label || null)
          }
        >
          {parcel.verified ? 'Un-verify' : 'Verify'}
        </button>
      </td>
    </tr>
  );
}

export default function OfficerConsole() {
  const { principal, logout } = useAuth();

  const [telemetry, setTelemetry] = useState(null);
  const [model, setModel] = useState(null);
  const [alerts, setAlerts] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const [district, setDistrict] = useState('Kolar');
  const [parcels, setParcels] = useState([]);
  const [busyParcel, setBusyParcel] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [t, m, a] = await Promise.all([
        api.telemetry(),
        api.model(),
        api.alerts({ limit: 10 }).catch(() => null),
      ]);
      setTelemetry(t);
      setModel(m);
      setAlerts(a);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadParcels = useCallback(async (name) => {
    try {
      const p = await api.reviewParcels({ district: name, limit: 200 });
      setParcels(p.parcels || []);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (district) loadParcels(district);
  }, [district, loadParcels]);

  const handleToggle = useCallback(
    async (parcelId, verified, cropLabel) => {
      setBusyParcel(parcelId);
      setNotice(null);
      try {
        const updated = await api.setVerification({ parcelId, verified, cropLabel });
        setParcels((cur) =>
          cur.map((p) =>
            p.id === parcelId
              ? {
                  ...p,
                  verified: updated.verified,
                  crop_label: updated.crop_label,
                  verified_by: updated.verified_by,
                }
              : p,
          ),
        );
        setNotice(
          `Parcel ${updated.parcel_uid} marked ${updated.verified ? 'verified' : 'unverified'}.`,
        );
        load();
      } catch (err) {
        setError(err.message);
      } finally {
        setBusyParcel(null);
      }
    },
    [load],
  );

  const districts = telemetry?.gee_tile_health?.map((t) => t.district) || [];

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-topbar shrink-0 items-center justify-between border-b border-line px-5">
        <div className="flex items-baseline gap-3">
          <NavLink to="/dashboard" className="text-md font-bold text-ink">
            NEYOGI
          </NavLink>
          <span className="text-xs text-muted">Officer console</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted">
            {principal?.username} · {principal?.role}
          </span>
          <button type="button" className="btn text-xs" onClick={load}>
            Refresh
          </button>
          <button type="button" className="btn text-xs" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        {error ? (
          <p className="border-b border-line px-5 py-3 text-base text-high">{error}</p>
        ) : null}
        {notice ? (
          <p className="border-b border-line px-5 py-3 text-base text-accent">{notice}</p>
        ) : null}

        {loading && !telemetry ? (
          <p className="p-5 text-base text-muted">Loading telemetry…</p>
        ) : null}

        {telemetry ? (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-2 lg:divide-x lg:divide-line">
              <ServiceHealth services={telemetry.services} />
              <GroundTruthAudit audit={telemetry.ground_truth_audit} />
            </div>

            <AlertLog payload={alerts} loading={loading} onSent={load} />

            <TileHealth tiles={telemetry.gee_tile_health} />

            <ModelCard model={model} />

            <YieldBaselineCoverage coverage={telemetry.yield_baseline_coverage} />

            <section className="card">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="card-title">Parcel Verification</h2>
                  <p className="card-sub">
                    Verifying asserts a human-attributed crop label. Only verified
                    parcels reach the ground-truth model.
                  </p>
                </div>
                <select
                  className="field w-auto"
                  value={district}
                  onChange={(e) => setDistrict(e.target.value)}
                >
                  {districts.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </div>

              {parcels.length === 0 ? (
                <p className="mt-4 text-base text-muted">
                  No parcels loaded for {district}.
                </p>
              ) : (
                <div className="mt-4 max-h-[26rem] overflow-y-auto">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Parcel</th>
                        <th>Crop label</th>
                        <th className="num">Area</th>
                        <th>Verified by</th>
                        <th>State</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {parcels.map((p) => (
                        <VerificationRow
                          key={p.id}
                          parcel={p}
                          onToggle={handleToggle}
                          busy={busyParcel === p.id}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}

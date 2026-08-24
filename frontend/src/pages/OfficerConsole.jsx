/**
 * Officer console — role-gated.
 *
 * Shows pipeline telemetry, the model confusion matrix, GEE tile status, and
 * the manual parcel verification toggle. Verification is the one write on this
 * page, and it is the gate on the whole classification path: marking a parcel
 * verified asserts that a human attributed that polygon to that crop, and the
 * API records who did it.
 */

import { useCallback, useEffect, useState } from 'react';

import api from '../api/client.js';
import ConfusionMatrix from '../components/ConfusionMatrix.jsx';
import {
  GroundTruthAudit,
  PipelineRuns,
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
    <tr className="hover:bg-parchment">
      <td className="px-4 py-2 font-mono text-xs text-forest-900/70">{parcel.parcel_uid}</td>
      <td className="px-4 py-2">
        <select
          className="field py-1 text-xs"
          value={cropLabel}
          onChange={(event) => setCropLabel(event.target.value)}
          disabled={busy}
        >
          <option value="">— no label —</option>
          {CROP_CLASSES.map((crop) => (
            <option key={crop} value={crop}>
              {crop}
            </option>
          ))}
        </select>
      </td>
      <td className="px-4 py-2 font-mono tabular-nums text-xs text-forest-900/70">
        {parcel.area_ha != null ? `${parcel.area_ha.toFixed(2)} ha` : '—'}
      </td>
      <td className="px-4 py-2 text-xs text-forest-900/60">{parcel.verified_by || '—'}</td>
      <td className="px-4 py-2">
        {parcel.verified ? (
          <span className="rounded-full bg-sage-100 px-2 py-0.5 text-xs font-semibold text-forest">
            verified
          </span>
        ) : (
          <span className="rounded-full bg-parchment-200 px-2 py-0.5 text-xs font-semibold text-forest-900/60">
            unverified
          </span>
        )}
      </td>
      <td className="px-4 py-2 text-right">
        <button
          type="button"
          className={parcel.verified ? 'btn-secondary px-2.5 py-1 text-xs' : 'btn-primary px-2.5 py-1 text-xs'}
          disabled={busy || (!parcel.verified && needsLabel)}
          title={
            needsLabel
              ? 'Choose a crop label first — a parcel cannot be verified without one.'
              : undefined
          }
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
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const [district, setDistrict] = useState('Kolar');
  const [parcels, setParcels] = useState([]);
  const [busyParcel, setBusyParcel] = useState(null);
  const [notice, setNotice] = useState(null);

  const loadTelemetry = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [telemetryPayload, modelPayload] = await Promise.all([
        api.telemetry(),
        api.model(),
      ]);
      setTelemetry(telemetryPayload);
      setModel(modelPayload);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadParcels = useCallback(async (name) => {
    try {
      const payload = await api.reviewParcels({ district: name, limit: 200 });
      setParcels(payload.parcels || []);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    loadTelemetry();
  }, [loadTelemetry]);

  useEffect(() => {
    if (district) loadParcels(district);
  }, [district, loadParcels]);

  const handleToggle = useCallback(
    async (parcelId, verified, cropLabel) => {
      setBusyParcel(parcelId);
      setNotice(null);
      try {
        const updated = await api.setVerification({ parcelId, verified, cropLabel });
        setParcels((current) =>
          current.map((p) =>
            p.id === parcelId
              ? { ...p, verified: updated.verified, crop_label: updated.crop_label, verified_by: updated.verified_by }
              : p,
          ),
        );
        setNotice(
          `Parcel ${updated.parcel_uid} marked ${updated.verified ? 'verified' : 'unverified'}.`,
        );
        // Verification changes what the system may claim, so refresh the audit.
        loadTelemetry();
      } catch (err) {
        setError(err.message);
      } finally {
        setBusyParcel(null);
      }
    },
    [loadTelemetry],
  );

  const districts = telemetry?.gee_tile_health?.map((t) => t.district) || [];

  return (
    <div className="mx-auto max-w-[100rem] px-4 py-6 lg:px-8">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-forest">Officer Console</h1>
          <p className="mt-1 text-sm text-forest-900/70">
            Pipeline telemetry, model diagnostics and ground-truth verification.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-forest-900/70">
            {principal?.username}
            <span className="ml-1.5 rounded-full bg-sage-100 px-2 py-0.5 text-xs font-semibold text-forest">
              {principal?.role}
            </span>
          </span>
          <button type="button" className="btn-secondary" onClick={loadTelemetry}>
            Refresh
          </button>
          <button type="button" className="btn-secondary" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      {error ? (
        <div className="mb-4 rounded-xl border border-terracotta-200 bg-terracotta-100 px-4 py-3 text-sm text-terracotta-600">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="mb-4 rounded-xl border border-sage-200 bg-sage-100 px-4 py-3 text-sm text-forest">
          {notice}
        </div>
      ) : null}

      {loading && !telemetry ? (
        <p className="py-12 text-center text-sm text-sage-600">Loading telemetry…</p>
      ) : null}

      {telemetry ? (
        <div className="space-y-5">
          <div className="grid gap-5 lg:grid-cols-[20rem_minmax(0,1fr)]">
            <div className="space-y-5">
              <ServiceHealth services={telemetry.services} />
              <YieldBaselineCoverage coverage={telemetry.yield_baseline_coverage} />
            </div>
            <GroundTruthAudit audit={telemetry.ground_truth_audit} />
          </div>

          <TileHealth tiles={telemetry.gee_tile_health} />

          <ConfusionMatrix model={model} />

          <section className="panel">
            <header className="panel-header">
              <div>
                <h2 className="panel-title">Manual parcel verification</h2>
                <p className="mt-0.5 text-xs text-forest-900/60">
                  Verifying a parcel asserts a human-attributed crop label. Only
                  verified parcels are ever classified.
                </p>
              </div>
              <select
                className="field w-auto min-w-[11rem]"
                value={district}
                onChange={(event) => setDistrict(event.target.value)}
              >
                {districts.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </header>

            {parcels.length === 0 ? (
              <p className="px-4 py-6 text-sm text-sage-600">
                No parcels loaded for {district}. Ingest ground truth with{' '}
                <code className="font-mono text-xs">
                  python -m ml_pipeline.load_ground_truth
                </code>
                .
              </p>
            ) : (
              <div className="max-h-[32rem] overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-white">
                    <tr className="border-b border-parchment-200 text-left">
                      {['Parcel', 'Crop label', 'Area', 'Verified by', 'State', ''].map((h) => (
                        <th
                          key={h}
                          className="px-4 py-2 text-xs uppercase tracking-wide text-sage-600"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-parchment-200">
                    {parcels.map((parcel) => (
                      <VerificationRow
                        key={parcel.id}
                        parcel={parcel}
                        onToggle={handleToggle}
                        busy={busyParcel === parcel.id}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <PipelineRuns runs={telemetry.pipeline_runs} />
        </div>
      ) : null}
    </div>
  );
}

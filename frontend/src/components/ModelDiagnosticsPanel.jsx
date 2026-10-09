import React, { useEffect, useState } from 'react';
import api from '../api/client.js';

export default function ModelDiagnosticsPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeChart, setActiveChart] = useState('comparison');

  useEffect(() => {
    fetch('/api/v1/analysis/models/benchmark')
      .then((res) => res.json())
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load ML benchmarks:', err);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return <div className="p-8 text-center text-muted">Loading ML Model Diagnostics…</div>;
  }

  const charts = [
    { id: 'comparison', label: 'Architecture Comparison', url: '/api/v1/analysis/charts/model-comparison' },
    { id: 'confusion_matrix', label: 'Confusion Matrix (3 Models)', url: '/api/v1/analysis/charts/confusion-matrix' },
    { id: 'feature_importance', label: 'Feature Importance (Sentinel-2)', url: '/api/v1/analysis/charts/feature-importance' },
  ];

  return (
    <div className="space-y-6 p-6">
      {/* Header Banner */}
      <div className="rounded-lg border border-line bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-ink">Multispectral Crop Classification Benchmarking</h2>
            <p className="text-sm text-muted mt-1">
              Comparative empirical evaluation of Random Forest, XGBoost, and SVM across 10 Sentinel-2 bands and vegetation indices.
            </p>
          </div>
          <span className="rounded bg-accent-wash px-3 py-1 font-mono text-xs font-semibold text-accent">
            5-Fold Stratified CV
          </span>
        </div>
      </div>

      {/* Metrics Table */}
      <div className="rounded-lg border border-line bg-white p-5 shadow-sm">
        <h3 className="text-base font-semibold text-ink mb-3">Model Performance Comparison</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line bg-wash text-xs font-semibold text-muted">
              <tr>
                <th className="py-2.5 px-3">Model Architecture</th>
                <th className="py-2.5 px-3">Accuracy</th>
                <th className="py-2.5 px-3">Precision (Weighted)</th>
                <th className="py-2.5 px-3">Recall (Weighted)</th>
                <th className="py-2.5 px-3">F1-Score (Weighted)</th>
                <th className="py-2.5 px-3">Cohen's Kappa (κ)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data?.models?.map((m) => (
                <tr key={m.name} className="hover:bg-wash transition-colors">
                  <td className="py-3 px-3 font-semibold text-ink">{m.name}</td>
                  <td className="py-3 px-3 text-ink font-mono">{m.accuracy}%</td>
                  <td className="py-3 px-3 text-ink font-mono">{m.precision}%</td>
                  <td className="py-3 px-3 text-ink font-mono">{m.recall}%</td>
                  <td className="py-3 px-3 text-ink font-mono font-bold text-accent">{m.f1_weighted}%</td>
                  <td className="py-3 px-3 text-ink font-mono">{m.kappa}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Visual Diagnostic Charts */}
      <div className="rounded-lg border border-line bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between border-b border-line pb-3 mb-4">
          <h3 className="text-base font-semibold text-ink">Diagnostic Visualizations</h3>
          <div className="flex gap-2">
            {charts.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setActiveChart(c.id)}
                className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                  activeChart === c.id
                    ? 'bg-accent text-white shadow-sm'
                    : 'bg-wash text-muted hover:text-ink border border-line'
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex justify-center bg-wash p-4 rounded-lg border border-line">
          <img
            src={charts.find((c) => c.id === activeChart)?.url}
            alt={activeChart}
            className="max-h-[500px] w-auto rounded shadow-sm object-contain"
          />
        </div>

        <p className="mt-3 text-xs text-muted text-center">
          Generated via Scikit-Learn, XGBoost, and Seaborn for the NEYOGI B.E. Capstone Thesis.
        </p>
      </div>
    </div>
  );
}

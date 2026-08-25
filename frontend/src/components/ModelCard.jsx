/**
 * Field-verified classifier metrics and confusion matrix.
 *
 * Distinct from the spectral model shown on the dashboard: this is the one
 * trained on ground-truth parcels, and it only exists once a field survey has
 * been loaded. Cohen's kappa leads rather than accuracy, because a
 * fallow-dominated label set flatters raw accuracy.
 */

function cellShade(value, rowTotal, isDiagonal) {
  if (!rowTotal || !value) return {};
  const share = value / rowTotal;
  const rgb = isDiagonal ? '26, 92, 42' : '192, 57, 43';
  return {
    backgroundColor: `rgba(${rgb}, ${0.08 + share * 0.6})`,
    color: share > 0.6 ? '#ffffff' : '#111111',
  };
}

export default function ModelCard({ model }) {
  if (!model?.active) {
    return (
      <section className="card">
        <h2 className="card-title">Field-Verified Classifier</h2>
        <p className="card-sub">Separate from the spectral model on the dashboard</p>
        <p className="mt-3 text-base text-muted">
          No ground-truth model is registered. Train one once verified parcels
          exist:
        </p>
        <code className="mt-2 block border border-line bg-wash px-3 py-2 font-mono text-xs text-ink">
          python -m ml_pipeline.train_classifier
        </code>
      </section>
    );
  }

  const { active } = model;
  const holdout = active.metrics?.holdout || {};
  const cv = active.metrics?.cross_validation || {};
  const perClass = holdout.per_class || {};
  const labels = active.confusion_matrix?.labels || active.class_labels || [];
  const matrix = active.confusion_matrix?.matrix || [];

  return (
    <section className="card">
      <h2 className="card-title">Field-Verified Classifier</h2>
      <p className="card-sub">
        {active.model_version} · {active.n_training_samples.toLocaleString()} observations
      </p>

      <div className="mt-4 grid grid-cols-4 gap-4">
        {[
          ["Cohen's kappa", holdout.cohen_kappa, 'chance-corrected'],
          ['Macro F1', holdout.macro_avg?.f1, 'unweighted mean'],
          ['Accuracy', holdout.accuracy, `${holdout.n_test_parcels ?? '?'} parcels`],
          [`CV kappa`, cv.kappa_mean, `${cv.n_splits || 5}-fold`],
        ].map(([label, value, hint]) => (
          <div key={label}>
            <p className="text-xs text-muted">{label}</p>
            <p className="mt-0.5 text-xl font-semibold text-ink tnum">
              {value != null ? value.toFixed(3) : '—'}
            </p>
            <p className="text-xs text-muted">{hint}</p>
          </div>
        ))}
      </div>

      {labels.length && matrix.length ? (
        <div className="mt-5 overflow-x-auto">
          <p className="text-xs text-muted">
            Confusion matrix — rows are ground truth, columns predictions
          </p>
          <table className="mt-2 text-xs">
            <thead>
              <tr>
                <th />
                {labels.map((l) => (
                  <th key={l} className="px-2 py-1 text-center font-medium text-muted">
                    {l}
                  </th>
                ))}
                <th className="px-2 py-1 text-center font-medium text-muted">Recall</th>
              </tr>
            </thead>
            <tbody>
              {matrix.map((row, ri) => {
                const total = row.reduce((s, v) => s + v, 0);
                const label = labels[ri];
                return (
                  <tr key={label}>
                    <th className="whitespace-nowrap py-1 pr-2 text-right font-medium text-muted">
                      {label}
                    </th>
                    {row.map((v, ci) => (
                      <td
                        key={`${label}-${labels[ci]}`}
                        className="px-2 py-1.5 text-center tnum"
                        style={cellShade(v, total, ri === ci)}
                      >
                        {v}
                      </td>
                    ))}
                    <td className="px-2 py-1.5 text-center text-muted tnum">
                      {perClass[label]?.recall != null
                        ? perClass[label].recall.toFixed(2)
                        : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

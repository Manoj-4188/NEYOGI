/**
 * Hold-out confusion matrix and per-class metrics for the active classifier.
 *
 * Cohen's kappa is given headline treatment rather than accuracy: with a
 * fallow-dominated label set, raw accuracy flatters the model, and kappa
 * discounts the agreement you would get by chance.
 */

const FOREST_RGB = '27, 59, 43';
const TERRACOTTA_RGB = '196, 90, 55';

function cellStyle(value, rowTotal, isDiagonal) {
  if (!rowTotal) return {};
  const share = value / rowTotal;
  if (share === 0) return {};
  const rgb = isDiagonal ? FOREST_RGB : TERRACOTTA_RGB;
  return {
    backgroundColor: `rgba(${rgb}, ${0.08 + share * 0.72})`,
    color: share > 0.55 ? '#F4F6F0' : '#12281D',
  };
}

function Metric({ label, value, hint, tone = 'forest' }) {
  const color = tone === 'terracotta' ? 'text-terracotta' : 'text-forest';
  return (
    <div>
      <p className="stat-label">{label}</p>
      <p className={`stat-value ${color}`}>{value}</p>
      {hint ? <p className="text-xs text-sage-600">{hint}</p> : null}
    </div>
  );
}

export default function ConfusionMatrix({ model }) {
  if (!model?.active) {
    return (
      <section className="panel px-4 py-6">
        <h2 className="panel-title mb-2">Classifier</h2>
        <p className="text-sm text-terracotta">
          No trained model is registered. Until one is, districts render as raw
          spectral indices and no crop predictions are produced.
        </p>
        <p className="mt-2 font-mono text-xs text-forest-900/60">
          python -m ml_pipeline.train_classifier
        </p>
      </section>
    );
  }

  const { active } = model;
  const labels = active.confusion_matrix?.labels || active.class_labels || [];
  const matrix = active.confusion_matrix?.matrix || [];
  const holdout = active.metrics?.holdout || {};
  const cv = active.metrics?.cross_validation || {};
  const perClass = holdout.per_class || {};

  const kappa = holdout.cohen_kappa;
  const kappaTone = kappa != null && kappa < 0.6 ? 'terracotta' : 'forest';

  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <h2 className="panel-title">Classifier — {active.model_version}</h2>
          <p className="mt-0.5 text-xs text-forest-900/60">
            {active.n_training_samples.toLocaleString()} observations ·{' '}
            {active.metrics?.protocol?.split || '80/20 stratified'} · trained{' '}
            {new Date(active.trained_at).toLocaleDateString()}
          </p>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-4 border-b border-parchment-200 px-4 py-3 sm:grid-cols-4">
        <Metric
          label="Cohen's kappa"
          value={kappa != null ? kappa.toFixed(3) : '—'}
          hint="hold-out, chance-corrected"
          tone={kappaTone}
        />
        <Metric
          label="Macro F1"
          value={holdout.macro_avg?.f1 != null ? holdout.macro_avg.f1.toFixed(3) : '—'}
          hint="unweighted class mean"
        />
        <Metric
          label="Accuracy"
          value={holdout.accuracy != null ? holdout.accuracy.toFixed(3) : '—'}
          hint={`${holdout.n_test_parcels ?? '?'} held-out parcels`}
        />
        <Metric
          label={`CV kappa (${cv.n_splits || 5}-fold)`}
          value={cv.kappa_mean != null ? cv.kappa_mean.toFixed(3) : '—'}
          hint={cv.kappa_std != null ? `±${cv.kappa_std.toFixed(3)}` : undefined}
        />
      </div>

      {labels.length && matrix.length ? (
        <div className="overflow-x-auto px-4 py-4">
          <p className="stat-label mb-2">
            Confusion matrix — rows are ground truth, columns are predictions
          </p>
          <table className="text-xs">
            <thead>
              <tr>
                <th className="px-2 py-1" />
                {labels.map((label) => (
                  <th
                    key={label}
                    className="max-w-[5.5rem] px-2 py-1 text-center font-medium text-sage-600"
                  >
                    {label}
                  </th>
                ))}
                <th className="px-2 py-1 text-center font-medium text-sage-600">Recall</th>
              </tr>
            </thead>
            <tbody>
              {matrix.map((row, rowIndex) => {
                const rowTotal = row.reduce((sum, value) => sum + value, 0);
                const label = labels[rowIndex];
                return (
                  <tr key={label}>
                    <th className="whitespace-nowrap px-2 py-1 text-right font-medium text-sage-600">
                      {label}
                    </th>
                    {row.map((value, columnIndex) => (
                      <td
                        key={`${label}-${labels[columnIndex]}`}
                        className="px-2 py-1.5 text-center font-mono tabular-nums"
                        style={cellStyle(value, rowTotal, rowIndex === columnIndex)}
                        title={`${value} ${label} parcel(s) predicted as ${labels[columnIndex]}`}
                      >
                        {value}
                      </td>
                    ))}
                    <td className="px-2 py-1.5 text-center font-mono tabular-nums text-forest-900/70">
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

      {Object.keys(perClass).length ? (
        <div className="overflow-x-auto border-t border-parchment-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-parchment-200 text-left">
                {['Class', 'Precision', 'Recall', 'F1', 'Support'].map((heading) => (
                  <th
                    key={heading}
                    className="px-4 py-2 text-xs uppercase tracking-wide text-sage-600"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-parchment-200">
              {Object.entries(perClass).map(([label, metrics]) => (
                <tr key={label}>
                  <td className="px-4 py-2 font-medium text-forest-900">{label}</td>
                  <td className="px-4 py-2 font-mono tabular-nums">
                    {metrics.precision.toFixed(3)}
                  </td>
                  <td className="px-4 py-2 font-mono tabular-nums">
                    {metrics.recall.toFixed(3)}
                  </td>
                  <td className="px-4 py-2 font-mono tabular-nums">
                    {metrics.f1.toFixed(3)}
                  </td>
                  <td className="px-4 py-2 font-mono tabular-nums text-forest-900/70">
                    {metrics.support}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Crop classification results from the spectral model.
 *
 * The subheading is not decoration. These areas are extrapolated from a point
 * sample classified by a model that was not trained on field-verified parcels
 * from this belt, and the card says so directly under its own title rather
 * than burying it in a tooltip.
 *
 * Confidence is shown per crop because it varies a lot between them, and a
 * reader deciding whether to act on "tomato, 142 ha" needs to see 0.49 next
 * to it.
 */

import { useLanguage } from '../i18n/LanguageContext.jsx';

export default function CropClassificationCard({ payload, loading, error, district }) {
  const { t } = useLanguage();
  const crops = payload?.crops || [];

  return (
    <section className="card">
      <h2 className="card-title">{t.classification.title}</h2>
      <p className="card-sub">{t.classification.subtitle}</p>

      {loading ? (
        <p className="mt-4 text-base text-muted">{t.status.loading}</p>
      ) : error ? (
        <p className="mt-4 text-base text-high">{error}</p>
      ) : crops.length === 0 ? (
        <div className="mt-4">
          <p className="text-base text-muted">
            No classification available for {district || 'this district'}.
          </p>
        </div>
      ) : (
        <>
          <table className="data-table mt-4">
            <thead>
              <tr>
                <th>{t.classification.cropCol}</th>
                <th className="num">{t.classification.areaCol}</th>
                <th className="num">{t.classification.confCol}</th>
              </tr>
            </thead>
            <tbody>
              {crops.map((c) => (
                <tr key={c.crop}>
                  <td className="font-medium">{t.crops[c.crop] || c.crop.replace(/_/g, ' ')}</td>
                  <td className="num">{Math.round(c.area_ha).toLocaleString()}</td>
                  <td className="num">
                    {c.crop === 'other' ? (
                      <span className="text-muted">—</span>
                    ) : (
                      c.confidence.toFixed(2)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-3 text-xs text-muted">
            {payload.samples_classified} {t.classification.samples} ·{' '}
            {Math.round(payload.cropland_area_ha).toLocaleString()} {t.classification.cropland} ·{' '}
            {t.classification.composite} {payload.composite_start}
          </p>
        </>
      )}
    </section>
  );
}

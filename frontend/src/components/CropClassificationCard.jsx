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

export default function CropClassificationCard({ payload, loading, error, district }) {
  const crops = payload?.crops || [];

  return (
    <section className="card">
      <h2 className="card-title">Crop Classification</h2>
      <p className="card-sub">Spectral model — field verification pending</p>

      {loading ? (
        <p className="mt-4 text-base text-muted">Running classification…</p>
      ) : error ? (
        <p className="mt-4 text-base text-high">{error}</p>
      ) : crops.length === 0 ? (
        <div className="mt-4">
          <p className="text-base text-muted">
            No classification available for {district || 'this district'}.
          </p>
          <p className="mt-1 text-xs text-muted">
            Either no cloud-free imagery was captured in the last composite
            window, or classification has not been run for this district yet.
          </p>
        </div>
      ) : (
        <>
          <table className="data-table mt-4">
            <thead>
              <tr>
                <th>Crop</th>
                <th className="num">Area (ha)</th>
                <th className="num">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {crops.map((c) => (
                <tr key={c.crop}>
                  <td>{c.crop.replace(/_/g, ' ')}</td>
                  <td className="num">{Math.round(c.area_ha).toLocaleString()}</td>
                  <td className="num">
                    {/* "other" is a real class, but a confidence for it says
                        nothing useful about a crop decision. */}
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
            {payload.samples_classified} sample points ·{' '}
            {Math.round(payload.cropland_area_ha).toLocaleString()} ha cropland ·
            composite {payload.composite_start}
          </p>
        </>
      )}
    </section>
  );
}

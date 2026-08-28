/**
 * Per-pixel crop map, with the cartographic furniture that makes a map
 * readable as a map: a legend, a scale bar, a north arrow and corner
 * coordinates.
 *
 * Building the raster takes tens of seconds, so it is requested on demand
 * rather than on page load, and the button says so.
 */

import { useCallback, useEffect, useState } from 'react';
import { MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet';

import api from '../api/client.js';

const CLASS_LABEL = {
  tomato: 'Tomato',
  onion: 'Onion',
  potato: 'Potato',
  leafy_greens: 'Leafy greens',
  other: 'Other / non-crop',
};

/** Reads the map's live bounds so the corner coordinates stay truthful. */
function CoordinateReadout({ onChange }) {
  const map = useMapEvents({
    moveend: () => onChange(map.getBounds()),
    zoomend: () => onChange(map.getBounds()),
  });
  useEffect(() => {
    onChange(map.getBounds());
  }, [map, onChange]);
  return null;
}

function Recenter({ center }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.setView(center, 10, { animate: true });
  }, [center, map]);
  return null;
}

/** Scale bar drawn from the map's own metres-per-pixel, not a fixed image. */
function ScaleBar({ bounds }) {
  if (!bounds) return null;
  // Rough ground width of the visible map, in km.
  const west = bounds.getWest();
  const east = bounds.getEast();
  const midLat = (bounds.getNorth() + bounds.getSouth()) / 2;
  const kmPerDegLon = 111.32 * Math.cos((midLat * Math.PI) / 180);
  const widthKm = Math.abs(east - west) * kmPerDegLon;

  // Pick a round number that occupies roughly a quarter of the view.
  const target = widthKm / 4;
  const steps = [1, 2, 5, 10, 25, 50, 100, 200, 500];
  const pick = steps.reduce((a, b) => (Math.abs(b - target) < Math.abs(a - target) ? b : a));
  const widthPct = (pick / widthKm) * 100;

  return (
    <div className="flex items-end gap-1.5">
      <div>
        <div
          className="h-1.5 border border-ink bg-white"
          style={{ width: `${Math.min(widthPct, 40)}%`, minWidth: 44 }}
        >
          <div className="h-full w-1/2 bg-ink" />
        </div>
        <div className="mt-0.5 flex justify-between text-2xs text-ink" style={{ minWidth: 44 }}>
          <span>0</span>
          <span>{pick} km</span>
        </div>
      </div>
    </div>
  );
}

export default function CropMapPanel({ district, center }) {
  const [layer, setLayer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [bounds, setBounds] = useState(null);
  // A fortnight of monsoon can be entirely cloud, so the compositing
  // window is adjustable. Longer stacks more passes and fills the holes,
  // at the cost of blurring anything that changed in between.
  const [windowDays, setWindowDays] = useState(30);

  // A raster belongs to one district; drop it when the selection changes
  // rather than showing Kolar's pixels under Belagavi's name.
  useEffect(() => {
    setLayer(null);
    setError(null);
  }, [district]);

  const build = useCallback(async () => {
    if (!district) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.cropMap({ district, windowDays });
      if (result.status === 'OK') setLayer(result);
      else setError(result.detail || result.status);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [district, windowDays]);

  return (
    <section className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="card-title">Crop map</h2>
          <p className="card-sub">
            Every cropland pixel classified, at 20 m
            {layer ? ` · composite ${layer.composite_start}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted">
            Days of imagery
            <select
              className="field w-auto py-1 text-xs"
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
            >
              <option value={16}>16</option>
              <option value={30}>30</option>
              <option value={60}>60</option>
              <option value={90}>90</option>
            </select>
          </label>
          <button type="button" className="btn" onClick={build} disabled={loading || !district}>
            {loading ? 'Building…' : layer ? 'Rebuild' : 'Build map'}
          </button>
        </div>
      </div>

      {error ? (
        <p className="mt-4 text-base text-high">{error}</p>
      ) : null}

      {!layer && !loading && !error ? (
        <p className="mt-4 max-w-2xl text-base text-muted">
          This classifies each pixel in the district rather than sampling a
          few hundred points, so you can see where crops sit and how fields are
          laid out. It takes about half a minute to build. During the monsoon a
          fortnight of imagery is often entirely cloud — widen the window to
          stack more passes.
        </p>
      ) : null}

      {loading ? (
        <p className="mt-4 text-base text-muted">
          Sampling the district, labelling the points and fitting the map…
        </p>
      ) : null}

      {layer ? (
        <>
          <div className="relative mt-4 h-[520px] border border-line">
            <MapContainer
              center={center ? [center.lat, center.lon] : [13.0, 77.6]}
              zoom={10}
              scrollWheelZoom
              className="h-full w-full"
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                opacity={0.35}
              />
              <TileLayer
                key={layer.composite_start}
                url={layer.tile_url_template}
                opacity={0.9}
                attribution="Sentinel-2 L2A via Google Earth Engine"
              />
              <Recenter center={center ? [center.lat, center.lon] : null} />
              <CoordinateReadout onChange={setBounds} />
            </MapContainer>

            {/* North arrow */}
            <div className="pointer-events-none absolute right-3 top-3 z-[400] flex flex-col items-center bg-white/85 px-1.5 py-1">
              <svg width="14" height="18" viewBox="0 0 14 18" aria-hidden="true">
                <polygon points="7,0 12,17 7,13 2,17" fill="#111111" />
              </svg>
              <span className="text-2xs font-semibold text-ink">N</span>
            </div>

            {/* Legend */}
            <div className="absolute bottom-3 right-3 z-[400] border border-line bg-white/95 px-3 py-2">
              <p className="text-xs font-semibold text-ink">Crop classes</p>
              <ul className="mt-1 space-y-0.5">
                {Object.entries(layer.legend).map(([name, colour]) => (
                  <li key={name} className="flex items-center gap-2 text-xs text-ink">
                    <span
                      className="inline-block h-3 w-3 border border-line"
                      style={{ backgroundColor: colour }}
                    />
                    {CLASS_LABEL[name] || name}
                  </li>
                ))}
              </ul>
            </div>

            {/* Scale bar and corner coordinates */}
            <div className="absolute bottom-3 left-3 z-[400] bg-white/90 px-2 py-1.5">
              <ScaleBar bounds={bounds} />
              {bounds ? (
                <p className="mt-1 text-2xs text-muted tnum">
                  {bounds.getSouth().toFixed(2)}–{bounds.getNorth().toFixed(2)}°N ·{' '}
                  {bounds.getWest().toFixed(2)}–{bounds.getEast().toFixed(2)}°E
                </p>
              ) : null}
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-baseline justify-between gap-3">
            <p className="text-xs text-muted">
              {layer.scene_count} Sentinel-2 scene
              {layer.scene_count === 1 ? '' : 's'} · {layer.training_points} training
              points · {layer.composite_start} to {layer.composite_end}
            </p>
            <p
              className="text-xs"
              style={{ color: layer.faithful ? '#1a5c2a' : '#d4882a' }}
            >
              Matches the district classifier on {(layer.agreement * 100).toFixed(0)}% of
              held-out points
            </p>
          </div>

          {layer.notes?.length ? (
            <ul className="mt-2 space-y-1">
              {layer.notes.map((n) => (
                <li key={n} className="text-xs" style={{ color: '#d4882a' }}>
                  {n}
                </li>
              ))}
            </ul>
          ) : null}

          <p className="mt-2 text-xs text-muted">
            Colours come from spectral patterns, not from anyone checking these
            fields. A pixel marked tomato resembles what the model was taught to
            call tomato.
          </p>
        </>
      ) : null}
    </section>
  );
}

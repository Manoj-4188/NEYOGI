/**
 * Leaflet map of parcel polygons.
 *
 * Two render modes, decided by the server via
 * `collection.properties.render_mode`:
 *
 * - `crop_classes` — the district has verified ground truth, so polygons are
 *   filled by crop class.
 * - `ndvi_basemap` — no verified labels. Polygons are drawn as neutral
 *   outlines over the raw Sentinel-2 NDVI tile, with no crop colouring at all.
 *
 * The component never infers a class from the spectral indices it receives.
 */

import { useEffect, useMemo } from 'react';
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet';

import { buildPopupHtml } from './ParcelPopup.jsx';

// Karnataka's southern vegetable belt.
const DEFAULT_CENTER = [13.0, 77.9];
const DEFAULT_ZOOM = 9;

const CROP_COLORS = {
  Tomato: '#C45A37',
  Onion: '#8C5BA6',
  Potato: '#C89B3C',
  'Leafy Greens': '#4E8752',
  'Fallow/Non-Crop': '#9AA398',
};

const UNCLASSIFIED_COLOR = '#4E8752';

function styleForFeature(feature, renderMode) {
  const props = feature.properties || {};

  if (renderMode !== 'crop_classes') {
    // Unvalidated district: outlines only, so the NDVI basemap reads through
    // and nothing suggests a crop identity we cannot support.
    return {
      color: '#1B3B2B',
      weight: 1,
      opacity: 0.75,
      fillOpacity: 0.04,
      fillColor: '#1B3B2B',
      dashArray: '3 3',
    };
  }

  const crop = props.predicted_class || props.crop_label;
  if (!crop) {
    return {
      color: UNCLASSIFIED_COLOR,
      weight: 1,
      opacity: 0.7,
      fillOpacity: 0.08,
      fillColor: UNCLASSIFIED_COLOR,
      dashArray: '3 3',
    };
  }

  const color = CROP_COLORS[crop] || UNCLASSIFIED_COLOR;
  // Model predictions are drawn slightly translucent and dashed relative to a
  // human-verified label, so certainty is visible at a glance.
  const isPrediction = Boolean(props.predicted_class) && !props.crop_label;
  return {
    color,
    weight: props.verified ? 1.6 : 1,
    opacity: 0.9,
    fillColor: color,
    fillOpacity: isPrediction ? 0.35 : 0.55,
    dashArray: isPrediction ? '4 2' : undefined,
  };
}

/** Recentre when the selected district's data changes. */
function FitToData({ collection }) {
  const map = useMap();

  useEffect(() => {
    if (!collection?.features?.length) return;
    const layer = window.L?.geoJSON(collection);
    if (!layer) return;
    const bounds = layer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
  }, [collection, map]);

  return null;
}

export function MapLegend({ renderMode, counts }) {
  if (renderMode !== 'crop_classes') {
    return (
      <div className="panel px-3 py-2 text-xs">
        <p className="font-semibold text-forest">NDVI basemap</p>
        <p className="mt-1 max-w-[15rem] text-forest-900/70">
          This district has no field-verified parcels, so no crop classes are
          shown. Polygons are digitised boundaries only.
        </p>
        <div className="mt-2 flex items-center gap-1">
          <span className="h-2 w-16 rounded bg-gradient-to-r from-[#b0623c] via-[#c9d98a] to-[#1B3B2B]" />
          <span className="text-forest-900/60">low → high</span>
        </div>
      </div>
    );
  }

  const entries = Object.entries(CROP_COLORS).filter(
    ([crop]) => !counts || counts[crop],
  );

  return (
    <div className="panel px-3 py-2 text-xs">
      <p className="font-semibold text-forest">Crop classes</p>
      <ul className="mt-1.5 space-y-1">
        {entries.map(([crop, color]) => (
          <li key={crop} className="flex items-center gap-2">
            <span
              className="inline-block h-3 w-3 rounded-sm"
              style={{ backgroundColor: color, opacity: 0.75 }}
            />
            <span className="text-forest-900/80">{crop}</span>
            {counts?.[crop] ? (
              <span className="ml-auto font-mono text-forest-900/50">{counts[crop]}</span>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="mt-2 border-t border-parchment-200 pt-1.5 text-forest-900/60">
        Solid fill = field-verified label. Dashed = model prediction.
      </p>
      <ColdStorageLegendRow />
    </div>
  );
}

function ColdStorageLegendRow() {
  return (
    <p className="mt-1.5 flex items-center gap-2 text-forest-900/60">
      <span
        className="inline-block h-3 w-3 rounded-full border-2"
        style={{ backgroundColor: '#C89B3C', borderColor: '#1B3B2B' }}
      />
      Cold storage (licensed capacity)
    </p>
  );
}

/**
 * Cold storage facilities as distinct markers.
 *
 * Only facilities the source register actually gave coordinates for are drawn.
 * Rows without a location are counted in the side panel but never placed here,
 * because a centroid-guessed pin would send someone to the wrong address.
 */
function ColdStorageMarkers({ stores }) {
  const mapped = (stores || []).filter(
    (s) => s.mapped && s.latitude != null && s.longitude != null,
  );
  if (!mapped.length) return null;

  return mapped.map((store) => (
    <CircleMarker
      key={`cs-${store.id}`}
      center={[store.latitude, store.longitude]}
      radius={6}
      pathOptions={{
        color: '#1B3B2B',
        weight: 2,
        fillColor: '#C89B3C',
        fillOpacity: 0.9,
      }}
    >
      <Popup>
        <div className="px-3 py-2 text-xs" style={{ fontFamily: 'inherit', minWidth: 170 }}>
          <p className="text-sm font-bold text-forest">{store.name}</p>
          <p className="mt-0.5 text-forest-900/60">
            {[store.taluk, store.district].filter(Boolean).join(', ')}
          </p>
          <p className="mt-1.5">
            <span className="text-sage-600">Licensed capacity: </span>
            <span className="font-mono font-semibold">
              {store.licensed_capacity_mt != null
                ? `${Math.round(store.licensed_capacity_mt).toLocaleString()} MT`
                : 'not published'}
            </span>
          </p>
          <p className="mt-1 text-[10px] leading-snug text-terracotta">
            Licensed capacity, not free space — live utilisation is not
            published. Call ahead.
          </p>
        </div>
      </Popup>
    </CircleMarker>
  ));
}

export default function CropMap({ collection, basemapTile, coldStores, onSelectParcel }) {
  const renderMode = collection?.properties?.render_mode || 'ndvi_basemap';

  const counts = useMemo(() => {
    const tally = {};
    (collection?.features || []).forEach((f) => {
      const crop = f.properties?.predicted_class || f.properties?.crop_label;
      if (crop) tally[crop] = (tally[crop] || 0) + 1;
    });
    return tally;
  }, [collection]);

  // Remount the GeoJSON layer when the data changes; Leaflet layers do not
  // re-derive their style from new props on their own.
  const geoJsonKey = useMemo(
    () => `${collection?.properties?.district || 'none'}-${collection?.features?.length || 0}-${renderMode}`,
    [collection, renderMode],
  );

  return (
    <div className="relative h-full min-h-[26rem] w-full">
      <MapContainer
        center={DEFAULT_CENTER}
        zoom={DEFAULT_ZOOM}
        scrollWheelZoom
        className="h-full w-full"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {basemapTile?.tile_url_template ? (
          <TileLayer
            key={basemapTile.composite_start}
            url={basemapTile.tile_url_template}
            opacity={renderMode === 'crop_classes' ? 0.55 : 0.85}
            attribution="Sentinel-2 L2A via Google Earth Engine"
          />
        ) : null}

        {collection?.features?.length ? (
          <>
            <GeoJSON
              key={geoJsonKey}
              data={collection}
              style={(feature) => styleForFeature(feature, renderMode)}
              onEachFeature={(feature, layer) => {
                // Bind per-feature HTML directly: a react-leaflet <Popup> child
                // of <GeoJSON> attaches to the whole layer group, not to the
                // clicked feature, so it cannot show per-parcel content.
                layer.bindPopup(buildPopupHtml(feature.properties, renderMode), {
                  maxWidth: 320,
                  closeButton: true,
                });
                layer.on('click', () => onSelectParcel?.(feature.properties));
              }}
            />
            <FitToData collection={collection} />
          </>
        ) : null}

        <ColdStorageMarkers stores={coldStores} />
      </MapContainer>

      <div className="pointer-events-none absolute bottom-4 right-4 z-[400]">
        <div className="pointer-events-auto">
          <MapLegend renderMode={renderMode} counts={counts} />
        </div>
      </div>
    </div>
  );
}

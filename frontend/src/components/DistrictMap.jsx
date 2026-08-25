/**
 * District map: NDVI basemap, cold storage points, parcel boundaries.
 *
 * Flat by design — no rounded corners, zoom control top-left only, no
 * decorative layer switcher. The map is a panel in the page, not a widget
 * floating above it.
 *
 * Cold storage markers are drawn only for facilities the register actually
 * geolocated. One without coordinates is counted in the side panel but never
 * placed here: a pin guessed from a district centroid would send someone to
 * the wrong address.
 */

import { useEffect } from 'react';
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet';

// Karnataka's southern vegetable belt.
const DEFAULT_CENTER = [13.0, 77.6];
const DEFAULT_ZOOM = 8;

const CROP_COLORS = {
  tomato: '#c0392b',
  onion: '#d4882a',
  leafy_greens: '#1a5c2a',
  other: '#9ca3af',
};

function RecenterOn({ center, zoom }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.setView(center, zoom ?? map.getZoom(), { animate: true });
  }, [center, zoom, map]);
  return null;
}

function parcelStyle(feature) {
  const props = feature.properties || {};
  const crop = props.predicted_class || props.crop_label;
  const color = CROP_COLORS[String(crop || '').toLowerCase()] || '#1a5c2a';
  return {
    color,
    weight: 1,
    opacity: 0.85,
    fillColor: color,
    fillOpacity: props.verified ? 0.45 : 0.2,
  };
}

export default function DistrictMap({
  center,
  basemapTile,
  coldStores,
  parcels,
}) {
  const mapped = (coldStores || []).filter(
    (s) => s.mapped && s.latitude != null && s.longitude != null,
  );

  return (
    <MapContainer
      center={DEFAULT_CENTER}
      zoom={DEFAULT_ZOOM}
      scrollWheelZoom
      zoomControl
      className="h-full w-full"
      attributionControl
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        opacity={0.55}
      />

      {basemapTile?.tile_url_template ? (
        <TileLayer
          key={basemapTile.composite_start}
          url={basemapTile.tile_url_template}
          opacity={0.85}
          attribution="Sentinel-2 L2A via Google Earth Engine"
        />
      ) : null}

      {parcels?.features?.length ? (
        <GeoJSON
          key={`p-${parcels.features.length}`}
          data={parcels}
          style={parcelStyle}
        />
      ) : null}

      {mapped.map((store) => (
        <CircleMarker
          key={`cs-${store.id}`}
          center={[store.latitude, store.longitude]}
          radius={5}
          pathOptions={{
            color: '#ffffff',
            weight: 1.5,
            fillColor: '#1a5c2a',
            fillOpacity: 1,
          }}
        >
          <Popup>
            <div style={{ padding: '10px 12px', minWidth: 180 }}>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: '#111111' }}>
                {store.name}
              </p>
              <p style={{ margin: '2px 0 8px', fontSize: 11, color: '#6b7280' }}>
                {[store.taluk, store.district].filter(Boolean).join(', ')}
              </p>

              <dl style={{ margin: 0, fontSize: 11, lineHeight: 1.7 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <dt style={{ color: '#6b7280' }}>Capacity</dt>
                  <dd style={{ margin: 0, color: '#111111', fontVariantNumeric: 'tabular-nums' }}>
                    {store.licensed_capacity_mt != null
                      ? `${Math.round(store.licensed_capacity_mt).toLocaleString()} t`
                      : '—'}
                  </dd>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <dt style={{ color: '#6b7280' }}>Cost</dt>
                  <dd style={{ margin: 0, color: '#111111', fontVariantNumeric: 'tabular-nums' }}>
                    {store.cost_per_tonne_day != null
                      ? `₹${store.cost_per_tonne_day}/t/day`
                      : '—'}
                  </dd>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <dt style={{ color: '#6b7280' }}>Crops</dt>
                  <dd style={{ margin: 0, color: '#111111' }}>
                    {store.crops_supported?.length
                      ? store.crops_supported.map((c) => c.replace(/_/g, ' ')).join(', ')
                      : '—'}
                  </dd>
                </div>
                {store.contact ? (
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <dt style={{ color: '#6b7280' }}>Contact</dt>
                    <dd style={{ margin: 0, color: '#111111' }}>{store.contact}</dd>
                  </div>
                ) : null}
              </dl>

              <p style={{ margin: '8px 0 0', fontSize: 10, color: '#6b7280', lineHeight: 1.5 }}>
                Licensed capacity, not free space.
              </p>
            </div>
          </Popup>
        </CircleMarker>
      ))}

      <RecenterOn center={center} zoom={9} />
    </MapContainer>
  );
}

"""Sentinel-2 tile service: live Earth Engine first, PostGIS cache second.

The contract this module keeps is that a returned tile URL is *always*
accompanied by a badge naming the composite date behind it. A cached tile is
never presented as a live one, and when neither is available the response says
so rather than rendering an empty map with no explanation.

Earth Engine's ``getMapId`` is a blocking call, so it runs in a worker thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


from backend import db, status
from backend.config import settings

logger = logging.getLogger(__name__)

#: Earth Engine map IDs are short-lived; refresh the cached handle well before
#: the server-side token would lapse.
TILE_TTL_HOURS = 12

#: NDVI visualisation used for the basemap, including for unvalidated
#: districts where it is the *only* layer shown.
NDVI_VIS = {
    "min": -0.2,
    "max": 0.9,
    "palette": [
        "#b0623c",  # bare / stressed
        "#d9c98a",
        "#c9d98a",
        "#8bbf6b",
        "#4E8752",  # NEYOGI sage
        "#1B3B2B",  # NEYOGI forest green -- dense canopy
    ],
}


@dataclass
class TileLayer:
    district: str
    index_name: str
    composite_start: date
    composite_end: date
    tile_url_template: str
    scene_count: int
    vis_params: dict

    def to_dict(self) -> dict:
        return {
            "district": self.district,
            "index_name": self.index_name,
            "composite_start": self.composite_start.isoformat(),
            "composite_end": self.composite_end.isoformat(),
            "tile_url_template": self.tile_url_template,
            "scene_count": self.scene_count,
            "vis_params": self.vis_params,
        }


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


async def cache_tile(layer: TileLayer, ttl_hours: int = TILE_TTL_HOURS) -> None:
    expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=ttl_hours)
    import json

    await db.execute(
        """
        INSERT INTO satellite_tile_cache
            (district, index_name, composite_start, composite_end,
             scene_count, tile_url_template, vis_params, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (district, index_name, composite_start) DO UPDATE SET
            composite_end     = EXCLUDED.composite_end,
            scene_count       = EXCLUDED.scene_count,
            tile_url_template = EXCLUDED.tile_url_template,
            vis_params        = EXCLUDED.vis_params,
            generated_at      = now(),
            expires_at        = EXCLUDED.expires_at
        """,
        (
            layer.district,
            layer.index_name,
            layer.composite_start,
            layer.composite_end,
            layer.scene_count,
            layer.tile_url_template,
            json.dumps(layer.vis_params),
            expires_at,
        ),
    )


async def cached_tile(district: str, index_name: str = "NDVI") -> TileLayer | None:
    """Newest non-expired cached tile for a district."""
    row = await db.fetch_one(
        """
        SELECT district, index_name, composite_start, composite_end,
               tile_url_template, scene_count, vis_params
        FROM satellite_tile_cache
        WHERE district = %s
          AND index_name = %s
          AND (expires_at IS NULL OR expires_at > now())
        ORDER BY composite_start DESC
        LIMIT 1
        """,
        (district, index_name),
    )
    if not row:
        return None
    return TileLayer(
        district=row[0],
        index_name=row[1],
        composite_start=row[2],
        composite_end=row[3],
        tile_url_template=row[4],
        scene_count=row[5],
        vis_params=row[6] or NDVI_VIS,
    )


async def latest_cached_composite_date(district: str) -> date | None:
    """Newest composite date in the parcel index cache, for the badge."""
    row = await db.fetch_one(
        """
        SELECT MAX(t.observed_on)
        FROM indices_time_series t
        JOIN parcels p ON p.id = t.parcel_id
        WHERE p.district = %s
        """,
        (district,),
    )
    return row[0] if row and row[0] else None


# --------------------------------------------------------------------------
# Live Earth Engine
# --------------------------------------------------------------------------


def _build_live_tile(district_name: str, index_name: str, window_days: int) -> TileLayer:
    """Blocking Earth Engine work -- must be called in a worker thread."""
    from ml_pipeline.feature_engineering import add_index_bands
    from ml_pipeline.gee_districts import district_geometry, resolve_districts
    from ml_pipeline.gee_ingestion import (
        SOURCE_BANDS,
        CompositeWindow,
        NoImageryAvailable,
        sentinel2_collection,
    )

    resolution = resolve_districts([district_name])
    resolved = resolution.get(district_name)
    if resolved is None:
        raise NoImageryAvailable(
            f"{district_name} did not resolve against FAO/GAUL/2015/level2"
        )

    end = datetime.now(tz=timezone.utc).date()
    start = end - timedelta(days=window_days)
    window = CompositeWindow(start=start, end=end)

    geometry = district_geometry(resolved)
    collection = sentinel2_collection(geometry, start, end)
    scene_count = int(collection.size().getInfo())
    if scene_count == 0:
        raise NoImageryAvailable(
            f"No cloud-free Sentinel-2 scenes for {district_name} in the last "
            f"{window_days} days"
        )

    composite = add_index_bands(
        collection.median().clip(geometry), available_bands=SOURCE_BANDS
    )
    map_id = composite.select(index_name).getMapId(NDVI_VIS)

    return TileLayer(
        district=resolved.gaul_name,
        index_name=index_name,
        composite_start=window.start,
        composite_end=window.end,
        tile_url_template=map_id["tile_fetcher"].url_format,
        scene_count=scene_count,
        vis_params=NDVI_VIS,
    )


async def get_tile_layer(
    district: str,
    index_name: str = "NDVI",
    window_days: int | None = None,
) -> tuple[TileLayer | None, status.StatusBadge]:
    """Live tile if Earth Engine answers, cached tile otherwise, badge always."""
    window_days = window_days or settings.composite_period_days

    try:
        from anyio import to_thread

        layer = await to_thread.run_sync(
            _build_live_tile, district, index_name, window_days
        )
        try:
            await cache_tile(layer)
        except db.DatabaseUnavailable as exc:
            logger.warning("Built a live tile but could not cache it: %s", exc)
        return layer, status.satellite_live(layer.composite_start)
    except Exception as exc:  # noqa: BLE001 - ee and network raise many types
        reason = f"Earth Engine unavailable: {exc}"
        logger.warning("Live tile build failed for %s: %s", district, exc)

    try:
        layer = await cached_tile(district, index_name)
    except db.DatabaseUnavailable as exc:
        return None, status.satellite_unavailable(
            f"{reason} The tile cache is also unreachable: {exc}"
        )

    if layer is not None:
        return layer, status.satellite_cached(layer.composite_start, reason=reason)

    # No tile handle cached, but parcel composites may still exist. Report the
    # newest composite date we hold so the user knows how current the vector
    # data behind the map is.
    try:
        observed = await latest_cached_composite_date(district)
    except db.DatabaseUnavailable:
        observed = None

    if observed is not None:
        return None, status.satellite_cached(
            observed,
            reason=f"{reason} No cached tile handle; vector data is from {observed}.",
        )
    return None, status.satellite_unavailable(reason)

"""``GET /api/v1/map/crops`` -- parcel vector data with verification status.

Returns a GeoJSON FeatureCollection. Whether crop classes appear at all is
decided server-side by the district's validation state, so a client cannot ask
for classifications the ground truth does not support.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status as http_status

from backend import db, status
from backend.services import parcels, satellite

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/map", tags=["map"])


@router.get("/crops", summary="Parcel polygons with crop labels and status badges")
async def crops(
    district: Annotated[str, Query(description="GAUL district name, e.g. Kolar")],
    on_date: Annotated[
        date | None, Query(description="Latest composite on or before this date")
    ] = None,
    include_unverified: Annotated[
        bool, Query(description="Include parcels without verified labels")
    ] = True,
    include_tile: Annotated[
        bool, Query(description="Also resolve the Sentinel-2 basemap tile URL")
    ] = True,
    limit: Annotated[int, Query(ge=1, le=20000)] = 5000,
) -> dict:
    try:
        collection = await parcels.parcels_geojson(
            district=district,
            on_date=on_date,
            include_unverified=include_unverified,
            limit=limit,
        )
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

    validation = collection["properties"]["validation"]
    badges = status.StatusSet()
    badges.add(
        status.district_validated(
            validation["verified_count"],
            date.fromisoformat(validation["last_verified_at"])
            if validation["last_verified_at"]
            else None,
        )
        if validation["is_validated"]
        else status.district_unvalidated(district, validation["parcel_count"])
    )

    tile_payload = None
    if include_tile:
        layer, tile_badge = await satellite.get_tile_layer(district, "NDVI")
        badges.add(tile_badge)
        tile_payload = layer.to_dict() if layer else None

    collection["properties"]["status"] = badges.to_dict()
    collection["properties"]["basemap_tile"] = tile_payload
    return collection


@router.get("/districts", summary="Validation state for every known district")
async def districts() -> dict:
    try:
        validations = await parcels.all_district_validations()
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostGIS is unreachable: {exc}",
        ) from exc

    from ml_pipeline import config as ml_config

    sources = await parcels.boundary_sources()
    known = {v.district for v in validations}
    payload = [
        dict(
            v.to_dict(),
            status=v.badge().to_dict(),
            boundary=sources.get(v.district),
        )
        for v in validations
    ]

    # Candidate districts with no parcels at all are still listed, explicitly
    # unvalidated, so the UI shows the full coverage picture rather than
    # silently omitting the ones nobody has surveyed.
    for candidate in ml_config.CANDIDATE_DISTRICTS:
        if candidate not in known:
            payload.append(
                {
                    "district": candidate,
                    "parcel_count": 0,
                    "verified_count": 0,
                    "verified_area_ha": 0.0,
                    "last_verified_at": None,
                    "is_validated": False,
                    "status": status.district_unvalidated(candidate, 0).to_dict(),
                    "boundary": sources.get(candidate),
                }
            )

    payload.sort(key=lambda d: d["district"])
    return {"districts": payload, "count": len(payload)}

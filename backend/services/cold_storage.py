"""Cold storage facilities -- the hold-or-sell half of an oversupply warning.

A projected glut is only actionable if the grower can hold the crop. This
module serves the licensed cold storage registered near a district, so the
dashboard can answer "and where would I put it?".

Two things this module will not do:

* **Report available space.** No public feed of real-time cold storage
  utilisation exists in India; the Ministry of Agriculture has stated capacity
  utilisation is not centrally maintained. Every response therefore carries
  ``utilisation_available: false`` and quotes licensed capacity only.
* **Geocode a facility to a district centroid.** A row without coordinates is
  returned in the list and counted, but not placed on the map. Inventing a
  point would put a real, findable business at a fictional address.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from backend import db, status
from backend.services.storage_economics import PRICE_RECOVERY_FACTOR

logger = logging.getLogger(__name__)


@dataclass
class ColdStore:
    id: int
    facility_uid: str
    name: str
    district: str
    taluk: str | None
    address: str | None
    capacity_mt: float | None
    commodity_focus: str | None
    ownership: str
    longitude: float | None
    latitude: float | None
    source: str
    source_url: str | None
    source_year: int | None
    verified_by: str | None
    #: INR per tonne per day. None when the source did not state a tariff --
    #: never 0, which would read as free storage.
    cost_per_tonne_day: float | None = None
    crops_supported: list = None
    contact: str | None = None

    @property
    def is_mapped(self) -> bool:
        return self.longitude is not None and self.latitude is not None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "facility_uid": self.facility_uid,
            "name": self.name,
            "district": self.district,
            "taluk": self.taluk,
            "address": self.address,
            # Explicitly named: this is the licensed nameplate figure, not
            # free space. The UI label depends on that distinction.
            "licensed_capacity_mt": self.capacity_mt,
            "commodity_focus": self.commodity_focus,
            "ownership": self.ownership,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "mapped": self.is_mapped,
            "source": self.source,
            "source_url": self.source_url,
            "source_year": self.source_year,
            "verified_by": self.verified_by,
            "cost_per_tonne_day": self.cost_per_tonne_day,
            "crops_supported": list(self.crops_supported or []),
            "contact": self.contact,
        }


def _row_to_store(row: tuple) -> ColdStore:
    return ColdStore(
        id=row[0],
        facility_uid=row[1],
        name=row[2],
        district=row[3],
        taluk=row[4],
        address=row[5],
        capacity_mt=float(row[6]) if row[6] is not None else None,
        commodity_focus=row[7],
        ownership=row[8],
        longitude=float(row[9]) if row[9] is not None else None,
        latitude=float(row[10]) if row[10] is not None else None,
        source=row[11],
        source_url=row[12],
        source_year=row[13],
        verified_by=row[14],
        cost_per_tonne_day=float(row[15]) if row[15] is not None else None,
        crops_supported=list(row[16] or []),
        contact=row[17],
    )


async def facilities_for_district(district: str, limit: int = 500) -> list[ColdStore]:
    rows = await db.fetch_all(
        """
        SELECT id, facility_uid, name, district, taluk, address,
               capacity_mt, commodity_focus, ownership,
               ST_X(geom), ST_Y(geom),
               source, source_url, source_year, verified_by,
               cost_per_tonne_day, crops_supported, contact
        FROM cold_storage_facilities
        WHERE district = %s
        ORDER BY capacity_mt DESC NULLS LAST, name
        LIMIT %s
        """,
        (district, limit),
    )
    return [_row_to_store(r) for r in rows]


async def district_summary(district: str) -> dict:
    row = await db.fetch_one(
        """
        SELECT facility_count, mapped_count, capacity_known_count,
               licensed_capacity_mt, newest_source_year,
               min_cost_per_tonne_day, max_cost_per_tonne_day
        FROM cold_storage_by_district
        WHERE district = %s
        """,
        (district,),
    )
    if not row:
        return {
            "facility_count": 0,
            "mapped_count": 0,
            "capacity_known_count": 0,
            "licensed_capacity_mt": None,
            "newest_source_year": None,
            "min_cost_per_tonne_day": None,
            "max_cost_per_tonne_day": None,
        }
    return {
        "facility_count": int(row[0]),
        "mapped_count": int(row[1]),
        "capacity_known_count": int(row[2]),
        # NULL rather than 0 when no facility in the district published a
        # capacity: "unknown total" is not "zero tonnes of cold storage".
        "licensed_capacity_mt": float(row[3]) if row[3] is not None else None,
        "newest_source_year": row[4],
        "min_cost_per_tonne_day": float(row[5]) if row[5] is not None else None,
        "max_cost_per_tonne_day": float(row[6]) if row[6] is not None else None,
    }


async def _attach_economics(
    payloads: list[dict], district: str, crop: str, quantity_t: float
) -> dict:
    """Add a hold-or-sell breakdown to each facility that quotes a tariff.

    A facility with no published tariff gets no economics rather than a
    guessed one -- the whole figure hinges on that number.
    """
    from backend.services import storage_economics as econ

    try:
        price, basis = await econ.current_price_per_quintal(district, crop)
    except KeyError:
        return {"available": False, "reason": f"No price basis for crop {crop!r}."}

    priced = 0
    for entry in payloads:
        tariff = entry.get("cost_per_tonne_day")
        if tariff is None:
            entry["economics"] = None
            continue
        entry["economics"] = econ.net_benefit(
            price_per_quintal=price,
            cost_per_tonne_day=float(tariff),
            quantity_t=quantity_t,
        )
        priced += 1

    return {
        "available": priced > 0,
        "crop": crop,
        "quantity_t": quantity_t,
        "holding_days": econ.DEFAULT_HOLDING_DAYS,
        "recovery_factor": econ.PRICE_RECOVERY_FACTOR,
        "price_per_quintal": round(price, 2),
        "price_basis": basis,
        "facilities_priced": priced,
    }


async def get_cold_storage(
    district: str,
    crop: str = "tomato",
    quantity_t: float = 1.0,
) -> dict:
    """Facilities plus a summary, hold-or-sell economics, and a status badge."""
    stores = await facilities_for_district(district)
    summary = await district_summary(district)
    badges = status.StatusSet()

    if not stores:
        badges.add(
            status.StatusBadge(
                source=status.SourceKind.GROUND_TRUTH,
                status=status.SourceStatus.UNAVAILABLE,
                severity=status.Severity.ERROR,
                label="🔴 NO COLD STORAGE REGISTRY LOADED",
                detail=(
                    f"No cold storage facilities have been ingested for {district}. "
                    "Load the NHB/state register with "
                    "`python -m ml_pipeline.load_cold_storage`."
                ),
                is_fallback=False,
            )
        )
    else:
        year = summary["newest_source_year"]
        badges.add(
            status.StatusBadge(
                source=status.SourceKind.GROUND_TRUTH,
                status=status.SourceStatus.CACHED,
                severity=status.Severity.WARN,
                label=f"🟡 COLD STORAGE REGISTER{f' ({year})' if year else ''}",
                detail=(
                    f"{summary['facility_count']} facility(ies) from a published "
                    "register. Licensed capacity only -- live utilisation is not "
                    "published by any Indian authority, so free space is unknown."
                ),
                is_fallback=False,
            )
        )

    facility_payloads = [s.to_dict() for s in stores]
    economics = await _attach_economics(facility_payloads, district, crop, quantity_t)

    return {
        "district": district,
        "summary": summary,
        "facilities": facility_payloads,
        "economics": economics,
        # Read by the UI to decide whether it may speak about free space.
        # It never may; this makes that explicit rather than implicit.
        "utilisation_available": False,
        "capacity_basis": "licensed",
        "status": badges.to_dict(),
        "notes": [
            "Capacity figures are licensed/nameplate values from the source "
            "register, not currently available space.",
            "Real-time cold storage utilisation is not published centrally in "
            "India, so NEYOGI cannot and does not estimate free space.",
            "Facilities without coordinates in the source register are listed "
            "but not mapped; they are never placed at a district centroid.",
            "Hold-or-sell figures assume prices recover to "
            f"{PRICE_RECOVERY_FACTOR:.2f}x today's rate after the holding "
            "period. That is a planning assumption, not a forecast, and "
            "quality loss in store is not modelled.",
        ],
    }

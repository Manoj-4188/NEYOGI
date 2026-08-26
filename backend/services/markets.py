"""Market finder -- where a given quantity nets the most after haulage.

Ranks Karnataka markets on::

    net_profit = (price x quantity) - (distance x 2.5 x quantity / 10)

with price in INR/quintal and quantity in quintals. The second term is a
transport model: ~₹2.5 per km per tonne, and quantity/10 converts quintals to
tonnes. It is a planning constant, not a quoted freight rate -- an actual
lorry hire depends on load size, road class and season.

Every input is real or the market is not ranked:

* **Prices** come from ``mandi_prices_cache``, which holds what AGMARKNET
  published. No quote, no ranking -- a market is never scored on an assumed
  price, because the whole output is a recommendation to drive somewhere.
* **Distances** are district-centroid to district-centroid, because AGMARKNET
  publishes no market coordinates. That is an approximation and is labelled as
  one; a market whose district has no known centroid is returned without a
  distance and without a net profit rather than with a guessed one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend import db, status
from backend.services.geo import district_distance_km

logger = logging.getLogger(__name__)

#: Transport cost, INR per kilometre per tonne. A planning constant.
TRANSPORT_COST_PER_KM_PER_TONNE = 2.5

#: Quintals in a tonne. AGMARKNET quotes prices per quintal.
QUINTALS_PER_TONNE = 10.0

#: How far back a quote may be and still be worth driving on.
DEFAULT_PRICE_WINDOW_DAYS = 14

#: Crop names as the API takes them, mapped to the cache's spelling.
CROP_ALIASES = {
    "tomato": "Tomato",
    "onion": "Onion",
    "potato": "Potato",
    "leafy_greens": "Leafy Greens",
    "leafy greens": "Leafy Greens",
}


def normalise_crop(crop: str) -> str | None:
    if not crop:
        return None
    return CROP_ALIASES.get(str(crop).strip().lower())


@dataclass
class MarketOption:
    market: str
    district: str
    crop: str
    modal_price: float
    arrival_date: str
    distance_km: float | None
    gross_revenue: float
    transport_cost: float | None
    net_profit: float | None

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "district": self.district,
            "crop": self.crop,
            "modal_price": round(self.modal_price, 2),
            "price_unit": "INR/quintal",
            "arrival_date": self.arrival_date,
            "distance_km": (
                round(self.distance_km, 1) if self.distance_km is not None else None
            ),
            "gross_revenue": round(self.gross_revenue, 2),
            "transport_cost": (
                round(self.transport_cost, 2)
                if self.transport_cost is not None
                else None
            ),
            "net_profit": (
                round(self.net_profit, 2) if self.net_profit is not None else None
            ),
        }


def transport_cost(distance_km: float, quantity_quintals: float) -> float:
    """``distance x 2.5 x quantity / 10`` -- rate is per tonne, quantity is quintals."""
    tonnes = quantity_quintals / QUINTALS_PER_TONNE
    return distance_km * TRANSPORT_COST_PER_KM_PER_TONNE * tonnes


async def best_markets(
    district: str,
    crop: str,
    quantity_quintals: float,
    top_n: int = 3,
    window_days: int = DEFAULT_PRICE_WINDOW_DAYS,
) -> dict:
    """Rank markets by net profit after haulage from ``district``."""
    canonical = normalise_crop(crop)
    if canonical is None:
        return {
            "district": district,
            "crop": crop,
            "quantity_quintals": quantity_quintals,
            "markets": [],
            "error": (
                f"Unknown crop {crop!r}. Supported: "
                f"{', '.join(sorted(set(CROP_ALIASES.values())))}"
            ),
            "status": status.StatusSet()
            .add(status.market_unavailable(f"Unknown crop {crop!r}."))
            .to_dict(),
        }

    since = datetime.now(tz=timezone.utc).date() - timedelta(days=window_days)

    # Newest quote per market. DISTINCT ON keeps one row per market without a
    # second round trip, and a stale quote never outranks a fresh one.
    rows = await db.fetch_all(
        """
        SELECT DISTINCT ON (market)
               market, district, crop, modal_price, arrival_date
        FROM mandi_prices_cache
        WHERE crop = %s
          AND arrival_date >= %s
          AND modal_price IS NOT NULL
        ORDER BY market, arrival_date DESC
        """,
        (canonical, since),
    )

    options: list[MarketOption] = []
    unplaced: list[str] = []

    for market, market_district, row_crop, modal_price, arrival_date in rows:
        distance = district_distance_km(district, market_district)
        gross = float(modal_price) * quantity_quintals

        if distance is None:
            # Ranked markets must have a real distance; this one is reported
            # separately rather than scored on a guessed one.
            unplaced.append(market)
            cost = None
            net = None
        else:
            cost = transport_cost(distance, quantity_quintals)
            net = gross - cost

        options.append(
            MarketOption(
                market=market,
                district=market_district,
                crop=row_crop,
                modal_price=float(modal_price),
                arrival_date=arrival_date.isoformat(),
                distance_km=distance,
                gross_revenue=gross,
                transport_cost=cost,
                net_profit=net,
            )
        )

    rankable = [o for o in options if o.net_profit is not None]
    rankable.sort(key=lambda o: o.net_profit, reverse=True)
    top = rankable[:top_n]

    badges = status.StatusSet()
    if top:
        newest = max(o.arrival_date for o in top)
        badges.add(status.market_cached(datetime.fromisoformat(newest).date()))
    else:
        badges.add(
            status.market_unavailable(
                f"No AGMARKNET quotes for {canonical} in the last {window_days} "
                "days, so no market can be ranked. Rankings appear once the "
                "price feed publishes."
            )
        )

    notes = [
        f"Net profit = (price x quantity) - (distance x "
        f"{TRANSPORT_COST_PER_KM_PER_TONNE} x quantity / {QUINTALS_PER_TONNE:.0f}).",
        "Transport is a planning constant of about "
        f"₹{TRANSPORT_COST_PER_KM_PER_TONNE}/km/tonne, not a quoted freight rate.",
        "Distances are district-centre to district-centre: AGMARKNET publishes "
        "no market coordinates, so these approximate road distance.",
    ]
    if unplaced:
        notes.append(
            f"{len(unplaced)} market(s) omitted from the ranking -- no known "
            f"centroid for their district: {', '.join(sorted(set(unplaced))[:5])}"
        )

    return {
        "district": district,
        "crop": canonical,
        "quantity_quintals": quantity_quintals,
        "quantity_tonnes": round(quantity_quintals / QUINTALS_PER_TONNE, 2),
        "markets": [o.to_dict() for o in top],
        "considered": len(options),
        "price_window_days": window_days,
        "status": badges.to_dict(),
        "notes": notes,
    }

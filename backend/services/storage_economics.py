"""Hold-or-sell arithmetic for cold storage.

For a given quantity and crop::

    storage_cost    = cost_per_tonne_day x quantity_t x holding_days
    current_revenue = price_per_tonne x quantity_t
    recovery_revenue= price_per_tonne x PRICE_RECOVERY_FACTOR x quantity_t
    net_benefit     = recovery_revenue - storage_cost - current_revenue

which reduces to::

    net_benefit = quantity_t x [ price_per_tonne x (factor - 1)
                                 - cost_per_tonne_day x holding_days ]

Units matter here and are easy to get wrong: tariffs are quoted per **tonne**
per day while mandi prices are quoted per **quintal**, so prices are converted
to a per-tonne basis (x10) before either term is used.

A caveat that has to travel with every number this module produces
------------------------------------------------------------------
``PRICE_RECOVERY_FACTOR`` -- the assumption that a crop is worth 35% more after
18 days in store -- is a **planning assumption, not a measurement**. Nothing in
this platform observes it. Real post-storage price movement depends on how the
wider glut resolves, on what other growers do, and on quality loss in store,
which this model does not represent at all. In a season where everyone holds,
the recovery does not arrive and the storage cost is still paid.

So the factor is a named constant, exposed in every payload, and configurable
through ``STORAGE_PRICE_RECOVERY_FACTOR`` rather than buried in an expression.
The UI is expected to show it next to any figure derived from it. Treat the
output as "what holding would be worth *if* prices recover as assumed", never
as a forecast of what holding will earn.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: Default holding period, in days.
DEFAULT_HOLDING_DAYS = int(os.getenv("STORAGE_HOLDING_DAYS", "18"))

#: Assumed price after the holding period, as a multiple of today's price.
#: 1.35 means "35% higher". See the module docstring: this is an assumption.
PRICE_RECOVERY_FACTOR = float(os.getenv("STORAGE_PRICE_RECOVERY_FACTOR", "1.35"))

QUINTALS_PER_TONNE = 10.0

#: Prices used when the cache holds no quote for the crop, in INR/quintal.
#: These are order-of-magnitude placeholders so the panel can demonstrate the
#: arithmetic while AGMARKNET is unavailable. Any figure derived from one is
#: flagged ``price_basis="assumed"`` so the UI can mark it, and it must not be
#: read as a market rate.
FALLBACK_PRICES_PER_QUINTAL = {
    "tomato": 1200.0,
    "onion": 850.0,
    "leafy_greens": 600.0,
}

#: Crop naming differs between the classifier (snake_case) and the price cache
#: (title case); this is the bridge.
CROP_CACHE_NAMES = {
    "tomato": "Tomato",
    "onion": "Onion",
    "potato": "Potato",
    "leafy_greens": "Leafy Greens",
}


def price_per_tonne(price_per_quintal: float) -> float:
    return price_per_quintal * QUINTALS_PER_TONNE


def storage_cost(
    cost_per_tonne_day: float, quantity_t: float, holding_days: int
) -> float:
    return cost_per_tonne_day * quantity_t * holding_days


def net_benefit(
    price_per_quintal: float,
    cost_per_tonne_day: float,
    quantity_t: float,
    holding_days: int = DEFAULT_HOLDING_DAYS,
    recovery_factor: float = PRICE_RECOVERY_FACTOR,
) -> dict:
    """Full hold-or-sell breakdown for one facility and one quantity.

    Returns every intermediate term, not just the bottom line, so the caller
    can show what the number is made of instead of asking for it on trust.
    """
    per_tonne = price_per_tonne(price_per_quintal)

    current_revenue = per_tonne * quantity_t
    recovery_revenue = per_tonne * recovery_factor * quantity_t
    cost = storage_cost(cost_per_tonne_day, quantity_t, holding_days)
    benefit = recovery_revenue - cost - current_revenue

    return {
        "quantity_t": round(quantity_t, 3),
        "holding_days": holding_days,
        "price_per_quintal": round(price_per_quintal, 2),
        "price_per_tonne": round(per_tonne, 2),
        "recovery_factor": recovery_factor,
        "current_revenue": round(current_revenue, 2),
        "recovery_revenue": round(recovery_revenue, 2),
        "storage_cost": round(cost, 2),
        "net_benefit": round(benefit, 2),
        # Break-even: the price multiple at which holding stops paying for
        # itself. More useful than the headline when the factor is an
        # assumption -- it says how much recovery is actually needed.
        #
        # Six decimal places, not the two used for currency: this number sits
        # just above 1.0, so rounding it coarsely moves the implied break-even
        # by hundreds of rupees on a full lorry load.
        "breakeven_factor": round(
            1.0 + (cost_per_tonne_day * holding_days) / per_tonne, 6
        )
        if per_tonne > 0
        else None,
        "assumption": (
            f"Assumes prices recover to {recovery_factor:.2f}x today's rate after "
            f"{holding_days} days. This is a planning assumption, not a forecast: "
            "nothing in NEYOGI observes post-storage price movement, and quality "
            "loss in store is not modelled."
        ),
    }


async def current_price_per_quintal(district: str, crop_key: str) -> tuple[float, str]:
    """Newest cached modal price for a crop, or the documented fallback.

    Returns ``(price, basis)`` where basis is ``"observed"`` when the figure
    came from a real AGMARKNET quote and ``"assumed"`` when it came from
    :data:`FALLBACK_PRICES_PER_QUINTAL`. Callers must surface the basis.
    """
    from backend import db

    cache_name = CROP_CACHE_NAMES.get(crop_key)
    if cache_name:
        try:
            row = await db.fetch_one(
                """
                SELECT modal_price
                FROM mandi_prices_cache
                WHERE district = %s AND crop = %s AND modal_price IS NOT NULL
                ORDER BY arrival_date DESC
                LIMIT 1
                """,
                (district, cache_name),
            )
            if row and row[0]:
                return float(row[0]), "observed"

            # Nothing local: a state-wide quote still beats a placeholder.
            row = await db.fetch_one(
                """
                SELECT AVG(modal_price)::float
                FROM mandi_prices_cache
                WHERE crop = %s AND modal_price IS NOT NULL
                  AND arrival_date >= CURRENT_DATE - INTERVAL '14 days'
                """,
                (cache_name,),
            )
            if row and row[0]:
                return float(row[0]), "observed_statewide"
        except db.DatabaseUnavailable as exc:
            logger.warning("Price lookup failed for %s/%s: %s", district, crop_key, exc)

    fallback = FALLBACK_PRICES_PER_QUINTAL.get(crop_key)
    if fallback is None:
        raise KeyError(f"No price and no fallback for crop {crop_key!r}")
    return fallback, "assumed"

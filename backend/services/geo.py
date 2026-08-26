"""Distances and district centroids.

Great-circle distance is enough here: the belt spans a few hundred kilometres,
and the transport-cost model is linear in distance anyway, so road-network
routing would add precision the cost model cannot use.

**On the centroids.** ``mandi_prices_cache`` records a market's *name* and its
district, but no coordinates -- AGMARKNET does not publish them. Distance to a
market is therefore measured centroid-to-centroid between districts, which is
an approximation of a real road distance and is labelled as such wherever it
surfaces. A market inside the grower's own district reports 0 km rather than
a fabricated intra-district figure.

Replacing these with surveyed APMC yard coordinates would make the distances
real; until then they are a planning aid, not a route.
"""

from __future__ import annotations

import math

#: Approximate administrative centres, WGS 84. Sourced from the district
#: headquarters town, not from a polygon centroid, because a headquarters is
#: where the APMC yard usually sits.
DISTRICT_CENTROIDS: dict[str, tuple[float, float]] = {
    # district: (latitude, longitude)
    "Kolar": (13.136, 78.129),
    "Chikkaballapur": (13.435, 77.727),
    "Chikkaballapura": (13.435, 77.727),  # geoBoundaries spelling
    "Bengaluru Rural": (13.190, 77.700),
    "Bangalore Rural": (13.190, 77.700),  # GAUL spelling
    "Bengaluru Urban": (12.972, 77.594),
    "Tumakuru": (13.341, 77.101),
    "Tumkur": (13.341, 77.101),  # GAUL spelling
    "Hassan": (13.005, 76.099),
    "Mandya": (12.523, 76.895),
    "Mysuru": (12.295, 76.639),
    "Mysore": (12.295, 76.639),  # GAUL spelling
    "Belagavi": (15.849, 74.498),
    "Belgaum": (15.849, 74.498),  # GAUL spelling
    "Ramanagara": (12.678, 77.336),
    "Chikkamagaluru": (13.316, 75.774),
    "Chikmagalur": (13.316, 75.774),  # GAUL spelling
    "Dharwad": (15.459, 75.007),
    "Davanagere": (14.466, 75.924),
    "Ballari": (15.139, 76.921),
    "Bellary": (15.139, 76.921),
    "Kalaburagi": (17.329, 76.834),
    "Gulbarga": (17.329, 76.834),
    "Shivamogga": (13.929, 75.568),
    "Shimoga": (13.929, 75.568),
    "Vijayapura": (16.831, 75.710),
    "Bijapur": (16.831, 75.710),
    "Kodagu": (12.342, 75.807),
    "Udupi": (13.341, 74.746),
    "Chitradurga": (14.230, 76.399),
    "Koppal": (15.350, 76.154),
    "Raichur": (16.205, 77.355),
    "Bagalkot": (16.181, 75.696),
    "Bidar": (17.913, 77.520),
    "Gadag": (15.429, 75.635),
    "Haveri": (14.795, 75.404),
    "Chamrajnagar": (11.923, 76.940),
    "Dakshin Kannad": (12.914, 74.856),
    "Uttar Kannand": (14.799, 74.135),
}

EARTH_RADIUS_KM = 6371.0


def haversine_km(
    origin: tuple[float, float], destination: tuple[float, float]
) -> float:
    """Great-circle distance in kilometres between two (lat, lon) pairs."""
    lat1, lon1 = origin
    lat2, lon2 = destination

    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def centroid_for(district: str) -> tuple[float, float] | None:
    """Centroid for a district name, tolerating the GAUL spellings.

    Returns None for an unknown district rather than a default point: a wrong
    centroid would silently produce a wrong distance and therefore a wrong
    ranking, which is worse than declining to rank.
    """
    if not district:
        return None
    if district in DISTRICT_CENTROIDS:
        return DISTRICT_CENTROIDS[district]
    key = district.strip().lower()
    for name, coords in DISTRICT_CENTROIDS.items():
        if name.lower() == key:
            return coords
    return None


def district_distance_km(origin_district: str, target_district: str) -> float | None:
    """Distance between two district centres, or None if either is unknown.

    Returns 0.0 when both names resolve to the same place -- a market in the
    grower's own district carries no inter-district haulage.
    """
    origin = centroid_for(origin_district)
    target = centroid_for(target_district)
    if origin is None or target is None:
        return None
    return haversine_km(origin, target)

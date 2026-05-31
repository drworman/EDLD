"""
core/geo.py — Planetary surface geometry helpers.

Great-circle distance and bearing between two latitude/longitude points on a
body of a given radius, used by the on-foot exobiology aid to tell a commander
how far they are from a previous organic sample (clonal-distance spacing) and
which way to head.
"""

from __future__ import annotations

import math
from typing import Optional


def surface_distance(lat1: float, lon1: float, lat2: float, lon2: float,
                     radius_m: float) -> float:
    """Great-circle distance in metres between two points on a sphere."""
    if radius_m <= 0:
        return 0.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi   = math.radians(lat2 - lat1)
    dlam   = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2)
    return radius_m * 2 * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing (degrees, 0–360, 0=N) from point 1 to point 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlam   = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def nearest_waypoint(lat: float, lon: float, radius_m: float,
                     waypoints: list[tuple[float, float]]) -> Optional[dict]:
    """Closest waypoint to (lat, lon): {distance, bearing, latitude, longitude}."""
    best = None
    for wlat, wlon in waypoints:
        d = surface_distance(lat, lon, wlat, wlon, radius_m)
        if best is None or d < best["distance"]:
            best = {"distance": d, "bearing": bearing(lat, lon, wlat, wlon),
                    "latitude": wlat, "longitude": wlon}
    return best

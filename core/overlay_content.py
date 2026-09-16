"""
core/overlay_content.py — What the overlay says, and when it says nothing.

Kept apart from both the transport and the plugin so the decision of what
belongs on screen is a pure function of the commander's situation, and can be
tested without a display, a game, or a database.

The rule this file exists to enforce
------------------------------------
The overlay is not a second dashboard. It sits on top of a HUD that is already
competing for the same attention, so it earns its place only when it is telling
the commander something they need *while driving* and cannot get from the game.
Everywhere else it draws nothing at all — not a header, not a logo, not an
"EDLD ready". A component's overlay_panel() returns None far more often than
it returns a panel, and that is the intended behaviour rather than a gap.

Concretely: bearings to deposits you have already found, while you are in an
SRV on a body that has some. Docked, in supercruise, in the ship, or on a body
with nothing recorded, the overlay is blank.
"""

from __future__ import annotations

from typing import Iterable, Optional

from core.geo import bearing as geo_bearing, surface_distance

#: Deposit marks, coloured by how much is thought to be left. A worked-out site
#: still gets drawn — knowing a site is empty saves the drive out to it — but
#: it is dimmed so it does not compete with one worth visiting.
_AMOUNT_COLOURS = {
    "High":     "#7ee787",
    "Medium":   "#8fd1ff",
    "Low":      "#e3b341",
    "Depleted": "#6b7280",
    "":         "#8fd1ff",
}

#: Beyond this the bearing is not useful — the commander should be flying, not
#: driving, and a mark on the tape would imply otherwise.
MAX_RANGE_M = 20_000.0


def _fmt_distance(metres: float) -> str:
    if metres < 1000:
        return f"{metres:.0f}m"
    return f"{metres / 1000:.1f}km"


def nearest_deposits(latitude: float, longitude: float, radius_m: float,
                     deposits: Iterable[dict], limit: int = 5,
                     max_range_m: float = MAX_RANGE_M) -> list[dict]:
    """Deposits within range, nearest first, each with distance and bearing.

    Each returned dict is the stored row plus ``distance_m`` and ``bearing``.
    """
    out = []
    for dep in deposits:
        lat, lon = dep.get("latitude"), dep.get("longitude")
        if lat is None or lon is None:
            continue
        d = surface_distance(latitude, longitude, lat, lon, radius_m)
        if d > max_range_m:
            continue
        out.append({**dep, "distance_m": d,
                    "bearing": geo_bearing(latitude, longitude, lat, lon)})
    out.sort(key=lambda r: r["distance_m"])
    return out[:limit]

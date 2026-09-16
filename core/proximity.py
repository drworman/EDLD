"""
core/proximity.py — Noticing that you are standing on something.

Surface mining exposes no target in the journal and none in Status.json —
``ShipTargeted`` is the only targeting event in a full journal corpus and it is
ships only. So "keep the deposit targeted and drive within X" cannot be built:
EDLD cannot know what is targeted. Position is all there is, and position turns
out to be enough, because nothing else is within 25 m of a deposit.

That is simpler than the targeting version anyway. Nothing to explain to the
commander, and no failure mode where they forgot to lock something.

Hysteresis
----------
The naive version fires on every sample inside the radius, which at two samples
a second means a parked SRV rewrites the same row a hundred times a minute and
`last_confirmed` becomes a record of how long someone idled rather than when
they were last there. Worse, every one of those writes clears ``published_at``,
so a stationary commander would push the same deposit to the shared sheet on
every flush forever.

So an entry fires once, and the deposit must be left — past a wider exit radius
than the entry one — before it can fire again. The two radii differ on purpose:
a single threshold makes a commander sitting at exactly 25 m generate an
entry/exit pair per sample, which is the same bug with extra steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

#: How close counts as standing on a deposit. Comfortably inside the area the
#: game highlights on the ground, and far tighter than the radius that decides
#: whether two sightings are the same deposit — so an arrival can never be
#: ambiguous between neighbours.
DEFAULT_ENTER_M = 25.0

#: How far away counts as having left. Must exceed the entry radius; see the
#: module docstring on why a single threshold oscillates.
EXIT_FACTOR = 2.0


@dataclass
class ProximityTracker:
    """Tracks which deposits the commander is currently standing on."""

    enter_m: float = DEFAULT_ENTER_M
    exit_factor: float = EXIT_FACTOR
    _inside: set[str] = field(default_factory=set)

    @property
    def exit_m(self) -> float:
        return self.enter_m * max(1.01, self.exit_factor)

    @property
    def inside(self) -> frozenset[str]:
        return frozenset(self._inside)

    def reset(self) -> None:
        """Forget everything. Called when the commander leaves the body.

        Not doing this would mean returning to a body later and being told you
        are still standing where you were when you left it.
        """
        self._inside.clear()

    def update(self, distances: dict[str, float]) -> list[str]:
        """Feed one sample. Returns the deposits newly arrived at.

        ``distances`` maps deposit id to metres. A deposit absent from the map
        is treated as out of range — which is what happens when the commander
        changes body, and is why that case needs no special handling here.
        """
        arrived: list[str] = []
        exit_m = self.exit_m

        for dep_id in list(self._inside):
            d = distances.get(dep_id)
            if d is None or d > exit_m:
                self._inside.discard(dep_id)

        for dep_id, d in distances.items():
            if d <= self.enter_m and dep_id not in self._inside:
                self._inside.add(dep_id)
                arrived.append(dep_id)

        return arrived


def distances_to(latitude: float, longitude: float, radius_m: float,
                 deposits: Iterable[dict],
                 measure: Optional[Callable] = None) -> dict[str, float]:
    """Distance from a position to each deposit, keyed by deposit id."""
    if measure is None:
        from core.geo import surface_distance as measure
    out: dict[str, float] = {}
    for dep in deposits:
        dep_id = dep.get("deposit_id")
        lat, lon = dep.get("latitude"), dep.get("longitude")
        if not dep_id or lat is None or lon is None:
            continue
        out[dep_id] = measure(latitude, longitude, lat, lon, radius_m)
    return out

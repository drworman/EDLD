"""
core/explo_db.py — Exploration accessors for the body database.

Stars, planets, rings and non-bodies: the things a Scan and a surface mapping
write, and the things the Exploration window reads.  This is a mixin, not a
standalone store — :class:`core.bodies_db.BodyDB` composes it with the
exobiology accessors over one connection, and the generic helpers it calls
(``_upsert``, ``_set_status``, ``_filter``) come from
:class:`core.bodies_db.BodiesCore`.

Sibling: :mod:`core.exobio_db` holds the flora side.  ``planet_signals`` is in
:mod:`core.bodies_db` rather than here because one ``FSSBodySignals`` event
carries geological and biological signals together.
"""

from __future__ import annotations

from typing import Any

# Whitelists for partial-update setters — guard against arbitrary column names
# reaching the SQL string.  Add new columns here as well as to the migration,
# or upsert_* will silently drop them.
_STAR_STATUS_FLAGS   = {"discovered", "was_discovered", "scan_state", "scanned_at"}
_PLANET_STATUS_FLAGS = {
    "discovered", "was_discovered", "mapped", "was_mapped",
    "efficient", "footfall", "scan_state", "scanned_at", "mapped_at",
}

_STAR_COLS = {
    "name", "type", "subclass", "luminosity", "mass", "radius", "temp",
    "distance", "rotation", "orbital_period",
}
_PLANET_COLS = {
    "name", "type", "atmosphere", "volcanism", "terraform_state", "distance",
    "mass", "radius", "gravity", "temp", "pressure", "rotation",
    "orbital_period", "parent_stars", "materials", "landable",
    "bio_signals", "geo_signals",
}


class ExplorationAccessors:
    """Star, planet, ring and non-body reads and writes."""

    # ── stars ─────────────────────────────────────────────────────────────

    def upsert_star(self, system_id: int, body_id: int, **props: Any) -> int:
        values = {"system_id": system_id, "body_id": body_id}
        values.update(self._filter(_STAR_COLS, props))
        return self._upsert("stars", ("system_id", "body_id"), values)

    def set_star_status(self, star_id: int, commander_id: int, **flags: Any) -> None:
        self._set_status(
            "star_status", ("star_id", "commander_id"),
            (star_id, commander_id), _STAR_STATUS_FLAGS, flags,
        )

    # ── planets ───────────────────────────────────────────────────────────

    def upsert_planet(self, system_id: int, body_id: int, **props: Any) -> int:
        values = {"system_id": system_id, "body_id": body_id}
        values.update(self._filter(_PLANET_COLS, props))
        return self._upsert("planets", ("system_id", "body_id"), values)

    def set_planet_status(self, planet_id: int, commander_id: int, **flags: Any) -> None:
        self._set_status(
            "planet_status", ("planet_id", "commander_id"),
            (planet_id, commander_id), _PLANET_STATUS_FLAGS, flags,
        )

    def set_planet_gas(self, planet_id: int, gas_name: str, percent: float) -> int:
        return self._upsert(
            "planet_gas", ("planet_id", "gas_name"),
            {"planet_id": planet_id, "gas_name": gas_name, "percent": percent},
        )

    # ── rings & non-bodies ────────────────────────────────────────────────

    def add_ring(self, parent_kind: str, parent_id: int, name: str, ring_type: str = "") -> int:
        if parent_kind not in ("star", "planet"):
            raise ValueError(f"parent_kind must be 'star' or 'planet' (got {parent_kind!r})")
        return self._upsert(
            "rings", ("parent_kind", "parent_id", "name"),
            {"parent_kind": parent_kind, "parent_id": parent_id,
             "name": name, "type": ring_type},
        )

    def upsert_non_body(self, system_id: int, body_id: int, name: str = "") -> int:
        return self._upsert(
            "non_bodies", ("system_id", "body_id"),
            {"system_id": system_id, "body_id": body_id, "name": name},
        )

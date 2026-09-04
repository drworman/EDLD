"""
core/exobio_db.py — Exobiology accessors for the body database.

Flora, per-commander sample status and sample waypoints: the things
``ScanOrganic`` writes, and the things the Exobiology window reads.  This is a
mixin, not a standalone store — :class:`core.bodies_db.BodyDB` composes it with
the exploration accessors over one connection, and the generic helpers it calls
(``_upsert``, ``_set_status``) come from :class:`core.bodies_db.BodiesCore`.

Flora rows hang off ``planets``, which the exploration side owns, so the two
domains share a database even though they no longer share a module.  Sibling:
:mod:`core.explo_db`.
"""

from __future__ import annotations

from typing import Any

# Whitelist for the partial-update setter — guard against arbitrary column
# names reaching the SQL string.
_FLORA_STATUS_FLAGS = {"count", "logged", "scanned_at"}


class ExobiologyAccessors:
    """Flora, sample-status and waypoint reads and writes."""

    # ── flora ─────────────────────────────────────────────────────────────

    def upsert_flora(self, planet_id: int, genus: str, species: str = "", color: str = "") -> int:
        return self._upsert(
            "flora", ("planet_id", "genus", "species"),
            {"planet_id": planet_id, "genus": genus, "species": species, "color": color},
        )

    def set_flora_status(self, flora_id: int, commander_id: int, **flags: Any) -> None:
        self._set_status(
            "flora_status", ("flora_id", "commander_id"),
            (flora_id, commander_id), _FLORA_STATUS_FLAGS, flags,
        )

    def add_waypoint(
        self, flora_id: int, commander_id: int,
        latitude: float, longitude: float, wp_type: str = "tag",
    ) -> int:
        with self._w() as conn:
            cur = conn.execute(
                "INSERT INTO flora_waypoints "
                "(flora_id, commander_id, type, latitude, longitude) "
                "VALUES (?, ?, ?, ?, ?)",
                (flora_id, commander_id, wp_type, latitude, longitude),
            )
            return int(cur.lastrowid)

    def reset_other_in_progress_flora(self, commander_id: int, keep_flora_id: int) -> int:
        """A commander can have only one organic sample in progress at a time;
        starting to sample a different species drops any incomplete progress on
        the previous one.  Reset every other in-progress row (count 1 or 2, not
        yet logged) for this commander back to 0 so the dashboard shows it as
        begun anew.  Returns the number of rows reset.
        """
        with self._w() as conn:
            cur = conn.execute(
                "UPDATE flora_status SET count = 0 "
                "WHERE commander_id = ? AND flora_id <> ? "
                "AND logged = 0 AND count IN (1, 2)",
                (commander_id, keep_flora_id),
            )
            return cur.rowcount

    def planet_flora(self, planet_id: int, commander_id: int) -> list[dict]:
        return [
            dict(r) for r in self._c.execute(
                "SELECT f.*, fs.count, fs.logged, fs.scanned_at "
                "FROM flora f "
                "LEFT JOIN flora_status fs "
                "  ON fs.flora_id = f.id AND fs.commander_id = ? "
                "WHERE f.planet_id = ? ORDER BY f.genus, f.species",
                (commander_id, planet_id),
            )
        ]

    def flora_waypoints(self, flora_id: int, commander_id: int) -> list[dict]:
        return [
            dict(r) for r in self._c.execute(
                "SELECT type, latitude, longitude FROM flora_waypoints "
                "WHERE flora_id = ? AND commander_id = ?",
                (flora_id, commander_id),
            )
        ]

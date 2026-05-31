"""
core/explo_db.py — Shared body/exploration data store.

A single SQLite database at the data root holds the universal galaxy facts
(systems, stars, planets, rings, non-bodies, flora) once, and segments the
per-commander state (discovered / mapped / scanned / sampled) into status
tables keyed by commander.  The Exploration and Exobiology windows read from
it; their data-provider components write to it as journal events arrive and as
the lifetime journal import backfills history.

Design notes
------------
- **Engine:** standard-library ``sqlite3`` only; no ORM dependency.
- **Location:** ``<EDLD_DATA_DIR>/explo.db`` (shared across commanders).
- **Concurrency:** connections are cached per process id.  EDLD forks early in
  GTK4 mode, so a connection opened before the fork must never be reused in the
  child — the PID check reopens a fresh connection on first use in any new
  process.  Within a process, a re-entrant lock serialises writes and WAL mode
  keeps readers non-blocking.
- **Migrations:** an integer ``schema_version`` in the ``meta`` table gates a
  forward-only migration list.  ``current_version()`` lets callers refuse to
  read from a database newer than they understand.

Upgrading the schema (additive contract)
-----------------------------------------
The store is built to grow as more fields become available — whether the game
starts emitting new journal data or richer facts are merged in from an external
source.  Every upgrade is *additive*: existing rows are never rewritten or
dropped.  To extend the schema:

1. Bump :data:`SCHEMA_VERSION`.
2. Add a new ``if have < N:`` block in :meth:`ExploDB._migrate` that only
   introduces things — ``CREATE TABLE IF NOT EXISTS`` for new tables,
   ``self._add_column(...)`` for new columns (a no-op if already present).
   Never edit an existing migration block.
3. Add any new column names to the relevant ``_*_COLS`` write whitelist so
   :meth:`upsert_*` will persist them.

Because new columns are introduced with defaults, an older database simply gains
empty columns on upgrade, and a newer writer talking to a not-yet-migrated
schema drops unknown fields harmlessly (the migration is what makes them land).
Importing facts from any external dataset uses the same idempotent upserts keyed
on the game's identifiers, so a merge or re-import only fills gaps — it cannot
corrupt rows already collected from the journals.

The natural keys are the game's own 64-bit identifiers: ``SystemAddress`` for
systems and the per-system ``BodyID`` for bodies, so re-scanning a body updates
the same row rather than duplicating it.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

from core.state import EDLD_DATA_DIR

# Bumped whenever the schema below changes.  Add a migration step rather than
# editing an existing one so existing databases upgrade cleanly.
SCHEMA_VERSION = 1


# ── Schema ────────────────────────────────────────────────────────────────────
# Baseline (v1).  Every table uses an INTEGER PRIMARY KEY surrogate plus a
# UNIQUE natural key so upserts can target a stable row.

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS journals (
    name        TEXT PRIMARY KEY,
    imported_at TEXT
);

CREATE TABLE IF NOT EXISTS commanders (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    fid  TEXT UNIQUE,
    name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS systems (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    address        INTEGER UNIQUE,
    name           TEXT NOT NULL DEFAULT '',
    x              REAL NOT NULL DEFAULT 0.0,
    y              REAL NOT NULL DEFAULT 0.0,
    z              REAL NOT NULL DEFAULT 0.0,
    region         INTEGER,
    body_count     INTEGER NOT NULL DEFAULT 0,
    non_body_count INTEGER NOT NULL DEFAULT 0,
    population     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_systems_name ON systems(name);

CREATE TABLE IF NOT EXISTS system_status (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id     INTEGER NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    commander_id  INTEGER NOT NULL REFERENCES commanders(id) ON DELETE CASCADE,
    honked        INTEGER NOT NULL DEFAULT 0,
    fully_scanned INTEGER NOT NULL DEFAULT 0,
    fully_mapped  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(system_id, commander_id)
);

CREATE TABLE IF NOT EXISTS stars (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id      INTEGER NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    body_id        INTEGER NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    type           TEXT NOT NULL DEFAULT '',
    subclass       INTEGER NOT NULL DEFAULT 0,
    luminosity     TEXT NOT NULL DEFAULT '',
    mass           REAL NOT NULL DEFAULT 0.0,
    radius         REAL NOT NULL DEFAULT 0.0,
    temp           REAL,
    distance       REAL NOT NULL DEFAULT 0.0,
    rotation       REAL NOT NULL DEFAULT 0.0,
    orbital_period REAL NOT NULL DEFAULT 0.0,
    UNIQUE(system_id, body_id)
);

CREATE TABLE IF NOT EXISTS star_status (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    star_id        INTEGER NOT NULL REFERENCES stars(id) ON DELETE CASCADE,
    commander_id   INTEGER NOT NULL REFERENCES commanders(id) ON DELETE CASCADE,
    discovered     INTEGER NOT NULL DEFAULT 0,
    was_discovered INTEGER NOT NULL DEFAULT 0,
    scan_state     INTEGER NOT NULL DEFAULT 0,
    scanned_at     TEXT,
    UNIQUE(star_id, commander_id)
);

CREATE TABLE IF NOT EXISTS planets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id       INTEGER NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    body_id         INTEGER NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    type            TEXT NOT NULL DEFAULT '',
    atmosphere      TEXT NOT NULL DEFAULT '',
    volcanism       TEXT NOT NULL DEFAULT '',
    terraform_state TEXT NOT NULL DEFAULT '',
    distance        REAL NOT NULL DEFAULT 0.0,
    mass            REAL NOT NULL DEFAULT 0.0,
    radius          REAL NOT NULL DEFAULT 0.0,
    gravity         REAL NOT NULL DEFAULT 0.0,
    temp            REAL,
    pressure        REAL,
    rotation        REAL NOT NULL DEFAULT 0.0,
    orbital_period  REAL NOT NULL DEFAULT 0.0,
    parent_stars    TEXT NOT NULL DEFAULT '',
    materials       TEXT NOT NULL DEFAULT '',
    landable        INTEGER NOT NULL DEFAULT 0,
    bio_signals     INTEGER NOT NULL DEFAULT 0,
    geo_signals     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(system_id, body_id)
);

CREATE TABLE IF NOT EXISTS planet_status (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id     INTEGER NOT NULL REFERENCES planets(id) ON DELETE CASCADE,
    commander_id  INTEGER NOT NULL REFERENCES commanders(id) ON DELETE CASCADE,
    discovered    INTEGER NOT NULL DEFAULT 0,
    was_discovered INTEGER NOT NULL DEFAULT 0,
    mapped        INTEGER NOT NULL DEFAULT 0,
    was_mapped    INTEGER NOT NULL DEFAULT 0,
    efficient     INTEGER NOT NULL DEFAULT 0,
    footfall      INTEGER NOT NULL DEFAULT 0,
    scan_state    INTEGER NOT NULL DEFAULT 0,
    scanned_at    TEXT,
    mapped_at     TEXT,
    UNIQUE(planet_id, commander_id)
);

CREATE TABLE IF NOT EXISTS planet_gas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL REFERENCES planets(id) ON DELETE CASCADE,
    gas_name  TEXT NOT NULL,
    percent   REAL NOT NULL DEFAULT 0.0,
    UNIQUE(planet_id, gas_name)
);

CREATE TABLE IF NOT EXISTS planet_signals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL REFERENCES planets(id) ON DELETE CASCADE,
    kind      TEXT NOT NULL,            -- 'bio' | 'geo' | other signal class
    genus     TEXT NOT NULL DEFAULT '', -- localised genus when known, else ''
    count     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(planet_id, kind, genus)
);

CREATE TABLE IF NOT EXISTS rings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_kind TEXT NOT NULL,          -- 'star' | 'planet'
    parent_id   INTEGER NOT NULL,       -- stars.id or planets.id (by parent_kind)
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT '',
    UNIQUE(parent_kind, parent_id, name)
);

CREATE TABLE IF NOT EXISTS non_bodies (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id INTEGER NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    body_id   INTEGER NOT NULL,
    name      TEXT NOT NULL DEFAULT '',
    UNIQUE(system_id, body_id)
);

CREATE TABLE IF NOT EXISTS flora (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL REFERENCES planets(id) ON DELETE CASCADE,
    genus     TEXT NOT NULL,
    species   TEXT NOT NULL DEFAULT '',
    color     TEXT NOT NULL DEFAULT '',
    UNIQUE(planet_id, genus, species)
);

CREATE TABLE IF NOT EXISTS flora_status (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    flora_id     INTEGER NOT NULL REFERENCES flora(id) ON DELETE CASCADE,
    commander_id INTEGER NOT NULL REFERENCES commanders(id) ON DELETE CASCADE,
    count        INTEGER NOT NULL DEFAULT 0,
    logged       INTEGER NOT NULL DEFAULT 0,
    scanned_at   TEXT,
    UNIQUE(flora_id, commander_id)
);

CREATE TABLE IF NOT EXISTS flora_waypoints (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    flora_id     INTEGER NOT NULL REFERENCES flora(id) ON DELETE CASCADE,
    commander_id INTEGER NOT NULL REFERENCES commanders(id) ON DELETE CASCADE,
    type         TEXT NOT NULL DEFAULT 'tag',
    latitude     REAL NOT NULL DEFAULT 0.0,
    longitude    REAL NOT NULL DEFAULT 0.0
);
"""

# Whitelists for partial-update setters — guard against arbitrary column names
# reaching the SQL string.
_SYSTEM_STATUS_FLAGS = {"honked", "fully_scanned", "fully_mapped"}
_STAR_STATUS_FLAGS   = {"discovered", "was_discovered", "scan_state", "scanned_at"}
_PLANET_STATUS_FLAGS = {
    "discovered", "was_discovered", "mapped", "was_mapped",
    "efficient", "footfall", "scan_state", "scanned_at", "mapped_at",
}
_FLORA_STATUS_FLAGS  = {"count", "logged", "scanned_at"}

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
_SYSTEM_COLS = {
    "name", "x", "y", "z", "region", "body_count", "non_body_count", "population",
}


# ── Connection manager ──────────────────────────────────────────────────────

class ExploDB:
    """Process- and thread-safe accessor for the shared body database."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None
        self._pid: Optional[int] = None
        self._lock = threading.RLock()
        # >0 while inside a transaction() block: write helpers defer their
        # commit to the enclosing batch so a full-archive import is one commit
        # per journal rather than one per row.
        self._batch_depth = 0

    # ── connection lifecycle ──────────────────────────────────────────────

    def _open(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._path), check_same_thread=False, timeout=30.0
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @contextmanager
    def _w(self):
        """Serialise a single write and commit it, unless inside a batch."""
        with self._lock:
            conn = self._c
            try:
                yield conn
                if self._batch_depth == 0:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise

    @contextmanager
    def transaction(self):
        """Group many writes into one commit.

        Used by the journal importer to commit per-journal rather than
        per-row.  Re-entrant; the outermost block commits (or rolls back the
        whole batch on error).
        """
        with self._lock:
            conn = self._c
            self._batch_depth += 1
            try:
                yield conn
                if self._batch_depth == 1:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self._batch_depth -= 1

    @property
    def _c(self) -> sqlite3.Connection:
        """Return this process's connection, reopening after a fork."""
        pid = os.getpid()
        if self._conn is None or self._pid != pid:
            self._conn = self._open()
            self._pid = pid
            self._migrate(self._conn)
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
                    self._pid = None

    # ── migrations ────────────────────────────────────────────────────────

    def _migrate(self, conn: sqlite3.Connection) -> None:
        with self._lock:
            conn.executescript(
                "CREATE TABLE IF NOT EXISTS meta "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');"
            )
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            have = int(row["value"]) if row else 0

            # Forward-only, additive steps.  Each block must be idempotent and
            # must only introduce tables/columns — never alter or drop existing
            # data.  See "Upgrading the schema" in the module docstring.
            if have < 1:
                conn.executescript(_SCHEMA_V1)

            # Example of the pattern for the next revision (kept as a guide):
            #   if have < 2:
            #       self._add_column(conn, "planets", "ascending_node REAL")
            #       conn.executescript(_SCHEMA_V2_NEW_TABLES)

            if have < SCHEMA_VERSION:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(SCHEMA_VERSION),),
                )
                conn.commit()

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
        return any(
            r["name"] == column
            for r in conn.execute(f"PRAGMA table_info({table})")
        )

    def _add_column(self, conn: sqlite3.Connection, table: str, coldef: str) -> None:
        """Add a column if it isn't already present (idempotent migration aid).

        ``coldef`` is the full SQLite column definition, e.g.
        ``"ascending_node REAL"`` or ``"discovered INTEGER NOT NULL DEFAULT 0"``.
        Existing rows receive the column's default; their data is untouched.
        """
        column = coldef.split()[0]
        if not self._column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")

    def current_version(self) -> int:
        row = self._c.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        return int(row["value"]) if row else 0

    # ── low-level helpers ─────────────────────────────────────────────────

    def _upsert(
        self,
        table: str,
        conflict: tuple[str, ...],
        values: dict[str, Any],
    ) -> int:
        """Insert or update a row by its unique key; return the row id.

        ``conflict`` names the columns of the UNIQUE constraint.  All other
        keys in ``values`` are updated on conflict.
        """
        cols = list(values.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_sql = ", ".join(cols)
        updates = [c for c in cols if c not in conflict]
        with self._w() as conn:
            if updates:
                set_sql = ", ".join(f"{c}=excluded.{c}" for c in updates)
                sql = (
                    f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
                    f"ON CONFLICT({', '.join(conflict)}) DO UPDATE SET {set_sql}"
                )
            else:
                sql = (
                    f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
                    f"ON CONFLICT({', '.join(conflict)}) DO NOTHING"
                )
            conn.execute(sql, [values[c] for c in cols])
            where = " AND ".join(f"{c}=?" for c in conflict)
            row = conn.execute(
                f"SELECT id FROM {table} WHERE {where}",
                [values[c] for c in conflict],
            ).fetchone()
            return int(row["id"])

    def _set_status(
        self,
        table: str,
        key_cols: tuple[str, ...],
        key_vals: tuple[Any, ...],
        allowed: set[str],
        flags: dict[str, Any],
    ) -> None:
        bad = set(flags) - allowed
        if bad:
            raise ValueError(f"{table}: unknown status fields {sorted(bad)}")
        key_sql = ", ".join(key_cols)
        key_ph = ", ".join("?" for _ in key_cols)
        with self._w() as conn:
            conn.execute(
                f"INSERT OR IGNORE INTO {table} ({key_sql}) VALUES ({key_ph})",
                key_vals,
            )
            if flags:
                set_sql = ", ".join(f"{k}=?" for k in flags)
                where = " AND ".join(f"{c}=?" for c in key_cols)
                conn.execute(
                    f"UPDATE {table} SET {set_sql} WHERE {where}",
                    (*flags.values(), *key_vals),
                )

    @staticmethod
    def _filter(cols: set[str], data: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in data.items() if k in cols}

    # ── commanders ────────────────────────────────────────────────────────

    def ensure_commander(self, fid: str, name: str = "") -> int:
        return self._upsert("commanders", ("fid",), {"fid": fid, "name": name})

    # ── systems ───────────────────────────────────────────────────────────

    def upsert_system(self, address: int, **props: Any) -> int:
        values = {"address": address}
        values.update(self._filter(_SYSTEM_COLS, props))
        return self._upsert("systems", ("address",), values)

    def system_id_by_address(self, address: int) -> Optional[int]:
        row = self._c.execute(
            "SELECT id FROM systems WHERE address=?", (address,)
        ).fetchone()
        return int(row["id"]) if row else None

    def set_system_status(self, system_id: int, commander_id: int, **flags: Any) -> None:
        self._set_status(
            "system_status", ("system_id", "commander_id"),
            (system_id, commander_id), _SYSTEM_STATUS_FLAGS, flags,
        )

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

    def set_planet_signal(
        self, planet_id: int, kind: str, count: int, genus: str = ""
    ) -> int:
        return self._upsert(
            "planet_signals", ("planet_id", "kind", "genus"),
            {"planet_id": planet_id, "kind": kind, "genus": genus, "count": count},
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

    # ── journal import bookmark ───────────────────────────────────────────

    def is_journal_imported(self, name: str) -> bool:
        row = self._c.execute(
            "SELECT 1 FROM journals WHERE name=?", (name,)
        ).fetchone()
        return row is not None

    def mark_journal_imported(self, name: str, imported_at: str = "") -> None:
        with self._w() as conn:
            conn.execute(
                "INSERT INTO journals(name, imported_at) VALUES(?, ?) "
                "ON CONFLICT(name) DO UPDATE SET imported_at=excluded.imported_at",
                (name, imported_at),
            )

    def imported_journals(self) -> set[str]:
        return {
            r["name"] for r in self._c.execute("SELECT name FROM journals")
        }

    # ── reads for the windows ─────────────────────────────────────────────

    def get_system(self, address: int) -> Optional[dict]:
        row = self._c.execute(
            "SELECT * FROM systems WHERE address=?", (address,)
        ).fetchone()
        return dict(row) if row else None

    def system_bodies(self, system_id: int, commander_id: int) -> dict[str, list[dict]]:
        """Return the stars / planets / non-bodies of a system joined with this
        commander's status, ordered by ``body_id`` (the in-system ordering)."""
        stars = [
            dict(r) for r in self._c.execute(
                "SELECT s.*, "
                "ss.discovered, ss.was_discovered, ss.scan_state, ss.scanned_at "
                "FROM stars s "
                "LEFT JOIN star_status ss "
                "  ON ss.star_id = s.id AND ss.commander_id = ? "
                "WHERE s.system_id = ? ORDER BY s.body_id",
                (commander_id, system_id),
            )
        ]
        planets = [
            dict(r) for r in self._c.execute(
                "SELECT p.*, "
                "ps.discovered, ps.was_discovered, ps.mapped, ps.was_mapped, "
                "ps.efficient, ps.footfall, ps.scan_state, ps.scanned_at, ps.mapped_at "
                "FROM planets p "
                "LEFT JOIN planet_status ps "
                "  ON ps.planet_id = p.id AND ps.commander_id = ? "
                "WHERE p.system_id = ? ORDER BY p.body_id",
                (commander_id, system_id),
            )
        ]
        non_bodies = [
            dict(r) for r in self._c.execute(
                "SELECT * FROM non_bodies WHERE system_id = ? ORDER BY body_id",
                (system_id,),
            )
        ]
        return {"stars": stars, "planets": planets, "non_bodies": non_bodies}

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

    def planet_signals(self, planet_id: int) -> list[dict]:
        return [
            dict(r) for r in self._c.execute(
                "SELECT kind, genus, count FROM planet_signals "
                "WHERE planet_id = ? ORDER BY kind, genus",
                (planet_id,),
            )
        ]

    def counts(self) -> dict[str, int]:
        """Row counts for the principal tables (diagnostics / progress)."""
        out: dict[str, int] = {}
        for t in ("systems", "stars", "planets", "flora", "journals"):
            out[t] = int(
                self._c.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            )
        return out


# ── module-level singleton ──────────────────────────────────────────────────

_DB: Optional[ExploDB] = None
_DB_LOCK = threading.Lock()


def db_path() -> Path:
    """Path to the shared body database at the data root."""
    return EDLD_DATA_DIR / "explo.db"


def get_db() -> ExploDB:
    """Return the process-wide :class:`ExploDB` singleton, creating it lazily."""
    global _DB
    if _DB is None:
        with _DB_LOCK:
            if _DB is None:
                _DB = ExploDB(db_path())
    return _DB

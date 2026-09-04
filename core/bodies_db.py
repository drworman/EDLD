"""
core/bodies_db.py — Shared body catalogue: connection, schema, and the tables
both domains own jointly.

A single SQLite database at the data root holds the universal galaxy facts
(systems, stars, planets, rings, non-bodies, flora) once, and segments the
per-commander state (discovered / mapped / scanned / sampled) into status
tables keyed by commander.  The Exploration and Exobiology windows read from
it; the ``explo_sync`` component writes to it as journal events arrive and as
the lifetime journal import backfills history.

Module layout
-------------
This module owns what neither domain owns alone: the connection lifecycle,
the schema and its migrations, the corrupt-file quarantine, the generic
upsert/status helpers, and the shared tables — ``commanders``, ``systems``,
``journals``, and ``planet_signals``.

The domain accessors live beside the code that uses them:

- :mod:`core.explo_db` — stars, planets, rings, non-bodies.
- :mod:`core.exobio_db` — flora, sample status, waypoints.

Both are mixins, composed here into the single :class:`BodyDB`.  The split is
by concern, not by storage: the tables interlink through ``systems`` and
``planets``, so one database and one connection serve both.

``planet_signals`` stays here deliberately.  A single ``FSSBodySignals`` event
carries biological, geological and human signals together, so the table has one
writer and two readers and belongs to neither domain.

Design notes
------------
- **Engine:** standard-library ``sqlite3`` only; no ORM dependency.
- **Location:** ``<EDLD_DATA_DIR>/explo.db`` (shared across commanders).
- **Concurrency:** connections are cached per process id as a defensive
  guard — a connection is never reused across processes; the PID check reopens
  a fresh connection on first use in any new process.  Within a process, a
  re-entrant lock serialises writes and WAL mode keeps readers non-blocking.
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
2. Add a new ``if have < N:`` block in :meth:`BodiesCore._migrate` that only
   introduces things — ``CREATE TABLE IF NOT EXISTS`` for new tables,
   ``self._add_column(...)`` for new columns (a no-op if already present).
   Never edit an existing migration block.
3. Add any new column names to the relevant ``_*_COLS`` write whitelist so
   ``upsert_*`` will persist them — in this module for systems, in
   :mod:`core.explo_db` for stars and planets.

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

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from core.state import EDLD_DATA_DIR
from core.exobio_db import ExobiologyAccessors
from core.explo_db import ExplorationAccessors


# Corruption is not distinguished by exception class — sqlite3 raises the same
# DatabaseError for a malformed image as for a file that was never a database
# at all — so the message is what separates "this file is unusable" from an
# ordinary query error that must not trigger a rebuild.
_CORRUPTION_MARKERS = (
    "database disk image is malformed",
    "file is not a database",
    "database corruption",
    "malformed database schema",
)


def _is_corruption(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _CORRUPTION_MARKERS)


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
# reaching the SQL string.  Star, planet and flora whitelists live with their
# accessors in core.explo_db and core.exobio_db.
_SYSTEM_STATUS_FLAGS = {"honked", "fully_scanned", "fully_mapped"}
_SYSTEM_COLS = {
    "name", "x", "y", "z", "region", "body_count", "non_body_count", "population",
}


# ── Connection manager ──────────────────────────────────────────────────────

class BodiesCore:
    """Connection, schema and shared-table accessors for the body database.

    Not instantiated directly — :class:`BodyDB` composes this with the two
    domain accessor mixins.
    """

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
            try:
                self._conn = self._open()
                self._pid  = pid
                self._migrate(self._conn)
            except sqlite3.DatabaseError as e:
                # "database disk image is malformed" / "file is not a database".
                # Every row here is derived from the journal archive and nothing
                # else, so the file is a cache, not a record — it can be thrown
                # away and rebuilt.  Left in place it fails every read and write
                # forever, and the Exploration and Exobiology windows stay empty
                # across every future launch with no way back short of deleting
                # the file by hand.
                #
                # Both _open() and _migrate() can be the one to notice: opening
                # runs PRAGMA statements, which is often where a truncated or
                # overwritten file first refuses.
                #
                # The bad file is renamed rather than removed: a corrupt SQLite
                # database is often still partly readable, and it costs nothing
                # to keep it for a post-mortem.
                if not _is_corruption(e):
                    raise
                self._quarantine(e)
                self._conn = self._open()
                self._pid  = pid
                self._migrate(self._conn)
        return self._conn

    def _quarantine(self, exc: Exception) -> None:
        """Move a corrupt database aside so a fresh one can be built."""
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

        stamp = time.strftime("%Y%m%d-%H%M%S")
        moved = []
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(self._path) + suffix)
            if not src.exists():
                continue
            dst = Path(f"{self._path}.corrupt-{stamp}{suffix}")
            try:
                src.rename(dst)
                moved.append(dst.name)
            except OSError:
                # Cannot rename it — try to get out of the way regardless, or
                # the next open hits the same corrupt file again.
                try:
                    src.unlink()
                except OSError:
                    pass

        msg = (
            f"body database corrupt ({exc}); moved aside as "
            f"{', '.join(moved) or '(could not rename)'} and rebuilding from "
            f"the journal archive"
        )
        try:
            from core import debug as _dbg
            _dbg.log(f"[BodyDB] {msg}", level="ERROR")
        except Exception:
            pass
        print(f"[BodyDB] {msg}")

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
    def planet_signals(self, planet_id: int) -> list[dict]:
        return [
            dict(r) for r in self._c.execute(
                "SELECT kind, genus, count FROM planet_signals "
                "WHERE planet_id = ? ORDER BY kind, genus",
                (planet_id,),
            )
        ]
    def set_planet_signal(
        self, planet_id: int, kind: str, count: int, genus: str = ""
    ) -> int:
        return self._upsert(
            "planet_signals", ("planet_id", "kind", "genus"),
            {"planet_id": planet_id, "kind": kind, "genus": genus, "count": count},
        )

    def counts(self) -> dict[str, int]:
        """Row counts for the principal tables (diagnostics / progress)."""
        out: dict[str, int] = {}
        for t in ("systems", "stars", "planets", "flora", "journals"):
            out[t] = int(
                self._c.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            )
        return out


# ── Composition ─────────────────────────────────────────────────────────────

class BodyDB(ExplorationAccessors, ExobiologyAccessors, BodiesCore):
    """The body database: shared core plus both domains' accessors.

    One class and one connection.  The mixins carry no state of their own —
    they reach the database through the helpers :class:`BodiesCore` provides —
    so composition order carries no meaning beyond readability.
    """


# ── module-level singleton ──────────────────────────────────────────────────

_DB: Optional[BodyDB] = None
_DB_LOCK = threading.Lock()


def db_path() -> Path:
    """Path to the shared body database at the data root."""
    return EDLD_DATA_DIR / "explo.db"


def get_db() -> BodyDB:
    """Return the process-wide :class:`BodyDB` singleton, creating it lazily."""
    global _DB
    if _DB is None:
        with _DB_LOCK:
            if _DB is None:
                _DB = BodyDB(db_path())
    return _DB

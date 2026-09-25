"""
core/mining_db.py — Surface mining survey store.

A SQLite database of planetary surface mining deposits: where they are, what
they yield, how rich they were, and when somebody last stood on one.  The
``surface_mining`` component writes to it as journal events arrive; the
Options window and the (forthcoming) Sheets publisher read from it.

Design notes
------------
- **Engine:** standard-library ``sqlite3`` only; no ORM dependency.
- **Location:** ``<EDLD_DATA_DIR>/data/mining.db`` — shared across commanders.
  A deposit is in the same place whoever finds it.
- **Separate from explo.db, deliberately.**  The body catalogue interleaves
  universal facts with per-commander status tables keyed by commander id, and
  the survey needs neither.  It needs a handful of body columns (class,
  gravity, radius) and it needs to be exportable on its own, so it keeps its
  own denormalised copy of those four values rather than taking a dependency
  on a schema it does not otherwise use.  Four duplicated columns are cheaper
  than the coupling.
- **Concurrency:** connection cached per process id, re-entrant lock around
  writes, WAL so readers do not block.  Same shape as :mod:`core.bodies_db`.
- **Migrations:** integer ``schema_version`` in ``meta`` gates a forward-only,
  strictly additive migration list.  Never edit an existing migration block.

Deposit identity
----------------
Two sightings are the same deposit when they share ``(system_address, body_id,
commodity)`` and lie within :data:`DEDUPE_RADIUS_M` of each other on the
surface.  Coordinates are never compared for equality: re-scans do not repeat
floats, and rounding to a fixed precision draws an arbitrary grid across the
body with some deposits straddling a line.

On first sighting a deposit is given a stable id — the leading 12 hex digits
of a SHA-1 over the identity tuple and that first position.  Every later
sighting resolves to that id by geometry and the id itself never moves.  It is
what the shared spreadsheet keys on, so the published side matches by string
equality and never has to reimplement a haversine.

Depletion
---------
Working a site out is not a delete, and it is not an amount either. Amount and
density describe the deposit — what the HUD says is there when it is full — and
a worked-out site is the same deposit, empty for now. So ``mark_depleted``
touches neither: it appends a dated line to ``depletion_log``, and the date of
the most recent line is the whole of how depletion is recorded, shown and
shared. "Empty on the twelfth" is worth more to the next commander than a
missing row, and more than an amount that would have to be put back by hand
once the site refilled.

Sites do refill. How long that takes is not yet known, so
:data:`REPLENISH_DAYS` is ``None`` and :func:`replenishes_on` answers nothing;
once it is measured, setting it is the whole change, and every depletion date
already recorded becomes a refresh date.

Amount and density
------------------
These are assessments, and a sighting does not overturn one: a later refine or
a drive-by fills them only where they are blank. They change when a commander
corrects them, and a correction stamps ``assessment_updated``. That stamp, not
``last_confirmed``, is what decides between two versions on the sheet and on
import — otherwise anyone who merely drove onto a site would re-send whatever
they had imported weeks ago with a fresh date, and undo the correction.

Notes
-----
``notes`` is free text a commander writes about a site — the way in, a hazard,
what else is on the ridge. Unlike every other field it is not an observation,
so it does not merge like one. The sighting fields fill blanks and follow
``last_confirmed``; a note follows ``notes_updated``, the moment it was last
written, and the most recent writing wins outright — including a blank one,
because emptying the box is how a note is withdrawn.

Tying it to ``last_confirmed`` would have let any commander who merely drove
onto a site re-send whatever note they imported weeks ago with a fresh date,
and silently put back text its author had since changed or removed.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from core.geo import surface_distance

SCHEMA_VERSION = 2

#: Two sightings of the same commodity on the same body within this many metres
#: are the same deposit.
#:
#: Sized against the gap between real deposits rather than against measurement
#: error. Observed spacing on surveyed bodies is 400-500 m at the closest, so
#: 100 m cannot merge two neighbours, and anything this wide is still close
#: enough to walk from. The rig spacing the game actually requires is not known
#: — if it turns out to be consistent, this is the number to revisit.
DEDUPE_RADIUS_M = 100.0

#: Fallback body radius, in metres, when no Scan has supplied one.  Only used
#: so distance comparisons degrade to something sane rather than dividing by
#: zero; a body with no radius is recorded and flagged rather than dropped.
_FALLBACK_RADIUS_M = 2.0e6

#: Lowest first. "Depleted" is deliberately absent — see Depletion above.
AMOUNT_LEVELS  = ("Low", "Medium", "High")

#: The assessed fields, which only a correction changes once they are set.
ASSESSED_FIELDS = ("amount", "density_observed", "density_claimed")

#: Days for a worked-out site to refill. Unknown: None until it is measured.
REPLENISH_DAYS: int | None = None

#: Longest note kept. A cap against a pasted page rather than a style rule: the
#: note travels to a shared sheet and back into every squadron member's form.
MAX_NOTES_CHARS = 1000
DENSITY_LEVELS = ("Low", "Medium", "High")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalise_notes(raw) -> str:
    """A note as it is stored: plain text, ``\n`` line ends, no outer space.

    Applied to what the form submits and to what the sheet sends back alike,
    since a sheet is a document people edit by hand. Control characters other
    than line breaks are dropped and tabs become spaces. Length is not
    touched; see :func:`clean_notes`.
    """
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ")
    text = "".join(ch for ch in text
                   if ch == "\n" or (ch >= " " and ch != "\x7f"))
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def clean_notes(raw) -> str:
    """:func:`normalise_notes`, cut to :data:`MAX_NOTES_CHARS`.

    For text arriving from the sheet, which is cut rather than refused —
    refusing is the form's job, where somebody can act on it.
    """
    return normalise_notes(raw)[:MAX_NOTES_CHARS]


def replenishes_on(depleted_on: str) -> str:
    """The day a site worked out on ``depleted_on`` should have refilled.

    ``""`` while :data:`REPLENISH_DAYS` is unknown, and for no date. The one
    place the refill rule lives, so the sheet, the overlay and the form can all
    ask it once it means something.
    """
    day = str(depleted_on or "")[:10]
    if not day or REPLENISH_DAYS is None:
        return ""
    from datetime import date, timedelta
    try:
        return (date.fromisoformat(day) + timedelta(days=REPLENISH_DAYS)).isoformat()
    except ValueError:
        return ""


def deposit_id(system_address: int, body_id: int, commodity: str,
               latitude: float, longitude: float) -> str:
    """Stable 12-hex-digit id for a deposit, from its first recorded position.

    Never recomputed for a deposit that already exists — a later sighting a few
    metres away resolves to the existing row by distance and keeps its id.
    """
    raw = f"{int(system_address)}|{int(body_id)}|{commodity.lower()}|" \
          f"{float(latitude):.6f}|{float(longitude):.6f}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bodies (
    system_address INTEGER NOT NULL,
    body_id        INTEGER NOT NULL,
    system_name    TEXT    NOT NULL DEFAULT '',
    body_name      TEXT    NOT NULL DEFAULT '',
    planet_class   TEXT    NOT NULL DEFAULT '',
    gravity        REAL,
    radius_m       REAL,
    atmosphere     TEXT    NOT NULL DEFAULT '',
    volcanism      TEXT    NOT NULL DEFAULT '',
    surface_temp   REAL,
    updated_at     TEXT    NOT NULL,
    PRIMARY KEY (system_address, body_id)
);

-- One row per body per DSS.  The count is what the surface scan reported for
-- $PlanetaryMiningLocation_Name; — how many mining location signals exist,
-- which is known before any of them has been visited.
CREATE TABLE IF NOT EXISTS body_survey (
    system_address  INTEGER NOT NULL,
    body_id         INTEGER NOT NULL,
    signal_count    INTEGER NOT NULL DEFAULT 0,
    hotspots        TEXT    NOT NULL DEFAULT '',
    first_seen      TEXT    NOT NULL,
    last_seen       TEXT    NOT NULL,
    PRIMARY KEY (system_address, body_id)
);

CREATE TABLE IF NOT EXISTS deposits (
    deposit_id       TEXT    PRIMARY KEY,
    system_address   INTEGER NOT NULL,
    body_id          INTEGER NOT NULL,
    commodity        TEXT    NOT NULL,
    commodity_display TEXT   NOT NULL DEFAULT '',
    latitude         REAL    NOT NULL,
    longitude        REAL    NOT NULL,
    signal_no        INTEGER,
    density_claimed  TEXT    NOT NULL DEFAULT '',
    density_observed TEXT    NOT NULL DEFAULT '',
    amount           TEXT    NOT NULL DEFAULT '',
    rigs             INTEGER,
    refine_count     INTEGER NOT NULL DEFAULT 0,
    first_seen       TEXT    NOT NULL,
    last_confirmed   TEXT    NOT NULL,
    reported_by      TEXT    NOT NULL DEFAULT '',
    is_test          INTEGER NOT NULL DEFAULT 0,
    published_at     TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (system_address, body_id)
        REFERENCES bodies(system_address, body_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_deposits_body
    ON deposits(system_address, body_id, commodity);
CREATE INDEX IF NOT EXISTS idx_deposits_unpublished
    ON deposits(published_at);

CREATE TABLE IF NOT EXISTS depletion_log (
    deposit_id TEXT NOT NULL REFERENCES deposits(deposit_id) ON DELETE CASCADE,
    noted_at   TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (deposit_id, noted_at)
);
"""


class MiningDB:
    """Connection lifecycle, schema, and accessors for the survey store."""

    def __init__(self, path: Path | str, log=None) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._pid = -1
        self._log = log or (lambda _m: None)

    @property
    def path(self) -> Path:
        return self._path

    # ── connection ────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is not None and self._pid == os.getpid():
                return self._conn
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.executescript(_SCHEMA)
            self._migrate(conn)
            self._conn = conn
            self._pid = os.getpid()
            return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()
        have = int(row["value"]) if row else 0
        # Version 1 is the initial schema, created in full by _SCHEMA above.
        # Later versions add strictly — CREATE TABLE IF NOT EXISTS for new
        # tables, ALTER TABLE ADD COLUMN for new columns.  Never edit a block
        # that has shipped.
        if have < 2:
            # A commander's free-text note, and when it was last written.
            # Checked rather than assumed: a store copied back from a newer
            # build can already have the columns with an older version number.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(deposits)")}
            if "notes" not in cols:
                conn.execute("ALTER TABLE deposits ADD COLUMN "
                             "notes TEXT NOT NULL DEFAULT ''")
            if "notes_updated" not in cols:
                conn.execute("ALTER TABLE deposits ADD COLUMN "
                             "notes_updated TEXT NOT NULL DEFAULT ''")
            # When amount or density was last corrected by hand.
            if "assessment_updated" not in cols:
                conn.execute("ALTER TABLE deposits ADD COLUMN "
                             "assessment_updated TEXT NOT NULL DEFAULT ''")
            # Depletion leaves the amount. A row that says Depleted keeps the
            # fact as a dated log line — its last confirmation, if nothing
            # already dates it — and loses the word, which describes the site
            # rather than how much it holds. published_at is left alone: this
            # is a change of representation, not news for the sheet.
            conn.execute(
                "INSERT OR IGNORE INTO depletion_log(deposit_id, noted_at, note) "
                "SELECT deposit_id, last_confirmed, "
                "       'Worked out ' || substr(last_confirmed, 1, 10) "
                "FROM deposits d WHERE amount='Depleted' AND NOT EXISTS "
                "(SELECT 1 FROM depletion_log l WHERE l.deposit_id=d.deposit_id)")
            conn.execute("UPDATE deposits SET amount='' WHERE amount='Depleted'")
        if have < SCHEMA_VERSION:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),))
            conn.commit()

    def current_version(self) -> int:
        conn = self._connect()
        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 0

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
                    self._pid = -1

    # ── bodies ────────────────────────────────────────────────────────────────

    def upsert_body(self, system_address: int, body_id: int, **fields) -> None:
        """Record or update what is known about a body.

        Only supplied fields are written, so a later ``Scan`` filling in
        volcanism does not blank a gravity recorded earlier from Status.json.
        """
        cols = ("system_name", "body_name", "planet_class", "gravity",
                "radius_m", "atmosphere", "volcanism", "surface_temp")
        given = {k: v for k, v in fields.items() if k in cols and v is not None}
        now = _utcnow()
        conn = self._connect()
        with self._lock:
            conn.execute(
                "INSERT OR IGNORE INTO bodies(system_address, body_id, updated_at) "
                "VALUES(?,?,?)", (int(system_address), int(body_id), now))
            if given:
                sets = ", ".join(f"{k}=?" for k in given)
                conn.execute(
                    f"UPDATE bodies SET {sets}, updated_at=? "
                    "WHERE system_address=? AND body_id=?",
                    (*given.values(), now, int(system_address), int(body_id)))
            conn.commit()

    def body(self, system_address: int, body_id: int) -> Optional[dict]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM bodies WHERE system_address=? AND body_id=?",
            (int(system_address), int(body_id))).fetchone()
        return dict(row) if row else None

    def body_radius(self, system_address: int, body_id: int) -> float:
        b = self.body(system_address, body_id)
        r = (b or {}).get("radius_m")
        return float(r) if r else _FALLBACK_RADIUS_M

    # ── body survey (DSS census) ──────────────────────────────────────────────

    def record_survey(self, system_address: int, body_id: int,
                      signal_count: int, hotspots: str = "") -> None:
        """Record what a surface scan said about a body's mining locations."""
        now = _utcnow()
        conn = self._connect()
        with self._lock:
            conn.execute(
                "INSERT INTO body_survey(system_address, body_id, signal_count, "
                "hotspots, first_seen, last_seen) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(system_address, body_id) DO UPDATE SET "
                "signal_count=excluded.signal_count, hotspots=excluded.hotspots, "
                "last_seen=excluded.last_seen",
                (int(system_address), int(body_id), int(signal_count),
                 hotspots, now, now))
            conn.commit()

    def survey(self, system_address: int, body_id: int) -> Optional[dict]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM body_survey WHERE system_address=? AND body_id=?",
            (int(system_address), int(body_id))).fetchone()
        return dict(row) if row else None

    # ── deposits ──────────────────────────────────────────────────────────────

    def find_deposit_near(self, system_address: int, body_id: int,
                          commodity: str, latitude: float, longitude: float,
                          radius_m: float | None = None) -> Optional[dict]:
        """Return the existing deposit this position belongs to, or None.

        Nearest match wins when several are inside the radius, which happens on
        bodies where the same commodity appears in a tight cluster.
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM deposits WHERE system_address=? AND body_id=? "
            "AND commodity=?",
            (int(system_address), int(body_id), commodity.lower())).fetchall()
        if not rows:
            return None
        body_r = radius_m if radius_m else self.body_radius(system_address, body_id)
        best, best_d = None, None
        for r in rows:
            d = surface_distance(latitude, longitude,
                                 r["latitude"], r["longitude"], body_r)
            if d <= DEDUPE_RADIUS_M and (best_d is None or d < best_d):
                best, best_d = dict(r), d
        return best

    def record_deposit(self, system_address: int, body_id: int, commodity: str,
                       latitude: float, longitude: float, *,
                       commodity_display: str = "",
                       density_claimed: str = "", density_observed: str = "",
                       amount: str = "", rigs: int | None = None,
                       signal_no: int | None = None,
                       reported_by: str = "", is_test: bool = False,
                       refined: bool | int = False) -> tuple[str, bool]:
        """Record a sighting.  Returns ``(deposit_id, created)``.

        An existing deposit within :data:`DEDUPE_RADIUS_M` is confirmed rather
        than duplicated: ``last_confirmed`` moves, the refine counter rises, and
        any field this sighting knows that the stored row does not is filled in.
        Stored values are not overwritten with blanks.
        """
        commodity = (commodity or "").lower()
        now = _utcnow()
        conn = self._connect()
        with self._lock:
            existing = self.find_deposit_near(
                system_address, body_id, commodity, latitude, longitude)

            if existing:
                did = existing["deposit_id"]
                updates = {"last_confirmed": now}
                if refined:
                    # A run of refines is collapsed into one call, so the
                    # counter advances by how many there were rather than by
                    # one — otherwise a deposit worked for an hour and one
                    # touched once are indistinguishable.
                    updates["refine_count"] = (int(existing["refine_count"])
                                               + max(1, int(refined)))
                for key, val in (("commodity_display", commodity_display),
                                 ("density_claimed",  density_claimed),
                                 ("density_observed", density_observed),
                                 ("amount",           amount),
                                 ("reported_by",      reported_by)):
                    if val and not existing[key]:
                        updates[key] = val
                if rigs is not None:
                    updates["rigs"] = int(rigs)
                if signal_no is not None and existing["signal_no"] is None:
                    updates["signal_no"] = int(signal_no)
                # Any change makes the published copy stale.
                updates["published_at"] = ""
                sets = ", ".join(f"{k}=?" for k in updates)
                conn.execute(f"UPDATE deposits SET {sets} WHERE deposit_id=?",
                             (*updates.values(), did))
                conn.commit()
                return did, False

            did = deposit_id(system_address, body_id, commodity,
                             latitude, longitude)
            conn.execute(
                "INSERT OR IGNORE INTO deposits("
                " deposit_id, system_address, body_id, commodity,"
                " commodity_display, latitude, longitude, signal_no,"
                " density_claimed, density_observed, amount, rigs,"
                " refine_count, first_seen, last_confirmed, reported_by,"
                " is_test, published_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'')",
                (did, int(system_address), int(body_id), commodity,
                 commodity_display, float(latitude), float(longitude),
                 signal_no, density_claimed, density_observed, amount,
                 rigs, max(1, int(refined)) if refined else 0, now, now,
                 reported_by,
                 1 if is_test else 0))
            conn.commit()
            return did, True

    def nearest_deposit(self, system_address: int, body_id: int,
                        latitude: float, longitude: float,
                        radius_m: float | None = None) -> Optional[dict]:
        """Closest deposit to a position on this body, whatever the commodity.

        Unlike :meth:`find_deposit_near`, which answers "is this the same
        deposit I am recording" and so must not cross commodities, this answers
        "which deposit am I standing on" — and the commander standing on one
        does not need to name it first.
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM deposits WHERE system_address=? AND body_id=?",
            (int(system_address), int(body_id))).fetchall()
        if not rows:
            return None
        body_r = radius_m if radius_m else self.body_radius(system_address, body_id)
        best, best_d = None, None
        for r in rows:
            d = surface_distance(latitude, longitude,
                                 r["latitude"], r["longitude"], body_r)
            if d <= DEDUPE_RADIUS_M and (best_d is None or d < best_d):
                best, best_d = dict(r), d
        return best

    def annotate_deposit(self, dep_id: str, *, amount: str = "",
                         density_observed: str = "",
                         density_claimed: str = "",
                         rigs: int | None = None,
                         signal_no: int | None = None,
                         depleted_on: str = "",
                         is_test: bool | None = None,
                         notes: str | None = None) -> bool:
        """Apply a commander's assessment to a deposit.  Returns whether it changed.

        Blank arguments leave the stored value alone, so setting the amount
        does not wipe a density recorded earlier. Any change clears
        ``published_at`` so the sheet is told about it on the next flush —
        otherwise the correction would sit in the local store forever while the
        squadron kept reading the old value.

        Setting amount or density to something other than what is stored is a
        correction, and stamps ``assessment_updated`` — the stamp that lets it
        replace another commander's value on the sheet and on their import.

        ``depleted_on`` adds a dated line to the depletion log and changes
        nothing else: the amount stays what the site holds when it is full.

        ``notes`` is the exception: ``None`` leaves the note alone, and any
        string — the empty one included — replaces it, since the form always
        shows the current note and an emptied box is a deliberate removal. A
        changed note stamps ``notes_updated``, which is what decides between
        two commanders' versions of it; an unchanged one stamps nothing.
        """
        updates: dict = {}
        if amount:
            updates["amount"] = amount
        if density_observed:
            updates["density_observed"] = density_observed
        if density_claimed:
            updates["density_claimed"] = density_claimed
        if rigs is not None:
            updates["rigs"] = int(rigs)
        if signal_no is not None:
            updates["signal_no"] = int(signal_no)
        if is_test is not None:
            updates["is_test"] = 1 if is_test else 0
        if not updates and not depleted_on and notes is None:
            return False

        now = _utcnow()
        conn = self._connect()
        with self._lock:
            row = conn.execute("SELECT * FROM deposits WHERE deposit_id=?",
                               (dep_id,)).fetchone()
            if row is None:
                return False
            if notes is not None and notes != (row["notes"] or ""):
                updates["notes"] = notes
                updates["notes_updated"] = now
            if not depleted_on:
                if not updates or all(str(row[k]) == str(v)
                                      for k, v in updates.items()):
                    return False
            if any(k in updates and str(row[k] or "") != str(updates[k])
                   for k in ASSESSED_FIELDS):
                updates["assessment_updated"] = now
            updates["last_confirmed"] = now
            updates["published_at"] = ""
            sets = ", ".join(f"{k}=?" for k in updates)
            conn.execute(f"UPDATE deposits SET {sets} WHERE deposit_id=?",
                         (*updates.values(), dep_id))
            if depleted_on:
                stamp = f"{depleted_on}T00:00:00Z"
                conn.execute(
                    "INSERT OR REPLACE INTO depletion_log(deposit_id, noted_at, note) "
                    "VALUES(?,?,?)", (dep_id, stamp, f"Worked out {depleted_on}"))
            conn.commit()
            return True

    def touch_deposit(self, dep_id: str) -> bool:
        """Record that somebody was just standing on this deposit.

        Freshness is the one thing about a deposit that decays on its own and
        that nobody will ever update by hand — sites are worked out by other
        commanders, so an old High is not a current High. Driving onto one is
        evidence it is still there, and that evidence is free.

        Deliberately not annotate_deposit(): that exists to apply a judgement
        and refuses a call with no fields, which a visit is. This moves the
        timestamp and nothing else, and clears published_at so the shared sheet
        learns the site was seen recently rather than keeping a date from
        whenever it was first dug.
        """
        now = _utcnow()
        conn = self._connect()
        with self._lock:
            cur = conn.execute(
                "UPDATE deposits SET last_confirmed=?, published_at='' "
                "WHERE deposit_id=?", (now, dep_id))
            conn.commit()
            return bool(cur.rowcount)

    def mark_depleted(self, dep_id: str, note: str = "") -> bool:
        """Stamp today as the day this site was worked out.

        Not a delete, and not an amount: the dated log line is the whole
        record. See Depletion in the module docstring.
        """
        now = _utcnow()
        conn = self._connect()
        with self._lock:
            cur = conn.execute(
                "UPDATE deposits SET last_confirmed=?, "
                "published_at='' WHERE deposit_id=?", (now, dep_id))
            if cur.rowcount == 0:
                return False
            conn.execute(
                "INSERT OR REPLACE INTO depletion_log(deposit_id, noted_at, note) "
                "VALUES(?,?,?)", (dep_id, now, note or f"Mined {now[:10]}"))
            conn.commit()
            return True

    def depletion_history(self, dep_id: str) -> list[dict]:
        conn = self._connect()
        return [dict(r) for r in conn.execute(
            "SELECT noted_at, note FROM depletion_log WHERE deposit_id=? "
            "ORDER BY noted_at", (dep_id,)).fetchall()]

    def deposits_on(self, system_address: int, body_id: int) -> list[dict]:
        """This body's deposits, each with ``depleted_on``: its latest date."""
        conn = self._connect()
        return [dict(r) for r in conn.execute(
            "SELECT d.*, (SELECT MAX(noted_at) FROM depletion_log l "
            " WHERE l.deposit_id = d.deposit_id) AS depleted_on "
            "FROM deposits d WHERE system_address=? AND body_id=? "
            "ORDER BY commodity, first_seen",
            (int(system_address), int(body_id))).fetchall()]

    def unpublished(self, limit: int = 500, include_test: bool = False) -> list[dict]:
        """Deposits changed since they were last published, oldest first."""
        conn = self._connect()
        sql = ("SELECT d.*, b.system_name, b.body_name, b.planet_class, "
               "b.gravity, b.radius_m, b.atmosphere, b.volcanism, "
               # The most recent depletion, from the log rather than the row.
               "(SELECT MAX(noted_at) FROM depletion_log l "
               " WHERE l.deposit_id = d.deposit_id) AS depleted_on "
               "FROM deposits d LEFT JOIN bodies b "
               "ON d.system_address=b.system_address AND d.body_id=b.body_id "
               "WHERE d.published_at=''")
        if not include_test:
            sql += " AND d.is_test=0"
        sql += " ORDER BY d.last_confirmed LIMIT ?"
        return [dict(r) for r in conn.execute(sql, (int(limit),)).fetchall()]

    def import_deposits(self, rows: Iterable[dict],
                        log=None) -> tuple[int, int]:
        """Merge deposits found by somebody else. Returns ``(added, updated)``.

        Imported rows are stamped as already published, so a deposit that came
        down from the sheet is never sent back up to it. Without that every
        commander would re-publish every other commander's finds on their next
        flush, and the sheet would spend its write quota echoing itself.

        Local observation wins. A row already in the store keeps every field it
        has; the import only fills blanks, and only advances ``last_confirmed``
        if the sheet's is newer. What the commander saw with their own eyes is
        better evidence than what a stranger wrote down last month.
        """
        conn = self._connect()
        now = _utcnow()
        added = updated = 0

        with self._lock:
            for row in rows:
                dep_id = str(row.get("deposit_id", "") or "").strip()
                if not dep_id:
                    continue
                try:
                    sa = int(row.get("system_address"))
                    bid = int(row.get("body_id"))
                    lat = float(row.get("latitude"))
                    lon = float(row.get("longitude"))
                except (TypeError, ValueError):
                    if log:
                        log(f"skipped malformed imported deposit {dep_id!r}")
                    continue

                existing = conn.execute(
                    "SELECT * FROM deposits WHERE deposit_id=?",
                    (dep_id,)).fetchone()

                # Amount and density are closed vocabularies. An imported row
                # is written as the sheet spells it, and a sheet is a document
                # people edit by hand — so "high" or "Very High" can arrive and
                # would then be stored as a value nothing downstream accepts.
                # Matched case-insensitively; anything unrecognised is dropped
                # rather than kept, because a wrong value is worse than a blank
                # one a later sighting can fill in.
                row = dict(row)
                notes = clean_notes(row.get("notes", ""))
                notes_at = str(row.get("notes_updated", "") or "").strip()
                for _key, _allowed in (("amount", AMOUNT_LEVELS),
                                       ("density_observed", DENSITY_LEVELS),
                                       ("density_claimed", DENSITY_LEVELS)):
                    _raw = str(row.get(_key, "") or "").strip()
                    row[_key] = next((a for a in _allowed
                                      if a.lower() == _raw.lower()), "")

                if existing is None:
                    conn.execute(
                        "INSERT INTO deposits("
                        " deposit_id, system_address, body_id, commodity,"
                        " commodity_display, latitude, longitude, signal_no,"
                        " density_claimed, density_observed, amount, rigs,"
                        " refine_count, first_seen, last_confirmed,"
                        " reported_by, is_test, published_at,"
                        " notes, notes_updated, assessment_updated)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,0,?,?,?,?)",
                        (dep_id, sa, bid,
                         str(row.get("commodity", "") or "").lower(),
                         str(row.get("commodity_display")
                             or row.get("commodity", "") or ""),
                         lat, lon, row.get("signal_no") or None,
                         str(row.get("density_claimed", "") or ""),
                         str(row.get("density_observed", "") or ""),
                         str(row.get("amount", "") or ""),
                         row.get("rigs") or None,
                         str(row.get("first_seen", "") or now),
                         str(row.get("last_confirmed", "") or now),
                         str(row.get("reported_by", "") or ""),
                         now, notes, notes_at,
                         str(row.get("assessment_updated", "") or "").strip()))
                    stamp = str(row.get("depleted_on", "") or "").strip()[:10]
                    if stamp:
                        conn.execute(
                            "INSERT OR REPLACE INTO depletion_log"
                            "(deposit_id, noted_at, note) VALUES(?,?,?)",
                            (dep_id, f"{stamp}T00:00:00Z",
                             f"Worked out {stamp}"))
                    added += 1
                    continue

                # Latest wins, the same way last_confirmed does. Sites reset
                # and are worked out again, so the freshest sighting of an
                # empty one describes the current state; an older date would
                # keep asserting a depletion that has since been undone.
                stamp = str(row.get("depleted_on", "") or "").strip()[:10]
                if stamp:
                    mine = conn.execute(
                        "SELECT MAX(noted_at) FROM depletion_log "
                        "WHERE deposit_id=?", (dep_id,)).fetchone()[0] or ""
                    if stamp > str(mine)[:10]:
                        conn.execute(
                            "INSERT OR REPLACE INTO depletion_log"
                            "(deposit_id, noted_at, note) VALUES(?,?,?)",
                            (dep_id, f"{stamp}T00:00:00Z",
                             f"Worked out {stamp}"))

                changes: dict = {}
                for field_name in ("commodity_display", "density_claimed",
                                   "density_observed", "amount", "reported_by"):
                    incoming = str(row.get(field_name, "") or "")
                    if incoming and not existing[field_name]:
                        changes[field_name] = incoming
                # A correction made since the one held here replaces it —
                # the one case where the sheet overrides what was seen
                # locally, because somebody has said the local value is wrong.
                assessed_at = str(row.get("assessment_updated", "") or "").strip()
                if assessed_at and assessed_at > str(existing["assessment_updated"] or ""):
                    for field_name in ASSESSED_FIELDS:
                        incoming = str(row.get(field_name, "") or "")
                        if incoming and incoming != existing[field_name]:
                            changes[field_name] = incoming
                    changes["assessment_updated"] = assessed_at
                theirs = str(row.get("last_confirmed", "") or "")
                if theirs and theirs > str(existing["last_confirmed"] or ""):
                    changes["last_confirmed"] = theirs
                # The note is not an observation, so "local wins" does not
                # apply: whoever wrote it last wins, even with a blank, which
                # is how its author withdraws it. Equal stamps mean this is the
                # note already held, echoed back.
                if notes_at and notes_at > str(existing["notes_updated"] or ""):
                    if notes != (existing["notes"] or ""):
                        changes["notes"] = notes
                    changes["notes_updated"] = notes_at
                elif (notes and not notes_at and not existing["notes"]
                        and not existing["notes_updated"]):
                    # Typed straight into the sheet, so never stamped. It can
                    # only fill a blank, like any other unattributed field.
                    changes["notes"] = notes
                if changes:
                    sets = ", ".join(f"{k}=?" for k in changes)
                    conn.execute(f"UPDATE deposits SET {sets} WHERE deposit_id=?",
                                 (*changes.values(), dep_id))
                    updated += 1
            conn.commit()
        return added, updated

    def delete_deposit(self, dep_id: str) -> bool:
        """Remove a deposit and its depletion history. Returns whether it went.

        Deletion is for a row that should never have existed — a bad commodity,
        a position filed under the wrong body — not for a site that is empty.
        An empty site gets a depletion date, which somebody else wants;
        deleting it throws that away and invites the next commander to rediscover
        it.
        """
        conn = self._connect()
        with self._lock:
            conn.execute("DELETE FROM depletion_log WHERE deposit_id=?", (dep_id,))
            cur = conn.execute("DELETE FROM deposits WHERE deposit_id=?", (dep_id,))
            conn.commit()
            return bool(cur.rowcount)

    def mark_published(self, ids: Iterable[str]) -> int:
        ids = [i for i in ids if i]
        if not ids:
            return 0
        now = _utcnow()
        conn = self._connect()
        with self._lock:
            cur = conn.executemany(
                "UPDATE deposits SET published_at=? WHERE deposit_id=?",
                [(now, i) for i in ids])
            conn.commit()
            return cur.rowcount or 0

    def counts(self) -> dict:
        """Row counts, for the Options window and the startup log line."""
        conn = self._connect()
        def one(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])
        return {
            "bodies":   one("SELECT COUNT(*) FROM bodies"),
            "surveyed": one("SELECT COUNT(*) FROM body_survey"),
            "deposits": one("SELECT COUNT(*) FROM deposits"),
            "pending":  one("SELECT COUNT(*) FROM deposits WHERE published_at=''"),
        }


_instance: Optional[MiningDB] = None
_instance_lock = threading.Lock()


def get_db(log=None) -> MiningDB:
    """Return the process-wide survey store, opening it on first use."""
    global _instance
    with _instance_lock:
        if _instance is None:
            from core.state import shared_data_dir
            _instance = MiningDB(shared_data_dir() / "mining.db", log=log)
        return _instance

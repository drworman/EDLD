"""
components/explo_sync.py — keep the shared body database current.

This component has no UI.  It does two things:

1. **Live write-through.**  It subscribes to the exploration / exobiology
   journal events and feeds each one to the shared :class:`Ingestor`, so the
   body database tracks the active session in real time.  Because the journal
   preload replays the current journal through ``on_event`` first, the active
   session's existing history lands the same way.

2. **Historical backfill.**  On load it starts the background journal importer
   for the rest of the archive (every journal *except* the currently-active
   one, which the live path owns).  The import runs on a daemon thread so a
   multi-year archive never blocks startup, and is incremental across launches.

The Exploration and Exobiology windows read the data this component maintains
and can poll :meth:`import_progress` to show backfill status.
"""

from __future__ import annotations

from typing import Optional

from core.plugin_loader import BasePlugin
from core.explo_db import ExploDB, db_path, get_db
from core.explo_ingest import INGEST_EVENTS, Ingestor
from core.explo_import import JournalImporter

try:
    from core import debug as _dbg
except Exception:  # pragma: no cover - debug facility optional in some contexts
    _dbg = None

# Events after which the Exploration window should repaint.
_VIEW_EVENTS = {
    "FSDJump", "Location", "CarrierJump",
    "FSSDiscoveryScan", "FSSAllBodiesFound",
    "Scan", "FSSBodySignals", "SAASignalsFound", "SAAScanComplete",
    "ScanOrganic", "Disembark",
}

# Events after which the Exobiology window should repaint.
_BIO_EVENTS = {
    "FSDJump", "Location", "CarrierJump",
    "FSSBodySignals", "SAASignalsFound", "SAAScanComplete",
    "ScanOrganic", "Disembark",
}


class ExploSyncPlugin(BasePlugin):
    PLUGIN_NAME        = "explo_sync"
    PLUGIN_DISPLAY     = "Exploration Data"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = "Maintains the shared body database from journal history and live play."
    PLUGIN_DEFAULT_ENABLED = True
    SUBSCRIBED_EVENTS = list(INGEST_EVENTS)

    def on_load(self, core) -> None:
        super().on_load(core)
        self._ingestor = Ingestor(get_db())
        self._importer: Optional[JournalImporter] = None
        self._progress: Optional[tuple[int, int]] = None
        self._import_done = False
        try:
            self._start_import()
        except Exception as e:
            self._log(f"import bootstrap failed: {e}")

    # ── live write-through ────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        # Fires during preload (active-journal history) and live play alike.
        try:
            self._ingestor.ingest(event)
        except Exception:
            # A single unsupported/malformed event must never disrupt play.
            pass
        ev_name = event.get("event")

        # On a sample, record the current surface position as a waypoint so the
        # on-foot aid can space samples by clonal distance.
        if ev_name == "ScanOrganic" and state is not None:
            try:
                lat = getattr(state, "surface_latitude", None)
                lon = getattr(state, "surface_longitude", None)
                fid = self._ingestor.last_flora_id()
                cid = self._ingestor.current_commander_id()
                if lat is not None and lon is not None and fid and cid:
                    get_db().add_waypoint(fid, cid, float(lat), float(lon),
                                          wp_type=str(event.get("ScanType", "tag")))
            except Exception:
                pass

        # Nudge the windows to repaint after view-relevant events.  The GUI
        # coalesces these into a single refresh per poll cycle.
        gq = getattr(self.core, "gui_queue", None)
        if gq is not None:
            try:
                if ev_name in _VIEW_EVENTS:
                    gq.put(("exploration_update", None))
                if ev_name in _BIO_EVENTS:
                    gq.put(("exobiology_update", None))
            except Exception:
                pass

    def on_unload(self) -> None:
        if self._importer is not None:
            self._importer.stop()

    # ── historical backfill ───────────────────────────────────────────────

    def _start_import(self) -> None:
        from core.journal import find_latest_journal

        jdir = getattr(self.core, "journal_dir", None)
        if not jdir:
            return

        # Force the shared connection through migration once, before a second
        # connection (the importer's) opens — so they don't race on first-run
        # schema creation.
        try:
            get_db().current_version()
        except Exception:
            pass

        active = find_latest_journal(jdir)
        exclude = [active] if active else []

        # The importer gets its own connection so its per-journal transactions
        # don't serialise against the live write-through path's connection.
        self._importer = JournalImporter(
            jdir,
            db=ExploDB(db_path()),
            on_progress=self._on_progress,
            on_complete=self._on_complete,
        )
        started = self._importer.start(exclude=exclude)
        if started:
            self._log("started journal-history import")

    # ── progress accessors (for the windows) ──────────────────────────────

    def import_running(self) -> bool:
        return self._importer is not None and self._importer.is_running()

    def import_progress(self) -> Optional[tuple[int, int]]:
        """``(done, total)`` while importing, or ``None`` when idle/complete."""
        return self._progress

    def import_done(self) -> bool:
        return self._import_done

    # ── live location (for the Exploration / Exobiology windows) ──────────────

    def current_system_address(self):
        """SystemAddress of the player's current system, or None."""
        return self._ingestor.current_system_address() if self._ingestor else None

    def current_commander_id(self):
        """Db id of the active commander, or None."""
        return self._ingestor.current_commander_id() if self._ingestor else None

    # ── callbacks ─────────────────────────────────────────────────────────

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self._progress = (done, total)
        self._notify_ui()

    def _on_complete(self, counts: dict) -> None:
        self._progress = None
        self._import_done = True
        self._log(f"journal-history import complete: {counts}")
        self._notify_ui()

    def _notify_ui(self) -> None:
        gq = getattr(self.core, "gui_queue", None)
        if gq is not None:
            try:
                gq.put(("explo_import", None))
            except Exception:
                pass

    def _log(self, msg: str) -> None:
        if _dbg is not None:
            try:
                _dbg.info(f"[ExploSync] {msg}")
            except Exception:
                pass

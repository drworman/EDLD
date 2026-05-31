"""
core/explo_import.py — Background journal-history importer.

Walks the commander's entire journal archive once to backfill the body
database, then leaves the live write-through path to keep it current.  Designed
to run on a daemon thread so a multi-year archive never blocks startup.

Behaviour
---------
- Journals are processed oldest-first so discovery / scan / map status
  accumulates in the order it actually happened.
- Each journal is recorded in the ``journals`` table once fully processed, so
  subsequent launches only touch new files.  The import is therefore
  incremental and resumable — stopping and restarting picks up where it left
  off, and because every write is an idempotent upsert keyed on the game's own
  identifiers, re-processing a partially-done file can never double-count.
- The currently-active journal is skipped; the live path owns it until it rolls
  over, at which point a later run imports the completed file.
- Each journal is ingested inside a single transaction, so the import commits
  once per file rather than once per row.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.explo_db import ExploDB, get_db
from core.explo_ingest import Ingestor

# How often to check the stop flag while reading a single (possibly huge) file.
_STOP_CHECK_LINES = 1000

_JOURNAL_GLOB = "Journal*.log"
_TOKEN_RE = re.compile(r"Journal\.(.+?)\.\d+\.log$")


def _log(msg: str) -> None:
    """Best-effort log line; the debug facility may be absent in tests."""
    try:
        from core import debug as _dbg
        _dbg.info(f"[ExploImport] {msg}")
    except Exception:
        pass


def journal_datetime(path: Path) -> datetime:
    """Sort key for a journal file, parsed from its embedded timestamp.

    Handles both the modern ``Journal.YYYY-MM-DDTHHMMSS.NN.log`` and the legacy
    ``Journal.YYMMDDHHMMSS.NN.log`` filename forms, falling back to the file's
    modification time when neither parses.
    """
    m = _TOKEN_RE.match(path.name)
    token = m.group(1) if m else ""
    for fmt in ("%Y-%m-%dT%H%M%S", "%y%m%d%H%M%S"):
        try:
            return datetime.strptime(token, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return datetime.min


class JournalImporter:
    """Owns the background import thread."""

    def __init__(
        self,
        journal_dir: Path,
        db: Optional[ExploDB] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_complete: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._journal_dir = Path(journal_dir)
        self._db = db or get_db()
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── control ───────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, exclude: Optional[Iterable[Path]] = None) -> bool:
        """Start the import on a daemon thread.  No-op if already running."""
        if self.is_running():
            return False
        self._stop.clear()
        excl = {Path(p).name for p in (exclude or [])}
        self._thread = threading.Thread(
            target=self._run, args=(excl,), name="explo-import", daemon=True
        )
        self._thread.start()
        return True

    def stop(self, join: bool = False, timeout: float = 5.0) -> None:
        self._stop.set()
        if join and self._thread is not None:
            self._thread.join(timeout)

    # ── work ──────────────────────────────────────────────────────────────

    def pending(self, exclude_names: Optional[set[str]] = None) -> list[Path]:
        """Journals not yet imported (and not excluded), oldest-first."""
        exclude_names = exclude_names or set()
        try:
            done = self._db.imported_journals()
        except Exception:
            done = set()
        files = [
            p for p in self._journal_dir.glob(_JOURNAL_GLOB)
            if p.name not in done and p.name not in exclude_names
        ]
        files.sort(key=journal_datetime)
        return files

    def _run(self, exclude_names: set[str]) -> None:
        files = self.pending(exclude_names)
        total = len(files)
        if total == 0:
            _log("nothing to import")
            self._fire_complete()
            return

        _log(f"importing {total} journal(s)")
        ingestor = Ingestor(self._db)
        done = 0
        for path in files:
            if self._stop.is_set():
                _log("stop requested — leaving remaining journals for next run")
                break
            try:
                self._import_one(path, ingestor)
            except Exception as e:           # one bad file must not abort the run
                _log(f"error importing {path.name}: {e}")
                continue
            done += 1
            self._fire_progress(done, total, path.name)

        _log(f"import finished: {done}/{total} journal(s) this run")
        self._fire_complete()

    def _import_one(self, path: Path, ingestor: Ingestor) -> None:
        completed = True
        with self._db.transaction():
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i % _STOP_CHECK_LINES == 0 and self._stop.is_set():
                        completed = False
                        break
                    line = line.strip()
                    if line:
                        try:
                            ingestor.ingest_line(line)
                        except Exception:
                            # Skip a single malformed/unsupported event.
                            pass
        # Only bookmark the file when we read it to the end; a stopped file is
        # re-read in full next run (idempotent, so safe).
        if completed:
            self._db.mark_journal_imported(path.name, datetime.utcnow().isoformat())

    # ── callbacks (best-effort) ───────────────────────────────────────────

    def _fire_progress(self, done: int, total: int, name: str) -> None:
        if self._on_progress:
            try:
                self._on_progress(done, total, name)
            except Exception:
                pass

    def _fire_complete(self) -> None:
        if self._on_complete:
            try:
                self._on_complete(self._db.counts())
            except Exception:
                pass

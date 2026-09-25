"""
tests/test_terminal_mode.py — ``--terminal`` gets the same background work.

Two faults, both invisible:

* The redraw queue had no reader in terminal mode.  The journal reader and the
  components post to it in every mode, so it grew for the life of the process.
* The Status.json poller was only started by the dashboards.  Terminal mode
  never read Status.json at all, so fuel, balance and shields went stale and
  every live surface refine was discarded for want of a position.
"""
from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.journal import _discard_gui_queue  # noqa: E402


def test_discard_drains_the_queue():
    q: queue.Queue = queue.Queue()
    for i in range(5000):
        q.put(("vessel_update", None))
    threading.Thread(target=_discard_gui_queue, args=(q,), daemon=True).start()
    deadline = time.monotonic() + 5
    while not q.empty() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert q.empty()


def test_discard_tolerates_no_queue():
    _discard_gui_queue(None)          # returns rather than spinning


def _terminal_branch() -> str:
    src = (ROOT / "edld.py").read_text(encoding="utf-8")
    start = src.index("else:  # terminal")
    return src[start:]


def test_terminal_mode_drains_the_redraw_queue():
    branch = _terminal_branch()
    assert "_discard_gui_queue" in branch
    assert branch.index("_discard_gui_queue") < branch.index("run_monitor()")


def test_terminal_mode_starts_the_status_poller():
    branch = _terminal_branch()
    assert "_start_status_poller()" in branch
    assert branch.index("_start_status_poller()") < branch.index("run_monitor()")

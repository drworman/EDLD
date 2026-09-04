"""
gui/search_dialog.py — Modal search dialog (Qt).

The Qt counterpart of ``tui/search_modal.py``.  Used by the Cargo block to
pick a target market and by the Commander block to set a home location; both
pass a ``search_fn`` that hits Spansh and a ``result_label`` that renders one
row of whatever that call returns.

Searching happens on a worker thread and results arrive back through a signal.
A search that ran on the GUI thread would freeze the whole dashboard for the
length of an HTTP round trip, and the dashboard is meant to keep updating
while the commander is typing into this box.

Typing is debounced: the query fires a short interval after the last
keystroke, so a commander typing a full station name issues one request rather
than one per character.
"""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from gui.theme import stylesheet

#: Milliseconds of keyboard silence before a query is issued.
_DEBOUNCE_MS = 320

#: Shortest query worth sending.  Single characters match most of the galaxy.
_MIN_QUERY = 2


class SearchDialog(QDialog):
    """Type-ahead search over an arbitrary callable.

    ``accepted_result`` carries the selected record (a dict) when the user
    confirms, and is not emitted at all if they cancel — matching the TUI
    modal's callback contract, where a dismissal passes ``None`` and callers
    check for it.
    """

    accepted_result = Signal(object)
    _results_ready = Signal(str, object)

    def __init__(
        self,
        parent,
        title: str,
        placeholder: str,
        search_fn: Callable[[str], list],
        result_label: Callable[[dict], str],
        theme: str = "default",
    ) -> None:
        super().__init__(parent)
        self._search_fn = search_fn
        self._result_label = result_label
        self._records: list[dict] = []
        self._query_seq = 0

        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.setStyleSheet(stylesheet(theme))
        # A modal dialog still gets its own title bar with close control on
        # every platform, which is what makes Escape and the [x] both work.
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(placeholder)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._on_return)
        lay.addWidget(self._input)

        self._status = QLabel("")
        self._status.setProperty("role", "dim")
        lay.addWidget(self._status)

        self._list = QListWidget()
        self._list.itemActivated.connect(lambda _i: self._accept_current())
        self._list.itemDoubleClicked.connect(lambda _i: self._accept_current())
        lay.addWidget(self._list, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_current)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._run_search)

        self._results_ready.connect(self._on_results)
        self._input.setFocus()

    # ── Query lifecycle ───────────────────────────────────────────────────────

    def _on_text_changed(self, _text: str) -> None:
        self._timer.start()

    def _run_search(self) -> None:
        query = self._input.text().strip()
        if len(query) < _MIN_QUERY:
            self._list.clear()
            self._records = []
            self._status.setText("")
            return

        self._query_seq += 1
        seq = self._query_seq
        self._status.setText("Searching…")

        def _worker():
            try:
                results = self._search_fn(query) or []
            except Exception as exc:
                results = {"_error": f"{type(exc).__name__}: {exc}"}
            self._results_ready.emit(str(seq), results)

        threading.Thread(target=_worker, daemon=True,
                         name="gui-search").start()

    def _on_results(self, seq: str, results) -> None:
        # Discard anything from a query the user has already typed past, so a
        # slow early request can't overwrite the results of a later one.
        if seq != str(self._query_seq):
            return

        self._list.clear()
        self._records = []

        if isinstance(results, dict) and results.get("_error"):
            self._status.setText(f"Search failed: {results['_error']}")
            return
        if not results:
            self._status.setText("No matches.")
            return

        for rec in results:
            try:
                label = self._result_label(rec)
            except Exception:
                label = str(rec)
            item = QListWidgetItem(label)
            self._list.addItem(item)
            self._records.append(rec)

        self._status.setText(f"{len(self._records)} result(s)")
        self._list.setCurrentRow(0)

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_return(self) -> None:
        # Enter in the text box goes straight to the top hit when one is
        # showing, and otherwise forces the pending query to run now.
        if self._records:
            self._accept_current()
        else:
            self._timer.stop()
            self._run_search()

    def _accept_current(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._records):
            self.accepted_result.emit(self._records[row])
            self.accept()

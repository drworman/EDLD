"""
gui/sell_dialog.py — the sell table as a popup window.

The GUI counterpart of tui/sell_modal.py.  Both render the same dict that the
Markdown and HTML files are written from, so the four never disagree about
what a commodity is worth or which market is being quoted.

Two tabs.  Mineable opens first — of the things that can be dug up, what does
this place pay most for — and All Items is the same table unfiltered.

Opened from View → Sell Table or with Ctrl+S; closed with Ctrl+S again, with
Escape, or with the window's own close button.  The window is non-modal, so
the dashboard behind it keeps updating while it is open.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from core.sell_table import render_columns
from gui.theme import stylesheet


def _grid() -> QTableWidget:
    """One two-column price table, configured the same way for both tabs."""
    grid = QTableWidget(0, 2)
    grid.setHorizontalHeaderLabels(["Commodity", "Sell"])
    grid.verticalHeader().setVisible(False)
    grid.setSelectionMode(QAbstractItemView.NoSelection)
    grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
    grid.setShowGrid(False)
    grid.setAlternatingRowColors(True)
    header = grid.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.Stretch)
    header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
    return grid


def _fill(grid: QTableWidget, rows: list[tuple[str, str]]) -> None:
    grid.setRowCount(len(rows))
    for i, (name, price) in enumerate(rows):
        price_cell = QTableWidgetItem(price)
        price_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.setItem(i, 0, QTableWidgetItem(name))
        grid.setItem(i, 1, price_cell)


class SellDialog(QDialog):
    """Two-column sell table, highest price first, over two tabs."""

    def __init__(self, parent, table: dict, theme: str = "default") -> None:
        super().__init__(parent)
        self._theme = theme

        self.setWindowTitle("Sell Table")
        self.setMinimumSize(440, 560)
        self.setStyleSheet(stylesheet(theme))
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        self._heading = QLabel()
        self._heading.setObjectName("sellHeading")
        lay.addWidget(self._heading)

        self._tabs = QTabWidget(self)
        self._mineable = _grid()
        self._all = _grid()
        # Added first, so index 0 is the tab the window opens on.
        self._tabs.addTab(self._mineable, "Mineable")
        self._tabs.addTab(self._all, "All Items")
        lay.addWidget(self._tabs, 1)

        # Escape closes by Qt's own dialog convention; Ctrl+S is bound here so
        # the same key that opened the window also shuts it, matching the TUI.
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.close)

        self.set_table(table)

    def set_table(self, table: dict) -> None:
        """Replace the contents, so the window can be refreshed in place."""
        table = table or {}
        mineable = render_columns(table, mineable_only=True)
        every = render_columns(table)

        self._heading.setText(table.get("source_label") or "Galactic Average")
        _fill(self._mineable, mineable)
        _fill(self._all, every)
        # Counts live in the tab text rather than beside the heading, so each
        # tab says how much is behind it before it is opened.
        self._tabs.setTabText(0, f"Mineable ({len(mineable)})")
        self._tabs.setTabText(1, f"All Items ({len(every)})")
        self._tabs.setCurrentIndex(0)

"""
gui/block_base.py — Base class and row widgets for the Qt dashboard blocks.

Deliberately mirrors ``tui/block_base.py``.  The two front ends present the
same windows, and the blocks were ported by translating widget construction
rather than rewriting the logic that decides what to show, so this module
offers the same vocabulary the Textual blocks are written against:

    KVRow    key / value row
    SecHdr   section header
    HdrRow   section header fused with its primary value
    HRule    horizontal rule
    TextRow  free-standing line of (possibly marked-up) text

The formatters ``_fmt``, ``_fmt_credits`` and ``_health_cls`` are imported
from the TUI module when Textual is available and reimplemented identically
when it is not, so a GUI-only build on Windows or macOS needs no Textual
install while still formatting every figure the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.palette import rgb
from gui.markup import to_html
from gui.theme import classes_to_props

if TYPE_CHECKING:
    from core.core_api import CoreAPI


# ── Formatters ────────────────────────────────────────────────────────────────
# Identical to the TUI's.  Defined here rather than imported so the GUI does
# not depend on Textual being installed; the two are kept in step by their
# shared, small, and rarely-changing definition.

def _fmt_credits(n) -> str:
    if not n:
        return "—"
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B cr"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M cr"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K cr"
    return f"{v} cr"


def _fmt(n) -> str:
    if not n:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _health_cls(pct: int | None) -> str:
    if pct is None:
        return ""
    if pct > 75:
        return "health-good"
    if pct >= 25:
        return "health-warn"
    return "health-crit"


def _restyle(widget: QWidget) -> None:
    """Re-run the stylesheet against a widget after its properties change.

    Qt only re-evaluates property selectors when explicitly told to, so every
    dynamic property change has to be followed by this.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _apply_classes(label: QLabel, classes: str) -> None:
    props = classes_to_props(classes)
    label.setProperty("role", props.get("role", "val"))
    label.setProperty("health", props.get("health", ""))
    _restyle(label)


# ── Row widgets ───────────────────────────────────────────────────────────────

class RowLabel(QLabel):
    """A label that renders Rich markup and never steals the layout's width."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_map = rgb("default")
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.set_text(text)

    def set_palette_map(self, palette: dict) -> None:
        self._palette_map = palette

    def set_text(self, text: str) -> None:
        self.setText(to_html(text, self._palette_map))


class KVRow(QWidget):
    """Single key / value row: key on the left, value right-aligned."""

    def __init__(self, key: str = "", value: str = "—",
                 val_classes: str = "val", palette: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette or rgb("default")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(8)

        self._key = QLabel()
        self._key.setProperty("role", "key")
        self._key.setTextFormat(Qt.RichText)
        self._key.setWordWrap(False)
        self._key.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._val = QLabel()
        self._val.setTextFormat(Qt.RichText)
        self._val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._val.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        lay.addWidget(self._key, 1)
        lay.addWidget(self._val, 0)

        self.set_key(key)
        self.set_value(value, val_classes)

    def set_key(self, text: str) -> None:
        self._key.setText(to_html(text, self._palette))

    def set_value(self, text: str, classes: str = "val") -> None:
        self._val.setText(to_html(text, self._palette))
        _apply_classes(self._val, classes)


class SecHdr(QLabel):
    """Bold, accent-coloured section header."""

    def __init__(self, title: str = "", palette: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette or rgb("default")
        self.setProperty("role", "section")
        self.setTextFormat(Qt.RichText)
        self.setContentsMargins(6, 2, 6, 0)
        self.set_title(title)

    def set_title(self, title: str) -> None:
        # The TUI upper-cases section headers; matching that here keeps the
        # two dashboards reading identically.  Markup is left in place so a
        # header carrying colour (Colonisation's site rows) still renders.
        self.setText(to_html((title or "").upper(), self._palette))


class HdrRow(QWidget):
    """Section header fused with its primary value on one row."""

    def __init__(self, key: str = "", value: str = "",
                 palette: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette or rgb("default")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(8)

        self._key = QLabel()
        self._key.setProperty("role", "hdrkey")
        self._key.setTextFormat(Qt.RichText)
        self._val = QLabel()
        self._val.setProperty("role", "val")
        self._val.setTextFormat(Qt.RichText)
        self._val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lay.addWidget(self._key, 1)
        lay.addWidget(self._val, 0)

        self._key.setText(to_html((key or "").upper(), self._palette))
        self.set_value(value)

    def set_value(self, text: str, classes: str = "val") -> None:
        self._val.setText(to_html(text, self._palette))
        _apply_classes(self._val, classes)


class HRule(QFrame):
    """Visible horizontal rule."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "rule")
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(1)


class TextRow(RowLabel):
    """A free-standing line of text, optionally dimmed or marked up."""

    def __init__(self, text: str = "", classes: str = "",
                 palette: dict | None = None, wrap: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        if palette:
            self.set_palette_map(palette)
        self.setWordWrap(wrap)
        self.setContentsMargins(6, 0, 6, 0)
        self.set_text(text)
        _apply_classes(self, classes or "val")


# ── Scrolling body helper ─────────────────────────────────────────────────────

class RowScroll(QScrollArea):
    """A vertical scroll area that holds a stack of rows.

    ``set_rows()`` replaces the whole contents, which is how the ported blocks
    behave: they rebuild their row list on every refresh rather than diffing.
    That is cheap here — the row counts are small and refreshes are throttled
    to four a second — and it keeps the ported logic a faithful copy of the
    Textual original.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._body = QWidget()
        self._lay = QVBoxLayout(self._body)
        self._lay.setContentsMargins(0, 2, 0, 2)
        self._lay.setSpacing(0)
        self._lay.addStretch(1)
        self.setWidget(self._body)

    def clear_rows(self) -> None:
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def set_rows(self, rows: list[QWidget]) -> None:
        self.clear_rows()
        for i, w in enumerate(rows):
            self._lay.insertWidget(i, w)

    def add_row(self, w: QWidget) -> None:
        self._lay.insertWidget(self._lay.count() - 1, w)


# ── Block base ────────────────────────────────────────────────────────────────

class GuiBlock(QFrame):
    """Base class for every Qt dashboard block.

    Subclasses implement:

        _build_body(layout)  — construct the block's widgets once
        refresh_data()       — update them from ``self.core``

    which is the same contract ``TuiBlock`` defines, so a block's refresh
    logic reads the same in both trees.
    """

    BLOCK_TITLE: str = "Block"

    def __init__(self, core: "CoreAPI", theme: str = "default",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self.state = core.state
        self.theme = theme
        self.palette_map = rgb(theme)

        self.setObjectName("block")
        self.setFrameShape(QFrame.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._title = QLabel(self.BLOCK_TITLE)
        self._title.setObjectName("blockTitle")
        outer.addWidget(self._title)

        body_host = QWidget()
        self._body_layout = QVBoxLayout(body_host)
        self._body_layout.setContentsMargins(0, 2, 0, 2)
        self._body_layout.setSpacing(0)
        outer.addWidget(body_host, 1)

        self._build_body(self._body_layout)

    # ── Construction hook ─────────────────────────────────────────────────────

    def _build_body(self, layout: QVBoxLayout) -> None:
        """Build the block's static widget tree.  Override in subclasses."""

    def refresh_data(self) -> None:
        """Update displayed values.  Override in subclasses."""

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    # ── Row factories (palette pre-bound) ─────────────────────────────────────

    def kv(self, key: str, value: str = "—", classes: str = "val") -> KVRow:
        return KVRow(key, value, classes, palette=self.palette_map)

    def hdr(self, title: str) -> SecHdr:
        return SecHdr(title, palette=self.palette_map)

    def text(self, body: str, classes: str = "", wrap: bool = True) -> TextRow:
        return TextRow(body, classes, palette=self.palette_map, wrap=wrap)

    def rule(self) -> HRule:
        return HRule()

    def scroll(self) -> RowScroll:
        return RowScroll()

    # ── Convenience formatters (mirrors TuiBlock) ─────────────────────────────

    def fmt_credits(self, n) -> str:
        return _fmt_credits(n)

    def fmt_duration(self, s: float) -> str:
        from core.emit import fmt_duration
        return fmt_duration(int(s)) if s else "—"

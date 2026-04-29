"""
tui/block_base.py — Base class for all EDLD Textual dashboard blocks.

Every block:
  - Subclasses TuiBlock (a Textual Widget)
  - Receives the CoreAPI reference for data access
  - Implements refresh_data() called by the app on gui_queue events
  - Uses compose() to build its static widget tree once

Helper widgets:
  KVRow   — key/value display row with optional colour class on value
  SepRow  — horizontal separator row
  SecHdr  — bold section header
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from textual.app     import ComposeResult
from textual.widget  import Widget
from textual.widgets import Label, Static

if TYPE_CHECKING:
    from core.core_api import CoreAPI


# ── Helpers ───────────────────────────────────────────────────────────────────

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


# ── Widget helpers ────────────────────────────────────────────────────────────

class KVRow(Widget):
    """Single key / value display row. Call set_value() to update."""

    DEFAULT_CSS = "KVRow { height: 1; layout: horizontal; padding: 0 1; }"

    def __init__(self, key: str, value: str = "—",
                 val_classes: str = "val", **kw) -> None:
        super().__init__(**kw)
        self._key_text  = key
        self._val_text  = value
        self._val_cls   = val_classes

    def compose(self) -> ComposeResult:
        yield Label(self._key_text, classes="key")
        yield Label(self._val_text, id=f"val-{self.id}", classes=self._val_cls)

    def set_value(self, text: str, classes: str = "val") -> None:
        try:
            lbl = self.query_one(f"#val-{self.id}", Label)
            lbl.update(text)
            lbl.set_classes(classes)
        except Exception:
            pass

    def set_key(self, text: str) -> None:
        try:
            self.query_one(".key", Label).update(text)
        except Exception:
            pass


class SepRow(Static):
    """Thin separator line."""
    DEFAULT_CSS = "SepRow { height: 0; padding: 0; }"

    def __init__(self, **kw) -> None:
        super().__init__("─" * 40, classes="sep", **kw)


class SecHdr(Static):
    """Bold section header label."""
    DEFAULT_CSS = "SecHdr { height: 1; padding: 0 1; margin-top: 0; }"

    def __init__(self, title: str, **kw) -> None:
        super().__init__(title.upper(), classes="section-hdr", **kw)


class HdrRow(Widget):
    """Section header fused with its primary value on one row.

    The key is rendered in accent colour (bold) on the left.
    The value is right-aligned on the right — identical to KVRow but with
    an accent-styled key.  Eliminates the blank row that SecHdr + KVRow
    would otherwise consume.
    """

    DEFAULT_CSS = "HdrRow { height: 1; layout: horizontal; padding: 0 1; }"

    def __init__(self, key: str, value: str = "", **kw) -> None:
        super().__init__(**kw)
        self._key_text = key.upper()
        self._val_text = value

    def compose(self) -> ComposeResult:
        yield Label(self._key_text, classes="hdr-key")
        yield Label(self._val_text, id=f"hdrval-{self.id}", classes="val")

    def set_value(self, text: str, classes: str = "val") -> None:
        try:
            lbl = self.query_one(f"#hdrval-{self.id}", Label)
            lbl.update(text)
            lbl.set_classes(classes)
        except Exception:
            pass


# ── TuiBlock base ─────────────────────────────────────────────────────────────

class TuiBlock(Widget):
    """
    Base class for all EDLD TUI blocks.

    Subclasses must implement:
      _compose_body() → ComposeResult  — yields body widgets
      refresh_data()                   — updates content from core

    The block title is rendered as a .block-title label automatically.
    """

    BLOCK_TITLE: str = "Block"

    def __init__(self, core: "CoreAPI", **kw) -> None:
        super().__init__(**kw)
        self.core  = core
        self.state = core.state

    def compose(self) -> ComposeResult:
        yield Label(self.BLOCK_TITLE, classes="block-title")
        yield from self._compose_body()

    def _compose_body(self) -> ComposeResult:
        return
        yield  # make it a generator

    def refresh_data(self) -> None:
        """Override to update displayed values. Called on each relevant queue event."""
        pass

    # ── Convenience formatters (delegates to core) ────────────────────────────

    def fmt_credits(self, n) -> str:
        return _fmt_credits(n)

    def fmt_duration(self, s: float) -> str:
        from core.emit import fmt_duration
        return fmt_duration(int(s)) if s else "—"

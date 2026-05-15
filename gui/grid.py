"""
gui/grid.py — 32-column snap grid layout engine for the EDLD dashboard.

Manages block positions in grid units, handles persistence to layout.json,
and provides the GTK Fixed container that blocks are placed into.

Grid model
──────────
  Columns    32  — each = 1/32 of the available canvas width
  Row height ROW_PX pixels each (default 10px)
  Gap        GAP px between all blocks (default 2px)
  Min block  3 wide × 1 tall
  Layout     persisted to ~/.local/share/EDLD/<cmdr>/layout.json

Layout file versioning
──────────────────────
  The layout file carries a "version" key.  When the grid constants change
  (column count, row height) the persisted col/row/width/height values would
  no longer produce the intended pixel geometry, so on a version mismatch
  the file is discarded and the built-in DEFAULT_LAYOUT is applied and saved.
  Current layout version: 2  (introduced with 32-col / 10px-row grid).
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from core.state import EDLD_DATA_DIR, cmdr_data_dir


def _layout_file() -> Path:
    """Per-commander layout file path (evaluated lazily after FID is set)."""
    return cmdr_data_dir() / "layout.json"


LAYOUT_VERSION = 2          # increment when COLS or ROW_PX change
COLS     = 32
ROW_PX   = 10
GAP      = 2
MIN_W    = 3
MIN_H    = 1

# Default block layout — adopted from the user-provided layout.json.
# Four columns: col 0 (w=11), col 11 (w=10), col 21 (w=11).  The
# session_stats and ksw blocks from that file are intentionally omitted —
# the standalone Session Stats block was removed (its content folded into
# Career's Summary tab) and the kill-switch UI now lives in the Alerts
# block footer, so neither has a grid cell any more.  If a user's saved
# layout still references them, the layout engine simply ignores the
# unknown names.
DEFAULT_LAYOUT = {
    "assets":       {"col": 0,  "row": 0,   "width": 11, "height": 43},
    "engineering":  {"col": 0,  "row": 43,  "width": 11, "height": 35},
    "colonisation": {"col": 0,  "row": 78,  "width": 11, "height": 23},
    "commander":    {"col": 11, "row": 0,   "width": 10, "height": 32},
    "crew_slf":     {"col": 11, "row": 32,  "width": 10, "height": 18},
    "alerts":       {"col": 11, "row": 50,  "width": 10, "height": 16},
    "cargo":        {"col": 11, "row": 66,  "width": 10, "height": 35},
    "missions":     {"col": 21, "row": 0,   "width": 11, "height": 28},
    "navigation":   {"col": 21, "row": 28,  "width": 11, "height": 33},
    "career":       {"col": 21, "row": 61,  "width": 11, "height": 40},
}


@dataclass
class GridCell:
    col:    int
    row:    int
    width:  int
    height: int


class BlockGrid:
    """
    Manages the dashboard grid layout.

    Usage:
        grid = BlockGrid(canvas_width=1280)
        cell = grid.cell_for("commander")         # GridCell
        x, y, w, h = grid.pixel_rect(cell)        # pixel coords for placement
        grid.move_block("commander", col=4, row=0) # update position
        grid.save()                                # persist to disk
    """

    def __init__(self, canvas_width: int = 1280, canvas_height: int = 760):
        self._canvas_width  = canvas_width
        self._canvas_height = canvas_height
        self._cells: dict[str, GridCell] = {}
        self._load()

    # ── Layout persistence ────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load layout from disk, falling back to defaults.

        Version check: if the saved file carries a version < LAYOUT_VERSION
        (or no version at all), the constants have changed and the stored
        grid-unit values would produce the wrong pixel geometry.  In that
        case we discard the file and apply DEFAULT_LAYOUT so the dashboard
        looks correct immediately; the new layout is then saved so future
        launches load cleanly.

        After loading, any block present in DEFAULT_LAYOUT but absent from
        the saved file (e.g. a newly introduced block) is inserted at its
        default position and the file is re-saved.
        """
        try:
            data   = json.loads(_layout_file().read_text(encoding="utf-8"))
            if int(data.get("version", 1)) < LAYOUT_VERSION:
                # Grid constants changed — old unit values are invalid.
                raise ValueError("stale layout version")
            blocks = data.get("blocks", {})
            for name, d in blocks.items():
                self._cells[name] = GridCell(
                    col=int(d["col"]),
                    row=int(d["row"]),
                    width=max(MIN_W, int(d["width"])),
                    height=max(MIN_H, int(d["height"])),
                )
            # Backfill any blocks that exist in DEFAULT_LAYOUT but are missing
            # from the saved file — happens when a new block is introduced.
            added = False
            for name, d in DEFAULT_LAYOUT.items():
                if name not in self._cells:
                    self._cells[name] = GridCell(**d)
                    added = True
            if added:
                self.save()
        except Exception:
            self._apply_defaults()

    def _apply_defaults(self) -> None:
        for name, d in DEFAULT_LAYOUT.items():
            self._cells[name] = GridCell(**d)

    def save(self) -> None:
        """Persist current layout to disk."""
        try:
            _layout_file().parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": LAYOUT_VERSION,
                "blocks":  {n: asdict(c) for n, c in self._cells.items()},
            }
            _layout_file().write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except OSError:
            pass   # non-fatal

    def reset(self) -> None:
        """Reset all blocks to default positions and save."""
        self._cells.clear()
        self._apply_defaults()
        self.save()

    # ── Cell access ───────────────────────────────────────────────────────────

    def register_plugin_default(
        self,
        name: str,
        col: int,
        row: int,
        width: int,
        height: int,
    ) -> None:
        """Register a default position for a plugin block.

        Called by the window during block construction when the block class
        declares DEFAULT_COL / DEFAULT_ROW / DEFAULT_WIDTH / DEFAULT_HEIGHT.
        Only takes effect when there is no saved layout entry for this block.
        Has no effect after a layout entry already exists.
        """
        if name not in self._cells:
            self._cells[name] = GridCell(
                col=max(0, col),
                row=max(0, row),
                width=max(MIN_W, width),
                height=max(MIN_H, height),
            )

    def cell_for(self, name: str) -> GridCell:
        """Return the GridCell for a block, using defaults if unknown."""
        if name not in self._cells:
            d = DEFAULT_LAYOUT.get(name)
            if d:
                self._cells[name] = GridCell(**d)
            else:
                self._cells[name] = GridCell(col=0, row=0, width=MIN_W, height=MIN_H)
        return self._cells[name]

    def move_block(self, name: str, col: int, row: int) -> None:
        c = self.cell_for(name)
        c.col = max(0, min(col, COLS - c.width))
        c.row = max(0, row)

    def resize_block(self, name: str, width: int, height: int) -> None:
        c = self.cell_for(name)
        c.width  = max(MIN_W, min(width, COLS - c.col))
        c.height = max(MIN_H, height)

    # ── Pixel geometry ────────────────────────────────────────────────────────

    def col_width(self) -> float:
        """Width of one column unit in pixels."""
        return (self._canvas_width - GAP) / COLS

    def row_height(self) -> float:
        """Height of one row unit in pixels.

        Always returns ROW_PX — layout is fixed during normal runtime.
        Vertical overflow is handled by the dashboard ScrolledWindow, not by
        scaling blocks down.  Proportional scaling caused GTK4 to invalidate
        the entire scene graph on every window-height change, draining the
        compositor.
        """
        return float(ROW_PX)

    def _natural_row_extent(self) -> int:
        """Total rows spanned by the current layout (max row + height)."""
        if not self._cells:
            return 48   # fallback (≈ old 24 at double density)
        return max(c.row + c.height for c in self._cells.values())

    def pixel_rect(self, cell: GridCell) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) in pixels for a GridCell."""
        cw = self.col_width()
        rh = self.row_height()
        x  = int(cell.col * cw + GAP)
        y  = int(cell.row * rh + GAP)
        w  = int(cell.width  * cw - GAP)
        h  = int(cell.height * rh - GAP)
        return x, y, w, h

    def snap_to_col(self, px: float) -> int:
        """Snap a pixel x-coordinate to the nearest column index."""
        cw = self.col_width()
        col = round((px - GAP) / cw)
        return max(0, min(col, COLS - 1))

    def snap_to_row(self, py: float) -> int:
        """Snap a pixel y-coordinate to the nearest row index."""
        rh = self.row_height()
        row = round((py - GAP) / rh)
        return max(0, row)

    def update_canvas_width(self, width: int) -> None:
        """Call when the window width changes."""
        self._canvas_width = max(1, width)

    def update_canvas_height(self, height: int) -> None:
        """Call when the window height changes."""
        self._canvas_height = max(1, height)

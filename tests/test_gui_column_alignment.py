"""
tests/test_gui_column_alignment.py — the GUI must lay columns out like the TUI.

The shared helpers in core.ui_helpers align columns by padding with spaces.
Every label in the Qt window is ``Qt.RichText``, and Qt collapses runs of
spaces exactly as a browser does, so that padding was being squeezed to a
single space on its way to the screen: the cargo manifest's separators did
not line up with each other, and the totals row rendered its empty price
column as ``| |``.

The fault was invisible from either side on its own.  The strings are built
by shared code and are identical in both front ends, so comparing them proves
nothing; only what Qt lays out shows it.  These tests therefore round-trip
each string through a real QLabel and back.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def as_rendered(html: str) -> str:
    """What Qt will actually draw, with non-breaking spaces read back as spaces."""
    from PySide6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setHtml(html)
    return doc.toPlainText().replace("\u00a0", " ")


# ── The manifest columns ──────────────────────────────────────────────────────

CARGO = [
    ("Tritium", 120, 57_000, 6_840_000),
    ("Low Temp. Diamonds", 127, 291_000, 37_000_000),
    ("Thortveitite", 79, 484_000, 38_200_000),
]


def _rows(qapp):
    from core.palette import rgb
    from core.ui_helpers import cargo_cols, cargo_totals_cols
    from gui.block_base import KVRow

    pal = rgb("default")
    built = [(name, cargo_cols(count, price, line))
             for name, count, price, line in CARGO]
    built.append(("Totals", cargo_totals_cols("326/1024 t", 82_000_000)))

    out = []
    for name, value in built:
        row = KVRow(name, value, palette=pal)
        out.append((name, value, as_rendered(row._val.text())))
    return out


def test_the_gui_renders_the_columns_it_was_given(qapp):
    for name, built, rendered in _rows(qapp):
        assert rendered == built, (
            f"{name}: built {built!r} but Qt lays out {rendered!r}")


def test_the_separators_line_up_down_the_manifest(qapp):
    """The point of the padding.  Ragged separators are what this looked like
    on screen, and the strings themselves were never wrong."""
    positions = {name: [i for i, ch in enumerate(rendered) if ch == "|"]
                 for name, _built, rendered in _rows(qapp)}
    distinct = {tuple(p) for p in positions.values()}
    assert len(distinct) == 1, f"separators land in different columns: {positions}"


def test_the_totals_row_keeps_its_empty_price_column(qapp):
    """A totals line carries no price per unit, but the column still has to
    occupy its width or the row stops lining up with what it totals.  This
    rendered as '| |' before."""
    name, built, rendered = _rows(qapp)[-1]
    assert name == "Totals"
    assert "| |" not in rendered
    assert "|           |" in rendered


# ── The rule that makes it work ───────────────────────────────────────────────

def test_alignment_padding_is_protected(qapp):
    from core.palette import rgb
    from gui.markup import to_html
    pal = rgb("default")
    assert to_html("  two leading", pal).startswith("&nbsp;&nbsp;")
    assert "&nbsp;" in to_html("a    b", pal)
    assert as_rendered(to_html(" one leading", pal)) == " one leading"


def test_single_spaces_stay_breakable(qapp):
    """Protecting every space would stop wrapped labels wrapping, which
    matters for the prose rows elsewhere in the window."""
    from core.palette import rgb
    from gui.markup import to_html
    sentence = "a long sentence that should still wrap between its words"
    assert "&nbsp;" not in to_html(sentence, rgb("default"))


def test_padding_survives_alongside_markup(qapp):
    """Padded values are often coloured too, and the tag walker must not skip
    the protection on the text between the tags."""
    from core.palette import rgb
    from gui.markup import to_html
    out = to_html("[green]     42 t[/green] |     7 cr", rgb("default"))
    assert as_rendered(out) == "     42 t |     7 cr"


def test_escaping_still_happens(qapp):
    """Whitespace protection runs on already-escaped text; a station name
    with an angle bracket must not become markup."""
    from core.palette import rgb
    from gui.markup import to_html
    out = to_html("  <b>not bold</b>", rgb("default"))
    assert "<b>" not in out
    assert as_rendered(out).strip() == "<b>not bold</b>"


# ── The panel itself ──────────────────────────────────────────────────────────

def test_the_real_cargo_panel_lines_its_columns_up(qapp):
    """End to end through the actual block, not just the helpers."""
    import queue

    from core.state import MonitorState
    from gui.block_base import KVRow
    from gui.blocks.ship_info import ShipInfoBlock
    from gui.theme import stylesheet

    state = MonitorState()
    state.cargo_capacity = 1024
    state.cargo_items = {
        "tritium": {"name": "Tritium", "count": 120},
        "lowtemperaturediamond": {"name": "Low Temp. Diamonds", "count": 127},
        "thortveitite": {"name": "Thortveitite", "count": 79},
    }
    state.cargo_market_info = {
        "station_name": "Pausch City", "star_system": "Emerald",
        "commodities": {
            "tritium": {"name_local": "Tritium",
                        "sell_price": 57_000, "mean_price": 57_000},
            "lowtemperaturediamond": {"name_local": "Low Temp. Diamonds",
                                      "sell_price": 291_000,
                                      "mean_price": 291_000},
            "thortveitite": {"name_local": "Thortveitite",
                             "sell_price": 484_000, "mean_price": 484_000},
        },
    }

    class _Core:
        gui_queue = queue.Queue()
        _plugins: dict = {}
        journal_dir = "/tmp"
        def plugin_call(self, *a, **k):
            return None
        def register_block(self, *a, **k):
            pass
    _Core.state = state

    block = ShipInfoBlock(_Core(), "default")
    block.setStyleSheet(stylesheet("default"))
    block.resize(650, 320)
    block.show()
    block.refresh_data()
    qapp.processEvents()

    seps = []
    for row in block._cargo_scroll.findChildren(KVRow):
        rendered = as_rendered(row._val.text())
        if "|" in rendered:
            seps.append((as_rendered(row._key.text()),
                         tuple(i for i, ch in enumerate(rendered) if ch == "|")))
    assert len(seps) >= 4, f"expected a manifest and a totals row, got {seps}"
    assert len({s for _name, s in seps}) == 1, \
        f"separators land in different columns: {seps}"


# ── The font a coloured value wears ───────────────────────────────────────────
#
# classes_to_props turns "val dim" and "val highlight" into role="dim" and
# role="highlight", each of which carries a colour and nothing else.  Only
# role="val" named the monospace family, so a value marked either way silently
# fell back to the proportional face and stopped lining up with the values
# above and below it.  The cargo manifest's column headings were the visible
# case — proportional headings sitting over monospace figures — but every
# dimmed or highlighted value column in the window had the same fault.

VALUE_CLASSES = ["val", "val dim", "val highlight",
                 "val health-good", "val health-warn", "val health-crit"]


@pytest.mark.parametrize("classes", VALUE_CLASSES)
def test_a_value_column_is_monospace_whatever_colour_it_wears(qapp, classes):
    from PySide6.QtGui import QFontMetricsF
    from PySide6.QtWidgets import QWidget

    from core.palette import rgb
    from gui.block_base import KVRow
    from gui.theme import stylesheet

    host = QWidget()
    host.setStyleSheet(stylesheet("default"))
    row = KVRow("Commodity", "  1,234 cr", classes,
                palette=rgb("default"), parent=host)
    host.show()
    qapp.processEvents()

    metrics = QFontMetricsF(row._val.font())
    widths = {round(metrics.horizontalAdvance(ch), 3) for ch in "iW1 ."}
    assert len(widths) == 1, (
        f"{classes!r} renders in {row._val.font().family()!r}, which is not "
        f"fixed pitch: character widths {sorted(widths)}")


def test_all_value_colours_share_one_character_width(qapp):
    """Not just individually fixed-pitch — the same face, or a dim heading
    still would not sit over the row beneath it."""
    from PySide6.QtGui import QFontMetricsF
    from PySide6.QtWidgets import QWidget

    from core.palette import rgb
    from gui.block_base import KVRow
    from gui.theme import stylesheet

    host = QWidget()
    host.setStyleSheet(stylesheet("default"))
    rows = [KVRow("k", "1,234 cr", c, palette=rgb("default"), parent=host)
            for c in VALUE_CLASSES]
    host.show()
    qapp.processEvents()

    advances = {round(QFontMetricsF(r._val.font()).horizontalAdvance("0"), 3)
                for r in rows}
    assert len(advances) == 1, f"value columns disagree on width: {advances}"


def test_the_headings_land_over_their_columns_in_pixels(qapp):
    """The end of the whole chain: same string widths, same face, same right
    edge.  Asserted in laid-out pixels because that is the only place the
    fault ever showed."""
    import queue

    from PySide6.QtGui import QFontMetricsF, QTextDocument

    from core.state import MonitorState
    from gui.block_base import KVRow
    from gui.blocks.ship_info import ShipInfoBlock
    from gui.theme import stylesheet

    state = MonitorState()
    state.cargo_capacity = 1024
    state.cargo_items = {"monazite": {"name": "Monazite", "count": 382}}
    state.cargo_market_info = {
        "station_name": "Pausch City", "star_system": "Eme",
        "commodities": {"monazite": {"name_local": "Monazite",
                                     "sell_price": 763_000,
                                     "mean_price": 763_000}},
    }

    class _Core:
        gui_queue = queue.Queue()
        _plugins: dict = {}
        journal_dir = "/tmp"
        def plugin_call(self, *a, **k):
            return None
        def register_block(self, *a, **k):
            pass
    _Core.state = state

    block = ShipInfoBlock(_Core(), "default")
    block.setStyleSheet(stylesheet("default"))
    block.resize(650, 320)
    block.show()
    block.refresh_data()
    qapp.processEvents()

    def right_edges(row):
        doc = QTextDocument()
        doc.setHtml(row._val.text())
        raw = doc.toPlainText()
        metrics = QFontMetricsF(row._val.font())
        left = row._val.mapTo(block, row._val.rect().topLeft()).x()
        plain = raw.replace("\u00a0", " ")
        # Each column ends where its last non-space character does.
        edges, cursor = [], 0
        for width in (10, 13, 12):          # qty, " | " + price, " | " + value
            chunk = plain[cursor:cursor + width]
            end = cursor + len(chunk.rstrip())
            edges.append(round(left + metrics.horizontalAdvance(raw[:end]), 1))
            cursor += width
        return edges

    rows = [r for r in block._cargo_scroll.findChildren(KVRow) if r._val.text()]
    assert len(rows) >= 3, "expected a heading, a commodity and a totals row"

    heading, commodity = rows[0], rows[1]
    assert heading._val.property("role") == "dim", \
        "the heading is no longer the dimmed case this guards"
    assert right_edges(heading) == right_edges(commodity), (
        f"headings {right_edges(heading)} do not sit over the row "
        f"{right_edges(commodity)}")

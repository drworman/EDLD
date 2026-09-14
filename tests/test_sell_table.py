"""
tests/test_sell_table.py — the sell table must quote the market it names.

The table appears in four places — a Markdown file, an HTML file, and a popup
in each front end — all built from one dict.  What has to hold is that the
heading and the prices under it always describe the same market, that a
carrier never becomes that market, and that the ordering is the one the table
exists to provide.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.sell_table import (  # noqa: E402
    GALACTIC_LABEL,
    mineable_rows,
    is_carrier,
    render_columns,
    render_html,
    render_markdown,
    sell_table,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

class FakeState:
    """Only the fields cargo_price_context() and sell_table() actually read."""

    def __init__(self, **kw):
        self.cargo_market_info = kw.get("market", {}) or {}
        self.cargo_target_market = kw.get("target", {}) or {}
        self.cargo_target_market_name = kw.get("target_name", "")
        self.cargo_mean_prices = kw.get("mean_prices", {}) or {}
        self.cargo_price_galactic = kw.get("pinned", False)


def market(station, system, comms, station_type=""):
    return {
        "station_name": station,
        "star_system": system,
        "station_type": station_type,
        "commodities": comms,
    }


def comm(local, sell):
    return {"name_local": local, "sell_price": sell, "mean_price": 0}


LEDGER = {
    "gold":     {"name_localised": "Gold",     "mean_price": 47113},
    "platinum": {"name_localised": "Platinum", "mean_price": 55505},
    "silver":   {"name_localised": "Silver",   "mean_price": 36553},
    # No galactic average anywhere — carrier-only, as the real Titan Maw
    # samples are.  Frontier's internal symbol for these bears no relation
    # to the display name, which is why the match is on the latter.
    "thargoidtissuesampletype10a": {
        "name_localised": "Titan Maw Deep Tissue Sample", "mean_price": 0},
}


# ── Carrier detection ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("station_type", [
    "FleetCarrier",          # Frontier, Market.json
    "fleetcarrier",
    "SquadronCarrier",       # the spelling this has to survive unverified
    "Drake-Class Carrier",   # Spansh
])
def test_every_spelling_of_carrier_is_a_carrier(station_type):
    assert is_carrier(station_type)


@pytest.mark.parametrize("station_type", [
    "Coriolis", "Outpost", "Orbis", "Ocellus", "AsteroidBase",
    "MegaShip", "SurfaceStation", "CraterPort", "OnFootSettlement", "", None,
])
def test_ordinary_stations_are_not_carriers(station_type):
    assert not is_carrier(station_type)


# ── Which market gets quoted ──────────────────────────────────────────────────

def test_nothing_docked_quotes_the_galactic_average():
    t = sell_table(FakeState(), LEDGER)
    assert t["mode"] == "galactic"
    assert t["source_label"] == GALACTIC_LABEL
    assert [r["name"] for r in t["rows"]] == ["Platinum", "Gold", "Silver"]


def test_a_docked_station_quotes_its_own_prices():
    st = FakeState(market=market("Al Saud Ring", "Borfor", {
        "gold": comm("Gold", 67390),
        "silver": comm("Silver", 4000),
    }))
    t = sell_table(st, LEDGER)
    assert t["mode"] == "station"
    assert "Al Saud Ring" in t["source_label"]
    assert [(r["name"], r["price"]) for r in t["rows"]] == [
        ("Gold", 67390), ("Silver", 4000)]


def test_a_target_market_outranks_the_station_underfoot():
    st = FakeState(
        market=market("Al Saud Ring", "Borfor", {"gold": comm("Gold", 67390)}),
        target=market("Jameson Memorial", "Shinrarta Dezhra",
                      {"gold": comm("Gold", 99999)}, station_type="Orbis"),
        target_name="Jameson Memorial | Shinrarta Dezhra",
    )
    t = sell_table(st, LEDGER)
    assert t["mode"] == "target"
    assert "Jameson Memorial" in t["source_label"]
    assert t["rows"][0]["price"] == 99999


def test_pinning_to_galactic_overrides_a_loaded_station():
    st = FakeState(market=market("Al Saud Ring", "Borfor",
                                 {"gold": comm("Gold", 67390)}),
                   pinned=True)
    t = sell_table(st, LEDGER)
    assert t["mode"] == "galactic"
    assert t["source_label"] == GALACTIC_LABEL


# ── Carriers are ignored ──────────────────────────────────────────────────────

def test_a_carrier_target_is_never_quoted():
    """Carrier markets are player-run and mobile; the table declines them and
    falls back rather than presenting a price that may already be gone."""
    st = FakeState(target=market("VECTURA", "Borfor",
                                 {"gold": comm("Gold", 1)},
                                 station_type="Drake-Class Carrier"),
                   target_name="VECTURA | Borfor")
    t = sell_table(st, LEDGER)
    assert t["mode"] == "galactic"
    assert t["rows"][0]["price"] == 55505


def test_an_empty_market_falls_through_to_galactic():
    """Docking at a carrier leaves cargo_market_info empty — the Market.json
    reader declines to record one — and an empty market is not a quote."""
    t = sell_table(FakeState(market=market("", "", {})), LEDGER)
    assert t["mode"] == "galactic"


# ── Ordering and content ──────────────────────────────────────────────────────

def test_rows_run_from_the_most_valuable_down():
    st = FakeState(market=market("X", "Y", {
        "a": comm("Alpha", 100), "b": comm("Bravo", 900),
        "c": comm("Charlie", 500),
    }))
    prices = [r["price"] for r in sell_table(st, LEDGER)["rows"]]
    assert prices == sorted(prices, reverse=True)


def test_ties_are_broken_by_name_so_the_file_does_not_churn():
    st = FakeState(market=market("X", "Y", {
        "b": comm("Bravo", 500), "a": comm("Alpha", 500),
    }))
    assert [r["name"] for r in sell_table(st, LEDGER)["rows"]] == ["Alpha", "Bravo"]


def test_a_commodity_with_no_price_is_left_out():
    """A zero answers no question this table is asked."""
    t = sell_table(FakeState(), LEDGER)
    assert "Titan Maw Deep Tissue Sample" not in [r["name"] for r in t["rows"]]


# ── NPC prices only ───────────────────────────────────────────────────────────

def test_a_station_price_no_npc_will_pay_is_left_out():
    """Stations quote a sell price for carrier-only goods and no NPC will
    honour it.  The real Titan Maw Deep Tissue Sample lists at 476,614 cr and
    would otherwise head the table at almost every station in the bubble."""
    st = FakeState(market=market("Al Saud Ring", "Borfor", {
        "thargoidtissuesampletype10a": comm("Titan Maw Deep Tissue Sample",
                                            476614),
        "gold": comm("Gold", 67390),
    }))
    rows = sell_table(st, LEDGER)["rows"]
    assert [r["name"] for r in rows] == ["Gold"]


def test_the_exclusion_matches_on_display_name_not_internal_symbol():
    """Frontier calls it thargoidtissuesampletype10a and Spansh does not;
    the display name is the only thing both sources agree on."""
    st = FakeState(target=market("Jameson Memorial", "Shinrarta Dezhra", {
        # Spansh's own key shape: display name, lowercased, spaces removed.
        "titanmawdeeptissuesample": comm("Titan Maw Deep Tissue Sample",
                                         476614),
        "gold": comm("Gold", 99999),
    }, station_type="Orbis"), target_name="Jameson Memorial | Shinrarta")
    assert [r["name"] for r in sell_table(st, LEDGER)["rows"]] == ["Gold"]


def test_a_commodity_with_a_real_average_is_kept_however_odd():
    """Only the absence of an average excludes.  Titan Deep Tissue Sample has
    one and sells to NPCs, and no rule here may confuse the two."""
    ledger = dict(LEDGER)
    ledger["titandeep"] = {"name_localised": "Titan Deep Tissue Sample",
                           "mean_price": 498523}
    st = FakeState(market=market("X", "Y", {
        "titandeep": comm("Titan Deep Tissue Sample", 391203),
    }))
    assert [r["name"] for r in sell_table(st, ledger)["rows"]] == \
        ["Titan Deep Tissue Sample"]


def test_demand_is_not_what_decides():
    """A station with no current demand still pays; only the absence of an
    NPC price at all excludes.  The market dict carries no demand figure
    precisely because it is not consulted."""
    st = FakeState(market=market("X", "Y", {"gold": comm("Gold", 67390)}))
    assert len(sell_table(st, LEDGER)["rows"]) == 1


def test_an_empty_catalogue_excludes_nothing():
    """The exclusions are learned, so before anything is catalogued the table
    guesses at nothing and shows what the market says."""
    st = FakeState(market=market("X", "Y", {
        "thargoidtissuesampletype10a": comm("Titan Maw Deep Tissue Sample",
                                            476614),
    }))
    assert len(sell_table(st, {})["rows"]) == 1


def test_rows_carry_only_what_the_table_shows():
    t = sell_table(FakeState(), LEDGER)
    assert all(set(r) == {"name", "price", "mineable"} for r in t["rows"])


# ── Renderers ─────────────────────────────────────────────────────────────────

def test_markdown_heads_with_the_market_and_tables_the_rest():
    md = render_markdown(sell_table(FakeState(), LEDGER))
    assert md.startswith(f"# {GALACTIC_LABEL}\n")
    assert "| Commodity | Sell |" in md
    assert "| Platinum | 55,505 cr |" in md
    # Two columns and no more, on every row.
    for line in md.splitlines():
        if line.startswith("|"):
            assert line.count("|") == 3


def test_markdown_names_the_station_when_one_is_quoted():
    st = FakeState(market=market("Al Saud Ring", "Borfor",
                                 {"gold": comm("Gold", 67390)}))
    assert render_markdown(sell_table(st, LEDGER)).startswith("# Al Saud Ring")


def test_markdown_escapes_a_name_that_would_break_the_table():
    t = {"source_label": "X", "rows": [{"name": "Odd | Name", "price": 5}]}
    row = [l for l in render_markdown(t).splitlines() if "Odd" in l][0]
    assert "\\|" in row, "the name's own pipe is not escaped"
    # Three unescaped pipes: the two edges and the one column separator.
    assert len(re.findall(r"(?<!\\)\|", row)) == 3


def test_html_is_a_standalone_document_carrying_the_same_rows():
    html = render_html(sell_table(FakeState(), LEDGER))
    assert html.startswith("<!doctype html>")
    assert "</html>" in html
    assert f"<h1>{GALACTIC_LABEL}</h1>" in html
    assert "<td>Platinum</td>" in html
    assert "55,505 cr" in html
    assert len(re.findall(r"<tr><td>", html)) == 3


def test_html_escapes_markup_in_a_commodity_name():
    t = {"source_label": "<b>x</b>", "rows": [{"name": "<script>", "price": 1}]}
    html = render_html(t)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>x</b>" not in html


def test_an_empty_table_still_renders_both_formats():
    empty = {"source_label": GALACTIC_LABEL, "rows": []}
    assert GALACTIC_LABEL in render_markdown(empty)
    assert "No prices available." in render_html(empty)
    assert render_columns(empty) == []


def test_all_three_surfaces_agree_on_the_same_table():
    """The popups and the files are rendered from one dict; a divergence here
    means a commander comparing them sees two different answers."""
    st = FakeState(market=market("Al Saud Ring", "Borfor", {
        "gold": comm("Gold", 67390), "silver": comm("Silver", 4000),
    }))
    t = sell_table(st, LEDGER)
    md, html, cols = render_markdown(t), render_html(t), render_columns(t)
    assert [c[0] for c in cols] == [r["name"] for r in t["rows"]]
    for name, price in cols:
        assert f"| {name} | {price} |" in md
        assert f"<td>{name}</td>" in html
        assert price in html


# ── The popups render it ──────────────────────────────────────────────────────

TABLE = {
    "mode": "station",
    "source_label": "Al Saud Ring · Borfor",
    "rows": [
        {"name": "Iridium", "price": 542736, "mineable": False},
        {"name": "Rhodplumsite", "price": 444758, "mineable": True},
        {"name": "Low Temp. Diamonds", "price": 350291, "mineable": True},
    ],
}
MINEABLE_IN_TABLE = ["Rhodplumsite", "Low Temp. Diamonds"]


def _render_modal(table, size=(70, 24), press=()):
    """Boot the modal inside a real Textual app against the real stylesheet.

    Rendered rather than queried, because a widget existing in the DOM is
    exactly what let an off-screen layout survive review once already.
    """
    import asyncio

    from textual.app import App

    from tui.sell_modal import SellModal
    from tui.theme import build_css

    out = {}

    class _Host(App):
        CSS = build_css("default")

    async def _run():
        app = _Host()
        async with app.run_test(size=size) as pilot:
            await app.push_screen(SellModal(table))
            await pilot.pause()
            for key in press:
                await pilot.press(key)
                await pilot.pause()
            out["lines"] = ["".join(seg.text for seg in strip).rstrip()
                            for strip in app.screen._compositor.render_strips()]
            out["stack"] = list(app.screen_stack)
            # Query the modal screen, not the app: app.query() searches the
            # default screen and would quietly find nothing here.
            # Scoped to the visible pane: both tabs are composed, so an
            # app-wide query would mix the mineable rows in with the rest and
            # the alignment assertions below would compare across panes.
            pane = app.screen.query_one("#sell-rows-mineable")
            out["regions"] = {
                cls: [w.region for w in pane.query(f".{cls}")]
                for cls in ("sell-name", "sell-price")
            }
            out["tabs"] = [str(t.label) for t in app.screen.query("Tab")]
            out["active"] = app.screen.query_one("#sell-tabs").active
            out["width"] = app.screen.size.width
    asyncio.run(_run())
    return out


def test_the_tui_popup_draws_the_heading_and_the_mineable_rows():
    out = _render_modal(TABLE)
    screen = "\n".join(out["lines"])
    assert "Al Saud Ring" in screen
    for name in MINEABLE_IN_TABLE:
        assert name in screen
    assert "444,758 cr" in screen


def test_the_tui_popup_opens_on_mineable_not_on_everything():
    """The default tab is the whole point: arriving with a hold of ore, the
    answer wanted is about ore, not about the 300 things not being carried."""
    out = _render_modal(TABLE)
    assert out["active"] == "sell-tab-mineable"
    # Iridium is the most valuable thing in the market and cannot be mined,
    # so its absence from the opening screen is the assertion that matters.
    assert "Iridium" not in "\n".join(out["lines"])


def test_the_tui_tabs_are_named_and_counted():
    tabs = _render_modal(TABLE)["tabs"]
    assert tabs == ["Mineable (2)", "All Items (3)"]


def test_switching_to_all_items_shows_what_mineable_hid():
    out = _render_modal(TABLE, press=["right"])
    assert out["active"] == "sell-tab-all"
    assert "Iridium" in "\n".join(out["lines"])


def test_no_tui_price_is_laid_out_off_screen():
    """Every price cell has to land inside the modal, not past its edge."""
    out = _render_modal(TABLE)
    assert out["regions"]["sell-price"], "no price cells were laid out at all"
    for region in out["regions"]["sell-price"]:
        assert region.right <= out["width"], (
            f"price cell ends at x={region.right}, screen is {out['width']}")
        assert region.width > 0


def test_the_tui_price_column_is_aligned():
    """All prices share one right edge — a ragged column is unreadable at a
    glance, which is the only thing this popup is for."""
    rights = {r.right for r in _render_modal(TABLE)["regions"]["sell-price"]}
    assert len(rights) == 1, f"price column is ragged: {sorted(rights)}"


def test_the_tui_popup_says_how_to_close_itself():
    assert "Ctrl+S" in "\n".join(_render_modal(TABLE)["lines"])


def test_an_empty_tui_popup_explains_itself_rather_than_showing_nothing():
    screen = "\n".join(_render_modal(
        {"source_label": GALACTIC_LABEL, "rows": []})["lines"])
    assert GALACTIC_LABEL in screen
    assert "No mineable goods bought here." in screen


def test_a_market_with_no_ore_says_so_rather_than_looking_broken():
    """An empty Mineable tab beside a full All Items tab is a real answer —
    this market buys no ore — and must not read as a failure to load."""
    ore_free = {"source_label": "X", "rows": [
        {"name": "Beer", "price": 500, "mineable": False}]}
    out = _render_modal(ore_free)
    screen = "\n".join(out["lines"])
    assert "No mineable goods bought here." in screen
    assert out["tabs"] == ["Mineable (0)", "All Items (1)"]


def test_the_tui_modal_closes_on_both_of_its_keys():
    import asyncio

    from textual.app import App

    from tui.sell_modal import SellModal
    from tui.theme import build_css

    depths = {}

    class _Host(App):
        CSS = build_css("default")

    async def _run():
        for key in ("escape", "ctrl+s"):
            app = _Host()
            async with app.run_test(size=(70, 24)) as pilot:
                await app.push_screen(SellModal(TABLE))
                await pilot.pause()
                opened = len(app.screen_stack)
                await pilot.press(key)
                await pilot.pause()
                depths[key] = (opened, len(app.screen_stack))
    asyncio.run(_run())

    for key, (opened, closed) in depths.items():
        assert closed == opened - 1, f"{key} did not close the popup"


# ── The front ends are wired to it ────────────────────────────────────────────

def test_both_front_ends_bind_the_same_key_to_the_same_table():
    """The hotkey, the menu entry, and the action all have to agree, and both
    front ends have to reach the table through the same plugin call."""
    tui_src = (ROOT / "tui" / "app.py").read_text(encoding="utf-8")
    gui_src = (ROOT / "gui" / "app.py").read_text(encoding="utf-8")

    assert 'Binding("ctrl+s", "sell_table"' in tui_src
    assert "def action_sell_table" in tui_src
    assert 'QKeySequence("Ctrl+S")' in gui_src
    assert "def action_sell_table" in gui_src
    assert "view_menu.addAction(sell_act)" in gui_src, "no GUI menu entry"

    for src in (tui_src, gui_src):
        assert 'plugin_call("cargo", "sell_table")' in src, \
            "the front end builds its own table instead of asking for one"


def test_ctrl_s_is_not_already_spoken_for():
    """Ctrl+S is free in both front ends — EDLD saves nothing on demand — but
    a future binding could quietly shadow it."""
    tui_src = (ROOT / "tui" / "app.py").read_text(encoding="utf-8")
    assert tui_src.count('Binding("ctrl+s"') == 1
    gui_src = (ROOT / "gui" / "app.py").read_text(encoding="utf-8")
    assert gui_src.count('QKeySequence("Ctrl+S")') == 1


# ── The GUI popup ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    """One offscreen Qt application for the GUI tests in this module."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_the_gui_popup_draws_the_heading_and_both_tabs(qapp):
    from gui.sell_dialog import SellDialog
    dlg = SellDialog(None, TABLE, theme="default")
    assert dlg._heading.text() == TABLE["source_label"]

    for grid in (dlg._mineable, dlg._all):
        assert grid.columnCount() == 2, "two columns and no more"
        assert [grid.horizontalHeaderItem(i).text() for i in range(2)] == \
            ["Commodity", "Sell"]

    assert [dlg._all.item(r, 0).text() for r in range(dlg._all.rowCount())] == \
        [row["name"] for row in TABLE["rows"]]
    assert dlg._all.item(0, 1).text() == "542,736 cr"
    assert [dlg._mineable.item(r, 0).text()
            for r in range(dlg._mineable.rowCount())] == MINEABLE_IN_TABLE


def test_the_gui_popup_opens_on_mineable(qapp):
    from gui.sell_dialog import SellDialog
    dlg = SellDialog(None, TABLE, theme="default")
    assert dlg._tabs.currentIndex() == 0
    assert dlg._tabs.currentWidget() is dlg._mineable
    assert [dlg._tabs.tabText(i) for i in range(2)] == \
        ["Mineable (2)", "All Items (3)"]


def test_the_gui_price_column_is_right_aligned(qapp):
    from PySide6.QtCore import Qt as _Qt

    from gui.sell_dialog import SellDialog
    # The dialog is bound to a name, not chained through: dropping the last
    # Python reference takes the C++ object with it and the next call on the
    # table raises "already deleted".
    dlg = SellDialog(None, TABLE, theme="default")
    for grid in (dlg._mineable, dlg._all):
        for r in range(grid.rowCount()):
            assert grid.item(r, 1).textAlignment() & _Qt.AlignRight


def test_the_gui_popup_binds_its_own_close_key(qapp):
    from PySide6.QtGui import QShortcut

    from gui.sell_dialog import SellDialog
    dlg = SellDialog(None, TABLE, theme="default")
    keys = [s.key().toString() for s in dlg.findChildren(QShortcut)]
    assert "Ctrl+S" in keys, "the key that opens it does not close it"


def test_the_gui_popup_can_be_refilled_in_place(qapp):
    """The window is reused between openings, so a stale table left behind
    would quote a market the commander has long since left."""
    from gui.sell_dialog import SellDialog
    dlg = SellDialog(None, TABLE, theme="default")
    dlg.set_table({"source_label": GALACTIC_LABEL, "rows": [
        {"name": "Gold", "price": 47113, "mineable": True}]})
    assert dlg._heading.text() == GALACTIC_LABEL
    assert dlg._all.rowCount() == 1
    assert dlg._all.item(0, 0).text() == "Gold"
    # Both tabs and both counts are refilled, not just the visible one.
    assert dlg._mineable.rowCount() == 1
    assert [dlg._tabs.tabText(i) for i in range(2)] == \
        ["Mineable (1)", "All Items (1)"]
    assert dlg._tabs.currentIndex() == 0, "a refill must land back on Mineable"


def test_the_gui_toggle_opens_then_closes_one_window(qapp):
    """Two stacked copies of the same table would be a puzzle to get out of."""
    from gui.app import EdldWindow

    class _Core:
        _plugins = {"cargo": object()}
        def plugin_call(self, *a, **k):
            return TABLE

    from PySide6.QtWidgets import QWidget

    # A real QWidget, because SellDialog parents itself to whatever it is
    # handed and Qt will not accept a plain object.
    class _Stub(QWidget):
        _core = _Core()
        _theme = "default"
        _sell_dialog = None
        action_sell_table = EdldWindow.action_sell_table

    win = _Stub()

    win.action_sell_table()
    dlg = win._sell_dialog
    assert dlg is not None and dlg.isVisible()

    win.action_sell_table()
    assert not dlg.isVisible()
    assert win._sell_dialog is dlg, "a second window was created"

    win.action_sell_table()
    assert win._sell_dialog is dlg and dlg.isVisible()


def test_the_real_gui_menu_carries_the_entry(qapp):
    """Built from the real window rather than grepped for, because a menu
    entry that fails to attach is invisible in exactly the same way as one
    that was never written."""
    import queue

    from core.state import MonitorState
    from gui.app import EdldWindow

    class _Core:
        gui_queue = queue.Queue()
        _plugins: dict = {}
        journal_dir = "/tmp"
        state = MonitorState()
        def plugin_call(self, *a, **k):
            return None
        def register_block(self, *a, **k):
            pass

    win = EdldWindow(_Core(), "EDLD", "test", "D", "drworman/EDLD")
    entries = [
        (top.text(), act.text(), act.shortcut().toString())
        for top in win.menuBar().actions() if top.menu()
        for act in top.menu().actions()
    ]
    assert ("&View", "&Sell Table", "Ctrl+S") in entries, \
        f"no Sell Table entry under View: {entries}"

    # And nothing else claims the key.
    assert [e for e in entries if e[2] == "Ctrl+S"] == \
        [("&View", "&Sell Table", "Ctrl+S")]


# ── What counts as mineable ───────────────────────────────────────────────────

@pytest.mark.parametrize("name,category", [
    # Minerals, by category — the whole category is mined, so a mineral added
    # in a future update needs no edit to data/mining.py.
    ("Low Temp. Diamonds", "$MARKET_category_minerals;"),
    ("Painite",            "$MARKET_category_minerals;"),
    ("Void Opal",          "$MARKET_category_minerals;"),
    ("Bastnasite",         "$MARKET_category_minerals;"),
    ("Quartz Pyroxenite",  "$MARKET_category_minerals;"),
    ("Periclase Dunite",   "$MARKET_category_minerals;"),
    # Metals, by name — the refinery outputs, and only those.
    ("Platinum",     "$MARKET_category_metals;"),
    ("Osmium",       "$MARKET_category_metals;"),
    ("Praseodymium", "$MARKET_category_metals;"),
    ("Thorium",      "$MARKET_category_metals;"),
    # Chemicals, by name — ice-ring yields and carrier fuel.
    ("Tritium",           "$MARKET_category_chemicals;"),
    ("Water",             "$MARKET_category_chemicals;"),
    ("Liquid oxygen",     "$MARKET_category_chemicals;"),
    ("Hydrogen Peroxide", "$MARKET_category_chemicals;"),
])
def test_these_can_be_mined(name, category):
    from data.mining import is_mineable
    assert is_mineable(name, category)


@pytest.mark.parametrize("name,category", [
    # Iridium is the single most valuable thing in a real captured market and
    # cannot be mined — it is the reason the default tab exists.
    ("Iridium",        "$MARKET_category_metals;"),
    ("Steel",          "$MARKET_category_metals;"),
    ("Aluminium",      "$MARKET_category_metals;"),
    ("Titanium",       "$MARKET_category_metals;"),
    ("Uranium",        "$MARKET_category_metals;"),
    ("Lithium",        "$MARKET_category_metals;"),
    ("Helium-3",       "$MARKET_category_chemicals;"),
    ("Hydrogen Fuel",  "$MARKET_category_chemicals;"),
    ("Thargoid Probe", "$MARKET_category_salvage;"),
    ("Beer",           "$MARKET_category_drugs;"),
])
def test_these_cannot_be_mined(name, category):
    from data.mining import is_mineable
    assert not is_mineable(name, category)


@pytest.mark.parametrize("spelling", [
    "Liquid oxygen", "liquid_oxygen", "LiquidOxygen", "liquidoxygen",
])
def test_the_name_match_survives_every_spelling(spelling):
    """Market.json, the journals and Spansh each punctuate differently."""
    from data.mining import is_mineable
    assert is_mineable(spelling)


def test_a_category_alone_is_enough_and_so_is_a_name_alone():
    """Sources differ in what they report: Spansh gives a plain category
    string, the catalogue gives a canonical one, and some rows give neither."""
    from data.mining import is_mineable
    assert is_mineable(category="Minerals")
    assert is_mineable(category="minerals")
    assert is_mineable(name="Tritium")
    assert not is_mineable()


def test_the_sell_table_marks_each_row():
    """Mineability rides on the row, so all four surfaces split the same way
    rather than each re-deciding."""
    st = FakeState(market=market("X", "Y", {
        "painite": {"name_local": "Painite", "sell_price": 247663,
                    "category": "$MARKET_category_minerals;",
                    "category_local": "Minerals", "mean_price": 1},
        "iridium": {"name_local": "Iridium", "sell_price": 542736,
                    "category": "$MARKET_category_metals;",
                    "category_local": "Metals", "mean_price": 1},
    }))
    t = sell_table(st, LEDGER)
    by_name = {r["name"]: r["mineable"] for r in t["rows"]}
    assert by_name == {"Painite": True, "Iridium": False}
    assert [r["name"] for r in mineable_rows(t)] == ["Painite"]


def test_the_catalogue_rows_are_marked_too():
    """Galactic mode reads the catalogue, which carries its own category."""
    ledger = {
        "painite": {"name_localised": "Painite", "category": "minerals",
                    "mean_price": 247663},
        "iridium": {"name_localised": "Iridium", "category": "metals",
                    "mean_price": 542736},
        "tritium": {"name_localised": "Tritium", "category": "chemicals",
                    "mean_price": 40000},
    }
    t = sell_table(FakeState(), ledger)
    assert sorted(r["name"] for r in mineable_rows(t)) == ["Painite", "Tritium"]


@pytest.mark.parametrize("category", [
    "$MARKET_category_minerals;",   # Frontier, Market.json
    "$market_category_minerals;",
    "minerals",                     # the catalogue's canonical form
    "Minerals",                     # Spansh, and Category_Localised
])
def test_the_category_match_survives_frontiers_wrapper(category):
    """Squashing alone leaves 'marketcategoryminerals', which matches nothing
    — every mineral would have landed in All Items only."""
    from data.mining import is_mineable
    assert is_mineable("Painite", category)


# ── Zebra striping ────────────────────────────────────────────────────────────
#
# Asserted on rendered colour, not on class names or stylesheet text.  A class
# that is applied but paints nothing, a stripe that stops short of the row's
# full width, or two panels that stripe out of phase all look exactly like
# working code from the source.

STRIPE_TABLE = {
    "source_label": "Al Saud Ring · Borfor",
    "rows": [{"name": f"Commodity {i}", "price": 100000 - i * 1000,
              "mineable": True} for i in range(6)],
}

THEMES = ["default", "default-green", "default-light"]


def _tui_row_colours(theme: str, rows: int = 4):
    """Background colours actually painted across each row's full width."""
    import asyncio

    from textual.app import App

    from tui.sell_modal import SellModal
    from tui.theme import build_css

    out = []

    class _Host(App):
        CSS = build_css(theme)

    def _hex(colour):
        if colour is None:
            return None
        t = colour.get_truecolor()
        return "#%02x%02x%02x" % (t.red, t.green, t.blue)

    async def _run():
        app = _Host()
        async with app.run_test(size=(70, 24)) as pilot:
            await app.push_screen(SellModal(STRIPE_TABLE))
            await pilot.pause()
            strips = app.screen._compositor.render_strips()
            pane = app.screen.query_one("#sell-rows-mineable")
            for widget in list(pane.query(".sell-row"))[:rows]:
                region = widget.region
                seen, x = [], 0
                for seg in strips[region.y]:
                    for _ in range(len(seg.text)):
                        if region.x <= x < region.right:
                            seen.append(_hex(seg.style.bgcolor)
                                        if seg.style else None)
                        x += 1
                out.append(seen)
    asyncio.run(_run())
    return out


@pytest.mark.parametrize("theme", THEMES)
def test_the_tui_rows_alternate(theme):
    from core.palette import palette_for
    pal = palette_for(theme)
    colours = [set(row) for row in _tui_row_colours(theme)]
    assert colours[0] == colours[2] == {pal["$block-bg"]}
    assert colours[1] == colours[3] == {pal["$row-alt"]}


@pytest.mark.parametrize("theme", THEMES)
def test_the_tui_stripe_covers_the_whole_row(theme):
    """The two labels sit on top of the row's fill.  If they paint their own
    background the stripe comes out with a hole punched through it."""
    for n, row in enumerate(_tui_row_colours(theme)):
        assert len(set(row)) == 1, \
            f"row {n} is painted in {len(set(row))} colours: {sorted(set(row))}"
        assert len(row) > 20, f"row {n} is only {len(row)} columns wide"


@pytest.mark.parametrize("theme", sorted(__import__(
    "core.palette", fromlist=["PALETTES"]).PALETTES))
def test_the_stripe_survives_a_256_colour_terminal(theme):
    """The bug this replaced.  $title-bg is six points per channel above the
    block fill, and a 256-colour terminal quantises both onto entry 16 — so
    the stripe showed in the Qt window, which is always truecolor, and was
    invisible in the terminal.  Every palette must clear that threshold."""
    from rich.color import Color, ColorSystem

    from core.palette import palette_for

    pal = palette_for(theme)

    def quantised(value):
        return Color.parse(value).downgrade(ColorSystem.EIGHT_BIT).number

    assert quantised(pal["$block-bg"]) != quantised(pal["$row-alt"]), (
        f"{theme}: {pal['$block-bg']} and {pal['$row-alt']} both quantise to "
        f"{quantised(pal['$row-alt'])} on a 256-colour terminal")


@pytest.mark.parametrize("theme", sorted(__import__(
    "core.palette", fromlist=["PALETTES"]).PALETTES))
def test_the_stripe_is_subtle_not_loud(theme):
    """Just enough to separate the rows.  A stripe that reads as a highlight
    would fight the accent colour the panel titles already use."""
    from core.palette import palette_for
    pal = palette_for(theme)
    base = pal["$block-bg"].lstrip("#")
    alt = pal["$row-alt"].lstrip("#")
    steps = [abs(int(alt[i:i + 2], 16) - int(base[i:i + 2], 16))
             for i in (0, 2, 4)]
    assert max(steps) <= 32, f"{theme}: stripe differs by {steps}, too strong"
    assert max(steps) >= 8, f"{theme}: stripe differs by {steps}, too weak"


def test_a_custom_theme_gets_a_stripe_without_declaring_one(tmp_path):
    """Theme files state seven colours and know nothing about striping."""
    from core.palette import load_custom_palette
    css = tmp_path / "x.css"
    css.write_text(":root {\n  --bg-deep: #000010;\n  --bg-mid: #101020;\n"
                   "  --bg-panel: #181828;\n  --fg: #e0e0f0;\n"
                   "  --fg-dim: #707080;\n  --accent: #8080ff;\n"
                   "  --border: #303048;\n}\n", encoding="utf-8")
    pal = load_custom_palette(css)
    assert pal is not None
    assert pal["$row-alt"] not in ("", pal["$block-bg"])


@pytest.mark.parametrize("theme", THEMES)
def test_the_gui_rows_alternate(qapp, theme):
    """Sampled from the rendered viewport.  Qt supplies its own alternate
    colour when the stylesheet states none — a light grey, unreadable on
    every dark palette here — and that failure is invisible in the source."""
    from PySide6.QtGui import QPixmap

    from core.palette import rgb
    from gui.sell_dialog import SellDialog

    c = rgb(theme)
    dlg = SellDialog(None, STRIPE_TABLE, theme=theme)
    dlg.resize(440, 560)
    dlg.show()
    qapp.processEvents()

    grid = dlg._mineable
    assert grid.alternatingRowColors()
    # The viewport alone, so the header height does not shift the sampling
    # down by one row and invert the apparent phase.
    viewport = grid.viewport()
    pixmap = QPixmap(viewport.size())
    viewport.render(pixmap)
    image = pixmap.toImage()

    seen = []
    for r in range(4):
        rect = grid.visualItemRect(grid.item(r, 0))
        seen.append(image.pixelColor(rect.x() + rect.width() // 2,
                                     rect.y() + rect.height() // 2).name())
    assert seen[0] == seen[2] == c["block-bg"]
    assert seen[1] == seen[3] == c["row-alt"]


def test_both_front_ends_stripe_in_phase(qapp):
    """Same table, same theme, same row: the same colour in both.  Out of
    phase they would be two different-looking windows."""
    from PySide6.QtGui import QPixmap

    from gui.sell_dialog import SellDialog

    tui_first = _tui_row_colours("default", rows=2)
    dlg = SellDialog(None, STRIPE_TABLE, theme="default")
    dlg.resize(440, 560)
    dlg.show()
    qapp.processEvents()
    grid = dlg._mineable
    viewport = grid.viewport()
    pixmap = QPixmap(viewport.size())
    viewport.render(pixmap)
    image = pixmap.toImage()

    for r in range(2):
        rect = grid.visualItemRect(grid.item(r, 0))
        gui_colour = image.pixelColor(rect.x() + rect.width() // 2,
                                      rect.y() + rect.height() // 2).name()
        assert {gui_colour} == set(tui_first[r]), \
            f"row {r}: TUI {set(tui_first[r])} vs GUI {gui_colour}"

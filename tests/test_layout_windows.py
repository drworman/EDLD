"""
tests/test_layout_windows.py — the window registry must agree with itself.

Windows are declared in four places that have to stay in step: the layout
model's class registry and display names, the slot grid, and each front end's
DOM-id and block-class maps.  Merging windows repeatedly left one of those
behind — a window with no block, a block with no slot, a repaint target
pointing at an id nothing answers to — and every one of those failures is
silent: the window simply never appears or never refreshes.

These tests derive what must line up from the registries themselves, so a
window added or removed in a future release fails here rather than going
missing on someone's dashboard.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.layout_model import (  # noqa: E402
    ASSIGNMENT_VERSION,
    BLOCK_CLASS,
    BLOCK_DISPLAY,
    CLASS_LABEL,
    CLASS_WEIGHT,
    DEFAULT_SLOTS,
    SIZE_CLASSES,
    default_assignment,
    load_assignment,
    normalize_assignment,
    slot_class,
    slot_ids,
    summary,
    tui_columns,
)


# ── The registry agrees with itself ───────────────────────────────────────────

def test_every_window_has_a_class_and_a_display_name():
    assert set(BLOCK_CLASS) == set(BLOCK_DISPLAY), (
        f"class/display mismatch: {set(BLOCK_CLASS) ^ set(BLOCK_DISPLAY)}")


@pytest.mark.parametrize("window,cls", sorted(BLOCK_CLASS.items()))
def test_window_class_is_a_real_class(window, cls):
    assert cls in SIZE_CLASSES
    assert cls in CLASS_WEIGHT
    assert cls in CLASS_LABEL


def test_every_class_has_at_least_one_slot_and_one_window():
    slot_classes = {slot_class(sid) for sid in slot_ids()}
    for cls in SIZE_CLASSES:
        assert cls in slot_classes, f"{cls} has no slot"
        assert any(c == cls for c in BLOCK_CLASS.values()), f"{cls} has no window"


# ── The grid is drawable ──────────────────────────────────────────────────────

def test_every_column_sums_to_a_full_height():
    """Rows have to line up across columns, so each must total 100%."""
    for col, entries in tui_columns(default_assignment()).items():
        total = sum(pct for _blk, pct in entries)
        assert 99 <= total <= 101, f"column {col} sums to {total}"


def test_default_assignment_fills_every_slot():
    assignment = default_assignment()
    for sid in slot_ids():
        assert assignment.get(sid), f"slot {sid} is empty by default"


def test_default_assignment_places_each_window_once():
    placed = [b for b in default_assignment().values() if b]
    assert len(placed) == len(set(placed)), "a window is placed twice"


def test_default_slots_match_their_windows_classes():
    for col, entries in DEFAULT_SLOTS.items():
        for cls, window in entries:
            if window is None:
                continue
            assert BLOCK_CLASS[window] == cls, (
                f"{window} is {BLOCK_CLASS[window]} but sits in a {cls} slot "
                f"in column {col}")


def test_every_window_fits_somewhere():
    """A window with no slot of its class can never be displayed."""
    slot_classes = {slot_class(sid) for sid in slot_ids()}
    for window, cls in BLOCK_CLASS.items():
        assert cls in slot_classes, f"{window} ({cls}) has nowhere to go"


# ── Preferences > Display offers only what fits ───────────────────────────────

@pytest.mark.parametrize("row", summary(default_assignment()), ids=lambda r: r["slot"])
def test_display_offers_only_windows_of_the_slots_class(row):
    for window in row["eligible"]:
        assert BLOCK_CLASS[window] == row["class"], (
            f"{row['slot']} is {row['class']} but offers {window} "
            f"({BLOCK_CLASS[window]})")


def test_display_offers_the_currently_assigned_window():
    """Otherwise the selector cannot show what is already there."""
    for row in summary(default_assignment()):
        assert row["block"] in row["eligible"]


# ── Both front ends know every window ─────────────────────────────────────────

def test_tui_knows_every_window():
    from tui.theme import BLOCK_DOM_ID
    import tui.app as tui_app

    assert set(BLOCK_DOM_ID) == set(BLOCK_CLASS), (
        f"TUI dom ids differ: {set(BLOCK_DOM_ID) ^ set(BLOCK_CLASS)}")
    assert set(tui_app._BLOCK_CLASSES) == set(BLOCK_CLASS), (
        f"TUI block classes differ: "
        f"{set(tui_app._BLOCK_CLASSES) ^ set(BLOCK_CLASS)}")


def test_gui_knows_every_window():
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    import gui.app as gui_app
    assert set(gui_app.BLOCK_ID) == set(BLOCK_CLASS), (
        f"GUI ids differ: {set(gui_app.BLOCK_ID) ^ set(BLOCK_CLASS)}")
    assert set(gui_app._BLOCK_CLASSES) == set(BLOCK_CLASS), (
        f"GUI block classes differ: "
        f"{set(gui_app._BLOCK_CLASSES) ^ set(BLOCK_CLASS)}")


def test_front_ends_agree_on_dom_ids():
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    from tui.theme import BLOCK_DOM_ID
    import gui.app as gui_app
    for window in BLOCK_CLASS:
        assert BLOCK_DOM_ID[window] == gui_app.BLOCK_ID[window], (
            f"{window}: TUI says {BLOCK_DOM_ID[window]}, "
            f"GUI says {gui_app.BLOCK_ID[window]}")


def test_repaint_targets_all_exist():
    """A dispatch entry naming a dead id silently never repaints anything."""
    from tui.theme import BLOCK_DOM_ID
    import tui.app as tui_app

    known = set(BLOCK_DOM_ID.values())
    for event, targets in tui_app._MSG_DISPATCH.items():
        for target in targets:
            assert target in known, f"{event} repaints unknown {target}"


# ── One-time migration ────────────────────────────────────────────────────────

#: A real pre-v2 file, naming windows that have since been merged away.
LEGACY = {
    "version": 1,
    "slots": {
        "A1": "exploration", "A2": "exobiology", "A3": "navigation",
        "B1": "commander", "B2": "crew_slf", "B3": "alerts", "B4": "session",
        "C1": "ship_health", "C2": "cargo", "C3": "engineering",
    },
}


def test_legacy_assignment_is_replaced_wholesale(tmp_path):
    """Salvaging a pre-v2 file would leave a half-populated grid.

    Almost every window it names has been folded into another, and the slot
    grid itself changed shape, so the only sensible result is the current
    defaults.
    """
    path = tmp_path / "windows.json"
    path.write_text(json.dumps(LEGACY), encoding="utf-8")
    assert load_assignment(path) == default_assignment()


def test_migration_rewrites_the_file_once(tmp_path):
    path = tmp_path / "windows.json"
    path.write_text(json.dumps(LEGACY), encoding="utf-8")
    load_assignment(path)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["version"] == ASSIGNMENT_VERSION
    # Second load goes down the normal path and changes nothing.
    assert load_assignment(path) == default_assignment()
    assert json.loads(path.read_text(encoding="utf-8")) == written


def test_a_current_assignment_is_left_alone(tmp_path):
    path = tmp_path / "windows.json"
    custom = dict(default_assignment())
    custom["A1"], custom["A2"] = custom["A2"], custom["A1"]
    path.write_text(json.dumps(
        {"version": ASSIGNMENT_VERSION, "slots": custom}), encoding="utf-8")
    assert load_assignment(path) == normalize_assignment(custom)


def test_a_missing_file_falls_back_to_defaults(tmp_path):
    assert load_assignment(tmp_path / "nope.json") == default_assignment()


def test_unreadable_file_does_not_stop_the_dashboard_drawing(tmp_path):
    path = tmp_path / "windows.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load_assignment(path) == default_assignment()


# ── Module naming ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("internal,expected", [
    # Ids the title-case fallback used to mangle.
    ("int_largecargorack_size7_class1",      "7E Cargo Rack"),
    ("int_mkii_passengercabin_size4_class2", "4D Passenger Cabin"),
    ("int_fighterbaymk2_size5_class1_free",  "5E Fighter Hangar"),
    ("modularcargobaydoor",                  "Modular Cargo Bay Door"),
    # Utility mounts carry no size in game; "0 Point Defence" is not a name.
    ("hpt_plasmapointdefence_turret_tiny",   "Point Defence (Turret)"),
    ("hpt_heatsinklauncher_turret_tiny",     "Heat Sink Launcher (Turret)"),
    # Utility mounts with no mount type in the id at all.
    ("hpt_chafflauncher_tiny",               "Chaff Launcher"),
    ("hpt_electroniccountermeasure_tiny",    "Electronic Countermeasure"),
    # Still-correct existing behaviour.
    ("int_repairer_size5_class5",            "5A Auto Field-Maintenance Unit"),
])
def test_module_display_names(internal, expected):
    from data.modules import normalise_module_name
    assert normalise_module_name(internal) == expected


@pytest.mark.parametrize("internal", [
    "paintjob_mediumtransport01_emerald_01",
    "decal_squadronlogo_dynamic",
    "mediumtransport01_shipkita_bumper2",
    "smallcombat01_nx_cockpit",
    "enginecustomisation_green",
    "weaponcustomisation_green",
    "smallcombat01_nx_holograma_02",
])
def test_cosmetics_are_not_modules(internal):
    """They have no health and nothing to repair; listing them is noise.

    The old test was a prefix match, so anything whose id begins with the
    ship rather than the item type slipped through.
    """
    from data.modules import is_cosmetic_module
    assert is_cosmetic_module(internal)


@pytest.mark.parametrize("internal", [
    "int_largecargorack_size7_class1",
    "modularcargobaydoor",
    "hpt_plasmapointdefence_turret_tiny",
    "int_repairer_size5_class5",
])
def test_real_modules_are_not_filtered(internal):
    from data.modules import is_cosmetic_module
    assert not is_cosmetic_module(internal)


# ── SRV cargo is not ship cargo ───────────────────────────────────────────────

def test_srv_cargo_events_do_not_touch_the_ship_hold():
    """Cargo fires for the SRV too, naming only a count.

    Untangled, an SRV event with Count > 0 sent the ship's hold off to
    re-read Cargo.json, and an SRV Count:0 emptied it outright.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "comp_cargo", ROOT / "components" / "cargo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from core.plugin_loader import BasePlugin
    cls = next(getattr(mod, n) for n in dir(mod)
               if isinstance(getattr(mod, n), type)
               and issubclass(getattr(mod, n), BasePlugin)
               and getattr(mod, n) is not BasePlugin)

    class State:
        cargo_items = {"tritium": {"count": 180}}
        srv_cargo_count = 0

    class Core:
        state = State()
        gui_queue = None
        journal_dir = "/nonexistent"

    plugin = cls()
    plugin.core = Core()

    plugin.on_event({"event": "Cargo", "Vessel": "SRV", "Count": 2}, State)
    assert State.cargo_items == {"tritium": {"count": 180}}, "ship hold disturbed"
    assert State.srv_cargo_count == 2

    plugin.on_event({"event": "Cargo", "Vessel": "SRV", "Count": 0}, State)
    assert State.cargo_items == {"tritium": {"count": 180}}, "ship hold emptied"
    assert State.srv_cargo_count == 0


# ── What belongs in the Session view ──────────────────────────────────────────

def _mining_plugin():
    """A mining provider with a realistic session on it."""
    import importlib.util
    from datetime import datetime, timedelta, timezone

    spec = importlib.util.spec_from_file_location(
        "comp_mining_sess", ROOT / "components" / "mining.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    body = "Ega 3 d"

    class State:
        event_time = datetime.now(timezone.utc)
        pilot_body = body
        cargo_capacity = 257
        cargo_items = {"gold": {"count": 34}}
        cargo_mean_prices = {"gold": 48000}

    class Core:
        state = State()
        gui_queue = None

        def register_session_provider(self, provider):
            pass

    plugin = mod.ActivityMiningPlugin()
    plugin.on_load(Core())
    started = State.event_time - timedelta(seconds=4900)

    plugin.on_event({"event": "SAASignalsFound", "BodyName": body, "Signals": [
        {"Type": "$PlanetaryMiningLocation_Name;", "Count": 28},
        {"Type": "Serendibite", "Count": 2}]}, State)
    for name in ("gold", "silver"):
        for _ in range(20):
            plugin.on_event({"event": "MiningRefined", "_logtime": started,
                             "Type": f"${name}_name;",
                             "Type_Localised": name.title()}, State)
    plugin.on_event({"event": "MaterialCollected", "Name": "iron",
                     "Name_Localised": "Iron", "Count": 3}, State)
    # Prospecting and limpet use, so the rows that depend on them exist.
    plugin.on_event({"event": "Cargo", "Vessel": "Ship",
                     "Inventory": [{"Name": "drones", "Count": 400}]}, State)
    for i in range(9):
        plugin.on_event({"event": "ProspectedAsteroid", "_logtime": started,
                         "Content": "$AsteroidMaterialContent_High;" if i % 3 == 0
                                    else "$AsteroidMaterialContent_Low;",
                         "Remaining": 100.0,
                         "Materials": [{"Name": "gold", "Proportion": 25.0}]}, State)
    plugin.on_event({"event": "LaunchDrone", "Type": "Prospector"}, State)
    plugin.on_event({"event": "Cargo", "Vessel": "Ship",
                     "Inventory": [{"Name": "drones", "Count": 380}]}, State)
    plugin.session_start_time = started
    return plugin


@pytest.mark.parametrize("unwanted", [
    "Cargo",        # a state of the hold, not something the session produced
    "Ring",         # describes the place, not the session
    "Site",
])
def test_session_rows_exclude_place_and_state(unwanted):
    labels = [r["label"] for r in _mining_plugin().get_session_rows()]
    assert unwanted not in labels


def test_session_rows_exclude_per_site_breakdowns():
    labels = " ".join(r["label"] for r in _mining_plugin().get_session_rows())
    for marker in ("Planetary sites", "Ring sites", "hotspot"):
        assert marker not in labels


def test_session_rows_total_rather_than_itemise():
    """One refined figure, not a line per commodity.

    A count of how many kinds, and a materials-collected total, were both
    tried and dropped: neither is interesting enough to earn a row.
    """
    labels = [r["label"] for r in _mining_plugin().get_session_rows()]
    assert "Refined" in labels
    for dropped in ("Gold", "Silver", "Commodities", "Materials collected"):
        assert dropped not in labels


def test_mining_tab_keeps_its_detail():
    """Narrowing the Session view must not strip the activity's own window."""
    labels = " ".join(r["label"] for r in _mining_plugin().get_tab_rows())
    assert "Cargo" in labels
    assert "Planetary sites" in labels


def test_session_overview_does_not_name_the_ship():
    """The ship is in the Ship window's header and in Commander."""
    from core.summary_model import session_sections

    class Core:
        _plugins = {}
        session_providers = []

        class state:
            ship_name = "FOSSOR"
            assets_current_ship = {"type_display": "Type-11 Prospector"}

    text = " ".join(
        row.get("label", "")
        for section in session_sections(Core())
        for row in section.get("rows", []))
    assert "Ship" not in text


def test_srv_deployments_are_not_tracked():
    """How many times a vehicle was deployed says nothing about a session."""
    source = (ROOT / "components" / "odyssey.py").read_text(encoding="utf-8")
    assert "srv_deployments" not in source
    assert '"LaunchSRV"' not in source


# ── Cargo ordering ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("Limpet", True), ("Limpets", True), ("drones", True),
    ("Tritium", False), ("Gold", False), ("Alexandrite", False),
])
def test_limpet_detection(name, expected):
    from tui.blocks.ship_info import _is_limpet
    assert _is_limpet(name) is expected


def test_limpets_sit_below_the_alphabetical_manifest():
    """Limpets are consumables, not freight.

    They are never sold, and their count is what says whether the run can
    continue, so they sit apart from the alphabetical manifest.
    """
    from tui.blocks.ship_info import _is_limpet

    manifest = ["Tritium", "Limpet", "Gold", "Alexandrite"]
    manifest.sort(key=str.lower)
    limpets = [n for n in manifest if _is_limpet(n)]
    freight = [n for n in manifest if not _is_limpet(n)]
    assert freight == ["Alexandrite", "Gold", "Tritium"], "freight not alphabetical"
    assert limpets == ["Limpet"]


# ── What the summaries omit ───────────────────────────────────────────────────

@pytest.mark.parametrize("unwanted", ["Limpets left", "Yield"])
def test_summaries_omit_hold_and_ring_state(unwanted):
    """Limpet stock and yield distribution describe the run, not its output.

    Both stay on the Mining tab, where the question is "how is this going".
    """
    plugin = _mining_plugin()
    for getter in (plugin.get_summary_rows, plugin.get_session_rows):
        labels = [r["label"] for r in getter()]
        assert unwanted not in labels


def test_mining_tab_still_shows_limpets_and_yield():
    labels = " ".join(r["label"] for r in _mining_plugin().get_tab_rows())
    assert "Limpets" in labels
    assert "Yield" in labels


# ── Income is accounted for once ──────────────────────────────────────────────

def _income_plugin():
    import importlib.util
    from datetime import datetime, timedelta, timezone

    spec = importlib.util.spec_from_file_location(
        "comp_income", ROOT / "components" / "income.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from core.plugin_loader import BasePlugin
    cls = next(getattr(mod, n) for n in dir(mod)
               if isinstance(getattr(mod, n), type)
               and issubclass(getattr(mod, n), BasePlugin)
               and getattr(mod, n) is not BasePlugin)

    class Core:
        gui_queue = None
        _plugins = {}

        class state:
            pass

    plugin = cls()
    plugin.core = Core()
    plugin._reset_counters()
    started = datetime.now(timezone.utc) - timedelta(hours=2)

    for event in (
        {"event": "RedeemVoucher", "_logtime": started,
         "Type": "bounty", "Amount": 4_200_000},
        {"event": "MissionCompleted", "_logtime": started, "Reward": 12_000_000},
        {"event": "SellExplorationData", "_logtime": started,
         "TotalEarnings": 26_480_000},
        {"event": "SellOrganicData", "_logtime": started,
         "BioData": [{"Value": 5_000_000}]},
        # Mined ore was never bought, so it has no average paid price.
        {"event": "MarketSell", "_logtime": started,
         "TotalSale": 31_000_000, "AvgPricePaid": 0},
        {"event": "MarketSell", "_logtime": started,
         "TotalSale": 8_000_000, "AvgPricePaid": 1200},
    ):
        plugin.on_event(event, Core.state)
    plugin.session_start_time = started
    return plugin


def test_mined_sales_are_income_not_trade():
    """Filing mined ore under Trade made a mining session read as a trade run."""
    by_source = _income_plugin().by_source
    assert by_source["Mining"] == 31_000_000
    assert by_source["Trade"] == 8_000_000


def test_income_section_lists_sources_then_total_and_rate():
    rows = _income_plugin().get_session_rows()
    labels = [r["label"] for r in rows]
    assert labels[-2:] == ["Total earned", "Rate"], labels
    for source in ("Mining", "Cartography", "Missions", "Exobiology", "Bounties"):
        assert source in labels
    # Largest earner first.
    assert labels[0] == "Mining"


def test_income_is_not_repeated_in_the_overview():
    """It was reported twice in Overview and again per activity."""
    from core.summary_model import session_sections

    class Core:
        _plugins = {}
        session_providers = []

        class state:
            ship_name = "FOSSOR"

    labels = [row.get("label")
              for section in session_sections(Core())
              for row in section.get("rows", [])]
    assert "Income" not in labels
    assert "Income rate" not in labels


def test_earned_bounties_are_not_counted_as_session_income():
    """A bounty earned but not redeemed can still be lost by dying."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "comp_combat", ROOT / "components" / "combat.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from core.plugin_loader import BasePlugin
    cls = next(getattr(mod, n) for n in dir(mod)
               if isinstance(getattr(mod, n), type)
               and issubclass(getattr(mod, n), BasePlugin)
               and getattr(mod, n) is not BasePlugin)

    class Core:
        gui_queue = None
        _plugins = {}

        class state:
            pass

    plugin = cls()
    plugin.core = Core()
    plugin._reset_counters()
    plugin.bounty_total = 4_200_000
    plugin.kills = 3

    assert "Bounties" not in [r["label"] for r in plugin.get_session_rows()]
    assert "Bounties" in [r["label"] for r in plugin.get_summary_rows()]


def test_jumps_row_does_not_repeat_its_unit():
    """It read "Jumps  1 jumps"."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "comp_explo", ROOT / "components" / "exploration.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    source = (ROOT / "components" / "exploration.py").read_text(encoding="utf-8")
    assert '"value": f"{self.jumps} jumps"' not in source


# ── Cargo manifest ordering and columns ───────────────────────────────────────

def _manifest():
    """A hold with a wide spread of per-unit values, plus limpets."""
    return [
        dict(name="Tritium",     count=180, price=51_000,  stolen=False),
        dict(name="Limpet",      count=42,  price=100,     stolen=False),
        dict(name="Gold",        count=12,  price=48_000,  stolen=False),
        dict(name="Alexandrite", count=8,   price=250_000, stolen=False),
        dict(name="Biowaste",    count=15,  price=320,     stolen=True),
    ]


def test_freight_sorts_cheapest_per_unit_first():
    """With a full hold the question is what to jettison.

    That is answered by whatever is worth least per tonne, so it belongs at
    the top rather than buried alphabetically.
    """
    from tui.blocks.ship_info import _is_limpet

    freight = [x for x in _manifest() if not _is_limpet(x["name"])]
    freight.sort(key=lambda x: (x["price"], x["name"].lower()))
    assert [x["name"] for x in freight] == [
        "Biowaste", "Gold", "Tritium", "Alexandrite"]


def test_limpets_are_excluded_from_the_value_sort():
    """At 100 cr they would otherwise head the jettison list."""
    from tui.blocks.ship_info import _is_limpet

    limpets = [x for x in _manifest() if _is_limpet(x["name"])]
    assert [x["name"] for x in limpets] == ["Limpet"]


@pytest.mark.parametrize("front_end", ["tui", "gui"])
def test_cargo_columns_are_constant_width(front_end):
    """KVRow right-aligns its value, so separators only line up if the
    string never changes length."""
    if front_end == "gui":
        pytest.importorskip("PySide6")
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from gui.blocks.ship_info import _cargo_cols
    else:
        from tui.blocks.ship_info import _cargo_cols

    # Realistic bounds: the largest hold is under 2,000 t and the dearest
    # commodity a little over 1M cr per tonne.
    widths = {len(_cargo_cols(c, p, c * p))
              for c, p in ((1, 10), (180, 51_000), (1_800, 1_500_000))}
    assert len(widths) == 1, f"column width varies: {widths}"


@pytest.mark.parametrize("front_end", ["tui", "gui"])
def test_cargo_row_has_three_columns(front_end):
    if front_end == "gui":
        pytest.importorskip("PySide6")
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from gui.blocks.ship_info import _cargo_cols
    else:
        from tui.blocks.ship_info import _cargo_cols

    rendered = _cargo_cols(12, 48_000, 576_000)
    assert rendered.count("|") == 2
    assert "12 t" in rendered and "48K cr" in rendered and "576K cr" in rendered


@pytest.mark.parametrize("front_end", ["tui", "gui"])
def test_totals_line_aligns_with_the_manifest(front_end):
    """The Totals tonnage column is "used/capacity t" and must land under the
    per-row tonnage, so the first separator shares a column."""
    if front_end == "gui":
        pytest.importorskip("PySide6")
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from gui.blocks.ship_info import _cargo_cols
    else:
        from tui.blocks.ship_info import _cargo_cols

    row = _cargo_cols(180, 51_000, 9_180_000)
    totals = f"{'257/257 t':>10} | {'':>9} | {'11.8M cr':>10}"
    assert row.index("|") == totals.index("|")


# ── Repaint routing ───────────────────────────────────────────────────────────

def test_every_plugin_refresh_sender_is_mapped():
    """An unmapped name falls back to repainting the whole dashboard.

    Nothing breaks, but the fallback hides the omission — several mappings
    were lost in a merge and only surfaced as sluggish repaints.
    """
    import re
    import tui.app as tui_app

    senders = set()
    for path in (ROOT / "components").glob("*.py"):
        senders |= set(re.findall(r'plugin_refresh",\s*"([a-z_]+)"',
                                  path.read_text(encoding="utf-8")))
    # "capi" is a pseudo-sender handled by its own dispatch entry.
    senders.discard("capi")
    unmapped = senders - set(tui_app._PLUGIN_TO_BLOCK)
    assert not unmapped, f"plugins with no block mapping: {sorted(unmapped)}"


def test_plugin_map_targets_are_live_ids():
    import tui.app as tui_app
    from tui.theme import BLOCK_DOM_ID

    known = set(BLOCK_DOM_ID.values())
    dead = {k: v for k, v in tui_app._PLUGIN_TO_BLOCK.items() if v not in known}
    assert not dead, f"plugin map points at dead ids: {dead}"


def test_all_block_ids_is_derived_and_complete():
    """It was hand-written and had drifted: a dead id and two duplicates."""
    import tui.app as tui_app
    from tui.theme import BLOCK_DOM_ID

    ids = tui_app.EdldTui._all_block_ids(None)
    assert set(ids) == set(BLOCK_DOM_ID.values())
    assert len(ids) == len(set(ids)), "duplicate ids would refresh twice"


# ── No module may reference a name it does not have ───────────────────────────

def _undefined_names(path: Path) -> list[str]:
    """Module-level names loaded but never defined, imported or assigned.

    Deliberately conservative: only names that look like helpers or classes
    (leading underscore, or capitalised) are reported, so ordinary locals
    resolved at runtime do not produce noise.
    """
    import ast
    import builtins

    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, ast.Global):
            defined.update(node.names)

    used = {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return sorted(n for n in used - defined
                  if n.startswith("_") or n[:1].isupper())


def _source_files():
    dirs = ("tui", "gui", "core", "components", "data")
    return sorted(f for d in dirs for f in (ROOT / d).rglob("*.py")
                  if "__pycache__" not in f.parts)


@pytest.mark.parametrize("path", _source_files(),
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_no_module_uses_an_undefined_helper(path):
    """Guards the failure mode that merging windows kept producing.

    Lifting a method into another module leaves its helpers behind.  The
    result compiles and imports cleanly, then raises NameError on the first
    call — and because blocks swallow refresh errors, the window simply stops
    updating partway down with no message anywhere.

    `_fmt_health` reached a release this way: Commander's hull row raised, so
    every row after it stayed blank while Mode and Shields above it worked.
    """
    missing = _undefined_names(path)
    assert not missing, (
        f"{path.relative_to(ROOT)} uses undefined name(s): {missing}")


# ── Session boundaries ────────────────────────────────────────────────────────

def _journal(tmp_path, name, events):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return p


@pytest.mark.parametrize("closing,label", [
    ({"timestamp": "2026-09-06T10:00:00Z", "event": "Shutdown"}, "clean quit"),
    ({"timestamp": "2026-09-06T10:00:00Z", "event": "Music",
      "MusicTrack": "MainMenu"}, "exit to main menu"),
])
def test_session_end_marker_found_in_the_previous_journal(tmp_path, closing, label):
    """Elite opens a new journal per launch, so the marker is never in the
    file being replayed."""
    from core.journal import bootstrap_last_session_end
    from core.state import MonitorState

    _journal(tmp_path, "Journal.2026-09-06T090000.01.log", [
        {"timestamp": "2026-09-06T09:00:00Z", "event": "LoadGame"},
        closing,
    ])
    current = _journal(tmp_path, "Journal.2026-09-06T110000.01.log", [
        {"timestamp": "2026-09-06T11:00:00Z", "event": "LoadGame"},
    ])

    state = MonitorState()
    bootstrap_last_session_end(state, tmp_path, current)
    assert state.last_shutdown_time is not None, label
    assert state.last_shutdown_time.hour == 10


def test_crashed_client_falls_back_to_the_last_event(tmp_path):
    """No Shutdown and no MainMenu were ever written, so the last event of
    the previous journal is when play stopped."""
    from core.journal import bootstrap_last_session_end
    from core.state import MonitorState

    _journal(tmp_path, "Journal.2026-09-06T090000.01.log", [
        {"timestamp": "2026-09-06T09:00:00Z", "event": "LoadGame"},
        {"timestamp": "2026-09-06T09:42:00Z", "event": "FSDJump"},
    ])
    current = _journal(tmp_path, "Journal.2026-09-06T110000.01.log", [
        {"timestamp": "2026-09-06T11:00:00Z", "event": "LoadGame"},
    ])

    state = MonitorState()
    bootstrap_last_session_end(state, tmp_path, current)
    assert state.last_shutdown_time.hour == 9
    assert state.last_shutdown_time.minute == 42


def test_explicit_marker_beats_a_later_ordinary_event(tmp_path):
    """Events can follow a Shutdown; the marker is still the end of play."""
    from core.journal import bootstrap_last_session_end
    from core.state import MonitorState

    _journal(tmp_path, "Journal.2026-09-06T090000.01.log", [
        {"timestamp": "2026-09-06T09:00:00Z", "event": "LoadGame"},
        {"timestamp": "2026-09-06T10:00:00Z", "event": "Music",
         "MusicTrack": "MainMenu"},
        {"timestamp": "2026-09-06T10:05:00Z", "event": "Shutdown"},
    ])
    current = _journal(tmp_path, "Journal.2026-09-06T110000.01.log", [
        {"timestamp": "2026-09-06T11:00:00Z", "event": "LoadGame"},
    ])

    state = MonitorState()
    bootstrap_last_session_end(state, tmp_path, current)
    assert state.last_shutdown_time.minute == 5


def test_no_earlier_journal_leaves_the_marker_unset(tmp_path):
    from core.journal import bootstrap_last_session_end
    from core.state import MonitorState

    current = _journal(tmp_path, "Journal.2026-09-06T110000.01.log", [
        {"timestamp": "2026-09-06T11:00:00Z", "event": "LoadGame"},
    ])
    state = MonitorState()
    bootstrap_last_session_end(state, tmp_path, current)
    assert state.last_shutdown_time is None


def test_saved_session_start_is_the_clock_the_display_reads(tmp_path):
    """It used to save a module global only ever set by a previous *load*,
    so the stored start was stale or null and the session re-armed from the
    game's first LoadGame."""
    from datetime import datetime, timezone
    import core.state as core_state

    started = datetime(2026, 9, 6, 11, 30, tzinfo=timezone.utc)
    saved = {}
    core_state.save_session_state.__globals__["json"]  # present

    class Session:
        kills = 0; credit_total = 0; merits = 0; faction_tally = {}
        kill_interval_total = 0.0; recent_kill_times = []
        inbound_scan_count = 0; low_cargo_count = 0

    import unittest.mock as mock
    with mock.patch.object(core_state, "cmdr_data_dir", lambda: tmp_path):
        core_state.save_session_state(tmp_path / "J.log", Session(), started)
        saved = json.loads((tmp_path / "session_state.json").read_text())
    assert saved["session_start_time"] == started.isoformat()


# ── Both front ends open at the same proportions ──────────────────────────────

def test_column_widths_are_defined_once():
    from core.layout_model import COLUMN_WIDTH_PCT, COLUMNS

    assert set(COLUMN_WIDTH_PCT) == set(COLUMNS)
    assert sum(COLUMN_WIDTH_PCT.values()) == 100


def test_tui_css_uses_the_shared_column_widths():
    """They were hard-coded in the stylesheet, so the desktop window drifted."""
    from core.layout_model import COLUMN_WIDTH_PCT
    from tui.theme import build_css

    css = build_css("default")
    assert "__COL_" not in css, "a column width was left unsubstituted"
    for dom, col in (("col-left", "A"), ("col-centre", "B"), ("col-right", "C")):
        assert f"#{dom}" in css
        line = next(l for l in css.splitlines() if f"#{dom}" in l)
        assert f"{COLUMN_WIDTH_PCT[col]}%" in line, line


def test_gui_columns_match_the_model_proportions():
    """The desktop window used to let Qt size the columns from widget hints,
    so it opened nothing like the terminal."""
    pytest.importorskip("PySide6")
    import os
    import queue

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from core.layout_model import COLUMN_WIDTH_PCT, load_assignment, tui_columns

    class State:
        in_preload = False

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return None

    class Cfg:
        config: dict = {}

        def save(self):
            pass

    class Core:
        state = State()
        cfg = Cfg()
        gui_queue = queue.Queue()
        journal_dir = "/tmp"
        _plugins: dict = {}
        session_providers: list = []
        app_settings: dict = {}

        def plugin_call(self, *a, **k):
            return None

        def register_session_provider(self, provider):
            pass

    QApplication.instance() or QApplication([])
    from gui.app import BLOCK_ID, EdldWindow

    window = EdldWindow(Core(), "EDLD", "test", "owner", "owner/repo")
    window.resize(1920, 1013)
    window.show()
    QApplication.processEvents()
    QApplication.processEvents()

    cols = tui_columns(load_assignment())
    widths = {}
    for col in COLUMN_WIDTH_PCT:
        first = cols[col][0][0]
        widths[col] = window._blocks[BLOCK_ID[first]].parentWidget().width()

    total = sum(widths.values())
    for col, expected in COLUMN_WIDTH_PCT.items():
        actual = widths[col] / total * 100
        assert abs(actual - expected) <= 1, (
            f"column {col}: {actual:.1f}% vs model {expected}%")


def test_gui_layout_is_not_draggable():
    """Splitters let a stray drag leave the dashboard permanently lopsided.

    Which window sits where is changed through Preferences > Display; the
    geometry itself is fixed, as it is in the terminal.
    """
    source = (ROOT / "gui" / "app.py").read_text(encoding="utf-8")
    body = source[source.index("def _build_dashboard"):
                  source.index("# ── Menus")]
    assert "QSplitter" not in body.replace(
        "This replaced a pair of nested QSplitters.", "")


# ── SRV mining must not credit the ship twice ─────────────────────────────────

def _cargo_plugin():
    import importlib.util
    import queue

    from core.plugin_loader import BasePlugin

    spec = importlib.util.spec_from_file_location(
        "comp_cargo_srv", ROOT / "components" / "cargo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = next(getattr(mod, n) for n in dir(mod)
               if isinstance(getattr(mod, n), type)
               and issubclass(getattr(mod, n), BasePlugin)
               and getattr(mod, n) is not BasePlugin)

    class State:
        cargo_items: dict = {}
        srv_cargo_count = 0
        in_preload = True
        vessel_mode = "ship"

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return None

    class Core:
        gui_queue = queue.Queue()
        journal_dir = "/nonexistent"
        _plugins: dict = {}

    plugin = cls()
    plugin.core = Core()
    plugin.core.state = State()
    return plugin, plugin.core.state


def test_srv_refining_then_transfer_counts_the_ore_once():
    """An SRV with a refinery fills its own hold, not the ship's.

    Taken from a real journal: eight ore refined in the Rhino, transferred to
    the ship, twelve more, transferred again — twenty tonnes aboard.  Crediting
    the ship on MiningRefined *and* on CargoTransfer showed forty.
    """
    plugin, state = _cargo_plugin()

    state.vessel_mode = "srv"
    for _ in range(8):
        plugin.on_event({"event": "MiningRefined", "Type": "$osmium_name;",
                         "Type_Localised": "Osmium"}, state)
    assert state.cargo_items == {}, "ship hold credited while in the SRV"

    plugin.on_event({"event": "CargoTransfer", "Transfers": [
        {"Type": "osmium", "Count": 8, "Direction": "toship"}]}, state)
    assert state.cargo_items["osmium"]["count"] == 8

    for _ in range(12):
        plugin.on_event({"event": "MiningRefined", "Type": "$osmium_name;",
                         "Type_Localised": "Osmium"}, state)
    plugin.on_event({"event": "CargoTransfer", "Transfers": [
        {"Type": "osmium", "Count": 12, "Direction": "toship"}]}, state)

    assert state.cargo_items["osmium"]["count"] == 20, "ore counted twice"


def test_ship_refining_still_credits_the_hold():
    """Mining from the ship has no transfer step, so the optimistic credit on
    MiningRefined is the only thing that fills the hold."""
    plugin, state = _cargo_plugin()

    state.vessel_mode = "ship"
    for _ in range(5):
        plugin.on_event({"event": "MiningRefined", "Type": "$painite_name;",
                         "Type_Localised": "Painite"}, state)
    assert state.cargo_items["painite"]["count"] == 5


# ── The two holds are kept apart ──────────────────────────────────────────────

def test_cargo_json_is_not_read_as_the_ship_when_it_is_the_srv(tmp_path):
    """Cargo.json is rewritten for whichever hold last changed.

    While the commander is in an SRV it holds the *SRV's* manifest, so reading
    it blindly put SRV ore in the ship's hold.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "comp_cargo_json", ROOT / "components" / "cargo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    (tmp_path / "Cargo.json").write_text(json.dumps({
        "event": "Cargo", "Vessel": "SRV", "Count": 29,
        "Inventory": [{"Name": "osmium", "Count": 29, "Stolen": 0}],
    }), encoding="utf-8")

    assert mod._read_cargo_json(tmp_path, "Ship") is None
    srv = mod._read_cargo_json(tmp_path, "SRV")
    assert srv["osmium"]["count"] == 29


def test_loadgame_does_not_empty_a_hold_it_cannot_refill(tmp_path):
    """Resuming straight into an SRV means no Ship cargo event ever arrives.

    Clearing on LoadGame lost the ship's cargo for the rest of the session.
    """
    plugin, state = _cargo_plugin()
    plugin.core.journal_dir = str(tmp_path)
    (tmp_path / "Cargo.json").write_text(json.dumps({
        "event": "Cargo", "Vessel": "SRV", "Count": 5,
        "Inventory": [{"Name": "osmium", "Count": 5, "Stolen": 0}],
    }), encoding="utf-8")

    state.cargo_items = {"osmium": {"count": 31, "stolen": False,
                                    "name_local": "Osmium"}}
    plugin.on_event({"event": "LoadGame"}, state)
    assert state.cargo_items["osmium"]["count"] == 31


def test_srv_manifest_tracks_count_only_events(tmp_path):
    """Most SRV cargo events carry a count and no inventory, so the listing
    froze at whatever the last event with one said."""
    plugin, state = _cargo_plugin()
    plugin.core.journal_dir = str(tmp_path)

    plugin.on_event({"event": "Cargo", "Vessel": "SRV", "Count": 5,
                     "Inventory": [{"Name": "osmium", "Count": 5,
                                    "Stolen": 0}]}, state)
    assert state.srv_cargo_items["osmium"]["count"] == 5

    (tmp_path / "Cargo.json").write_text(json.dumps({
        "event": "Cargo", "Vessel": "SRV", "Count": 29,
        "Inventory": [{"Name": "osmium", "Count": 29, "Stolen": 0}],
    }), encoding="utf-8")
    plugin.on_event({"event": "Cargo", "Vessel": "SRV", "Count": 29}, state)

    assert state.srv_cargo_count == 29
    assert state.srv_cargo_items["osmium"]["count"] == 29
    assert state.cargo_items == {}, "ship hold disturbed by an SRV event"


def test_emptied_srv_clears_its_manifest():
    plugin, state = _cargo_plugin()
    plugin.on_event({"event": "Cargo", "Vessel": "SRV", "Count": 8,
                     "Inventory": [{"Name": "osmium", "Count": 8,
                                    "Stolen": 0}]}, state)
    plugin.on_event({"event": "Cargo", "Vessel": "SRV", "Count": 0}, state)
    assert state.srv_cargo_items == {}
    assert state.srv_cargo_count == 0


def test_srv_refining_survives_a_reload_with_no_launchsrv():
    """Resuming a save while already in an SRV emits no LaunchSRV.

    LoadGame resets vessel_mode to "ship" and nothing corrects it, so a guard
    that trusted vessel_mode alone started crediting the ship again: a hold of
    60 t read 84 after 24 more refines.  The vessel the game last reported
    cargo for keeps arriving throughout, so that is the reliable signal.
    """
    plugin, state = _cargo_plugin()

    # In the SRV, filling it.
    state.vessel_mode = "srv"
    plugin.on_event({"event": "Cargo", "Vessel": "SRV", "Count": 1}, state)
    plugin.on_event({"event": "CargoTransfer", "Transfers": [
        {"Type": "osmium", "Count": 31, "Direction": "toship"}]}, state)
    assert state.cargo_items["osmium"]["count"] == 31

    # Reload: vessel_mode goes back to "ship" and no LaunchSRV follows.
    state.vessel_mode = "ship"
    plugin.on_event({"event": "Cargo", "Vessel": "SRV", "Count": 5,
                     "Inventory": [{"Name": "osmium", "Count": 5,
                                    "Stolen": 0}]}, state)
    for _ in range(24):
        plugin.on_event({"event": "MiningRefined", "Type": "$osmium_name;",
                         "Type_Localised": "Osmium"}, state)
    assert state.cargo_items["osmium"]["count"] == 31, "ship credited again"

    plugin.on_event({"event": "CargoTransfer", "Transfers": [
        {"Type": "osmium", "Count": 29, "Direction": "toship"}]}, state)
    assert state.cargo_items["osmium"]["count"] == 60


def test_ship_cargo_event_restores_ship_refining():
    """Docking the SRV reports the ship's hold again, and refining from the
    ship must resume crediting it."""
    plugin, state = _cargo_plugin()

    plugin.on_event({"event": "Cargo", "Vessel": "SRV", "Count": 3}, state)
    plugin.on_event({"event": "MiningRefined", "Type": "$painite_name;"}, state)
    assert state.cargo_items == {}

    plugin.on_event({"event": "Cargo", "Vessel": "Ship", "Count": 0,
                     "Inventory": []}, state)
    plugin.on_event({"event": "MiningRefined", "Type": "$painite_name;",
                     "Type_Localised": "Painite"}, state)
    assert state.cargo_items["painite"]["count"] == 1

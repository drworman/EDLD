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


# ── Cargo pricing is a property of the commodity, not the vessel ──────────────

def _price_ctx(docked=None, target=None, target_name=""):
    """A price context built the way _refresh_cargo builds one."""
    from core.ui_helpers import cargo_price_context

    class _S:
        pass

    s = _S()
    s.cargo_market_info        = docked or {}
    s.cargo_target_market      = target or {}
    s.cargo_target_market_name = target_name
    s.cargo_mean_prices        = {"osmium": 44_051, "tritium": 51_294,
                                  "alexandrite": 205_143}
    return cargo_price_context(s)


_MARKET = {
    "station_name": "Metz Enterprise",
    "star_system":  "Ega",
    "commodities": {
        # Real spreads from Metz Enterprise: sell price runs 6x over galactic
        # average on osmium and well under it on alexandrite, so a hold priced
        # from the wrong source is wrong in both directions.
        "osmium":      dict(name_local="Osmium",      sell_price=264_306,
                            mean_price=44_051),
        "tritium":     dict(name_local="Tritium",     sell_price=42_374,
                            mean_price=51_294),
        "alexandrite": dict(name_local="Alexandrite", sell_price=89_643,
                            mean_price=205_143),
        "drones":      dict(name_local="Limpet",      sell_price=0,
                            mean_price=100),
    },
}


@pytest.mark.parametrize("ctx_kwargs", [
    dict(docked=_MARKET),                                  # docked, no target
    dict(),                                                # galactic average
    dict(target=_MARKET, target_name="Metz Enterprise"),   # target loaded
    dict(docked=_MARKET, target_name="Elsewhere"),         # target not loaded
])
def test_srv_hold_is_priced_like_the_ship_hold(ctx_kwargs):
    """The SRV manifest quoted galactic average while the ship quoted the
    station's sell price.

    It was invisible because both numbers were plausible and the panel prints
    one price-source label above both sections, so the SRV rows looked like
    they came from the market named in the header.  On osmium at Metz
    Enterprise that is 44,051 against 264,306 for the same tonne.
    """
    from core.ui_helpers import cargo_manifest

    ctx  = _price_ctx(**ctx_kwargs)
    hold = {"osmium": {"count": 20}, "alexandrite": {"count": 4},
            "tritium": {"count": 60}}
    srv  = {"osmium": {"count": 33}, "alexandrite": {"count": 2},
            "tritium": {"count": 5}}

    ship_prices = {x["name"]: x["price"] for x in cargo_manifest(hold, ctx)[0]}
    srv_prices  = {x["name"]: x["price"] for x in cargo_manifest(srv,  ctx)[0]}
    assert ship_prices == srv_prices


def test_srv_freight_sorts_cheapest_per_unit_first():
    """The SRV sorted on galactic average while the ship sorted on the
    resolved price, so the two manifests could disagree about what to
    jettison first."""
    from core.ui_helpers import cargo_manifest

    ctx  = _price_ctx(docked=_MARKET)
    hold = {"osmium": {"count": 20}, "alexandrite": {"count": 4},
            "tritium": {"count": 60}}
    srv  = {"osmium": {"count": 33}, "alexandrite": {"count": 2},
            "tritium": {"count": 5}}

    order = lambda items: [x["name"] for x in cargo_manifest(items, ctx)[0]]
    assert order(hold) == order(srv) == ["Tritium", "Alexandrite", "Osmium"]


def test_srv_limpets_are_separated_like_the_ships():
    """The SRV section had no limpet handling at all, so limpets sorted into
    the manifest and headed the jettison list at ~100 cr a tonne."""
    from core.ui_helpers import cargo_manifest

    ctx = _price_ctx(docked=_MARKET)
    freight, limpets = cargo_manifest(
        {"osmium": {"count": 33}, "drones": {"count": 8}}, ctx)
    assert [x["name"] for x in freight] == ["Osmium"]
    assert [x["name"] for x in limpets] == ["Limpet"]


def test_a_hold_priced_from_galactic_average_orders_differently():
    """Sanity check that the fixture actually exercises the branch: osmium is
    the cheapest tonne on galactic average and the dearest at the station."""
    from core.ui_helpers import cargo_manifest

    hold = {"osmium": {"count": 20}, "alexandrite": {"count": 4},
            "tritium": {"count": 60}}
    gal = [x["name"] for x in cargo_manifest(hold, _price_ctx())[0]]
    stn = [x["name"] for x in cargo_manifest(hold, _price_ctx(docked=_MARKET))[0]]
    assert gal[0] == "Osmium" and stn[-1] == "Osmium"


@pytest.mark.parametrize("front_end", ["tui", "gui"])
def test_both_holds_are_priced_through_the_shared_path(front_end):
    """Structural guard, not a behaviour check.

    The bug was two price expressions in one method, eighty lines apart: the
    ship's resolved a target or docked sell price, the SRV's only ever read
    cargo_mean_prices.  Asserting on cargo_manifest() alone would not catch a
    future edit that open-codes a price lookup in the block again, so this
    asserts the shape: exactly one price context per repaint, one manifest
    call per hold, and no local price arithmetic left behind.
    """
    source = (ROOT / front_end / "blocks" / "ship_info.py").read_text(
        encoding="utf-8")
    # Count call sites only: not the import that brings the names in, and not
    # the comments that explain them.
    source = "\n".join(ln for ln in source.splitlines()
                       if not ln.lstrip().startswith(("from ", "import ", "#"))
                       and "is_limpet)" not in ln)

    assert source.count("cargo_price_context(") == 1, \
        "one price context per panel, so both holds quote the same market"
    assert source.count("cargo_manifest(") == 2, \
        "one manifest call for the ship's hold and one for the SRV's"
    for leftover in ("mean_prices.get(", "sell_price", "mean_price"):
        assert leftover not in source, \
            f"{leftover!r} is priced in core.ui_helpers now, not in the block"

    # The totals lines are formatted by the shared helper too — the SRV's was
    # built by formatting a zero price and string-replacing it back out.
    assert ".replace(" not in source, \
        "totals columns come from cargo_totals_cols(), not string surgery"
    assert source.count("cargo_totals_cols(") == 3, \
        "one totals line for the ship and two for the SRV's two branches"


# ── Totals lines and SRV capacity ─────────────────────────────────────────────

def test_totals_line_uses_the_manifest_column_widths():
    """The SRV totals line was built by formatting a zero price and then
    string-replacing it back out.  It worked, but it broke the moment the
    credit formatter's output width changed."""
    from core.ui_helpers import cargo_cols, cargo_totals_cols

    widths = {len(cargo_cols(c, p, c * p))
              for c, p in ((1, 10), (180, 51_000), (1_800, 1_500_000))}
    widths |= {len(cargo_totals_cols("62/256 t", 5_286_120)),
               len(cargo_totals_cols("33/72 t",  8_722_098)),
               len(cargo_totals_cols("33 t",     0))}
    assert len(widths) == 1, f"totals line does not match the manifest: {widths}"


def test_totals_line_leaves_the_price_column_blank():
    """A totals row has no price per unit, but the column still has to hold
    its width or the separators stop lining up with the rows above."""
    from core.ui_helpers import cargo_totals_cols

    rendered = cargo_totals_cols("62/256 t", 5_286_120)
    assert rendered.count("|") == 2
    assert "0 cr" not in rendered and "—" not in rendered.split("|")[1]
    assert rendered.split("|")[1].strip() == ""


@pytest.mark.parametrize("vehicle,expected", [
    ("mev_rhino",               72),   # read off the in-game panels
    ("SRV Rhino",               72),   # state records the display name
    ("testbuggy",                4),
    ("combat_multicrew_srv_01",  2),
    ("lander01",                 0),   # Nomad: no confirmed figure
    ("",                         0),
    (None,                       0),
])
def test_srv_cargo_capacity_resolves_by_id_or_display_name(vehicle, expected):
    """state.srv_type holds a localised display name, not the journal id, so
    the lookup has to accept both."""
    from data.ships import srv_cargo_capacity

    assert srv_cargo_capacity(vehicle) == expected


def test_srv_tonnage_omits_an_unknown_denominator():
    """The journal never reports SRV capacity — not on LaunchSRV, not on
    Cargo, not in Status.json — so for a vehicle with no confirmed figure the
    manifest shows plain tonnage rather than a denominator that might be
    wrong.  A wrong one would read as a full hold while there was room."""
    from core.ui_helpers import srv_tonnage

    assert srv_tonnage(33, 72) == "33/72 t"
    assert srv_tonnage(33, 0)  == "33 t"


def test_the_rhino_capacity_covers_what_the_journals_actually_show():
    """Third-party references say 24 t.  Real journals run smoothly past 24
    to a high-water mark of 68 t, so a 24 t denominator would have shown a
    283%-full hold."""
    from data.ships import srv_cargo_capacity

    assert srv_cargo_capacity("mev_rhino") >= 68


# ── Price source is stated, and can be pinned to galactic average ─────────────

def _ctx_state(**kw):
    class _S: pass
    s = _S()
    s.cargo_mean_prices        = kw.get("means", {})
    s.cargo_market_info        = kw.get("docked", {})
    s.cargo_target_market      = kw.get("target", {})
    s.cargo_target_market_name = kw.get("target_name", "")
    s.cargo_price_galactic     = kw.get("pinned", False)
    return s


def test_the_panel_names_the_market_it_is_quoting():
    """The label is built beside the prices so the two cannot disagree."""
    from core.ui_helpers import cargo_price_context

    assert cargo_price_context(
        _ctx_state(docked=_MARKET))["source_label"] == "Metz Enterprise · Ega"
    assert cargo_price_context(_ctx_state())["source_label"] == "Gal. Avg"


def test_pinning_galactic_average_overrides_both_markets():
    """Clearing the target alone falls back to the docked station's prices,
    which is not what galactic average means — so the pin beats both."""
    from core.ui_helpers import cargo_manifest, cargo_price_context

    kw = dict(means={"osmium": 44_051}, docked=_MARKET, target=_MARKET,
              target_name="Metz Enterprise")
    one = {"osmium": {"count": 1}}

    ctx = cargo_price_context(_ctx_state(**kw, pinned=False))
    assert ctx["mode"] == "target"
    assert cargo_manifest(one, ctx)[0][0]["price"] == 264_306

    ctx = cargo_price_context(_ctx_state(**kw, pinned=True))
    assert ctx["mode"] == "galactic"
    assert ctx["source_label"] == "Gal. Avg"
    assert cargo_manifest(one, ctx)[0][0]["price"] == 44_051


@pytest.mark.parametrize("front_end", ["tui", "gui"])
def test_the_price_source_widget_actually_exists(front_end):
    """theme.py carried rules for #cargo-price-src all along, but the TUI
    never mounted the row and the update sat inside a bare except — so the
    label silently never appeared."""
    source = (ROOT / front_end / "blocks" / "ship_info.py").read_text(
        encoding="utf-8")
    if front_end == "tui":
        assert 'id="cargo-price-src"' in source, \
            "the price-source label is queried but never composed"
        assert 'id="cargo-hdr-row"' in source
    else:
        assert "self._price_src" in source


@pytest.mark.parametrize("front_end", ["tui", "gui"])
def test_both_front_ends_offer_a_galactic_average_control(front_end):
    source = (ROOT / front_end / "blocks" / "ship_info.py").read_text(
        encoding="utf-8")
    assert "Gal. Avg" in source
    assert "cargo_price_galactic" in source


# ── Session boundaries: a mid-session menu bounce is not an end ───────────────

def _sess_journal(tmp_path, name, events):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n",
                 encoding="utf-8")
    return p


def test_a_menu_bounce_does_not_date_the_session_end(tmp_path):
    """Dropping to the main menu and picking a mode again seconds later left
    a MainMenu mid-file.  bootstrap kept it as the session end, so every hour
    played afterwards counted as idle: one real capture dated the end to
    20:22 and then played on until 15:02 the next day, an 18.7-hour phantom
    gap that split the session two minutes after the commander sat down."""
    from core.journal import bootstrap_last_session_end
    from core.state import MonitorState

    _sess_journal(tmp_path, "Journal.2026-06-04T151137.01.log", [
        {"timestamp": "2026-06-04T20:12:35Z", "event": "LoadGame"},
        {"timestamp": "2026-06-04T20:22:43Z", "event": "Music",
         "MusicTrack": "MainMenu"},
        {"timestamp": "2026-06-04T20:22:48Z", "event": "LoadGame"},
        {"timestamp": "2026-06-05T15:02:15Z", "event": "FSDJump"},  # crash
    ])
    current = _sess_journal(tmp_path, "Journal.2026-06-05T100356.01.log", [
        {"timestamp": "2026-06-05T15:04:43Z", "event": "LoadGame"},
    ])

    state = MonitorState()
    bootstrap_last_session_end(state, tmp_path, current)
    assert state.last_shutdown_time is not None
    assert state.last_shutdown_time.isoformat().startswith("2026-06-05T15:02:15")


def test_a_menu_exit_with_no_resume_still_ends_the_session(tmp_path):
    """The marker is what makes an idle-at-the-menu gap visible, so clearing
    it on any LoadGame at all would break the case it exists for."""
    from core.journal import bootstrap_last_session_end
    from core.state import MonitorState

    _sess_journal(tmp_path, "Journal.2026-06-04T151137.01.log", [
        {"timestamp": "2026-06-04T20:12:35Z", "event": "LoadGame"},
        {"timestamp": "2026-06-04T22:00:00Z", "event": "Music",
         "MusicTrack": "MainMenu"},
        {"timestamp": "2026-06-05T00:00:00Z", "event": "Music",
         "MusicTrack": "MainMenu"},
    ])
    current = _sess_journal(tmp_path, "Journal.2026-06-05T100356.01.log", [
        {"timestamp": "2026-06-05T10:04:43Z", "event": "LoadGame"},
    ])

    state = MonitorState()
    bootstrap_last_session_end(state, tmp_path, current)
    assert state.last_shutdown_time.isoformat().startswith("2026-06-05T00:00:00")


def test_a_clean_shutdown_still_ends_the_session(tmp_path):
    from core.journal import bootstrap_last_session_end
    from core.state import MonitorState

    _sess_journal(tmp_path, "Journal.2026-06-04T151137.01.log", [
        {"timestamp": "2026-06-04T20:12:35Z", "event": "LoadGame"},
        {"timestamp": "2026-06-04T23:30:00Z", "event": "Shutdown"},
    ])
    current = _sess_journal(tmp_path, "Journal.2026-06-05T100356.01.log", [
        {"timestamp": "2026-06-05T10:04:43Z", "event": "LoadGame"},
    ])

    state = MonitorState()
    bootstrap_last_session_end(state, tmp_path, current)
    assert state.last_shutdown_time.isoformat().startswith("2026-06-04T23:30:00")


# ── Footer controls have to actually be drawn ─────────────────────────────────
#
# Asserting a control exists in the DOM proves nothing about whether anyone can
# see it.  A Static defaults to filling its Horizontal, so the first control in
# a footer takes the whole strip and everything after it is laid out beyond the
# right edge: present, clickable in a synthetic test, and never drawn.  These
# render the block for real and check where things landed.

def _render_block(block_cls, size=(82, 34), before_render=None):
    """Boot a one-block Textual app with the real stylesheet and render it.

    Returns (screen_lines, {widget_id: Region}) for the block's footer.
    """
    import asyncio
    from textual.app import App
    from tui.theme import build_css

    result = {}

    class _One(App):
        CSS = build_css("default")
        def compose(self):
            yield block_cls(core_mod, id="block-under-test")

    async def _run():
        app = _One()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            if before_render is not None:
                before_render(app)
            await pilot.pause()
            lines = ["".join(seg.text for seg in strip).rstrip()
                     for strip in app.screen._compositor.render_strips()]
            footers = {}
            for w in app.query(".footer-lbl"):
                footers[str(w.id)] = (w.region, w.parent.region)
            result["lines"] = lines
            result["footers"] = footers

    asyncio.run(_run())
    return result["lines"], result["footers"]


import core as core_mod


@pytest.mark.parametrize("module,cls_name", [
    ("tui.blocks.ship_info",  "ShipInfoBlock"),
    ("tui.blocks.navigation", "NavigationBlock"),
    ("tui.blocks.commander",  "CommanderBlock"),
])
def test_no_footer_control_is_laid_out_off_screen(module, cls_name):
    """Every footer control must sit inside the footer it belongs to.

    The Cargo footer's "Gal. Avg" control shipped invisible: cargo-target-btn
    computed to the full 80-column width, so Gal. Avg was placed at x=81 and
    the target-name label at x=161.  The navigation footer escaped only
    because it set width:auto per id.
    """
    import importlib
    cls = getattr(importlib.import_module(module), cls_name)
    _, footers = _render_block(cls)
    assert footers, f"{cls_name} exposes no .footer-lbl controls to check"
    for wid, (region, parent) in footers.items():
        assert region.right <= parent.right, (
            f"{wid} is drawn to x={region.right}, past its footer's "
            f"right edge at {parent.right} — it will never be visible")


def test_the_cargo_footer_draws_both_of_its_controls():
    """The specific regression: Set Target rendered, Gal. Avg did not."""
    from tui.blocks.ship_info import ShipInfoBlock

    lines, _ = _render_block(
        ShipInfoBlock,
        before_render=lambda app: app.query_one(ShipInfoBlock)._refresh_cargo())
    footer = [ln for ln in lines if ">> Set Target" in ln]
    assert footer, "the Cargo footer did not render at all"
    assert "Gal. Avg" in footer[0], (
        f"Gal. Avg is missing from the rendered footer: {footer[0]!r}")


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


# ── Ship cargo survives a journal roll ────────────────────────────────────────

def test_capacity_is_recovered_from_an_earlier_journal(tmp_path):
    """Loadout is only written on the launch that produced it.

    Resume a save while already in an SRV and the new journal has no Loadout
    and no Ship cargo event at all — only SRV ones — so capacity was unknown
    for the whole session and the Totals row read as a dash.
    """
    import importlib.util
    import queue

    from core.plugin_loader import BasePlugin
    from core.state import MonitorState

    (tmp_path / "Journal.2026-09-07T005842.01.log").write_text("\n".join(
        json.dumps(e) for e in [
            {"timestamp": "2026-09-07T06:00:00Z", "event": "LoadGame"},
            {"timestamp": "2026-09-07T06:00:01Z", "event": "Loadout",
             "CargoCapacity": 300},
        ]) + "\n", encoding="utf-8")
    (tmp_path / "Journal.2026-09-07T124429.01.log").write_text("\n".join(
        json.dumps(e) for e in [
            {"timestamp": "2026-09-07T17:46:02Z", "event": "LoadGame"},
            {"timestamp": "2026-09-07T17:46:15Z", "event": "Cargo",
             "Vessel": "SRV", "Count": 0},
        ]) + "\n", encoding="utf-8")

    spec = importlib.util.spec_from_file_location(
        "comp_cargo_boot", ROOT / "components" / "cargo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = next(getattr(mod, n) for n in dir(mod)
               if isinstance(getattr(mod, n), type)
               and issubclass(getattr(mod, n), BasePlugin)
               and getattr(mod, n) is not BasePlugin)

    class Storage:
        def read_json(self, name=None):
            return {}

        def write_json(self, data, name=None):
            pass

    class Core:
        gui_queue = queue.Queue()
        journal_dir = str(tmp_path)
        _plugins: dict = {}

        def register_block(self, *a, **k):
            pass

        def register_session_provider(self, provider):
            pass

    core = Core()
    core.state = MonitorState()
    plugin = cls()
    plugin.storage = Storage()
    plugin.core = core
    plugin.on_load(core)

    assert core.state.cargo_capacity == 300


def test_hold_recovery_replays_transfers_after_a_count_only_event():
    """The newest ship cargo event is often count-only.

    A real capture ended with "Count: 71" and no inventory, while transfers
    afterwards brought the hold to 110.  Picking a single event found an
    older, emptied snapshot and reported nothing aboard.
    """
    import importlib.util
    import queue
    import tempfile

    from core.plugin_loader import BasePlugin
    from core.state import MonitorState

    tmp = Path(tempfile.mkdtemp())
    (tmp / "Journal.2026-09-07T005842.01.log").write_text("\n".join(
        json.dumps(e) for e in [
            {"timestamp": "2026-09-07T06:00:00Z", "event": "Loadout",
             "CargoCapacity": 300},
            # Baseline: emptied hold, with an inventory.
            {"timestamp": "2026-09-07T06:11:55Z", "event": "Cargo",
             "Vessel": "Ship", "Count": 0, "Inventory": []},
            {"timestamp": "2026-09-07T06:44:15Z", "event": "CargoTransfer",
             "Transfers": [{"Type": "osmium", "Count": 71,
                            "Direction": "toship"}]},
            # Count-only, and not the final state.
            {"timestamp": "2026-09-07T08:08:36Z", "event": "Cargo",
             "Vessel": "Ship", "Count": 71},
            {"timestamp": "2026-09-07T08:49:31Z", "event": "CargoTransfer",
             "Transfers": [{"Type": "osmium", "Count": 39,
                            "Direction": "toship"}]},
        ]) + "\n", encoding="utf-8")

    spec = importlib.util.spec_from_file_location(
        "comp_cargo_replay", ROOT / "components" / "cargo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = next(getattr(mod, n) for n in dir(mod)
               if isinstance(getattr(mod, n), type)
               and issubclass(getattr(mod, n), BasePlugin)
               and getattr(mod, n) is not BasePlugin)

    class Storage:
        def read_json(self, name=None):
            # A poisoned save, written during a session when the hold was
            # not yet known — the journals must still win.
            return {"capacity": 300, "items": {}} if name == "cargo.json" else {}

        def write_json(self, data, name=None):
            pass

    class Core:
        gui_queue = queue.Queue()
        journal_dir = str(tmp)
        _plugins: dict = {}

        def register_block(self, *a, **k):
            pass

        def register_session_provider(self, provider):
            pass

    core = Core()
    core.state = MonitorState()
    plugin = cls()
    plugin.storage = Storage()
    plugin.core = core
    plugin.on_load(core)

    assert core.state.cargo_capacity == 300
    assert core.state.cargo_items["osmium"]["count"] == 110


def test_ship_hold_is_persisted_and_restored():
    """The hold's true contents are often the result of transfers rather than
    any single Cargo event, so the last event on disk can say empty while
    tonnes were moved aboard afterwards."""
    plugin, state = _cargo_plugin()

    store: dict = {}

    class Storage:
        def read_json(self, name=None):
            return store.get(name or "data.json", {})

        def write_json(self, data, name=None):
            store[name or "data.json"] = data

    plugin.storage = Storage()
    plugin._saved_cargo = {}
    state.cargo_capacity = 300

    plugin.on_event({"event": "CargoTransfer", "Transfers": [
        {"Type": "osmium", "Count": 71, "Direction": "toship"}]}, state)

    saved = store.get("cargo.json")
    assert saved["capacity"] == 300
    assert saved["items"]["osmium"]["count"] == 71


# ── Resuming in a surface vehicle ─────────────────────────────────────────────

def _commander_plugin():
    import importlib.util
    import types

    from core.plugin_loader import BasePlugin
    from core.state import MonitorState

    spec = importlib.util.spec_from_file_location(
        "comp_cmdr_srv", ROOT / "components" / "commander.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = next(getattr(mod, n) for n in dir(mod)
               if isinstance(getattr(mod, n), type)
               and issubclass(getattr(mod, n), BasePlugin)
               and getattr(mod, n) is not BasePlugin)

    state = MonitorState()
    state.ship_name = "FOSSOR"
    state.ship_ident = "T11-FO"
    state.pilot_ship = "Type-11 Prospector"

    class Core:
        gui_queue = None
        _plugins: dict = {}
        notify_levels: dict = {}
        active_session = types.SimpleNamespace(fuel_check_time=0,
                                              fuel_check_level=0)

        class emitter:
            @staticmethod
            def emit(**kwargs):
                pass

        def register_session_provider(self, provider):
            pass

    plugin = cls()
    plugin.core = Core()
    plugin.core.state = state
    return plugin, state


RESUME_IN_SRV = {
    "timestamp": "2026-09-07T17:46:02Z", "event": "LoadGame",
    "Commander": "SILVAN HOLLOWAY", "Ship": "MEV_Rhino",
    "Ship_Localised": "SRV Rhino", "ShipID": 36,
    "ShipName": "", "ShipIdent": "", "FID": "F1", "_logtime": None,
}


def test_resuming_in_an_srv_keeps_the_ship_identity():
    """LoadGame reports the *vehicle* when resuming in one, with ShipName and
    ShipIdent blank.  Taking that as the ship renamed the commander's vessel
    "SRV Rhino" in every window that names it."""
    plugin, state = _commander_plugin()
    try:
        plugin.on_event(RESUME_IN_SRV, state)
    except Exception:
        pass

    assert state.pilot_ship == "Type-11 Prospector"
    assert state.ship_name == "FOSSOR"
    assert state.ship_ident == "T11-FO"


def test_resuming_in_an_srv_sets_the_vessel_mode():
    """No LaunchSRV follows, so nothing else would ever correct it."""
    plugin, state = _commander_plugin()
    try:
        plugin.on_event(RESUME_IN_SRV, state)
    except Exception:
        pass

    assert state.vessel_mode == "srv"
    assert state.srv_type == "SRV Rhino"


def test_resuming_in_the_ship_still_sets_ship_mode():
    plugin, state = _commander_plugin()
    event = dict(RESUME_IN_SRV, Ship="type9_military",
                 Ship_Localised="Type-11 Prospector",
                 ShipName="FOSSOR", ShipIdent="T11-FO")
    try:
        plugin.on_event(event, state)
    except Exception:
        pass

    assert state.vessel_mode == "ship"
    assert state.pilot_ship == "Type-11 Prospector"

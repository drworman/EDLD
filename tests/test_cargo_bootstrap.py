"""
tests/test_cargo_bootstrap.py — the hold EDLD shows after a restart.

The hold cannot be read from any single journal event, so it is rebuilt by
replaying the recent journals: the last event carrying a manifest is the
baseline, and everything that moved cargo afterwards is applied on top.

The replay used to skip sales, on the stated grounds that a sale emits its
own cargo event which resets the baseline.  It does emit one — but in a real
capture that event carries no Inventory.  Selling 120 t of Tritium produced
``Count: 127`` with no manifest, and selling the remaining Low Temperature
Diamonds produced ``Count: 0`` with no manifest.  Neither reset anything, so
both cargoes survived every restart and a later Thortveitite transfer was
added on top of goods sold hours earlier: 326 t shown, 79 t aboard.

The sequence below is that capture, event for event.
"""

from __future__ import annotations

import importlib.util
import json
import queue
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── The capture ───────────────────────────────────────────────────────────────

def cargo(vessel, count, inventory=None, ts="2026-09-13T06:00:00Z"):
    ev = {"timestamp": ts, "event": "Cargo", "Vessel": vessel, "Count": count}
    if inventory is not None:
        ev["Inventory"] = inventory
    return ev


REAL_SEQUENCE = [
    {"timestamp": "2026-09-13T06:02:00Z", "event": "Loadout",
     "Ship": "type9_military", "CargoCapacity": 1024},
    # The last event that carries a manifest.  Everything after it is inferred.
    cargo("Ship", 247, [
        {"Name": "lowtemperaturediamond",
         "Name_Localised": "Low Temp. Diamonds", "Count": 127, "Stolen": False},
        {"Name": "tritium", "Name_Localised": "Tritium",
         "Count": 120, "Stolen": False},
    ], ts="2026-09-13T06:03:16Z"),
    {"timestamp": "2026-09-13T06:15:43Z", "event": "MarketSell",
     "Type": "tritium", "Type_Localised": "Tritium",
     "Count": 120, "SellPrice": 56740, "TotalSale": 6808800},
    cargo("Ship", 127, ts="2026-09-13T06:15:45Z"),          # no manifest
    {"timestamp": "2026-09-13T06:15:58Z", "event": "MarketSell",
     "Type": "lowtemperaturediamond", "Type_Localised": "Low Temp. Diamonds",
     "Count": 127, "SellPrice": 291305, "TotalSale": 36995735},
    cargo("Ship", 0, ts="2026-09-13T06:16:00Z"),            # no manifest
    # SRV mining, then two transfers into the ship.
    cargo("SRV", 67, ts="2026-09-13T08:56:33Z"),
    {"timestamp": "2026-09-13T09:00:35Z", "event": "CargoTransfer",
     "Transfers": [{"Type": "thortveitite", "Type_Localised": "Thortveitite",
                    "Count": 67, "Direction": "toship"}]},
    cargo("SRV", 0, ts="2026-09-13T09:00:38Z"),
    {"timestamp": "2026-09-13T09:03:42Z", "event": "CargoTransfer",
     "Transfers": [{"Type": "thortveitite", "Type_Localised": "Thortveitite",
                    "Count": 12, "Direction": "toship"}]},
    cargo("SRV", 0, ts="2026-09-13T09:03:45Z"),
    {"timestamp": "2026-09-13T09:03:57Z", "event": "Shutdown"},
]


# ── Harness ───────────────────────────────────────────────────────────────────

def bootstrap(tmp_path, events, cargo_json=None):
    """Run the cargo component's startup replay over a written journal."""
    from core.plugin_loader import PluginStorage, _make_sandboxed_open
    from core.state import MonitorState
    import core.state as core_state

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    data_dir = tmp_path / "cmdr"
    (data_dir / "data").mkdir(parents=True, exist_ok=True)
    core_state.cmdr_data_dir = lambda: data_dir

    (journal_dir / "Journal.2026-09-13T060000.01.log").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    # Cargo.json on disk is always the *current* one, never the historical
    # one a replayed event was written beside.  After an SRV session it names
    # the SRV, which is why the replay must not lean on it.
    (journal_dir / "Cargo.json").write_text(json.dumps(
        cargo_json or {"event": "Cargo", "Vessel": "SRV",
                       "Count": 0, "Inventory": []}), encoding="utf-8")

    import builtins
    spec = importlib.util.spec_from_file_location(
        "_test_plugin_cargo", ROOT / "components" / "cargo.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__builtins__ = vars(builtins).copy()
    mod.__builtins__["open"] = _make_sandboxed_open("cargo")
    sys.modules["_test_plugin_cargo"] = mod
    spec.loader.exec_module(mod)

    class _Core:
        gui_queue = queue.Queue()
        _plugins: dict = {}
        def __init__(self):
            self.journal_dir = str(journal_dir)
            self.state = MonitorState()
        def register_block(self, *a, **k):
            pass
        def register_session_provider(self, p):
            pass

    core = _Core()
    plugin = mod.CargoPlugin()
    plugin.storage = PluginStorage("cargo")
    plugin.core = core
    plugin.on_load(core)
    core.state._test_plugin = plugin
    return core.state


def held(state):
    return {v.get("name_local") or k: v["count"]
            for k, v in (state.cargo_items or {}).items()}


# ── The regression ────────────────────────────────────────────────────────────

def test_sold_cargo_does_not_come_back_after_a_restart(tmp_path):
    state = bootstrap(tmp_path, REAL_SEQUENCE)
    assert held(state) == {"Thortveitite": 79}


def test_the_tonnage_matches_what_is_aboard(tmp_path):
    """326/1024 was what the panel read.  79 is what was in the hold."""
    state = bootstrap(tmp_path, REAL_SEQUENCE)
    assert sum(v["count"] for v in state.cargo_items.values()) == 79
    assert state.cargo_capacity == 1024


def test_a_manifestless_zero_empties_the_hold(tmp_path):
    """The one count-only form whose contents are not in doubt."""
    events = REAL_SEQUENCE[:6]      # up to and including the Count: 0
    assert bootstrap(tmp_path, events).cargo_items == {}


def test_a_manifestless_nonzero_count_is_left_alone(tmp_path):
    """The journal does not say what such a count is made of, and Cargo.json
    on disk belongs to the present, not to the replayed moment.  Guessing is
    worse than carrying the last known manifest forward."""
    events = REAL_SEQUENCE[:4]      # baseline, one sale, then Count: 127
    assert held(bootstrap(tmp_path, events)) == {"Low Temp. Diamonds": 127}


def test_a_purchase_is_replayed_too(tmp_path):
    events = REAL_SEQUENCE[:2] + [
        {"timestamp": "2026-09-13T06:20:00Z", "event": "MarketBuy",
         "Type": "gold", "Type_Localised": "Gold", "Count": 40},
    ]
    assert held(bootstrap(tmp_path, events)) == {
        "Low Temp. Diamonds": 127, "Tritium": 120, "Gold": 40}


def test_jettisoned_cargo_is_replayed_too(tmp_path):
    events = REAL_SEQUENCE[:2] + [
        {"timestamp": "2026-09-13T06:20:00Z", "event": "EjectCargo",
         "Type": "tritium", "Type_Localised": "Tritium", "Count": 120},
    ]
    assert held(bootstrap(tmp_path, events)) == {"Low Temp. Diamonds": 127}


def test_market_events_before_any_manifest_are_ignored(tmp_path):
    """With no baseline there is nothing to subtract from, and inventing one
    from a sale would report a hold that was never seen."""
    events = [
        {"timestamp": "2026-09-13T06:15:43Z", "event": "MarketSell",
         "Type": "tritium", "Count": 120},
    ]
    assert bootstrap(tmp_path, events).cargo_items == {}


def test_srv_cargo_events_never_touch_the_ship(tmp_path):
    """An SRV Count: 0 emptying the ship's hold is a bug this file has seen
    before; the vessel check must survive the new branches beside it."""
    events = REAL_SEQUENCE[:2] + [cargo("SRV", 0, ts="2026-09-13T06:30:00Z")]
    assert held(bootstrap(tmp_path, events)) == {
        "Low Temp. Diamonds": 127, "Tritium": 120}


# ── Column headings ───────────────────────────────────────────────────────────

def test_the_headings_sit_over_the_columns_they_name():
    """Three unlabelled numbers, the middle one per tonne and the last a line
    total, is not something a reader should have to infer."""
    from core.ui_helpers import cargo_cols, cargo_header_cols, cargo_totals_cols

    heading = cargo_header_cols()
    row = cargo_cols(79, 484_000, 38_200_000)
    totals = cargo_totals_cols("79/1024 t", 38_200_000)

    assert len(heading) == len(row) == len(totals)
    for label, cell in zip(("Tonnes", "Price", "Value"),
                           ("79 t", "484K cr", "38.2M cr")):
        assert heading.index(label) + len(label) == row.index(cell) + len(cell), \
            f"'{label}' does not end where '{cell}' does:\n{heading}\n{row}"


def test_both_front_ends_head_the_manifest():
    """Parity: a labelled table in one window and an unlabelled one in the
    other is worse than neither being labelled."""
    for path in (ROOT / "tui" / "blocks" / "ship_info.py",
                 ROOT / "gui" / "blocks" / "ship_info.py"):
        src = path.read_text(encoding="utf-8")
        assert src.count("cargo_header_cols()") == 2, (
            f"{path.name}: expected a heading row for the ship's hold and "
            f"the SRV's, found {src.count('cargo_header_cols()')}")
        assert '"Commodity"' in src


# ── Which journals get replayed ───────────────────────────────────────────────

def test_the_replay_picks_journals_by_name_not_mtime(tmp_path):
    """Elite's journal names are ISO timestamps and sort chronologically on
    their own.  Mtimes do not survive a file sync between machines: in a real
    capture the four newest by mtime were from May and the newest by name from
    September, so the replay ran over four-month-old journals and reported
    their hold instead of the current one.  Once an empty result was allowed
    to stand rather than falling through to the persisted copy, that surfaced
    as no cargo at all after startup.
    """
    import os

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    (tmp_path / "cmdr" / "data").mkdir(parents=True)

    def write(name, events, mtime):
        path = journal_dir / name
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n",
                        encoding="utf-8")
        os.utime(path, (mtime, mtime))

    # Old by name, but touched most recently — a sync, a backup, a copy.
    write("Journal.2026-05-19T003353.01.log", [
        {"timestamp": "2026-05-19T00:34:00Z", "event": "Loadout",
         "Ship": "sidewinder", "CargoCapacity": 4},
        cargo("Ship", 0, [], ts="2026-05-19T00:34:01Z"),
    ], mtime=2_000_000_000)

    # Newest by name, oldest by mtime.
    write("Journal.2026-09-13T204826.01.log", [
        {"timestamp": "2026-09-14T01:50:46Z", "event": "Loadout",
         "Ship": "type9_military", "CargoCapacity": 1024},
        cargo("Ship", 382, [{"Name": "monazite", "Name_Localised": "Monazite",
                             "Count": 382, "Stolen": False}],
              ts="2026-09-14T01:50:48Z"),
    ], mtime=1_000_000_000)

    from core.plugin_loader import PluginStorage, _make_sandboxed_open
    from core.state import MonitorState
    import core.state as core_state
    core_state.cmdr_data_dir = lambda: tmp_path / "cmdr"

    import builtins
    spec = importlib.util.spec_from_file_location(
        "_test_plugin_cargo_order", ROOT / "components" / "cargo.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__builtins__ = vars(builtins).copy()
    mod.__builtins__["open"] = _make_sandboxed_open("cargo")
    sys.modules["_test_plugin_cargo_order"] = mod
    spec.loader.exec_module(mod)

    class _Core:
        gui_queue = queue.Queue()
        _plugins: dict = {}
        def __init__(self):
            self.journal_dir = str(journal_dir)
            self.state = MonitorState()
        def register_block(self, *a, **k):
            pass
        def register_session_provider(self, p):
            pass

    core = _Core()
    plugin = mod.CargoPlugin()
    plugin.storage = PluginStorage("cargo")
    plugin.core = core
    plugin.on_load(core)

    assert held(core.state) == {"Monazite": 382}, \
        "the replay read the wrong journal"
    assert core.state.cargo_capacity == 1024, \
        "capacity came from the wrong journal too"


# ── Cargo.json has the last word ──────────────────────────────────────────────

def snap(vessel, count, inventory, ts):
    return {"timestamp": ts, "event": "Cargo", "Vessel": vessel,
            "Count": count, "Inventory": inventory}


def test_an_srv_hold_is_restored_at_startup(tmp_path):
    """Nothing else seeds it.  A mining session is left in the SRV, and on the
    next launch the SRV manifest read empty until the next refined chunk
    landed — with 11 t of Monazite aboard and Cargo.json saying so."""
    state = bootstrap(tmp_path, REAL_SEQUENCE[:2], cargo_json=snap(
        "SRV", 11, [{"Name": "monazite", "Count": 11, "Stolen": 0}],
        "2026-09-14T05:57:55Z"))
    assert state.srv_cargo_count == 11
    assert list(state.srv_cargo_items) == ["monazite"]
    assert state.srv_cargo_items["monazite"]["count"] == 11


def test_an_srv_snapshot_never_lands_in_the_ships_hold(tmp_path):
    """Reading this file blindly is what once put SRV ore in the ship."""
    state = bootstrap(tmp_path, REAL_SEQUENCE[:2], cargo_json=snap(
        "SRV", 11, [{"Name": "monazite", "Count": 11, "Stolen": 0}],
        "2026-09-14T05:57:55Z"))
    assert held(state) == {"Low Temp. Diamonds": 127, "Tritium": 120}


def test_the_ships_hold_is_not_this_functions_business(tmp_path):
    """on_load already applies a Ship snapshot over the replay.  This guards
    against a second, unguarded application creeping back in here."""
    state = bootstrap(tmp_path, REAL_SEQUENCE, cargo_json=snap(
        "SRV", 11, [{"Name": "monazite", "Count": 11, "Stolen": 0}],
        "2026-09-14T05:57:55Z"))
    assert held(state) == {"Thortveitite": 79}
    assert state.srv_cargo_count == 11


def test_an_unreadable_snapshot_is_no_snapshot_at_all(tmp_path):
    """A half-written file must leave the replay standing, not empty the hold."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_test_cargo_snap", ROOT / "components" / "cargo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "Cargo.json").write_text("{ not json", encoding="utf-8")
    assert mod._read_cargo_snapshot(tmp_path) is None
    assert mod._read_cargo_snapshot(tmp_path / "nope") is None


# ── Following Cargo.json live ─────────────────────────────────────────────────
#
# Cargo.json is a live file: the game rewrites it whenever the hold changes.
# EDLD read it once at startup and thereafter only when a journal event said
# to, so the manifest was only ever as fresh as the journal — and journals lag.
# In a real capture the newest journal stood still for five hours while
# Cargo.json tracked 620 t of ore through the hold, and the ship read empty
# the whole time.

def plugin_on(tmp_path, events, cargo_json):
    state = bootstrap(tmp_path, events, cargo_json=cargo_json)
    return state, sys.modules["_test_plugin_cargo"]


def rewrite(tmp_path, payload):
    (tmp_path / "journal" / "Cargo.json").write_text(json.dumps(payload),
                                                     encoding="utf-8")


def test_the_hold_follows_cargo_json_with_no_journal_event(tmp_path):
    state = bootstrap(tmp_path, REAL_SEQUENCE[:2], cargo_json=snap(
        "Ship", 0, [], "2026-09-14T01:50:48Z"))
    plugin = state._test_plugin
    assert held(state) == {}

    rewrite(tmp_path, snap("Ship", 620, [
        {"Name": "monazite", "Name_Localised": "Monazite",
         "Count": 598, "Stolen": 0},
        {"Name": "thortveitite", "Name_Localised": "Thortveitite",
         "Count": 22, "Stolen": 0}], "2026-09-14T06:51:00Z"))
    plugin._poll_cargo_json()
    assert held(state) == {"Monazite": 598, "Thortveitite": 22}


def test_an_srv_rewrite_never_reaches_the_ships_hold(tmp_path):
    state = bootstrap(tmp_path, REAL_SEQUENCE[:2], cargo_json=snap(
        "Ship", 0, [], "2026-09-14T01:50:48Z"))
    plugin = state._test_plugin
    rewrite(tmp_path, snap("SRV", 11, [
        {"Name": "monazite", "Count": 11, "Stolen": 0}],
        "2026-09-14T05:57:55Z"))
    plugin._poll_cargo_json()
    assert held(state) == {}
    assert state.srv_cargo_count == 11


def test_an_unchanged_file_costs_nothing(tmp_path):
    """Polled every two seconds beside the market watcher — it must not
    re-read and re-push on every tick."""
    state = bootstrap(tmp_path, REAL_SEQUENCE[:2], cargo_json=snap(
        "Ship", 0, [], "2026-09-14T01:50:48Z"))
    plugin = state._test_plugin
    while not plugin.core.gui_queue.empty():
        plugin.core.gui_queue.get()
    for _ in range(5):
        plugin._poll_cargo_json()
    assert plugin.core.gui_queue.empty()


def test_a_vanished_file_is_not_an_error(tmp_path):
    state = bootstrap(tmp_path, REAL_SEQUENCE[:2], cargo_json=snap(
        "Ship", 0, [], "2026-09-14T01:50:48Z"))
    plugin = state._test_plugin
    (tmp_path / "journal" / "Cargo.json").unlink()
    plugin._poll_cargo_json()
    assert held(state) == {}

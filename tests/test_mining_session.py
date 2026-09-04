"""
tests/test_mining_session.py — mining session tracking and summary layout.

The gaps closed here came from comparing EDLD's mining component against the
EDMC Mining Analytics plugin.  EDLD already tracked tonnage, TPH, RPM, yield
distribution and limpet counts; what it had no notion of was:

  * how many limpets are left (the thing that ends a run)
  * how full the hold is (the other thing that ends a run)
  * which ring this is, and whether it is worth being in
  * raw materials picked up alongside the ore

Reserve level and hotspots matter most: 180 t is excellent in a depleted ring
and mediocre in a pristine one, and without that context the tonnage figures
mean very little to anyone reading them.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_mining():
    """Load the component by path, the way the plugin loader does."""
    spec = importlib.util.spec_from_file_location(
        "comp_mining", ROOT / "components" / "mining.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mining = _load_mining()

RING = "Hyades Sector DB-X d1-112 A 1 A Ring"


class FakeState:
    def __init__(self):
        self.event_time = datetime.now(timezone.utc)
        self.pilot_body = RING
        self.cargo_capacity = 512
        self.cargo_items = {"painite": {"count": 276}}
        self.cargo_mean_prices = {"painite": 480_000}


class FakeCore:
    def __init__(self, state):
        self.state = state
        self.gui_queue = None
        self._plugins = {}

    def register_session_provider(self, provider):
        pass


@pytest.fixture
def plugin():
    state = FakeState()
    p = mining.ActivityMiningPlugin()
    p.on_load(FakeCore(state))
    p.state = state
    return p


def _rows_by_label(rows) -> dict:
    return {r["label"]: r for r in rows}


# ── Limpet stock ──────────────────────────────────────────────────────────────

def test_limpets_remaining_read_from_cargo(plugin):
    plugin.on_event({"event": "Cargo", "Inventory": [
        {"Name": "drones", "Count": 400}]}, plugin.state)
    assert plugin.limpets_remaining == 400
    assert plugin.limpets_start == 400


def test_limpet_consumption_tracked_across_cargo_updates(plugin):
    for count in (400, 260, 140):
        plugin.on_event({"event": "Cargo", "Inventory": [
            {"Name": "drones", "Count": count}]}, plugin.state)
    plugin.on_event({"event": "LaunchDrone", "Type": "Prospector"}, plugin.state)

    row = _rows_by_label(plugin.get_summary_rows())["Limpets left"]
    assert row["value"] == "140"
    assert "260 used" in row["rate"]


def test_restocking_does_not_make_consumption_negative(plugin):
    """Buying more limpets mid-run must not produce a negative used count."""
    for count in (400, 140, 600):
        plugin.on_event({"event": "Cargo", "Inventory": [
            {"Name": "drones", "Count": count}]}, plugin.state)
    plugin.on_event({"event": "LaunchDrone", "Type": "Prospector"}, plugin.state)
    row = _rows_by_label(plugin.get_summary_rows())["Limpets left"]
    assert row["value"] == "600"
    assert row["rate"] is None or "-" not in row["rate"]


def test_cargo_event_without_inventory_is_ignored(plugin):
    """The summary-form Cargo event carries no Inventory; it is not zero limpets."""
    plugin.on_event({"event": "Cargo", "Inventory": [
        {"Name": "drones", "Count": 400}]}, plugin.state)
    plugin.on_event({"event": "Cargo", "Count": 276}, plugin.state)
    assert plugin.limpets_remaining == 400


def test_no_limpet_row_before_any_mining(plugin):
    plugin.on_event({"event": "Cargo", "Inventory": [
        {"Name": "drones", "Count": 400}]}, plugin.state)
    assert "Limpets left" not in _rows_by_label(plugin.get_summary_rows())


# ── Ring context ──────────────────────────────────────────────────────────────

def test_reserve_level_captured_from_scan(plugin):
    plugin.on_event({"event": "Scan", "ReserveLevel": "PristineResources",
                     "Rings": [{"Name": RING, "RingClass": "eRingClass_Metalic"}]},
                    plugin.state)
    assert plugin.reserve_level == "Pristine"
    assert plugin.ring_type == "Metallic"
    assert plugin.ring_name == RING


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("eRingClass_Metalic", "Metallic"),      # the journal's one-l spelling
        ("eRingClass_MetalRich", "Metal-rich"),
        ("eRingClass_Icy", "Icy"),
        ("eRingClass_Rocky", "Rocky"),
    ],
)
def test_ring_class_spellings(raw, expected):
    assert mining._ring_class(raw) == expected


def test_hotspots_captured_from_surface_scan(plugin):
    plugin.on_event({"event": "SAASignalsFound", "BodyName": RING, "Signals": [
        {"Type": "Painite", "Count": 2},
        {"Type": "Platinum", "Count": 1}]}, plugin.state)
    assert plugin.hotspots == {"Painite": 2, "Platinum": 1}


def test_ring_context_line_leads_with_reserves(plugin):
    plugin.on_event({"event": "Scan", "ReserveLevel": "PristineResources",
                     "Rings": [{"Name": RING, "RingClass": "eRingClass_Metalic"}]},
                    plugin.state)
    plugin.on_event({"event": "SAASignalsFound", "BodyName": RING, "Signals": [
        {"Type": "Painite", "Count": 2}]}, plugin.state)
    ctx = plugin.ring_context()
    assert ctx.startswith("Pristine")
    assert "Metallic" in ctx and "Painite x2" in ctx


def test_ring_context_empty_when_unknown(plugin):
    assert plugin.ring_context() == ""


def test_scan_of_a_different_body_does_not_claim_our_ring(plugin):
    plugin.on_event({"event": "Scan", "ReserveLevel": "DepletedResources",
                     "Rings": [{"Name": "Some Other Ring",
                                "RingClass": "eRingClass_Icy"}]}, plugin.state)
    assert plugin.ring_type == ""


# ── Materials ─────────────────────────────────────────────────────────────────

def test_materials_collected_accumulate(plugin):
    for _ in range(3):
        plugin.on_event({"event": "MaterialCollected", "Name": "iron",
                         "Name_Localised": "Iron", "Count": 2}, plugin.state)
    assert plugin.materials_collected == {"Iron": 6}


# ── Cargo fill ────────────────────────────────────────────────────────────────

def test_cargo_fill_reported(plugin):
    plugin.on_event({"event": "MiningRefined", "_logtime": plugin.state.event_time,
                     "Type": "$painite_name;", "Type_Localised": "Painite"},
                    plugin.state)
    row = _rows_by_label(plugin.get_summary_rows())["Cargo"]
    assert row["value"] == "276 / 512 t"
    assert "54% full" in row["rate"]


def test_cargo_fill_absent_without_capacity(plugin):
    plugin.state.cargo_capacity = 0
    assert plugin.cargo_fill() is None


# ── Prospecting hit rate ──────────────────────────────────────────────────────

def test_high_content_hit_rate_in_summary(plugin):
    for i in range(10):
        content = "$AsteroidMaterialContent_High;" if i < 3 else "$AsteroidMaterialContent_Low;"
        plugin.on_event({"event": "ProspectedAsteroid",
                         "_logtime": plugin.state.event_time,
                         "Content": content, "Remaining": 100.0,
                         "Materials": [{"Name": "painite", "Proportion": 20.0 + i}]},
                        plugin.state)
    assert "30% high" in _rows_by_label(plugin.get_summary_rows())["Prospected"]["rate"]


# ── Summary layout ────────────────────────────────────────────────────────────

def test_wide_value_does_not_stretch_the_column():
    """A long ring description must not right-shift every numeric column.

    The Ring row is far wider than any figure in the block; before the width
    cap it set the column width and pushed all the numbers across the line.
    """
    from core.emit import emit_summary

    class State:
        event_time = datetime.now(timezone.utc)
        pilot_name = "Calursus"
        pilot_ship = "Krait Mk II"
        pilot_mode = "Solo"
        pilot_system = "Hyades Sector DB-X d1-112"
        pilot_body = RING
        fuel_current = 20.4
        fuel_tank_size = 32.0
        fuel_burn_rate = 6.1

    class Provider:
        ACTIVITY_TAB_TITLE = "Mining"

        def has_activity(self):
            return True

        def get_summary_rows(self):
            return [
                {"label": "Tonnes refined", "value": "276 t", "rate": "180.0 t/hr"},
                {"label": "Ring", "value": "Pristine · Metallic · Painite x2, Platinum",
                 "rate": None},
            ]

    class Session:
        core = None

        def session_duration_seconds(self):
            return 5520.0

    captured = {}

    class Emitter:
        def emit(self, msg_term, msg_discord, **kw):
            captured["text"] = msg_term

    emit_summary(Emitter(), State, [Provider()], Session())
    lines = captured["text"].splitlines()

    tonnes = next(l for l in lines if "Tonnes refined" in l)
    # "276 t" must sit close to its label, not be pushed out by the Ring row.
    assert tonnes.index("276 t") - tonnes.index("Tonnes refined") < 30


def test_summary_header_carries_commander_and_location():
    from core.emit import emit_summary

    class State:
        event_time = datetime.now(timezone.utc)
        pilot_name = "Calursus"
        pilot_ship = "Krait Mk II"
        pilot_mode = "Solo"
        pilot_system = "Deciat"
        pilot_body = "Deciat 6 A Ring"

    class Provider:
        ACTIVITY_TAB_TITLE = "Mining"

        def has_activity(self):
            return True

        def get_summary_rows(self):
            return [{"label": "Tonnes refined", "value": "276 t", "rate": None}]

    class Session:
        core = None

        def session_duration_seconds(self):
            return 5520.0

    captured = {}

    class Emitter:
        def emit(self, msg_term, msg_discord, **kw):
            captured["text"] = msg_term

    emit_summary(Emitter(), State, [Provider()], Session())
    text = captured["text"]
    assert "CMDR Calursus" in text
    assert "Krait Mk II" in text
    assert "Deciat / Deciat 6 A Ring" in text


def test_income_reaches_the_summary():
    """Income was tracked by the income plugin but never appeared in the summary."""
    from core.emit import emit_summary

    class State:
        event_time = datetime.now(timezone.utc)
        pilot_name = "Calursus"
        pilot_ship = "Krait"
        pilot_mode = "Solo"
        pilot_system = "Deciat"
        pilot_body = None

    class Income:
        total_income = 132_480_000

    class Core:
        _plugins = {"income": Income()}

    class Provider:
        ACTIVITY_TAB_TITLE = "Mining"

        def has_activity(self):
            return True

        def get_summary_rows(self):
            return [{"label": "Tonnes refined", "value": "276 t", "rate": None}]

    class Session:
        core = Core()

        def session_duration_seconds(self):
            return 3600.0

    captured = {}

    class Emitter:
        def emit(self, msg_term, msg_discord, **kw):
            captured["text"] = msg_term

    emit_summary(Emitter(), State, [Provider()], Session())
    assert "Income" in captured["text"]
    assert "132.48M" in captured["text"]
    assert "/hr" in captured["text"]

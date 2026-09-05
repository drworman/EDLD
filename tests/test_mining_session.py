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
    assert plugin.mining_body == RING


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


def test_context_line_leads_with_the_body(plugin):
    plugin.on_event({"event": "Scan", "ReserveLevel": "PristineResources",
                     "Rings": [{"Name": RING, "RingClass": "eRingClass_Metalic"}]},
                    plugin.state)
    plugin.on_event({"event": "SAASignalsFound", "BodyName": RING, "Signals": [
        {"Type": "Painite", "Count": 2}]}, plugin.state)
    ctx = plugin.ring_context()
    # The body is the thing being described, so it leads.
    assert ctx.startswith(RING)
    assert "Pristine" in ctx and "Metallic" in ctx and "Painite x2" in ctx


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


# ── Surface signals that are not hotspots ─────────────────────────────────────

def test_surface_poi_signals_are_not_hotspots(plugin):
    """A planetary surface scan returns two unrelated families of signal.

    Human settlements, biological and geological sites, and the planetary
    mining location marker all arrive through SAASignalsFound alongside real
    commodity hotspots.  Counting them produced rows like "Human 3 hotspots"
    in the mining panel.
    """
    plugin.on_event({"event": "SAASignalsFound", "BodyName": "Ega 3 d", "Signals": [
        {"Type": "$PlanetaryMiningLocation_Name;",
         "Type_Localised": "Planetary Mining Location", "Count": 28},
        {"Type": "$SAA_SignalType_Human;", "Type_Localised": "Human", "Count": 3},
        {"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 4},
        {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 5},
        {"Type": "Serendibite", "Count": 2},
    ]}, plugin.state)
    assert plugin.hotspots == {"Serendibite": 2}


@pytest.mark.parametrize("raw,expected", [
    ("Painite", "Painite"),
    ("tritium", "Tritium"),               # the journal uses both cases
    ("Tritium", "Tritium"),
    ("$SAA_SignalType_Human;", ""),
    ("$PlanetaryMiningLocation_Name;", ""),
    ("", ""),
])
def test_hotspot_name_filtering(raw, expected):
    assert mining._hotspot_name({"Type": raw}) == expected


def test_localised_commodity_name_is_preferred():
    assert mining._hotspot_name(
        {"Type": "Opal", "Type_Localised": "Void Opal"}) == "Void Opal"


def test_camel_case_falls_back_readably():
    """Most commodities carry no localised name."""
    assert mining._hotspot_name(
        {"Type": "LowTemperatureDiamond"}) == "Low Temperature Diamond"


def test_ring_and_planetary_sites_are_listed_separately(plugin):
    """They are different kinds of place and must not share a heading.

    A ring has hotspots you fly into; a planet has surface sites you land at.
    Merging them made a planetary body look like a ring with no hotspots.
    """
    # A planetary body with surface mining sites.
    plugin.on_event({"event": "SAASignalsFound", "BodyName": "Ega 3 d", "Signals": [
        {"Type": "$PlanetaryMiningLocation_Name;",
         "Type_Localised": "Planetary Mining Location", "Count": 28},
        {"Type": "$SAA_SignalType_Human;", "Type_Localised": "Human", "Count": 3},
    ]}, plugin.state)
    # A ring in the same system.
    plugin.on_event({"event": "SAASignalsFound", "BodyName": "Ega 3 A Ring",
                     "Signals": [{"Type": "Monazite", "Count": 2}]}, plugin.state)
    plugin.on_event({"event": "Scan", "BodyName": "Ega 3",
                     "ReserveLevel": "CommonResources",
                     "Rings": [{"Name": "Ega 3 A Ring",
                                "RingClass": "eRingClass_Rocky"}]}, plugin.state)

    rings, planets = plugin.sites_by_kind()
    assert [b for b, _ in rings] == ["Ega 3 A Ring"]
    assert [b for b, _ in planets] == ["Ega 3 d"]
    assert planets[0][1]["planetary_sites"] == 28
    assert rings[0][1]["hotspots"] == {"Monazite": 2}

    labels = [r["label"] for r in plugin.get_tab_rows()]
    assert any("Ring sites" in l for l in labels)
    assert any("Planetary sites" in l for l in labels)


def test_planetary_sites_carry_no_caveat_row(plugin):
    """The journal gives a count and nothing about what a site holds.

    That is worth knowing but not worth a row: the panel is short on width and
    a caveat is not information.
    """
    plugin.on_event({"event": "SAASignalsFound", "BodyName": "Ega 3 d", "Signals": [
        {"Type": "$PlanetaryMiningLocation_Name;", "Count": 28}]}, plugin.state)
    rows = plugin.get_tab_rows()
    labels = " ".join(r["label"] for r in rows)
    assert "journal" not in labels.lower()
    # The site count itself is still reported.
    assert any("28 site" in str(r["value"]) for r in rows)


def test_body_with_nothing_mineable_is_not_listed(plugin):
    """Scanned but empty bodies would pad the panel with useless entries."""
    plugin.on_event({"event": "Scan", "BodyName": "Ega 4",
                     "ReserveLevel": "DepletedResources", "Rings": []},
                    plugin.state)
    rings, planets = plugin.sites_by_kind()
    assert rings == [] and planets == []


def test_ring_class_and_reserves_attach_to_the_ring(plugin):
    plugin.on_event({"event": "SAASignalsFound", "BodyName": "Ega 3 A Ring",
                     "Signals": [{"Type": "Painite", "Count": 1}]}, plugin.state)
    plugin.on_event({"event": "Scan", "BodyName": "Ega 3",
                     "ReserveLevel": "PristineResources",
                     "Rings": [{"Name": "Ega 3 A Ring",
                                "RingClass": "eRingClass_Metalic"}]}, plugin.state)
    rings, _ = plugin.sites_by_kind()
    _body, rec = rings[0]
    assert rec["reserves"] == "Pristine"
    assert rec["ring_type"] == "Metallic"


@pytest.mark.parametrize("raw,localised,expected", [
    ("$SAA_RingHotspot:#type=$painite_name;;", "Painite Hotspot", "Painite"),
    ("$SAA_RingHotspot:#type=$LowTemperatureDiamond_name;;",
     "Low Temp. Diamonds Hotspot", "Low Temp. Diamonds"),
    ("$SAA_RingHotspot:#type=$Tritium_name;;", "", "Tritium"),
    ("Bosch Station", "", ""),
    ("$MULTIPLAYER_SCENARIO77_TITLE;", "Resource Extraction Site [Low]", ""),
])
def test_active_hotspot_from_supercruise_drop(raw, localised, expected):
    """Overlapping hotspots make the ring's signal list ambiguous.

    Dropping in names the one actually being worked.
    """
    ev = {"event": "SupercruiseDestinationDrop", "Type": raw}
    if localised:
        ev["Type_Localised"] = localised
    assert mining._ring_hotspot_name(ev) == expected


def test_section_is_headed_by_the_body_not_the_word_ring(plugin):
    """A planetary mining location is not a ring."""
    plugin.on_event({"event": "SAASignalsFound", "BodyName": "Ega 3 d",
                     "Signals": [{"Type": "Monazite", "Count": 2}]}, plugin.state)
    plugin.on_event({"event": "Scan", "ReserveLevel": "CommonResources",
                     "Rings": []}, plugin.state)
    labels = [r["label"] for r in plugin.get_tab_rows()]
    assert any("Ega 3 d" in l for l in labels)
    headers = [l for l in labels if "───" in l]
    assert not any(h.strip("─ ") == "Ring" for h in headers)


def test_every_handled_event_is_subscribed():
    """A handler for an unsubscribed event never runs.

    The hotspot-drop handler was written before its event was added to
    SUBSCRIBED_EVENTS and was silently dead.
    """
    import re as _re
    source = (ROOT / "components" / "mining.py").read_text(encoding="utf-8")
    handled = set(_re.findall(r'case "(\w+)"', source))
    subscribed = set(mining.ActivityMiningPlugin.SUBSCRIBED_EVENTS)
    assert handled <= subscribed, f"handled but not subscribed: {handled - subscribed}"

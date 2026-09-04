"""
tests/test_route_follower.py — route store and clipboard follower.

Covers the behaviours that are easy to get subtly wrong:

  * converting all three EDLD route shapes into the game's NavRoute schema
  * which route wins when both an EDLD route and an in-game route exist
  * hyperspace awareness — mid-tunnel, "current" is the system being
    arrived at, not the one being left
  * Clear Route suppressing the *current* NavRoute.json but not a later one
  * never touching the clipboard during preload

The clipboard itself is stubbed throughout; the container has no clipboard
backend and the point here is the decision logic, not the OS call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.navigation import (  # noqa: E402
    NavigationPlugin,
    route_signature,
    spansh_result_to_navroute,
)


# ── Doubles ───────────────────────────────────────────────────────────────────

class FakeStorage:
    """In-memory stand-in for PluginStorage."""

    def __init__(self):
        self.files: dict[str, dict] = {}

    def read_json(self, purpose=None):
        return dict(self.files.get(purpose or "_primary", {}))

    def write_json(self, data, purpose=None):
        self.files[purpose or "_primary"] = json.loads(json.dumps(data))


class FakeState:
    def __init__(self, system="Sol"):
        self.pilot_system = system
        self.in_preload = False
        self.nav_follow_enabled = False
        self.nav_follow_source = ""
        self.nav_follow_next = ""
        self.nav_follow_status = ""
        self.nav_transit_to = ""
        self.nav_last_copied = ""


class FakeCore:
    def __init__(self, journal_dir, state):
        self.journal_dir = journal_dir
        self.state = state
        self.gui_queue = None


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    """A loaded NavigationPlugin with a stubbed clipboard recording copies."""
    copies: list[str] = []

    import core.clipboard as clipboard

    def fake_copy(text):
        copies.append(text)
        return True, "test"

    monkeypatch.setattr(clipboard, "copy", fake_copy)

    state = FakeState()
    p = NavigationPlugin()
    p.storage = FakeStorage()
    p.on_load(FakeCore(tmp_path, state))
    p.copies = copies
    return p


def write_navroute(journal_dir, systems, timestamp="2026-09-04T10:00:00Z"):
    doc = {
        "timestamp": timestamp,
        "event": "NavRoute",
        "Route": [
            {"StarSystem": s, "SystemAddress": i, "StarPos": [i, 0, 0], "StarClass": "G"}
            for i, s in enumerate(systems)
        ],
    }
    (Path(journal_dir) / "NavRoute.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


# ── Conversion to the NavRoute schema ─────────────────────────────────────────

NEUTRON = {"system_jumps": [
    {"system": "Sol", "x": 0, "y": 0, "z": 0, "distance_jumped": 0},
    {"system": "Jackson's Lighthouse", "x": 10, "y": 2, "z": 3,
     "distance_jumped": 180.2, "neutron_star": True},
]}

FSD = {"system_jumps": [
    {"system": "Shana Bei", "star_pos": [1, 2, 3], "distance_jumped": 0},
    {"system": "Deciat", "star_pos": [4, 5, 6], "distance_jumped": 48.3},
]}

CARRIER = {"jumps": [
    {"name": "Ogmar", "id64": 84180519395914, "x": -9534, "y": -905, "z": 19802,
     "distance": 0, "fuel_used": 0, "must_restock": 1, "restock_amount": 5001},
    {"name": "Deciat", "id64": 6681123623626, "x": 4, "y": 5, "z": 6,
     "distance": 499.7, "fuel_used": 119, "has_icy_ring": True},
]}


@pytest.mark.parametrize(
    "result,kind,first,last",
    [
        (NEUTRON, "neutron", "Sol", "Jackson's Lighthouse"),
        (FSD, "fsd", "Shana Bei", "Deciat"),
        (CARRIER, "carrier", "Ogmar", "Deciat"),
    ],
)
def test_all_three_route_shapes_convert(result, kind, first, last):
    doc = spansh_result_to_navroute(result, kind)
    assert doc["event"] == "NavRoute"
    assert doc["EDLDSource"] == kind
    assert [e["StarSystem"] for e in doc["Route"]] == [first, last]
    # Every entry carries the keys a NavRoute reader expects.
    for entry in doc["Route"]:
        assert set(entry) >= {"StarSystem", "SystemAddress", "StarPos", "StarClass"}
        assert len(entry["StarPos"]) == 3


def test_conversion_preserves_carrier_fuel_detail():
    doc = spansh_result_to_navroute(CARRIER, "carrier")
    assert doc["Route"][0]["EDLD"]["restock_amount"] == 5001
    assert doc["Route"][1]["EDLD"]["fuel_used"] == 119


def test_conversion_rejects_empty_and_malformed():
    assert spansh_result_to_navroute({}, "fsd") is None
    assert spansh_result_to_navroute({"system_jumps": []}, "fsd") is None
    assert spansh_result_to_navroute(None, "fsd") is None


# ── Route selection ───────────────────────────────────────────────────────────

def test_journal_route_used_when_no_edld_route(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Alpha Centauri"])
    route, source = plugin.active_route()
    assert source == "journal"
    assert [e["StarSystem"] for e in route] == ["Sol", "Alpha Centauri"]


def test_newer_edld_route_beats_older_journal_route(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359"],
                   timestamp="2026-09-01T00:00:00Z")
    plugin.store_route(NEUTRON, "neutron")          # stamped now
    _route, source = plugin.active_route()
    assert source == "edld"


def test_newer_journal_route_beats_older_edld_route(plugin):
    plugin.store_route(NEUTRON, "neutron")
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359"],
                   timestamp="2099-01-01T00:00:00Z")
    _route, source = plugin.active_route()
    assert source == "journal"


# ── Next-system logic ─────────────────────────────────────────────────────────

def test_next_system_from_current_position(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359", "Deciat"])
    plugin.core.state.pilot_system = "Sol"
    assert plugin.next_system() == ("Wolf 359", "")


def test_next_system_is_case_insensitive(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359"])
    plugin.core.state.pilot_system = "sOl"
    assert plugin.next_system()[0] == "Wolf 359"


def test_at_final_destination_reports_so(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Deciat"])
    plugin.core.state.pilot_system = "Deciat"
    name, why = plugin.next_system()
    assert name == ""
    assert "final destination" in why


def test_off_route_reports_so(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Deciat"])
    plugin.core.state.pilot_system = "Colonia"
    name, why = plugin.next_system()
    assert name == ""
    assert "not on the" in why


def test_no_route_reports_so(plugin):
    assert plugin.next_system() == ("", "No route stored.")


# ── Hyperspace awareness ──────────────────────────────────────────────────────

def test_mid_hyperspace_current_is_the_destination(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359", "Deciat"])
    plugin.core.state.pilot_system = "Sol"
    assert plugin.next_system()[0] == "Wolf 359"

    # Tunnel to Wolf 359 — the jump can no longer be cancelled.
    plugin.on_event({"event": "StartJump", "JumpType": "Hyperspace",
                     "StarSystem": "Wolf 359"}, plugin.core.state)
    assert plugin.effective_current_system() == "Wolf 359"
    assert plugin.next_system()[0] == "Deciat"


def test_supercruise_startjump_does_not_move_us(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359", "Deciat"])
    plugin.core.state.pilot_system = "Sol"
    plugin.on_event({"event": "StartJump", "JumpType": "Supercruise"},
                    plugin.core.state)
    assert plugin.effective_current_system() == "Sol"
    assert plugin.next_system()[0] == "Wolf 359"


def test_arrival_clears_transit(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359", "Deciat"])
    st = plugin.core.state
    st.pilot_system = "Sol"
    plugin.on_event({"event": "StartJump", "JumpType": "Hyperspace",
                     "StarSystem": "Wolf 359"}, st)
    st.pilot_system = "Wolf 359"
    plugin.on_event({"event": "FSDJump", "StarSystem": "Wolf 359"}, st)
    assert st.nav_transit_to == ""
    assert plugin.effective_current_system() == "Wolf 359"


# ── Auto-copy ─────────────────────────────────────────────────────────────────

def test_arrival_copies_next_when_enabled(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359", "Deciat"])
    st = plugin.core.state
    plugin.set_follow_enabled(True)
    st.pilot_system = "Wolf 359"
    plugin.on_event({"event": "FSDJump", "StarSystem": "Wolf 359"}, st)
    assert plugin.copies == ["Deciat"]


def test_arrival_does_not_copy_when_disabled(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359", "Deciat"])
    st = plugin.core.state
    st.pilot_system = "Wolf 359"
    plugin.on_event({"event": "FSDJump", "StarSystem": "Wolf 359"}, st)
    assert plugin.copies == []


def test_preload_never_touches_the_clipboard(plugin):
    """Replaying journal history at startup must not spam the clipboard."""
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359", "Deciat"])
    st = plugin.core.state
    plugin.set_follow_enabled(True)
    st.in_preload = True
    for system in ("Sol", "Wolf 359"):
        st.pilot_system = system
        plugin.on_event({"event": "FSDJump", "StarSystem": system}, st)
    assert plugin.copies == []


def test_repeat_arrival_does_not_recopy(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359", "Deciat"])
    st = plugin.core.state
    plugin.set_follow_enabled(True)
    st.pilot_system = "Wolf 359"
    for _ in range(3):
        plugin.on_event({"event": "Location", "StarSystem": "Wolf 359"}, st)
    assert plugin.copies == ["Deciat"]


# ── Clear Route ───────────────────────────────────────────────────────────────

def test_clear_wipes_edld_route(plugin):
    plugin.store_route(NEUTRON, "neutron")
    assert plugin.active_route()[1] == "edld"
    plugin.clear_route()
    assert plugin.active_route() == ([], "")


def test_clear_suppresses_current_journal_route(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Deciat"])
    assert plugin.active_route()[1] == "journal"
    plugin.clear_route()
    assert plugin.active_route() == ([], "")
    # The game's file is deliberately left in place for other tools.
    assert (Path(plugin.core.journal_dir) / "NavRoute.json").is_file()


def test_clear_does_not_suppress_a_later_journal_route(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Deciat"])
    plugin.clear_route()
    write_navroute(plugin.core.journal_dir, ["Sol", "Colonia"],
                   timestamp="2026-09-04T12:00:00Z")
    assert plugin.active_route()[1] == "journal"


def test_clear_stops_auto_copy_until_a_new_route(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Wolf 359", "Deciat"])
    st = plugin.core.state
    plugin.set_follow_enabled(True)
    plugin.clear_route()

    st.pilot_system = "Wolf 359"
    plugin.on_event({"event": "FSDJump", "StarSystem": "Wolf 359"}, st)
    assert plugin.copies == []

    plugin.store_route(NEUTRON, "neutron")
    st.pilot_system = "Sol"
    plugin.on_event({"event": "FSDJump", "StarSystem": "Sol"}, st)
    assert plugin.copies == ["Jackson's Lighthouse"]


def test_plotting_after_clear_supersedes_the_dismissal(plugin):
    write_navroute(plugin.core.journal_dir, ["Sol", "Deciat"])
    plugin.clear_route()
    plugin.on_event({"event": "NavRoute"}, plugin.core.state)
    assert plugin.active_route()[1] == "journal"


# ── Settings persistence ──────────────────────────────────────────────────────

def test_follow_toggle_persists_across_reload(tmp_path, plugin):
    plugin.set_follow_enabled(True)
    reloaded = NavigationPlugin()
    reloaded.storage = plugin.storage
    reloaded.on_load(FakeCore(plugin.core.journal_dir, FakeState()))
    assert reloaded.core.state.nav_follow_enabled is True


def test_stored_route_survives_reload(plugin):
    plugin.store_route(FSD, "fsd")
    reloaded = NavigationPlugin()
    reloaded.storage = plugin.storage
    reloaded.on_load(FakeCore(plugin.core.journal_dir, FakeState("Shana Bei")))
    route, source = reloaded.active_route()
    assert source == "edld"
    assert route[-1]["StarSystem"] == "Deciat"


# ── Signature helper ──────────────────────────────────────────────────────────

def test_signature_changes_when_the_route_changes():
    a = {"timestamp": "t1", "Route": [{"StarSystem": "Sol"}, {"StarSystem": "Deciat"}]}
    b = {"timestamp": "t2", "Route": [{"StarSystem": "Sol"}, {"StarSystem": "Deciat"}]}
    c = {"timestamp": "t1", "Route": [{"StarSystem": "Sol"}, {"StarSystem": "Colonia"}]}
    assert route_signature(a) != route_signature(b)
    assert route_signature(a) != route_signature(c)
    assert route_signature(a) == route_signature(dict(a))
    assert route_signature(None) == ""

"""
tests/test_carrier_jump_notifications.py — carrier jump lifecycle notifications.

Sequences here are taken from a real 269-journal capture, because the events
are thinner and noisier than they look:

  * ``CarrierJumpRequest``   names the destination and departure time, but not
                             the carrier — only ``CarrierID``.
  * ``CarrierJumpCancelled`` names neither destination nor carrier name, so the
                             pending jump recorded at request time is the only
                             record of where it was going.
  * completion arrives as ``CarrierLocation`` when the commander is elsewhere,
    or ``CarrierJump`` when aboard — and when aboard **both** fire, about a
    minute apart.
  * ``CarrierLocation`` is also a periodic status event. In the capture it
    outnumbers actual arrivals roughly two to one, so "the next location event
    after a request" is not an arrival.

Replaying the full capture in chronological order accounts for every request
exactly: 178 scheduled = 170 completed + 3 cancelled + 4 re-targeted + 1 still
pending at the end of the logs.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.plugin_loader import BasePlugin  # noqa: E402

CARRIER_ID = 3715178496
NAME = "BIG DECK ENERGY"
IDENT = "N2Z-N8M"


def _load_plugin_class():
    spec = importlib.util.spec_from_file_location(
        "comp_assets", ROOT / "components" / "assets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in dir(mod):
        obj = getattr(mod, name)
        if (isinstance(obj, type) and issubclass(obj, BasePlugin)
                and obj is not BasePlugin):
            return obj
    raise AssertionError("no plugin class in components/assets.py")


AssetsPlugin = _load_plugin_class()


class FakeState:
    def __init__(self, carrier=True, squadron=None, preload=False):
        self.in_preload = preload
        self.assets_carrier = ({
            "carrier_id": CARRIER_ID, "name": NAME, "callsign": IDENT,
            "system": "Origin", "carrier_type": "FleetCarrier",
        } if carrier else None)
        self.assets_squadron_carrier = squadron


@pytest.fixture
def plugin():
    """Plugin wired to a recording alerts double."""
    notes: list[tuple] = []

    class Alerts:
        def push_external(self, emoji, text, *, loglevel=3, **kw):
            notes.append((loglevel, emoji, text))

    class Core:
        notify_levels = {
            "CarrierJumpScheduled": 3,
            "CarrierJumpCancelled": 3,
            "CarrierJumpComplete": 2,
        }
        _plugins = {"alerts": Alerts()}
        gui_queue = None

    p = AssetsPlugin()
    p.core = Core()
    p._pending_jumps = {}
    p.notes = notes
    return p


def request(system="Bhutatani", body="Bhutatani ABC 2", cid=CARRIER_ID,
            ts="2026-05-21T06:17:34Z", dep="2026-05-21T06:33:10Z",
            ctype="FleetCarrier"):
    ev = {"timestamp": ts, "event": "CarrierJumpRequest", "CarrierType": ctype,
          "CarrierID": cid, "SystemName": system, "DepartureTime": dep}
    if body:
        ev["Body"] = body
    return ev


def location(system, cid=CARRIER_ID, ts="2026-05-21T06:33:10Z"):
    return {"timestamp": ts, "event": "CarrierLocation",
            "CarrierType": "FleetCarrier", "CarrierID": cid,
            "StarSystem": system}


def texts(plugin):
    return [t for _lvl, _e, t in plugin.notes]


# ── Scheduling ────────────────────────────────────────────────────────────────

def test_schedule_reports_name_ident_destination_and_countdown(plugin):
    plugin._schedule_carrier_jump(request(), FakeState())
    text = texts(plugin)[0]
    assert NAME in text and IDENT in text
    assert "JUMP SCHEDULED" in text
    assert "Bhutatani" in text
    assert "15m 36s" in text          # 06:17:34 → 06:33:10
    assert "departs 06:33" in text


def test_schedule_uses_the_configured_level(plugin):
    plugin._schedule_carrier_jump(request(), FakeState())
    assert plugin.notes[0][0] == "CarrierJumpScheduled"


def test_schedule_falls_back_when_the_carrier_is_unknown(plugin):
    """A jump can be scheduled before CarrierStats has been seen this session.

    The capture also contains four requests for a carrier that was later
    decommissioned and is no longer in state.
    """
    plugin._schedule_carrier_jump(request(cid=3707917312), FakeState())
    text = texts(plugin)[0]
    assert "Fleet carrier" in text
    assert "JUMP SCHEDULED" in text


def test_squadron_carrier_is_named_and_labelled(plugin):
    squadron = {"carrier_id": 999, "name": "SQUADRON ONE", "callsign": "SQ1-XYZ"}
    state = FakeState(squadron=squadron)
    plugin._schedule_carrier_jump(
        request(cid=999, ctype="SquadronCarrier"), state)
    assert "SQUADRON ONE (SQ1-XYZ)" in texts(plugin)[0]


def test_unknown_squadron_carrier_says_squadron(plugin):
    plugin._schedule_carrier_jump(
        request(cid=999, ctype="SquadronCarrier"), FakeState())
    assert "Squadron carrier" in texts(plugin)[0]


def test_body_is_included_when_present(plugin):
    plugin._schedule_carrier_jump(request(), FakeState())
    assert "(Bhutatani ABC 2)" in texts(plugin)[0]


def test_missing_body_is_omitted_not_blank(plugin):
    plugin._schedule_carrier_jump(request(body=None), FakeState())
    text = texts(plugin)[0]
    assert "Bhutatani" in text and "()" not in text


# ── Cancellation ──────────────────────────────────────────────────────────────

def test_cancel_names_the_destination_the_event_does_not_carry(plugin):
    state = FakeState()
    plugin._schedule_carrier_jump(request(system="Kitchang Mu"), state)
    plugin._cancel_carrier_jump(
        {"timestamp": "2026-05-28T20:47:41Z", "event": "CarrierJumpCancelled",
         "CarrierType": "FleetCarrier", "CarrierID": CARRIER_ID}, state)
    text = texts(plugin)[-1]
    assert "JUMP CANCELLED" in text
    assert "Kitchang Mu" in text
    assert NAME in text


def test_cancel_clears_the_pending_jump(plugin):
    state = FakeState()
    plugin._schedule_carrier_jump(request(), state)
    plugin._cancel_carrier_jump(
        {"event": "CarrierJumpCancelled", "CarrierID": CARRIER_ID}, state)
    assert plugin._pending_jumps == {}
    plugin._complete_carrier_jump(CARRIER_ID, "Bhutatani", state,
                                  location("Bhutatani"))
    assert sum("COMPLETE" in t for t in texts(plugin)) == 0


def test_cancel_without_a_pending_jump_still_reports(plugin):
    """Launching mid-lockdown means the request was never seen."""
    plugin._cancel_carrier_jump(
        {"event": "CarrierJumpCancelled", "CarrierType": "FleetCarrier",
         "CarrierID": CARRIER_ID}, FakeState())
    assert "JUMP CANCELLED" in texts(plugin)[0]


# ── Completion ────────────────────────────────────────────────────────────────

def test_arrival_at_the_destination_completes(plugin):
    state = FakeState()
    plugin._schedule_carrier_jump(request(), state)
    plugin._complete_carrier_jump(CARRIER_ID, "Bhutatani", state,
                                  location("Bhutatani"))
    assert "JUMP COMPLETE — arrived at Bhutatani" in texts(plugin)[-1]


def test_periodic_location_elsewhere_does_not_complete(plugin):
    """The bug this rule exists for.

    CarrierLocation fires as a status event roughly twice as often as an
    arrival; taking the next one after a request reported the wrong system.
    """
    state = FakeState()
    plugin._schedule_carrier_jump(request(system="Bhutatani"), state)
    plugin._complete_carrier_jump(CARRIER_ID, "Sounti", state,
                                  location("Sounti"))
    assert not any("COMPLETE" in t for t in texts(plugin))
    assert plugin._pending_jumps, "pending jump must survive an unrelated update"


def test_location_before_departure_does_not_complete(plugin):
    """Covers a re-plot to a body in the system the carrier is already in."""
    state = FakeState()
    plugin._schedule_carrier_jump(
        request(system="Tionisla", ts="2026-06-06T11:59:41Z",
                dep="2026-06-06T12:15:10Z"), state)
    plugin._complete_carrier_jump(
        CARRIER_ID, "Tionisla", state,
        location("Tionisla", ts="2026-06-06T12:00:00Z"))
    assert not any("COMPLETE" in t for t in texts(plugin))

    plugin._complete_carrier_jump(
        CARRIER_ID, "Tionisla", state,
        location("Tionisla", ts="2026-06-06T12:15:10Z"))
    assert "JUMP COMPLETE" in texts(plugin)[-1]


def test_aboard_arrival_fires_once_not_twice(plugin):
    """With the commander aboard, CarrierLocation and CarrierJump both fire."""
    state = FakeState()
    plugin._schedule_carrier_jump(request(system="Kamitra"), state)
    arrival = location("Kamitra", ts="2026-07-09T19:30:10Z")
    plugin._complete_carrier_jump(CARRIER_ID, "Kamitra", state, arrival)
    plugin._complete_carrier_jump(
        CARRIER_ID, "Kamitra", state,
        {"timestamp": "2026-07-09T19:31:11Z", "event": "CarrierJump",
         "MarketID": CARRIER_ID, "StarSystem": "Kamitra"})
    assert sum("COMPLETE" in t for t in texts(plugin)) == 1


def test_completion_without_a_pending_jump_is_silent(plugin):
    """Otherwise every periodic status update would announce an arrival."""
    plugin._complete_carrier_jump(CARRIER_ID, "Sounti", FakeState(),
                                  location("Sounti"))
    assert texts(plugin) == []


def test_retarget_replaces_the_pending_jump(plugin):
    """A new request may arrive with no cancel; the capture has four."""
    state = FakeState()
    plugin._schedule_carrier_jump(request(system="Prua Phoe GR-L d8-164"), state)
    plugin._schedule_carrier_jump(request(system="Clooku DX-D b15-13"), state)
    assert sum("SCHEDULED" in t for t in texts(plugin)) == 2

    plugin._complete_carrier_jump(CARRIER_ID, "Prua Phoe GR-L d8-164", state,
                                  location("Prua Phoe GR-L d8-164"))
    assert not any("COMPLETE" in t for t in texts(plugin))
    plugin._complete_carrier_jump(CARRIER_ID, "Clooku DX-D b15-13", state,
                                  location("Clooku DX-D b15-13"))
    assert "Clooku DX-D b15-13" in texts(plugin)[-1]


# ── Two carriers at once ──────────────────────────────────────────────────────

def test_fleet_and_squadron_jumps_are_tracked_independently(plugin):
    squadron = {"carrier_id": 999, "name": "SQUADRON ONE", "callsign": "SQ1-XYZ"}
    state = FakeState(squadron=squadron)
    plugin._schedule_carrier_jump(request(system="Bhutatani"), state)
    plugin._schedule_carrier_jump(
        request(system="Colonia", cid=999, ctype="SquadronCarrier"), state)

    plugin._complete_carrier_jump(999, "Colonia", state,
                                  location("Colonia", cid=999))
    done = [t for t in texts(plugin) if "COMPLETE" in t]
    assert len(done) == 1 and "SQUADRON ONE" in done[0] and "Colonia" in done[0]
    assert str(CARRIER_ID) in plugin._pending_jumps


# ── Preload ───────────────────────────────────────────────────────────────────

def test_preload_records_pending_but_stays_silent(plugin):
    """Replaying history must not announce jumps that resolved long ago.

    The pending entry is still recorded, so a jump scheduled before EDLD
    launched still reports its arrival once live.
    """
    state = FakeState(preload=True)
    plugin._schedule_carrier_jump(request(), state)
    assert texts(plugin) == []
    assert str(CARRIER_ID) in plugin._pending_jumps

    state.in_preload = False
    plugin._complete_carrier_jump(CARRIER_ID, "Bhutatani", state,
                                  location("Bhutatani"))
    assert "JUMP COMPLETE" in texts(plugin)[-1]


def test_preload_cancel_and_complete_are_silent(plugin):
    state = FakeState(preload=True)
    plugin._schedule_carrier_jump(request(), state)
    plugin._complete_carrier_jump(CARRIER_ID, "Bhutatani", state,
                                  location("Bhutatani"))
    plugin._cancel_carrier_jump(
        {"event": "CarrierJumpCancelled", "CarrierID": CARRIER_ID}, state)
    assert texts(plugin) == []


# ── Countdown formatting ──────────────────────────────────────────────────────

@pytest.mark.parametrize("seconds,expected", [
    (956, "15m 56s"),      # the median in the capture
    (911, "15m 11s"),      # the minimum
    (4306, "1h 11m"),      # the maximum
    (45, "45s"),
    (0, "0s"),
    (-30, "0s"),           # a departure already past must not go negative
])
def test_countdown_formatting(seconds, expected):
    assert AssetsPlugin._fmt_countdown(seconds) == expected


# ── Robustness ────────────────────────────────────────────────────────────────

def test_missing_alerts_component_does_not_raise(plugin):
    plugin.core._plugins = {}

    class Emitter:
        sent = []

        @staticmethod
        def emit(**kw):
            Emitter.sent.append(kw)

    plugin.core.emitter = Emitter
    plugin._schedule_carrier_jump(request(), FakeState())
    assert Emitter.sent, "should fall back to a direct emit"


def test_unparseable_departure_time_still_schedules(plugin):
    plugin._schedule_carrier_jump(request(dep="not-a-time"), FakeState())
    assert "JUMP SCHEDULED" in texts(plugin)[0]


def test_arrival_completes_when_departure_time_is_unreadable(plugin):
    """A carrier reporting arrival has arrived; a bad clock must not hide it."""
    state = FakeState()
    plugin._schedule_carrier_jump(request(dep=""), state)
    plugin._complete_carrier_jump(CARRIER_ID, "Bhutatani", state,
                                  location("Bhutatani"))
    assert "JUMP COMPLETE" in texts(plugin)[-1]

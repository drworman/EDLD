"""
tests/test_overlay.py — Overlay geometry, content, and transport.

The renderer itself needs a display and PySide6 and is not testable here. What
is testable is everything that decides *what* gets drawn and *where*, and the
client's behaviour when the renderer is absent, slow, broken, or lying — which
is where the bugs that matter live. A renderer that fails to start is a
disappointment; a client that thinks it started is a hang.

Two behaviours are asserted hardest:

  * the overlay draws nothing unless the commander is in an SRV near a
    recorded deposit, because an overlay that is always on is wallpaper;
  * a mark behind the commander is dropped rather than pinned to the edge of
    the tape, because a mark at the edge reads as "over there" when the truth
    is "behind you".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.overlay import (
    CFG_DEFAULTS, OverlayCapabilities, OverlayClient, client_from_config,
    relative_bearing, tape_positions, text,
)
from core.overlay_content import nearest_deposits
from core.overlay_proc import anchor_position


# ── bearing arithmetic ────────────────────────────────────────────────────────

@pytest.mark.parametrize("heading,bearing,expected", [
    (0,   0,   0),
    (0,   90,  90),
    (0,   270, -90),
    (350, 10,  20),
    (10,  350, -20),
    (180, 0,   180),
    (0,   180, 180),
])
def test_relative_bearing_wraps_the_short_way(heading, bearing, expected):
    assert relative_bearing(heading, bearing) == pytest.approx(expected)


def test_a_mark_behind_you_is_dropped_not_clamped():
    marks = [{"bearing": 0, "label": "ahead"}, {"bearing": 180, "label": "behind"}]
    placed = tape_positions(heading=0, span_deg=90, width=700, marks=marks)
    assert [m["label"] for _, m in placed] == ["ahead"]


def test_marks_place_proportionally_across_the_span():
    marks = [{"bearing": 315}, {"bearing": 0}, {"bearing": 45}]
    placed = tape_positions(heading=0, span_deg=90, width=900, marks=marks)
    assert [round(x) for x, _ in placed] == [0, 450, 900]


def test_a_degenerate_tape_places_nothing():
    assert tape_positions(0, 0, 700, [{"bearing": 0}]) == []
    assert tape_positions(0, 90, 0, [{"bearing": 0}]) == []


# ── window placement ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("anchor,expected", [
    ("top-left",      (10, 40)),
    ("top-centre",    (610, 40)),   # offset nudges a centred window
    ("top-right",     (1190, 40)),
    ("bottom-left",   (10, 1040)),
    ("bottom-centre", (610, 1040)),
    ("bottom-right",  (1190, 1040)),
])
def test_anchor_positions(anchor, expected):
    assert anchor_position(anchor, 1920, 1080, 720, 0, 10, 40) == expected


# ── what goes on screen, and what does not ────────────────────────────────────

def _dep(lat, lon, commodity="Monazite", amount=""):
    return {"latitude": lat, "longitude": lon, "commodity": commodity.lower(),
            "commodity_display": commodity, "amount": amount}


BODY_R = 1.5e6


def test_nearest_deposits_sorts_and_annotates():
    got = nearest_deposits(10.0, 20.0, BODY_R, [
        _dep(10.02, 20.0, "Far"), _dep(10.001, 20.0, "Near")])
    assert [d["commodity_display"] for d in got] == ["Near", "Far"]
    assert got[0]["distance_m"] < got[1]["distance_m"]
    assert 0.0 <= got[0]["bearing"] <= 360.0


def test_deposits_with_no_coordinates_are_skipped():
    assert nearest_deposits(10.0, 20.0, BODY_R,
                            [{"latitude": None, "longitude": None}]) == []


# ── the client, without a renderer ────────────────────────────────────────────

class _FakeProc:
    """Stands in for the renderer child."""

    def __init__(self, lines: list[str], alive: bool = True,
                 stdin_raises: Exception | None = None) -> None:
        self._lines = list(lines)
        self._alive = alive
        self.written: list[str] = []
        self.returncode = None if alive else 1
        self.stdout = self
        self.stderr = self
        self.stdin = self

    # stdout / stderr
    def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""

    def read(self) -> str:
        return "".join(self._lines)

    def __iter__(self):
        return iter([])

    # stdin
    def write(self, s: str) -> None:
        self.written.append(s)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def _caps_line(**over) -> str:
    base = {"event": "capabilities", "available": True, "platform": "xcb",
            "translucent": True, "click_through": True, "always_on_top": True,
            "compositing": True, "screens": 1}
    base.update(over)
    return json.dumps(base) + "\n"


def test_a_good_handshake_yields_a_usable_overlay():
    proc = _FakeProc([_caps_line()])
    c = OverlayClient(spawn=lambda: proc)
    caps = c.start()
    assert caps.usable and caps.platform == "xcb"
    assert c.send([text("t", 0, 0, "hello")]) is True
    assert json.loads(proc.written[0])["elements"][0]["text"] == "hello"


def test_wayland_reports_unavailable_rather_than_half_working():
    proc = _FakeProc([_caps_line(available=False, always_on_top=False,
                                 click_through=False,
                                 reason="Wayland does not permit always-on-top")])
    caps = OverlayClient(spawn=lambda: proc).start()
    assert caps.usable is False
    assert "Wayland" in caps.summary()


def test_an_overlay_without_click_through_is_not_usable():
    # Better no overlay than one that eats clicks meant for the cockpit.
    caps = OverlayCapabilities(available=True, always_on_top=True,
                               click_through=False, platform="xcb")
    assert caps.usable is False
    assert "click-through" in caps.summary()


def test_a_renderer_that_dies_immediately_is_reported_not_awaited():
    proc = _FakeProc(["ModuleNotFoundError: No module named 'PySide6'\n"],
                     alive=False)
    caps = OverlayClient(spawn=lambda: proc).start()
    assert caps.available is False
    assert "PySide6" in caps.reason


def test_a_renderer_that_cannot_be_spawned_is_reported():
    def boom():
        raise OSError("no such file")

    caps = OverlayClient(spawn=boom).start()
    assert caps.available is False and "no such file" in caps.reason


def test_sending_before_start_is_false_not_an_exception():
    assert OverlayClient(spawn=lambda: _FakeProc([])).send([]) is False


def test_a_broken_pipe_stops_the_client_rather_than_raising():
    proc = _FakeProc([_caps_line()])
    c = OverlayClient(spawn=lambda: proc)
    c.start()
    assert c.running

    def explode(_s):
        raise BrokenPipeError("renderer gone")

    proc.write = explode
    assert c.send([text("t", 0, 0, "x")]) is False
    assert c.running is False
    assert "went away" in c.status()


def test_client_is_none_unless_enabled():
    assert client_from_config({}) is None
    assert client_from_config({**CFG_DEFAULTS, "Enabled": False}) is None
    assert client_from_config({**CFG_DEFAULTS, "Enabled": True}) is not None


def test_a_nonsense_anchor_falls_back_and_says_so():
    seen: list[str] = []
    c = client_from_config({**CFG_DEFAULTS, "Enabled": True,
                            "Anchor": "middle-of-nowhere"}, log=seen.append)
    assert c is not None
    assert any("top-centre" in m for m in seen)


# ── the preferences tab ───────────────────────────────────────────────────────

def _plugin(tmp_path, monkeypatch):
    """A loaded SurfaceMiningPlugin with its store in a temp directory."""
    import core.state as state
    import core.mining_db as mdb
    monkeypatch.setattr(state, "EDLD_DATA_DIR", tmp_path)
    monkeypatch.setattr(state, "shared_data_dir", lambda: tmp_path)
    monkeypatch.setattr(mdb, "_instance", None)

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sm_under_test", ROOT / "components" / "surface_mining.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Core:
        _plugins: dict = {}

        def __init__(self):
            self.registered: list = []

        def register_session_provider(self, plugin):
            self.registered.append(plugin)

        def load_setting(self, section, defaults, warn=False):
            return dict(defaults)

    p = mod.SurfaceMiningPlugin()
    p.on_load(_Core())
    return p


def test_every_bound_widget_maps_to_a_real_config_key(tmp_path, monkeypatch):
    """A binding pointing at a key that does not exist saves into nothing.

    The failure is invisible: the control moves, Apply succeeds, and the
    setting is silently discarded on the next load.
    """
    from core.overlay import CFG_DEFAULTS as OV
    from core.sheets_publish import CFG_DEFAULTS as SH

    p = _plugin(tmp_path, monkeypatch)
    known = {"Overlay": OV, "SurfaceSurvey": SH}
    for wid, (section, key, _typ) in p.preferences_bindings().items():
        assert section in known, f"{wid} binds to unknown section {section}"
        assert key in known[section], f"{wid} binds to unknown key {section}.{key}"


def test_both_front_ends_offer_the_same_tab(tmp_path, monkeypatch):
    p = _plugin(tmp_path, monkeypatch)
    tui = p.tui_preferences_tab()
    gui = p.gui_preferences_tab()
    assert tui is not None and gui is not None
    assert tui[0] == gui[0] and tui[1] == gui[1], \
        "the Survey tab must have the same id and label in both front ends"


def test_the_gui_discovery_call_takes_no_arguments(tmp_path, monkeypatch):
    """Exactly what gui/preferences.py _extra_tabs() does.

    It calls ``gui_preferences_tab()`` with no arguments purely to discover the
    tab, and only the returned builder receives the dialog.  This previously
    returned None when handed no dialog, so the tab was never registered and
    the whole Survey page was invisible in GUI mode — while TUI, which has a
    different discovery call, showed it fine.  The earlier test asserted the
    broken behaviour, because it was written from the same wrong idea as the
    code.
    """
    p = _plugin(tmp_path, monkeypatch)
    entry = p.gui_preferences_tab()          # no arguments, as the front end does
    assert entry, "discovery must return a tuple, not None"
    tab_id, label, builder = entry
    assert tab_id and label
    assert callable(builder)


def test_the_component_registers_so_its_rows_are_ever_asked_for(tmp_path,
                                                                monkeypatch):
    """get_tab_rows() is only called for registered session providers.

    Defining the method is not enough: core.session_providers() returns only
    components that called register_session_provider(), so an unregistered one
    renders nowhere in either front end no matter what it returns.
    """
    from core.activity import ActivityProviderMixin

    p = _plugin(tmp_path, monkeypatch)
    assert isinstance(p, ActivityProviderMixin)
    assert p.ACTIVITY_TAB_TITLE
    assert p in p._core.registered, "on_load must register as a session provider"


def test_store_lines_survive_an_unreadable_store(tmp_path, monkeypatch):
    p = _plugin(tmp_path, monkeypatch)

    def boom():
        raise sqlite_error()

    class sqlite_error(Exception):
        pass

    p._db.counts = boom
    lines = p._store_lines()
    assert lines and "unavailable" in lines[0][1]


def test_the_survey_tab_no_longer_owns_the_overlay():
    """Overlay settings moved to their own tab and component.

    Leaving a second copy behind would give two pages writing the same config
    keys, and whichever was opened last would appear to win.
    """
    src = (ROOT / "components" / "surface_mining.py").read_text(encoding="utf-8")
    for token in ("OVERLAY_DEFAULTS", "_overlay_cfg", "srv-ov-"):
        assert token not in src, f"{token} still in the Survey tab"


def test_the_survey_compass_is_now_a_contributed_panel(tmp_path, monkeypatch):
    p = _plugin(tmp_path, monkeypatch)
    assert "survey_compass" in getattr(p, "OVERLAY_PANELS", ())
    assert callable(getattr(p, "overlay_panel", None))
    from core.overlay_panels import PanelContext
    assert p.overlay_panel("survey_compass", PanelContext()) is None

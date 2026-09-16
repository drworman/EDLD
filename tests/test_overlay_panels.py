"""
tests/test_overlay_panels.py — Zones, stacking, and the two hide modes.

The behaviour worth protecting is that the two hide modes genuinely differ and
each does what its name promises. ``collapse`` must close the gap; ``reserve``
must hold every panel below a hidden one exactly where it was. Getting that
backwards would be invisible in a screenshot and obvious in motion, which is
the worst combination to debug.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.overlay_panels import CFG_DEFAULTS as CFG_DEFAULTS_PANELS
from core.overlay_panels import (
    HIDE_MODES, LINE_HEIGHT, MODES, PANEL_GAP, Panel, PanelContext,
    PanelPlacement, ZONES, collect, layout, placements_from_config,
    resolve_zone, zone_x,
)


def _panel(pid, rows=2, title="Cargo"):
    return Panel(id=pid, title=title,
                 rows=[(f"l{i}", f"v{i}") for i in range(rows)])


def _place(pid, zone="left", mode="auto", order=10):
    return PanelPlacement(pid, zone=zone, mode=mode, order=order)


# ── panel basics ──────────────────────────────────────────────────────────────

def test_height_counts_the_title():
    assert _panel("a", rows=3).height == 4 * LINE_HEIGHT
    assert Panel(id="a", rows=[("x", "y")]).height == LINE_HEIGHT


def test_an_empty_panel_is_empty():
    assert Panel(id="a").is_empty()
    assert not _panel("a").is_empty()


# ── zone anchors ──────────────────────────────────────────────────────────────

def test_zone_anchors_and_alignment():
    assert zone_x("left", 1920) == (16, "left")
    assert zone_x("right", 1920) == (1904, "right")
    assert zone_x("centre", 1920) == (960, "centre")


def test_an_unknown_zone_falls_back_to_centre_rather_than_crashing():
    assert zone_x("nowhere", 1920)[1] == "centre"


# ── mode ──────────────────────────────────────────────────────────────────────

def test_off_never_draws_and_never_reserves():
    slots = resolve_zone([_place("a", mode="off")], {"a": _panel("a")},
                         hide_mode="reserve")
    assert slots == []


def test_auto_defers_to_the_component():
    avail = resolve_zone([_place("a")], {"a": _panel("a")}, "collapse")
    assert avail and avail[0].panel is not None

    gone = resolve_zone([_place("a")], {"a": None}, "collapse")
    assert gone == [], "collapse drops an ineligible panel entirely"


def test_on_still_needs_something_to_draw():
    """`on` means 'always show this', not 'invent content'."""
    slots = resolve_zone([_place("a", mode="on")], {"a": None}, "collapse")
    assert slots == []


def test_a_panel_with_no_rows_counts_as_absent():
    slots = resolve_zone([_place("a")], {"a": Panel(id="a")}, "collapse")
    assert slots == []


# ── the two hide modes ────────────────────────────────────────────────────────

def _ys(elements, prefix):
    return [e["y"] for e in elements if e["id"].startswith(prefix)]


def test_collapse_closes_the_gap_and_reserve_holds_it():
    places = [_place("a", order=1), _place("b", order=2), _place("c", order=3)]
    panels_all = {"a": _panel("a"), "b": _panel("b"), "c": _panel("c")}
    panels_gone = {"a": _panel("a"), "b": None, "c": _panel("c")}

    full, heights = layout(places, panels_all, 1920)
    c_full = _ys(full, "c.")[0]

    collapsed, _ = layout(places, panels_gone, 1920, hide_mode="collapse",
                          reserve_heights=heights)
    reserved, _ = layout(places, panels_gone, 1920, hide_mode="reserve",
                         reserve_heights=heights)

    assert _ys(collapsed, "c.")[0] < c_full, "collapse must move c up"
    assert _ys(reserved, "c.")[0] == c_full, \
        "reserve must leave c exactly where it was"


def test_reserve_uses_the_height_the_panel_last_had():
    places = [_place("a", order=1), _place("b", order=2)]
    _, heights = layout(places, {"a": _panel("a", rows=4), "b": _panel("b")}, 1920)
    assert heights["a"] == 5 * LINE_HEIGHT

    reserved, _ = layout(places, {"a": None, "b": _panel("b")}, 1920,
                         hide_mode="reserve", reserve_heights=heights)
    b_y = _ys(reserved, "b.")[0]
    assert b_y == 8 + heights["a"] + PANEL_GAP


def test_reserve_with_no_history_does_not_reserve_a_guess():
    """A panel never yet seen has no height to hold, and inventing one would
    put a gap on screen for something that may never appear."""
    reserved, _ = layout([_place("a", order=1), _place("b", order=2)],
                         {"a": None, "b": _panel("b")}, 1920,
                         hide_mode="reserve", reserve_heights={})
    assert _ys(reserved, "b.")[0] == 8


# ── stacking and ordering ─────────────────────────────────────────────────────

def test_panels_stack_in_order_within_a_zone():
    places = [_place("b", order=2), _place("a", order=1)]
    els, _ = layout(sorted(places, key=lambda p: p.order),
                    {"a": _panel("a"), "b": _panel("b")}, 1920)
    assert _ys(els, "a.")[0] < _ys(els, "b.")[0]


def test_zones_are_independent_stacks():
    places = [_place("a", zone="left"), _place("b", zone="right"),
              _place("c", zone="centre")]
    els, _ = layout(places, {k: _panel(k) for k in "abc"}, 1920)
    tops = {p: _ys(els, f"{p}.")[0] for p in "abc"}
    assert tops["a"] == tops["b"] == tops["c"], \
        "each zone starts at the top; they do not share a stack"

    xs = {e["id"].split(".")[0]: e["x"] for e in els if e["id"].endswith(".title")}
    assert xs["a"] < xs["c"] < xs["b"]


def test_alignment_travels_with_the_zone():
    els, _ = layout([_place("r", zone="right")], {"r": _panel("r")}, 1920)
    assert all(e["align"] == "right" for e in els)


def test_nothing_placed_draws_nothing():
    els, heights = layout([], {}, 1920)
    assert els == [] and heights == {}


# ── config ────────────────────────────────────────────────────────────────────

def test_placements_parse_and_sort_by_order():
    cfg = {"Panels": {
        "ship":   {"Zone": "right", "Mode": "on",   "Order": 2},
        "cargo":  {"Zone": "left",  "Mode": "auto", "Order": 1},
    }}
    got = placements_from_config(cfg)
    assert [p.panel_id for p in got] == ["cargo", "ship"]
    assert got[1].zone == "right" and got[1].mode == "on"


def test_a_bad_zone_is_reported_and_skipped_not_coerced():
    seen: list[str] = []
    got = placements_from_config(
        {"Panels": {"cargo": {"Zone": "middle", "Mode": "auto"}}}, log=seen.append)
    assert got == []
    assert seen and "middle" in seen[0]


def test_a_bad_mode_is_reported_and_skipped():
    seen: list[str] = []
    got = placements_from_config(
        {"Panels": {"cargo": {"Zone": "left", "Mode": "sometimes"}}},
        log=seen.append)
    assert got == [] and seen


def test_a_non_table_entry_is_reported_not_crashed_on():
    seen: list[str] = []
    assert placements_from_config({"Panels": {"cargo": True}}, log=seen.append) == []
    assert seen


def test_missing_panels_table_is_fine():
    assert placements_from_config({}) == []


# ── collection ────────────────────────────────────────────────────────────────

class _Comp:
    PLUGIN_NAME = "fake"
    OVERLAY_PANELS = ("alpha", "beta")

    def __init__(self, raise_on=None):
        self.asked: list[str] = []
        self._raise_on = raise_on

    def overlay_panel(self, panel_id, ctx):
        self.asked.append(panel_id)
        if panel_id == self._raise_on:
            raise RuntimeError("boom")
        return _panel(panel_id) if panel_id == "alpha" else None


def test_only_placed_panels_are_asked_for():
    c = _Comp()
    out = collect([c], PanelContext(), wanted={"alpha"})
    assert c.asked == ["alpha"]
    assert out["alpha"] is not None and "beta" not in out


def test_a_component_saying_no_is_recorded_as_absent():
    out = collect([_Comp()], PanelContext(), wanted={"alpha", "beta"})
    assert out["beta"] is None


def test_one_broken_panel_does_not_take_the_frame_with_it():
    seen: list[str] = []
    out = collect([_Comp(raise_on="alpha")], PanelContext(),
                  wanted={"alpha", "beta"}, log=seen.append)
    assert out["alpha"] is None
    assert "beta" in out, "collection must continue past a failure"
    assert seen and "boom" in seen[0]


def test_components_without_panels_are_skipped():
    class Plain:
        PLUGIN_NAME = "plain"

    assert collect([Plain()], PanelContext(), wanted={"alpha"}) == {}


def test_the_whole_frame_sees_one_context():
    """Panels must not each read live state — a frame that disagrees with
    itself is worse than a frame that is a moment old."""
    seen = []

    class Recorder(_Comp):
        def overlay_panel(self, panel_id, ctx):
            seen.append(id(ctx))
            return None

    ctx = PanelContext(in_srv=True)
    collect([Recorder(), Recorder()], ctx, wanted={"alpha", "beta"})
    assert len(set(seen)) == 1


# ── constants ─────────────────────────────────────────────────────────────────

def test_the_documented_vocabularies_are_what_the_code_accepts():
    assert set(ZONES) == {"left", "centre", "right", "dock-left", "dock-right"}
    assert set(MODES) == {"on", "off", "auto"}
    assert set(HIDE_MODES) == {"collapse", "reserve"}


# ── a real component's panel ──────────────────────────────────────────────────

def _cargo_plugin():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cargo_under_test", ROOT / "components" / "cargo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = mod.CargoPlugin.__new__(mod.CargoPlugin)
    return p


class _State:
    def __init__(self, **kw):
        self.cargo_items = kw.get("items", {})
        self.cargo_capacity = kw.get("cap", 0)
        self.srv_cargo_count = kw.get("srv", 0)
        self.srv_type = kw.get("srv_type", "")


def _with_state(st):
    p = _cargo_plugin()
    p._state = st
    return p


def test_cargo_panel_reports_the_ship_hold():
    p = _with_state(_State(items={"gold": {"count": 32}}, cap=300))
    panel = p.overlay_panel("cargo", PanelContext())
    assert panel and dict(panel.rows)["Hold"] == "32/300"


def test_cargo_panel_reports_both_holds_in_an_srv():
    """The run is limited by the mothership, not the SRV, so a commander who
    can see only one of them is the one who drives back to a full ship."""
    p = _with_state(_State(items={"gold": {"count": 290}}, cap=300,
                           srv=4, srv_type="SRV Scarab"))
    panel = p.overlay_panel("cargo", PanelContext(in_srv=True))
    rows = dict(panel.rows)
    assert rows["SRV"] == "4/4" and rows["Ship"] == "290/300"


def test_cargo_panel_is_absent_with_no_hold_at_all():
    p = _with_state(_State())
    assert p.overlay_panel("cargo", PanelContext()) is None


def test_cargo_panel_ignores_ids_that_are_not_its_own():
    p = _with_state(_State(cap=64))
    assert p.overlay_panel("exobio", PanelContext()) is None


def test_the_cargo_panel_flows_through_collection_and_layout():
    p = _with_state(_State(items={"gold": {"count": 10}}, cap=64))
    panels = collect([p], PanelContext(), wanted={"cargo"})
    els, heights = layout([_place("cargo", zone="right")], panels, 1920)
    assert els and all(e["align"] == "right" for e in els)
    assert heights["cargo"] == 2 * LINE_HEIGHT


# ── panels come from what components already compute ──────────────────────────

class _Activity:
    """Stands in for any activity component: exobiology, combat, trade..."""
    PLUGIN_NAME = "exobiology"
    ACTIVITY_TAB_TITLE = "Exobio"

    def __init__(self, active=True, rows=None):
        self._active = active
        self._rows = rows if rows is not None else [
            {"label": "Scanned", "value": "12", "rate": "4.1 /hr"},
            {"label": "Value", "value": "88M", "rate": None},
        ]

    def has_activity(self):
        return self._active

    def get_summary_rows(self):
        return self._rows


def _provider(**kw):
    from core.activity import ActivityProviderMixin
    return type("P", (_Activity, ActivityProviderMixin), {})(**kw)


def test_an_activity_component_gets_a_panel_without_declaring_one():
    """The mixin already knows the relevance test and the condensed rows.

    Asking components to write those again for the overlay would be a second
    answer to a question they have already answered, and the two would drift.
    """
    p = _provider()
    assert p.OVERLAY_PANELS == ("exobiology",)
    panel = p.overlay_panel("exobiology", PanelContext())
    assert panel and panel.title == "EXOBIO"
    assert panel.rows[0] == ("Scanned", "12  4.1 /hr")


def test_has_activity_is_the_relevance_test():
    assert _provider(active=False).overlay_panel("exobiology", PanelContext()) is None


def test_no_summary_rows_means_no_panel():
    assert _provider(rows=[]).overlay_panel("exobiology", PanelContext()) is None


def test_rows_are_trimmed_to_what_fits_over_a_game():
    rows = [{"label": f"l{i}", "value": str(i), "rate": None} for i in range(12)]
    panel = _provider(rows=rows).overlay_panel("exobiology", PanelContext())
    assert len(panel.rows) == 4


def test_a_component_raising_yields_no_panel_rather_than_a_traceback():
    from core.activity import ActivityProviderMixin

    class Broken(ActivityProviderMixin):
        PLUGIN_NAME = "broken"

        def has_activity(self):
            raise RuntimeError("nope")

    assert Broken().overlay_panel("broken", PanelContext()) is None


def test_the_default_panel_ignores_other_panel_ids():
    assert _provider().overlay_panel("cargo", PanelContext()) is None


def test_an_activity_panel_flows_through_collection():
    out = collect([_provider()], PanelContext(), wanted={"exobiology"})
    assert out["exobiology"] is not None


# ── ordering within a zone ────────────────────────────────────────────────────

def test_position_is_a_closed_vocabulary():
    from core.overlay_panels import POSITIONS
    assert POSITIONS[0] == "1" and len(POSITIONS) == 9


def test_position_decides_the_stack_order():
    cfg = {"Panels": {
        "ship":      {"Zone": "left", "Mode": "auto", "Order": 3},
        "cargo":     {"Zone": "left", "Mode": "auto", "Order": 1},
        "commander": {"Zone": "left", "Mode": "auto", "Order": 2},
    }}
    places = placements_from_config(cfg)
    panels = {k: _panel(k) for k in ("ship", "cargo", "commander")}
    els, _ = layout(places, panels, 1920)
    ys = {e["id"].split(".")[0]: e["y"] for e in els if e["id"].endswith(".title")}
    assert ys["cargo"] < ys["commander"] < ys["ship"]


def test_a_shared_position_falls_back_to_panel_id_not_dict_order():
    """Stable across restarts.

    A tie broken by whatever order the config happened to parse in would
    reshuffle the overlay between launches, which is worse than a boring
    alphabetical rule.
    """
    cfg = {"Panels": {
        "zulu":  {"Zone": "left", "Mode": "auto", "Order": 1},
        "alpha": {"Zone": "left", "Mode": "auto", "Order": 1},
    }}
    assert [p.panel_id for p in placements_from_config(cfg)] == ["alpha", "zulu"]

    reversed_cfg = {"Panels": dict(reversed(list(cfg["Panels"].items())))}
    assert [p.panel_id for p in placements_from_config(reversed_cfg)] \
        == ["alpha", "zulu"]


def test_ordering_is_per_zone_not_global():
    cfg = {"Panels": {
        "a": {"Zone": "left",  "Mode": "auto", "Order": 5},
        "b": {"Zone": "right", "Mode": "auto", "Order": 9},
    }}
    els, _ = layout(placements_from_config(cfg),
                    {"a": _panel("a"), "b": _panel("b")}, 1920)
    ys = {e["id"].split(".")[0]: e["y"] for e in els if e["id"].endswith(".title")}
    assert ys["a"] == ys["b"], "each zone starts at the top regardless of order"


# ── the renderer's own rules, without a display ───────────────────────────────

def test_the_renderer_does_not_use_window_opacity():
    """setWindowOpacity on a translucent window asks the compositor for a
    semi-transparent surface, and several answer by giving it an opaque one to
    fade — which is how an overlay with nothing on it became a black rectangle
    over the cockpit. Opacity belongs on the ink."""
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "setWindowOpacity" not in code


def test_the_renderer_hides_on_an_empty_frame():
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert "self.hide()" in src, "an empty frame must hide the window, not paint nothing"
    # and must not show itself before the first frame arrives
    assert "widget.show()" not in src


def test_the_renderer_watches_for_a_dead_parent():
    """Closing stdin is the normal shutdown, but a parent that is killed or
    never runs its unload path left the overlay drawing over the game with
    nothing feeding it."""
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert "getppid" in src and "_watch_parent" in src


# ── config keys the writer can actually store ─────────────────────────────────

def test_placement_uses_flat_keys_not_a_dotted_path():
    """The preferences writer assigns target[key] = value.

    A dotted key is therefore written literally — a flat string key containing
    dots, not a nested table — and nothing reads it back. Panel placement could
    be changed in either front end, saved without error, and do nothing at all.
    """
    from core.overlay_panels import placement_keys
    keys = placement_keys("cargo")
    assert set(keys) == {"zone", "mode", "order", "scope"}
    for k in keys.values():
        assert "." not in k, f"{k} would not survive the config writer"
        assert k.endswith("cargo")


def test_flat_keys_are_read_back():
    got = placements_from_config({
        "PanelZone_cargo": "right", "PanelMode_cargo": "on",
        "PanelOrder_cargo": 3})
    assert len(got) == 1
    assert got[0].zone == "right" and got[0].mode == "on" and got[0].order == 3


def test_a_hand_written_panels_table_still_works():
    got = placements_from_config(
        {"Panels": {"ship": {"Zone": "centre", "Mode": "auto", "Order": 5}}})
    assert got and got[0].zone == "centre"


def test_flat_keys_win_over_the_table():
    got = placements_from_config({
        "Panels": {"ship": {"Zone": "left", "Mode": "off", "Order": 9}},
        "PanelZone_ship": "right", "PanelMode_ship": "on"})
    assert got[0].zone == "right" and got[0].mode == "on"
    assert got[0].order == 9, "a field not overridden keeps the table's value"


def test_a_nonsense_order_does_not_crash_the_read():
    got = placements_from_config({"PanelZone_a": "left", "PanelMode_a": "on",
                                  "PanelOrder_a": "not a number"})
    assert got and got[0].order == 100


def test_unrelated_keys_in_the_section_are_ignored():
    got = placements_from_config({"HideMode": "reserve", "TitleColour": "#fff"})
    assert got == []


def test_the_overlay_component_binds_only_writable_keys():
    import ast

    src = (ROOT / "components" / "overlay.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("Panels."):
                pytest.fail(f"dotted config key {node.value!r} will not persist")


# ── the doctor ────────────────────────────────────────────────────────────────

def _doctor_output(section: dict, window: dict | None = None,
                   plugins=None) -> str:
    import io
    import contextlib

    from core.overlay_doctor import run

    class _Cfg:
        config_profile = "EDP1"
        config_path = "/tmp/config.toml"

        def load_setting(self, name, defaults, warn=False,
                         include_extra=False):
            if name == "Overlay":
                return {**defaults, **(window or {})}
            # The real one drops undeclared keys unless asked; the stub has to
            # behave the same way or the doctor tests would pass against a
            # reader that does not.
            assert include_extra, "OverlayPanels must be read with include_extra"
            return {**defaults, **section}

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run(_Cfg(), plugins=plugins)
    return buf.getvalue()


def test_doctor_names_a_disabled_overlay_first():
    out = _doctor_output({}, {"Enabled": False})
    assert "Overlay.Enabled is false" in out


def test_doctor_names_missing_placements():
    out = _doctor_output({}, {"Enabled": True})
    assert "placement keys found       0" in out
    assert "No panel placements in config" in out


def test_doctor_names_everything_switched_off():
    out = _doctor_output(
        {"PanelZone_cargo": "left", "PanelMode_cargo": "off"}, {"Enabled": True})
    assert "Every placed panel is mode=off" in out


def test_doctor_reports_a_sound_setup_as_sound():
    out = _doctor_output(
        {"PanelZone_cargo": "left", "PanelMode_cargo": "on"}, {"Enabled": True})
    assert "look sound" in out
    assert "zone=left mode=on" in out


def test_doctor_flags_a_placement_no_component_offers():
    class _C:
        PLUGIN_NAME = "cargo"
        OVERLAY_PANELS = ("cargo",)

    out = _doctor_output(
        {"PanelZone_ghost": "left", "PanelMode_ghost": "on"},
        {"Enabled": True}, plugins=[_C()])
    assert "placed but no component" in out
    assert "offered but unplaced" in out


def test_doctor_surfaces_an_invalid_zone():
    out = _doctor_output(
        {"PanelZone_cargo": "middle", "PanelMode_cargo": "on"}, {"Enabled": True})
    assert "middle" in out


# ── the renderer's environment ────────────────────────────────────────────────

def test_compositing_is_measured_not_assumed():
    """The previous check called app.isEffectivelyCompositing(), which does not
    exist on QApplication — so getattr(..., lambda: True) answered True every
    time and the value was never measured. Without a compositor a translucent
    window has no backing store and the overlay draws nothing at all."""
    import ast

    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    # An AST check, not a grep: the docstring explaining this bug names the
    # method, and a grep test would fail on its own explanation. That is the
    # second time a string-matching test has tripped over a comment about the
    # thing it was written to catch.
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Attribute) \
                and node.attr == "isEffectivelyCompositing":
            pytest.fail("compositing must be measured, not assumed")
        if isinstance(node, ast.Constant) and node.value == "isEffectivelyCompositing":
            pytest.fail("compositing must be measured, not assumed")
    assert "_NET_WM_CM_S0" in src, "ask X who owns the compositor selection"


def test_no_compositor_means_an_opaque_panel_not_an_invisible_one():
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert "self._composited" in src
    assert "WA_TranslucentBackground, self._composited" in src, \
        "translucency must be conditional on there being a compositor"
    assert "fillRect" in src, "without one, paint a background so text shows"


def test_unknown_compositing_state_errs_toward_visible():
    """Assuming a compositor and being wrong renders an invisible overlay.
    Assuming none and being wrong renders a readable one with a panel."""
    import inspect

    from core.overlay_proc import _x11_compositing

    src = inspect.getsource(_x11_compositing)
    assert src.rstrip().endswith("return False")


def test_the_renderer_reports_where_the_window_landed():
    """'The renderer is running' and 'there is something on screen' are
    different claims, and only the second one matters."""
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert '"event": "shown"' in src
    for field in ("visible", "geometry", "screen", "alpha"):
        assert f'"{field}"' in src


def test_the_selftest_frame_exists_and_is_drawable():
    from core.overlay_proc import _SELFTEST_FRAME

    assert _SELFTEST_FRAME
    for el in _SELFTEST_FRAME:
        assert el["type"] == "text" and el["text"]
        assert {"x", "y", "colour", "size", "align"} <= set(el)


# ── the frame itself is reported ──────────────────────────────────────────────

def test_the_component_reports_its_first_frame_and_its_empty_frames():
    """The doctor runs before components load, so it can report config and
    placement but never whether a frame would have content. 'Placement looks
    sound' plus 'renderer ready' still left no way to distinguish a frame with
    three panels from a frame with none."""
    src = (ROOT / "components" / "overlay.py").read_text(encoding="utf-8")
    assert "first frame sent" in src
    assert "frame is empty" in src
    assert "_empty_warned" in src, "say it once, not twice a second"


# ── cross-thread delivery ─────────────────────────────────────────────────────

def test_frames_cross_threads_by_signal_not_by_timer():
    """QTimer.singleShot creates its timer in the *calling* thread.

    From the stdin reader — a plain worker thread with no Qt event loop —
    nothing ever fires it, so every frame was accepted, marshalled and
    silently never delivered. The parent logged sent=True twice a second and
    was telling the truth: the frames reached the process and stopped at the
    thread boundary. --overlay-selftest worked because it calls singleShot
    from the main thread, where there is a loop to run it.
    """
    import ast

    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    worker_functions = {"_reader", "_watch_parent"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in worker_functions:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Attribute) and inner.attr == "singleShot":
                pytest.fail(f"{node.name} uses QTimer.singleShot across threads; "
                            f"emit a signal or invokeMethod instead")

    assert "_make_bridge" in src
    assert "bridge.frame.emit" in src
    assert "invokeMethod" in src, "quitting from a worker thread needs it too"


def test_the_bridge_lives_with_the_widget():
    """A signal only queues onto the receiver's thread if the receiver is
    there — an object created in the worker would marshal to the worker."""
    import ast

    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [n.func.id for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "_make_bridge" in calls, "the bridge must be built on the GUI thread"


# ── the vessel panel is titled for what you are in ────────────────────────────

def _commander_plugin(state):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cmdr_panel", ROOT / "components" / "commander.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = mod.CommanderPlugin.__new__(mod.CommanderPlugin)
    p.core = type("C", (), {"state": state})()
    return p


class _ShipState:
    ship_name = "Pictor"
    ship_ident = "CE-PIC"
    pilot_ship = "Caspian Explorer"
    ship_hull = 100
    capi_ship_value = None
    srv_type = "Scarab"


def test_vessel_panel_is_headed_by_the_ship_whatever_you_are_in():
    """The ship is your vessel whether you are sitting in it or not, so the
    header is stable; what you are in right now is the first row."""
    p = _commander_plugin(_ShipState())
    assert p.overlay_panel("ship", PanelContext()).title == "Pictor [CE-PIC]"
    assert p.overlay_panel("ship", PanelContext(in_srv=True)).title \
        == "Pictor [CE-PIC]"


def test_vessel_panel_names_the_srv_you_are_in():
    p = _commander_plugin(_ShipState())
    panel = p.overlay_panel("ship", PanelContext(in_srv=True))
    assert panel.rows[0][1] == "Scarab", "what you are in comes first"


def test_vessel_panel_names_the_suit_on_foot():
    p = _commander_plugin(_ShipState())
    panel = p.overlay_panel("ship", PanelContext(on_foot=True,
                                                 suit_name="Artemis Suit"))
    assert panel.rows[0][1] == "Artemis Suit"


# ── font, size and padding are configurable ───────────────────────────────────

def test_line_height_follows_the_body_size():
    """A commander who raises the font and finds the rows overlapping has been
    given a setting that breaks the layout."""
    from core.overlay_panels import line_height

    assert line_height(13) < line_height(20) < line_height(30)
    assert line_height(4) >= 12, "never collapse to unreadable"


def test_a_larger_body_size_spaces_the_rows_further():
    places = [_place("a", order=1), _place("b", order=2)]
    panels = {"a": _panel("a", rows=2), "b": _panel("b", rows=2)}
    small, _ = layout(places, panels, 1920, colours={"BodySize": 13})
    big, _ = layout(places, dict(panels), 1920, colours={"BodySize": 26})
    assert _ys(big, "b.")[0] > _ys(small, "b.")[0]


def test_padding_moves_the_first_row_off_the_edge():
    els, _ = layout([_place("a")], {"a": _panel("a")}, 1920, pad_x=40, pad_y=30)
    assert _ys(els, "a.")[0] == 30
    assert next(e["x"] for e in els if e["id"] == "a.title") == 40


def test_the_renderer_treats_y_as_a_top_not_a_baseline():
    """drawText takes a baseline. Passing a top as a baseline puts the whole
    ascent above the requested y, which clipped the first row no matter how
    far the window was padded from the screen edge."""
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert "fontMetrics().ascent()" in src


def test_a_configured_font_family_reaches_the_renderer():
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert 'cfg.get("FontFamily"' in src
    assert "setFamily" in src


# ── themes and fonts ──────────────────────────────────────────────────────────

def test_the_elite_theme_is_the_games_orange():
    from core.palette import overlay_colours

    c = overlay_colours("elite-orange")
    assert c["TitleColour"].lower() == "#ff7100"
    assert c["ValueColour"] and c["LabelColour"]


def test_every_edld_theme_yields_overlay_colours():
    """Derived from the palette, so a theme added to palette.py reaches the
    overlay without anything else being edited."""
    from core.palette import THEME_CHOICES, overlay_colours

    for _name, value in THEME_CHOICES:
        c = overlay_colours(value)
        assert c, f"{value} produced no overlay colours"
        assert set(c) == {"TitleColour", "LabelColour", "ValueColour"}


def test_custom_means_use_what_was_stored():
    from core.palette import overlay_colours

    assert overlay_colours("custom") is None
    assert overlay_colours("") is None
    assert overlay_colours("no-such-theme") is None


def test_a_theme_overrides_drawing_without_touching_stored_colours():
    from core.palette import overlay_colours

    stored = {"TitleColour": "#111111", "LabelColour": "#222222",
              "ValueColour": "#333333", "BodySize": 13}
    drawn = {**stored, **(overlay_colours("elite-orange") or {})}
    assert drawn["TitleColour"] == "#ff7100"
    assert stored["TitleColour"] == "#111111", "stored settings are untouched"

    back = {**stored, **(overlay_colours("custom") or {})}
    assert back["TitleColour"] == "#111111", "custom restores what was set"


def test_theme_colours_reach_the_drawn_elements():
    from core.palette import overlay_colours

    els, _ = layout([_place("a")], {"a": _panel("a")}, 1920,
                    colours={**CFG_DEFAULTS_PANELS,
                             **(overlay_colours("elite-orange") or {})})
    title = next(e for e in els if e["id"] == "a.title")
    assert title["colour"].lower() == "#ff7100"


def test_fonts_are_discovered_not_hardcoded():
    """The set of Elite faces on offer is not something this code should claim
    to know — register whatever is in the fonts directory and let the files
    name themselves."""
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert "addApplicationFont" in src
    assert "applicationFontFamilies" in src
    assert '"fonts"' in src, "the renderer reports what it registered"


# ── shipped fonts ─────────────────────────────────────────────────────────────

def test_the_renderer_looks_in_both_font_directories():
    """The repo directory is what everyone gets; the data directory is where a
    commander puts a face we cannot redistribute."""
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert "_repo_fonts_dir" in src
    assert "EDLD_DATA_DIR" in src
    assert "_MEIPASS" in src, "frozen builds keep fonts beside the bundle"


def test_shipped_fonts_reach_the_binary():
    src = (ROOT / "packaging" / "build_common.py").read_text(encoding="utf-8")
    assert '"fonts"' in src, "fonts must be in DATA_FILES or frozen builds have none"


def test_the_overlay_tab_scrolls_as_one_page():
    """An inner scroll area inside a fixed-height tab takes stretch from the
    form rows above it, so they are squeezed below their own minimum and the
    sections draw on top of each other. With twenty-odd settings the page is
    simply taller than the tab; the fix is to let the tab scroll rather than to
    compress its contents."""
    import ast

    src = (ROOT / "components" / "overlay.py").read_text(encoding="utf-8")
    assert src.count("QScrollArea()") == 1, \
        "one scroll area, around the whole page — not a second one inside it"

    tree = ast.parse(src)
    builder = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_build")
    body = ast.get_source_segment(src, builder) or ""
    assert "page.setWidget(content)" in body, "the scroll area owns the page"
    assert "lay.addStretch(1)" in body, \
        "without a trailing stretch the last widget absorbs the slack"


# ── sessions where an overlay makes no sense ──────────────────────────────────

def _overlay_plugin(ui_mode="textual", primary=True, env=None, monkeypatch=None):
    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "ov_under_test", ROOT / "components" / "overlay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Core:
        _plugins: dict = {}

        def __init__(self):
            self.ui_mode = ui_mode

        def load_setting(self, section, defaults, warn=False, include_extra=False):
            d = dict(defaults)
            if section == "Settings":
                d["PrimaryInstance"] = primary
            return d

    p = mod.OverlayPlugin()
    p._core = _Core()
    if monkeypatch is not None:
        for k, v in (env or {"DISPLAY": ":0"}).items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
    return p


def test_terminal_mode_gets_no_overlay(monkeypatch):
    p = _overlay_plugin(ui_mode="terminal", monkeypatch=monkeypatch)
    assert "terminal mode" in p._unsupported_reason()


def test_a_secondary_instance_gets_no_overlay(monkeypatch):
    """The overlay belongs on the machine the game is running on."""
    p = _overlay_plugin(primary=False, monkeypatch=monkeypatch)
    assert "secondary instance" in p._unsupported_reason()


def test_a_headless_session_gets_no_overlay(monkeypatch):
    p = _overlay_plugin(env={"DISPLAY": None, "WAYLAND_DISPLAY": None},
                        monkeypatch=monkeypatch)
    assert "headless" in p._unsupported_reason()


def test_a_normal_windowed_session_is_supported(monkeypatch):
    for mode in ("textual", "gui"):
        p = _overlay_plugin(ui_mode=mode, monkeypatch=monkeypatch)
        assert p._unsupported_reason() == "", mode


def test_wayland_counts_as_a_display(monkeypatch):
    p = _overlay_plugin(env={"DISPLAY": None, "WAYLAND_DISPLAY": "wayland-0"},
                        monkeypatch=monkeypatch)
    assert p._unsupported_reason() == ""


def test_the_core_carries_the_ui_mode():
    """A component cannot ask which front end is running unless something
    tells it."""
    import ast

    src = (ROOT / "core" / "core_api.py").read_text(encoding="utf-8")
    assert "self.ui_mode" in src
    edld = (ROOT / "edld.py").read_text(encoding="utf-8")
    assert "ui_mode=ui_mode" in edld, "edld.py must pass it to CoreAPI"


# ── docked windows ────────────────────────────────────────────────────────────

def test_the_top_bar_zones_keep_their_names():
    """Renaming them to top-left and so on would have silently unplaced every
    panel in every existing config, because an unknown zone is skipped."""
    from core.overlay_panels import ZONE_WINDOW

    for z in ("left", "centre", "right"):
        assert ZONE_WINDOW[z] == "top"


def test_each_dock_is_its_own_window():
    from core.overlay_panels import WINDOWS, ZONE_WINDOW

    assert ZONE_WINDOW["dock-left"] == "dock-left"
    assert ZONE_WINDOW["dock-right"] == "dock-right"
    assert set(WINDOWS) == {"top", "dock-left", "dock-right"}


def test_a_window_only_draws_its_own_zones():
    from core.overlay_panels import WINDOWS

    places = [_place("a", zone="centre"), _place("b", zone="dock-left"),
              _place("c", zone="dock-right")]
    panels = {k: _panel(k) for k in "abc"}
    drawn = {}
    for win in WINDOWS:
        els, _ = layout(places, panels, 720, window=win)
        drawn[win] = sorted({e["id"].split(".")[0] for e in els})
    assert drawn == {"top": ["a"], "dock-left": ["b"], "dock-right": ["c"]}


def test_an_empty_dock_produces_no_elements():
    """Which is what hides the window, so docking nothing costs nothing."""
    els, _ = layout([_place("a", zone="centre")], {"a": _panel("a")}, 720,
                    window="dock-left")
    assert els == []


def test_a_dock_stacks_in_position_order():
    places = [_place("a", zone="dock-left", order=3),
              _place("b", zone="dock-left", order=1),
              _place("c", zone="dock-left", order=2)]
    panels = {k: _panel(k) for k in "abc"}
    els, _ = layout(sorted(places, key=lambda p: p.order), panels, 260,
                    window="dock-left")
    ys = {e["id"].split(".")[0]: e["y"] for e in els if e["id"].endswith(".title")}
    assert ys["b"] < ys["c"] < ys["a"]


def test_both_docks_read_left_to_right():
    """A right-hand dock right-aligned against a narrow window would put its
    text hard against the screen edge, where it is least readable."""
    for zone in ("dock-left", "dock-right"):
        els, _ = layout([_place("a", zone=zone)], {"a": _panel("a")}, 260,
                        window=zone)
        assert all(e["align"] == "left" for e in els), zone


def test_the_protocol_carries_a_window_id():
    src = (ROOT / "core" / "overlay.py").read_text(encoding="utf-8")
    assert '"window": window' in src
    child = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert 'msg.get("window"' in child
    assert "Signal(str, list)" in child, "the bridge must carry the window too"


def test_the_commander_panel_uses_the_name_as_its_header():
    """A COMMANDER title immediately above "CMDR <name>" spends a line of a
    very small display saying the same thing twice."""
    class _S:
        pilot_name = "Merrick Calbruin"
        pilot_squadron_name = "Mining and Logistics Ltd"
        pilot_squadron_tag = "MALL"
        assets_balance = 1.47e9
        pilot_location = "Stefansson Station"

    p = _commander_plugin(_S())
    panel = p.overlay_panel("commander", PanelContext())
    assert panel.title == "CMDR Merrick Calbruin"
    joined = " ".join(v for _l, v in panel.rows)
    assert "CMDR" not in joined, "the name must not also appear in the body"
    assert "MALL" in joined and "Stefansson" in joined


def test_no_commander_name_means_no_panel():
    class _S:
        pilot_name = None

    assert _commander_plugin(_S()).overlay_panel("commander",
                                                 PanelContext()) is None


def test_the_commander_name_scan_walks_back_through_journals():
    """Elite writes a new journal on launch and emits no Commander or LoadGame
    until someone actually loads in, so the newest file can be a Fileheader and
    nothing else. Reading only that file left pilot_name empty — and with it
    profile auto-detection, EDSM, Inara and the overlay."""
    import ast

    src = (ROOT / "edld.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_scan_journals"), None)
    assert fn is not None, "the name lookup must share the FID scanner's walk-back"
    body = ast.get_source_segment(src, fn) or ""
    assert "glob" in body and "reverse=True" in body
    assert 'state.pilot_name = _scan_journals(' in src


# ── panel content moves ───────────────────────────────────────────────────────

def test_the_commander_panel_no_longer_carries_the_balance():
    """It is a number about money and belongs next to the rate changing it."""
    class _S:
        pilot_name = "Merrick Calbruin"
        pilot_squadron_name = "MALL"
        pilot_squadron_tag = "MALL"
        assets_balance = 1.47e9
        pilot_location = "Stefansson Station"

    panel = _commander_plugin(_S()).overlay_panel("commander", PanelContext())
    joined = " ".join(f"{l}{v}" for l, v in panel.rows)
    assert "cr" not in joined and "1.47" not in joined


def test_the_vessel_panel_is_name_type_and_value_only():
    class _S:
        ship_name = "Pictor"
        ship_ident = "CE-PIC"
        pilot_ship = "Caspian Explorer"
        ship_hull = 63
        capi_ship_value = {"total": 2_160_000}
        srv_type = "Scarab"

    panel = _commander_plugin(_S()).overlay_panel("ship", PanelContext())
    assert panel.title == "Pictor [CE-PIC]"
    labels = [l for l, _v in panel.rows]
    assert "Hull" not in labels, "the HUD already shows hull, unmissably"
    assert "Shields" not in labels
    assert "Value" in labels
    assert any(v == "Caspian Explorer" for _l, v in panel.rows)


def test_the_srv_still_says_what_you_are_in():
    class _S:
        ship_name = "Pictor"
        ship_ident = "CE-PIC"
        pilot_ship = "Caspian Explorer"
        capi_ship_value = None
        srv_type = "Scarab"

    panel = _commander_plugin(_S()).overlay_panel("ship", PanelContext(in_srv=True))
    assert panel.rows[0][1] == "Scarab"


def test_income_panel_carries_credits_and_the_session_rate():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "income_panel", ROOT / "components" / "income.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    p = mod.ActivityIncomePlugin.__new__(mod.ActivityIncomePlugin)
    p.core = type("C", (), {"state": type("S", (), {"assets_balance": 1.47e11})()})()
    p.total_income = 1_960_000
    p._cph = lambda: "4.22M/hr"

    panel = p.overlay_panel("income", PanelContext())
    rows = dict(panel.rows)
    assert panel.title == "INCOME"
    assert rows["Credits:"] == "147.00B cr"
    assert "|" in rows["Session:"] and "4.22M/hr" in rows["Session:"]


def test_income_panel_shows_credits_before_any_income():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "income_panel2", ROOT / "components" / "income.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    p = mod.ActivityIncomePlugin.__new__(mod.ActivityIncomePlugin)
    p.core = type("C", (), {"state": type("S", (), {"assets_balance": 5_000})()})()
    p.total_income = 0
    panel = p.overlay_panel("income", PanelContext())
    assert [l for l, _ in panel.rows] == ["Credits:"]


# ── options list and live reload ──────────────────────────────────────────────

def test_the_panel_list_is_alphabetical():
    """Grouping by zone made a row jump the moment its zone changed — the
    setting you had just edited moved somewhere else in the list."""
    src = (ROOT / "components" / "overlay.py").read_text(encoding="utf-8")
    assert "key=lambda r: r[0]" in src
    assert "ZONE_ORDER.get" not in src


def test_the_overlay_reloads_when_the_config_file_changes():
    """Both front ends write the same file and neither had a hook to notify a
    component with, so the file's modification time is what is watched."""
    src = (ROOT / "components" / "overlay.py").read_text(encoding="utf-8")
    assert "_reload_if_changed" in src
    assert "_cfg_mtime" in src
    assert "self._heights = {}" in src, \
        "reserved heights describe the old layout and must not survive a reload"


# ── powerplay ─────────────────────────────────────────────────────────────────

def _pp_plugin(power=None, rank=None):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pp_panel", ROOT / "components" / "powerplay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = mod.ActivityPowerplayPlugin.__new__(mod.ActivityPowerplayPlugin)
    p.power = power
    p.rank_current = rank
    p.core = type("C", (), {"state": type("S", (), {"pp_power": power,
                                                    "pp_rank": rank})()})()
    return p


def test_an_unpledged_commander_gets_no_powerplay_panel():
    """Not an empty panel, not one reading "None" — a line that exists only to
    say a feature is switched off is worse than the space it takes."""
    assert _pp_plugin().overlay_panel("powerplay", PanelContext()) is None


def test_a_pledged_commander_gets_power_and_rank_only():
    panel = _pp_plugin(power="Nakato Kaine", rank=103).overlay_panel(
        "powerplay", PanelContext())
    assert panel.title == "Nakato Kaine"
    assert panel.rows == [("", "Rank 103")]


def test_the_powerplay_panel_overrides_the_activity_default():
    """The mixin's default would report session merits, and only once some had
    been earned. Allegiance and rank are true the moment you undock."""
    import ast

    src = (ROOT / "components" / "powerplay.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and "Powerplay" in n.name)
    assert any(isinstance(m, ast.FunctionDef) and m.name == "overlay_panel"
               for m in cls.body)


# ── margin versus padding ─────────────────────────────────────────────────────

def test_margin_and_padding_are_separate_and_both_reachable():
    """OffsetY set the distance from the monitor edge and was exposed in
    neither front end, while the exposed "Padding Y" only moved text inside a
    fixed-size window. There was no reachable answer to "what moves the
    overlay down the screen"."""
    from core.overlay import CFG_DEFAULTS

    assert "MarginX" in CFG_DEFAULTS and "MarginY" in CFG_DEFAULTS
    assert "PadX" in CFG_DEFAULTS and "PadY" in CFG_DEFAULTS

    src = (ROOT / "components" / "overlay.py").read_text(encoding="utf-8")
    for key in ("MarginX", "MarginY", "PadX", "PadY"):
        assert src.count(f'"{key}"') >= 3, f"{key} must be in both front ends"


def test_the_old_offset_names_still_position_an_existing_config():
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert 'cfg.get("OffsetX"' in src and 'cfg.get("OffsetY"' in src, \
        "an existing config must keep the position it had"


# ── career / session scope ────────────────────────────────────────────────────

def _scoped(scope, session=None, career=None, section="Trade"):
    from core.activity import ActivityProviderMixin

    class P(ActivityProviderMixin):
        PLUGIN_NAME = "trade"
        ACTIVITY_TAB_TITLE = section
        OVERLAY_SCOPE = scope

        def __init__(self):
            self.core = object()

        def has_activity(self):
            return bool(session)

        def get_summary_rows(self):
            return list(session or [])

        def overlay_career_rows(self, core):
            return list(career or [])

    return P()


SESSION = [{"label": "Profit", "value": "1.96M", "rate": "4.22M/hr"}]
CAREER = [{"label": "Profit", "value": "12.4B", "rate": None}]


def test_session_scope_shows_the_session():
    panel = _scoped("session", SESSION, CAREER).overlay_panel("trade",
                                                              PanelContext())
    assert panel.rows == [("Profit", "1.96M  4.22M/hr")]


def test_career_scope_shows_the_career():
    panel = _scoped("career", SESSION, CAREER).overlay_panel("trade",
                                                             PanelContext())
    assert panel.rows == [("Profit", "12.4B")]


def test_both_puts_the_session_in_parentheses():
    """A commander who wants both wants to know what today added to the total,
    not to read two numbers and do the subtraction."""
    panel = _scoped("both", SESSION, CAREER).overlay_panel("trade",
                                                           PanelContext())
    assert panel.rows == [("Profit", "12.4B (Session: 1.96M)")]


def test_both_falls_back_to_session_when_there_is_no_career_row():
    panel = _scoped("both", SESSION, []).overlay_panel("trade", PanelContext())
    assert panel.rows == [("Profit", "1.96M  4.22M/hr")]


def test_career_scope_survives_a_quiet_session():
    """Career figures are true whether or not anything happened today."""
    panel = _scoped("career", [], CAREER).overlay_panel("trade", PanelContext())
    assert panel and panel.rows == [("Profit", "12.4B")]


def test_no_rows_at_all_means_no_panel():
    assert _scoped("both", [], []).overlay_panel("trade", PanelContext()) is None


def test_the_scope_picker_is_only_offered_where_both_halves_exist():
    """A dropdown choosing between career and session on an activity that has
    only one of them is a control that does nothing."""
    assert _scoped("session", SESSION, CAREER).overlay_has_career(object())
    assert not _scoped("session", SESSION, []).overlay_has_career(object())


def test_scope_is_a_flat_config_key_like_the_others():
    from core.overlay_panels import KEY_SCOPE, SCOPES, placement_keys

    assert placement_keys("trade")["scope"] == f"{KEY_SCOPE}trade"
    assert "." not in placement_keys("trade")["scope"]
    assert set(SCOPES) == {"session", "career", "both"}


# ── shadow colour ─────────────────────────────────────────────────────────────

def _lightness(hexcolour):
    raw = hexcolour.lstrip("#")
    r, g, b = (int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (max(r, g, b) + min(r, g, b)) / 2


def test_light_ink_gets_a_dark_shadow():
    from core.overlay_proc import shadow_colour

    for ink in ("#ff7100", "#ffb761", "#cfd6e4", "#ffffff"):
        assert _lightness(shadow_colour(ink)) < 0.2, ink


def test_dark_ink_gets_a_light_shadow():
    """A light theme's dark ink needs a shadow lighter than itself, or the two
    merge."""
    from core.overlay_proc import shadow_colour

    assert _lightness(shadow_colour("#1b2430")) > 0.8


def test_a_muted_colour_is_still_treated_as_light_ink():
    """The threshold judges the ink against the game behind it, not against a
    midpoint. A midpoint gave the muted amber label a near-white shadow, which
    against a starfield is the brightest thing on screen."""
    from core.overlay_proc import shadow_colour

    assert _lightness(shadow_colour("#8a5a22")) < 0.2


def test_the_shadow_keeps_the_inks_hue():
    """Flat black reads as a separate colour against a tinted palette — a black
    fringe on Elite orange looks like a printing error."""
    import colorsys

    from core.overlay_proc import shadow_colour

    out = shadow_colour("#ff7100").lstrip("#")
    r, g, b = (int(out[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    assert s > 0, "a pure grey shadow has lost the palette"
    assert abs(h - colorsys.rgb_to_hls(1.0, 0x71 / 255, 0.0)[0]) < 0.02


def test_a_nonsense_colour_falls_back_to_black():
    from core.overlay_proc import shadow_colour

    assert shadow_colour("not-a-colour") == "#000000"
    assert shadow_colour("") == "#000000"


def test_short_hex_is_accepted():
    from core.overlay_proc import shadow_colour

    assert shadow_colour("#fff") == shadow_colour("#ffffff")


def test_the_shadow_offset_is_capped_at_two_pixels():
    """Past that it stops reading as depth and starts reading as a second,
    blurry copy of the text."""
    src = (ROOT / "core" / "overlay_proc.py").read_text(encoding="utf-8")
    assert "min(2, int(cfg.get(\"ShadowOffset\"" in src
    assert 'cfg.get("ShadowStrength"' in src


def test_srv_cargo_shows_a_denominator():
    """The journal never reports a surface vehicle's capacity, so it comes from
    the same table the dashboard uses. Reading it from a state field that does
    not exist is why the overlay said "SRV 4" while the dashboard three feet
    away said "4/72"."""
    p = _with_state(_State(items={"silver": {"count": 0}}, cap=1024, srv=4))
    p._state.srv_type = "SRV Rhino"
    panel = p.overlay_panel("cargo", PanelContext(in_srv=True))
    rows = dict(panel.rows)
    assert rows["SRV"] == "4/72"
    assert rows["Ship"] == "0/1024"


def test_an_unknown_vehicle_shows_the_count_alone():
    """Omitted rather than guessed at."""
    p = _with_state(_State(srv=2, cap=64))
    p._state.srv_type = "SRV Something New"
    assert dict(p.overlay_panel("cargo", PanelContext(in_srv=True)).rows)["SRV"] == "2"

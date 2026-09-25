"""
tests/test_overlay_component.py — the overlay component's renderer lifecycle.

The overlay drew from the same state as the dashboards and still drifted from
them: after an Apply & Save it kept showing the frame it had when the button
was pressed. Reloading config replaced the renderer client without stopping the
old one, so the old renderer stayed on screen with its last frame while every
new frame went to a client that had never been started, and was dropped. Only a
TRACE line (``sent=False``) said so. These tests drive the component through
config reloads with a fake renderer and check that what the dashboard state
says is what reaches the screen.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ── fakes ─────────────────────────────────────────────────────────────────────

class _FakeClient:
    """A renderer client that records frames instead of drawing them."""

    instances: list["_FakeClient"] = []

    def __init__(self, cfg: dict) -> None:
        self.cfg = dict(cfg)
        self.alive = False
        self.stopped = False
        self.starts = 0
        self.frames: list[tuple[str, list[dict]]] = []
        self.fonts: list[str] = []
        _FakeClient.instances.append(self)

    @property
    def running(self) -> bool:
        return self.alive

    def start(self):
        self.starts += 1
        self.alive = True
        return SimpleNamespace(usable=True, summary=lambda: "ready")

    def send(self, elements, window="top") -> bool:
        if not self.alive:
            return False
        self.frames.append((window, elements))
        return True

    def clear(self, window="top") -> bool:
        return self.send([], window)

    def stop(self) -> None:
        self.alive = False
        self.stopped = True

    def status(self) -> str:
        return "ready" if self.alive else "not running"

    def last_text(self) -> str:
        """Every text body in the most recent non-empty frame."""
        for _win, els in reversed(self.frames):
            if els:
                return " ".join(str(e.get("text", e.get("body", "")))
                                for e in els)
        return ""


class _Cfg:
    def __init__(self, path: Path) -> None:
        self.config_path = path

    def refresh(self, terminal_print=False) -> None:
        pass


class _Core:
    ui_mode = "gui"

    def __init__(self, tmp_path: Path, state, plugins: dict) -> None:
        self.cfg = _Cfg(tmp_path / "config.toml")
        self.cfg.config_path.write_text("")
        self.state = state
        self._plugins = plugins
        self.sections: dict[str, dict] = {
            "Settings": {"PrimaryInstance": True},
            "Overlay": {"Enabled": True, "Anchor": "top-centre"},
            "OverlayPanels": {"Panels": {
                "cargo": {"Zone": "left", "Mode": "on", "Order": 1}}},
        }

    def load_setting(self, section, defaults, warn=False, include_extra=False):
        return {**dict(defaults), **self.sections.get(section, {})}

    def save(self, section: str, **values) -> None:
        """Stand-in for Apply & Save: change a section and touch config.toml."""
        self.sections[section] = {**self.sections.get(section, {}), **values}
        p = self.cfg.config_path
        import os
        st = p.stat()
        os.utime(p, (st.st_atime, st.st_mtime + 1))


class _CargoLike:
    """The shape of the cargo component's panel: one number from state."""

    OVERLAY_PANELS = ("cargo",)

    def __init__(self, state) -> None:
        self.state = state

    def overlay_panel(self, panel_id, ctx):
        if panel_id != "cargo":
            return None
        from core.overlay_panels import Panel
        return Panel(id="cargo", title="CARGO",
                     rows=[("SRV", f"{self.state.srv_cargo_count}/72")])


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    spec = importlib.util.spec_from_file_location(
        "overlay_under_test", ROOT / "components" / "overlay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    _FakeClient.instances = []
    monkeypatch.setattr(mod, "client_from_config",
                        lambda cfg, log=None: _FakeClient(cfg)
                        if cfg.get("Enabled") else None)
    # No background tick: the test drives every frame itself.
    monkeypatch.setattr(mod.threading, "Thread",
                        lambda *a, **k: SimpleNamespace(start=lambda: None))

    state = SimpleNamespace(srv_cargo_count=0)
    core = _Core(tmp_path, state, {"cargo": _CargoLike(state)})
    plugin = mod.OverlayPlugin()
    plugin.on_load(core)
    return mod, plugin, core, state


def _tick(plugin) -> None:
    plugin._reload_if_changed()
    plugin.refresh()


def _on_screen(plugin_clients) -> list["_FakeClient"]:
    return [c for c in plugin_clients if c.alive]


# ── the frozen overlay ────────────────────────────────────────────────────────

def test_a_layout_change_keeps_frames_flowing_to_the_screen(overlay):
    """The reported fault: SRV 22 on the overlay, 45 on the dashboard."""
    _mod, plugin, core, state = overlay
    _tick(plugin)                              # establishes the mtime baseline
    state.srv_cargo_count = 22
    _tick(plugin)
    assert "22/72" in _FakeClient.instances[0].last_text()

    core.save("OverlayPanels", HideMode="collapse")      # Apply & Save
    _tick(plugin)
    state.srv_cargo_count = 45
    _tick(plugin)

    live = _on_screen(_FakeClient.instances)
    assert len(live) == 1, "exactly one renderer may be on screen"
    assert "45/72" in live[0].last_text(), \
        "the overlay must show what the dashboard shows after a config reload"


def test_a_layout_only_change_does_not_respawn_the_renderer(overlay):
    _mod, plugin, core, state = overlay
    _tick(plugin)
    _tick(plugin)
    core.save("OverlayPanels", HideMode="collapse")
    _tick(plugin)
    assert len(_FakeClient.instances) == 1
    assert _FakeClient.instances[0].starts == 1


def test_a_window_change_replaces_the_renderer_and_stops_the_old_one(overlay):
    _mod, plugin, core, state = overlay
    _tick(plugin)
    _tick(plugin)
    first = _FakeClient.instances[0]

    core.save("Overlay", Width=900)
    state.srv_cargo_count = 7
    _tick(plugin)

    assert first.stopped, "the old renderer must not be left on screen"
    live = _on_screen(_FakeClient.instances)
    assert len(live) == 1 and live[0] is not first
    assert live[0].cfg.get("Width") == 900
    assert "7/72" in live[0].last_text()


def test_switching_the_overlay_off_takes_it_off_the_screen(overlay):
    _mod, plugin, core, state = overlay
    _tick(plugin)
    _tick(plugin)
    core.save("Overlay", Enabled=False)
    _tick(plugin)
    assert _on_screen(_FakeClient.instances) == []


def test_switching_the_overlay_on_later_needs_no_restart(tmp_path, monkeypatch,
                                                         overlay):
    """The tick used to start only when the overlay was enabled at launch."""
    mod, _plugin, _core, _state = overlay
    started: list = []
    monkeypatch.setattr(mod.threading, "Thread",
                        lambda *a, **k: SimpleNamespace(
                            start=lambda: started.append(k.get("name"))))
    state = SimpleNamespace(srv_cargo_count=3)
    core = _Core(tmp_path, state, {"cargo": _CargoLike(state)})
    core.sections["Overlay"] = {"Enabled": False}
    plugin = mod.OverlayPlugin()
    plugin.on_load(core)
    assert started, "the tick must run so a later Apply & Save is noticed"

    _tick(plugin)
    core.save("Overlay", Enabled=True)
    _tick(plugin)
    assert "3/72" in _on_screen(_FakeClient.instances)[-1].last_text()


def test_unplacing_everything_clears_the_last_frame(overlay):
    _mod, plugin, core, state = overlay
    _tick(plugin)
    _tick(plugin)
    core.sections["OverlayPanels"] = {"Panels": {}}
    core.save("OverlayPanels")
    _tick(plugin)
    client = _FakeClient.instances[0]
    assert client.frames[-1][1] == [], "a frame left up is a frame going stale"


# ── a renderer that goes away ─────────────────────────────────────────────────

def test_a_dead_renderer_is_reported_once_and_restarted(overlay, monkeypatch):
    mod, plugin, core, state = overlay
    logged: list[str] = []
    monkeypatch.setattr(plugin, "_log", logged.append)
    clock = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: clock[0])

    _tick(plugin)
    client = _FakeClient.instances[0]
    client.alive = False                       # renderer killed

    for _ in range(4):
        _tick(plugin)
    reports = [m for m in logged if "not reaching the renderer" in m]
    assert len(reports) == 1, "a dead renderer is said once, not every tick"
    assert client.starts == 1, "no respawn inside the backoff"

    clock[0] += mod._RESTART_BACKOFF_S + 1
    state.srv_cargo_count = 12
    _tick(plugin)
    assert client.starts == 2
    assert "12/72" in client.last_text()
    assert any("reaching the renderer again" in m for m in logged)

"""
components/overlay.py — The Streamer Stats Overlay.

The overlay used to live inside ``surface_mining``, which was only ever true of
the first thing it drew. It shows cargo, commander and ship identity, and
whatever else components contribute; owning it from a mining component made
every future panel a mining feature. It owns nothing but the window now —
every panel's data belongs to the component that produced it.

What this does
--------------
Once every :data:`_TICK_S` it builds one :class:`PanelContext`, asks every
registered component for the panels the commander has actually placed, lays
them out into three zones, and sends a frame. Nothing about what any panel
means is decided here.

The renderer is a child process and is not started until the first frame is
genuinely due, so a commander with the overlay switched off — or one whose
placed panels never become eligible — never pays for it.

Tab title: Overlay
"""

from __future__ import annotations

import threading
import time

from core.plugin_loader import BasePlugin
from core import overlay_panels as op
from core.overlay import CFG_DEFAULTS as WINDOW_DEFAULTS, client_from_config
from core.overlay import _ANCHORS
from core.overlay_panels import CFG_DEFAULTS as LAYOUT_DEFAULTS
from core.surface_survey import POSITIONS

#: Zones listed left to right, so the preferences page reads like the screen.
ZONE_ORDER = {"left": 0, "centre": 1, "right": 2}

#: Redraw cadence. Status.json is rewritten about twice a second, so anything
#: faster re-renders identical frames.
_TICK_S = 0.5

#: A position older than this means the game has stopped writing Status.json.
_STALE_S = 3.0

#: Shipped placement. Everything off until the commander places it — an
#: overlay that decides for you what to cover the game with is not a feature.
DEFAULT_PANELS = {
    "cargo":          {"Zone": "left",   "Mode": "off", "Order": 1},
    "commander":      {"Zone": "left",   "Mode": "off", "Order": 2},
    "ship":           {"Zone": "right",  "Mode": "off", "Order": 1},
    "survey_compass": {"Zone": "centre", "Mode": "off", "Order": 1},
}


class OverlayPlugin(BasePlugin):
    PLUGIN_NAME        = "overlay"
    PLUGIN_DISPLAY     = "Streamer Stats Overlay"
    PLUGIN_VERSION     = "1.2.0"
    PLUGIN_DESCRIPTION = ("Draws a small, context-aware stats overlay over the "
                          "game — the subset of the dashboard worth putting on "
                          "camera. Experimental.")

    SUBSCRIBED_EVENTS: list[str] = []

    def on_load(self, core) -> None:
        self._core = core
        self._client = None
        self._drawn = False
        self._started = False
        self._heights: dict[str, int] = {}
        self._stop = threading.Event()
        self._status = "off"
        self._empty_warned = False
        self._cfg_mtime: float | None = None

        self._window_cfg = dict(WINDOW_DEFAULTS)
        self._layout_cfg = dict(LAYOUT_DEFAULTS)
        self._placements: list[op.PanelPlacement] = []

        reason = self._unsupported_reason()
        if reason:
            self._status = reason
            self._log(f"not starting — {reason}")
            return

        try:
            self._reload_config()
        except Exception as exc:
            self._log(f"overlay config unreadable: {type(exc).__name__}: {exc}")
            return

        # Logged unconditionally at load, before anything can go wrong, so a
        # trace always answers "which build is this" without a repo diff. We
        # are a dozen archives deep and "did that fix get applied" has cost
        # more than one round trip.
        self._log(f"component {self.PLUGIN_VERSION}, "
                  f"{len(self._placements)} placement(s), "
                  f"{sum(1 for p in self._placements if p.mode != 'off')} active, "
                  f"client={'yes' if self._client else 'no'}")

        if self._client:
            threading.Thread(target=self._loop, daemon=True,
                             name="edld-overlay").start()

    def on_unload(self) -> None:
        self._stop.set()
        if self._client:
            self._client.stop()

    def _unsupported_reason(self) -> str:
        """Why the overlay should not run here, or empty if it should.

        Checked before any config is read, because none of these are settings
        a commander got wrong — they are sessions where an overlay cannot work
        or has nothing to sit on, and starting a renderer to draw over a
        terminal that is scrolling past is worse than not having the feature.
        """
        import os

        mode = str(getattr(self._core, "ui_mode", "") or "").lower()
        if mode == "terminal":
            return "terminal mode has no window for an overlay to sit beside"

        try:
            settings = self._core.load_setting("Settings", {"PrimaryInstance": True},
                                               warn=False)
            if not settings.get("PrimaryInstance", True):
                return ("secondary instance — the overlay belongs on the "
                        "machine the game is running on")
        except Exception:
            pass

        if os.name != "nt" and not (os.environ.get("DISPLAY")
                                    or os.environ.get("WAYLAND_DISPLAY")):
            return "no display — headless session"

        return ""

    # ── config ────────────────────────────────────────────────────────────────

    def _reload_config(self) -> None:
        core = self._core
        self._window_cfg = core.load_setting("Overlay", WINDOW_DEFAULTS, warn=False)
        layout_defaults = {**LAYOUT_DEFAULTS, "Panels": dict(DEFAULT_PANELS)}
        # include_extra: the placement keys are named after panels, which come
        # from whichever components are loaded, so they cannot be declared as
        # defaults — and load_setting() iterates defaults, so without this they
        # are read back as absent however plainly they are in config.toml.
        self._layout_cfg = core.load_setting("OverlayPanels", layout_defaults,
                                             warn=False, include_extra=True)
        self._placements = op.placements_from_config(self._layout_cfg,
                                                     log=self._log)
        self._client = client_from_config(self._window_cfg, log=self._log)
        self._status = "configured" if self._client else "off"

    def _trace(self, message: str) -> None:
        """Per-frame detail. TRACE so it is there when --trace is on and
        absent otherwise — two frames a second would drown an INFO log."""
        try:
            from core import debug as _debug
            _debug.trace(f"[overlay] {message}")
        except Exception:
            pass

    def _reload_if_changed(self) -> None:
        """Pick up Apply & Save without a restart.

        Watched by modification time rather than through a hook, because both
        front ends write the same file and neither had anything to notify a
        component with. It also means a hand-edited config.toml takes effect
        the same way.
        """
        try:
            path = self._core.cfg.config_path
            mtime = path.stat().st_mtime
        except Exception:
            return
        if self._cfg_mtime is None:
            self._cfg_mtime = mtime
            return
        if mtime <= self._cfg_mtime:
            return
        self._cfg_mtime = mtime
        try:
            self._core.cfg.refresh(terminal_print=False)
            self._reload_config()
            # Reserved heights describe the old layout; keeping them would
            # hold gaps for panels that have just been moved or switched off.
            self._heights = {}
            self._drawn = False
            self._empty_warned = False
            self._log("config changed — overlay reloaded")
        except Exception as exc:
            self._log(f"config reload failed: {type(exc).__name__}: {exc}")

    def _log(self, message: str) -> None:
        try:
            from core import debug as _debug
            _debug.info(f"[overlay] {message}")
        except Exception:
            pass

    # ── the frame ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.wait(_TICK_S):
            try:
                self._reload_if_changed()
                self.refresh()
            except Exception as exc:
                self._log(f"tick failed: {type(exc).__name__}: {exc}")

    def refresh(self) -> list[dict]:
        """Build and send one frame. Returns the elements, for tests."""
        if not self._client or not self._placements:
            return []

        pos = POSITIONS.latest()
        if pos is not None and (time.time() - pos.ts) > _STALE_S:
            pos = None
        ctx = op.context_from(pos, getattr(self._core, "state", None))

        wanted = {p.panel_id for p in self._placements if p.mode != "off"}

        # Scope is a per-panel setting, applied to the component just before it
        # is asked. Set on the component rather than passed through collect()
        # because a component that overrides overlay_panel() — cargo, the
        # survey compass — takes no scope argument and should not have to.
        for comp in self._components():
            for pid in getattr(comp, "OVERLAY_PANELS", ()) or ():
                if pid in wanted:
                    comp.OVERLAY_SCOPE = str(
                        self._layout_cfg.get(f"{op.KEY_SCOPE}{pid}", "session"))
        panels = op.collect(self._components(), ctx, wanted, log=self._log)

        from core.palette import overlay_colours
        theme = str(self._window_cfg.get("ColourTheme", "elite-orange"))
        # A theme overrides what is drawn, never what is stored — switching
        # back to Custom restores whatever the commander had set rather than
        # whatever the last theme happened to leave behind.
        colours = {**self._layout_cfg, **(overlay_colours(theme) or {})}

        per_window: dict[str, list[dict]] = {}
        heights: dict[str, int] = {}
        for win in op.WINDOWS:
            els, h = op.layout(
                self._placements, panels,
                width=int(self._window_cfg.get(
                    "Width" if win == "top" else "DockWidth",
                    720 if win == "top" else 260)),
                window=win,
                hide_mode=str(self._layout_cfg.get("HideMode", "reserve")),
                pad_x=int(self._window_cfg.get("PadX", 16)),
                pad_y=int(self._window_cfg.get("PadY", 8)),
                reserve_heights=self._heights,
                colours=colours,
            )
            per_window[win] = els
            heights.update(h)
        self._heights = heights
        elements = [e for els in per_window.values() for e in els]

        if not elements:
            if not self._empty_warned:
                self._empty_warned = True
                asked = sorted(wanted)
                gave = sorted(k for k, v in panels.items() if v is not None)
                self._log(f"frame is empty — asked {len(asked)} panel(s) "
                          f"({', '.join(asked) or 'none'}), "
                          f"{len(gave)} returned content "
                          f"({', '.join(gave) or 'none'}). Panels on 'auto' "
                          f"decide for themselves; try one on 'on'.")
            if self._drawn and self._client.running:
                for win in op.WINDOWS:
                    self._client.clear(win)
                self._drawn = False
            return []

        if not self._started:
            self._started = True
            caps = self._client.start()
            self._status = caps.summary()
            if not caps.usable:
                # Reported once by start(). Retrying a renderer that cannot
                # work on this platform twice a second would fill the log with
                # one line.
                self._client = None
                return []

        # One frame per window. A window sent an empty list hides itself, so a
        # commander who docks nothing never sees the dock windows at all.
        sent = all(self._client.send(els, win) for win, els in per_window.items())
        self._trace("frame: " + ", ".join(
            f"{w}={len(e)}" for w, e in per_window.items()) + f", sent={sent}")
        if sent:
            if not self._drawn:
                # Once, on the first frame that actually goes out. The doctor
                # can report config and placement but runs before the
                # components load, so it cannot say whether a frame would have
                # content — and "placement looks sound" plus "renderer ready"
                # still left no way to tell a frame with three panels in it
                # from a frame with none.
                contributed = sorted({e["id"].split(".")[0] for e in elements})
                self._log(f"first frame sent — {len(elements)} element(s) from "
                          f"{len(contributed)} panel(s): {', '.join(contributed)}")
            self._drawn = True
        return elements

    def _components(self) -> list:
        return list(getattr(self._core, "_plugins", {}).values())

    # ── preferences ───────────────────────────────────────────────────────────

    def preferences_bindings(self) -> dict:
        return {
            "ov-enabled":  ("Overlay", "Enabled",     bool),
            "ov-anchor":   ("Overlay", "Anchor",      str),
            "ov-monitor":  ("Overlay", "Monitor",     int),
            "ov-width":    ("Overlay", "Width",       int),
            "ov-opacity":  ("Overlay", "Opacity",     float),
            "ov-scale":    ("Overlay", "Scale",       float),
            "ov-hidemode":   ("OverlayPanels", "HideMode",    str),
            "ov-font":       ("Overlay",       "FontFamily",  str),
            "ov-theme":      ("Overlay",       "ColourTheme", str),
            "ov-shadowoff":  ("Overlay",       "ShadowOffset",   int),
            "ov-shadowstr":  ("Overlay",       "ShadowStrength", float),
            "ov-marginx":    ("Overlay",       "MarginX",     int),
            "ov-marginy":    ("Overlay",       "MarginY",     int),
            "ov-padx":       ("Overlay",       "PadX",        int),
            "ov-pady":       ("Overlay",       "PadY",        int),
            "ov-dockw":      ("Overlay",       "DockWidth",   int),
            "ov-docktop":    ("Overlay",       "DockTop",     int),
            "ov-titlesize":  ("OverlayPanels", "TitleSize",   int),
            "ov-bodysize":   ("OverlayPanels", "BodySize",    int),
            "ov-titlecol":   ("OverlayPanels", "TitleColour", str),
            "ov-labelcol":   ("OverlayPanels", "LabelColour", str),
            "ov-valuecol":   ("OverlayPanels", "ValueColour", str),
            **{f"ovp-{pid}-{part}": ("OverlayPanels",
                                     op.placement_keys(pid)[part],
                                     int if part == "order" else str)
               for pid, _z, _m, _o, _s, _c in self._panel_rows()
               for part in ("zone", "mode", "order")},
            **{f"ovp-{pid}-scope": ("OverlayPanels",
                                    op.placement_keys(pid)["scope"], str)
               for pid, _z, _m, _o, _s, scoped in self._panel_rows() if scoped},
        }

    def _panel_rows(self) -> list[tuple[str, str, str, int, str, bool]]:
        """(panel_id, zone, mode) for every panel any component can produce.

        Read from the components rather than from config, so a panel added by a
        component appears here without anything being registered twice.
        """
        placed = {p.panel_id: p for p in self._placements}
        out = []
        for comp in self._components():
            for pid in getattr(comp, "OVERLAY_PANELS", ()) or ():
                p = placed.get(pid)
                scoped = bool(getattr(comp, "overlay_has_career", None)
                              and comp.overlay_has_career(self._core))
                out.append((pid,
                            p.zone if p else "left",
                            p.mode if p else "off",
                            p.order if p else 100,
                            str(self._layout_cfg.get(
                                f"{op.KEY_SCOPE}{pid}", "session")),
                            scoped))
        # Alphabetical. Grouping by zone made the page read like the screen,
        # but it also meant a row moved the moment its zone changed — so the
        # setting you had just edited jumped somewhere else in the list.
        return sorted(set(out), key=lambda r: r[0])

    def _status_line(self) -> str:
        if not self._window_cfg.get("Enabled"):
            return "off"
        if not self._client:
            return "enabled, but the renderer could not be configured"
        if not self._started:
            return "enabled — starts when a placed panel first applies"
        return self._client.status()

    def gui_preferences_tab(self):
        # Discovery takes no arguments; only the builder receives the dialog.
        def _build(dlg):
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import (QLabel, QVBoxLayout, QFormLayout,
                                           QWidget, QGridLayout, QScrollArea)

            # One scroll area around the entire page, not an inner one around
            # the panel grid. An inner scroll took stretch inside a fixed-height
            # tab, so every form row above it was squeezed below its own minimum
            # and the sections drew on top of each other. The page is simply
            # taller than the tab now — twenty-odd settings will not fit
            # whatever the arrangement — so the tab scrolls and nothing is
            # compressed to make room.
            page = QScrollArea()
            page.setWidgetResizable(True)
            page.setFrameShape(QScrollArea.NoFrame)
            page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            content = QWidget()
            page.setWidget(content)
            lay = QVBoxLayout(content)
            lay.setContentsMargins(10, 10, 10, 10)
            lay.setSpacing(6)

            def section(title: str) -> QFormLayout:
                lbl = QLabel(title)
                lbl.setProperty("role", "section")
                lay.addWidget(lbl)
                form = QFormLayout()
                lay.addLayout(form)
                return form

            # core.load_setting(), not dlg._cfg.load_setting() — the two take
            # different keyword names and the TypeError is swallowed by the
            # tab loop, which is how a page silently fails to exist.
            wcfg = self._core.load_setting("Overlay", WINDOW_DEFAULTS, warn=False)

            win = section("STREAMER STATS OVERLAY  \u2014  EXPERIMENTAL")
            win.addRow("Status", QLabel(self._status_line()))
            win.addRow("Show overlay",
                       dlg._bool_combo(bool(wcfg.get("Enabled")),
                                       "Overlay", "Enabled"))
            win.addRow("Anchor", dlg._text_edit(wcfg.get("Anchor", "top-centre"),
                                                "Overlay", "Anchor"))
            win.addRow("Monitor", dlg._text_edit(wcfg.get("Monitor", 0),
                                                 "Overlay", "Monitor", typ=int))
            win.addRow("Width", dlg._text_edit(wcfg.get("Width", 720),
                                               "Overlay", "Width", typ=int))
            win.addRow("Opacity", dlg._text_edit(wcfg.get("Opacity", 0.85),
                                                 "Overlay", "Opacity", typ=float))
            win.addRow("Scale", dlg._text_edit(wcfg.get("Scale", 1.0),
                                               "Overlay", "Scale", typ=float))
            win.addRow("Margin from screen X",
                       dlg._text_edit(wcfg.get("MarginX", wcfg.get("OffsetX", 0)),
                                      "Overlay", "MarginX", typ=int))
            win.addRow("Margin from screen Y",
                       dlg._text_edit(wcfg.get("MarginY", wcfg.get("OffsetY", 40)),
                                      "Overlay", "MarginY", typ=int))
            win.addRow("Padding inside X", dlg._text_edit(wcfg.get("PadX", 16),
                                                          "Overlay", "PadX", typ=int))
            win.addRow("Padding inside Y", dlg._text_edit(wcfg.get("PadY", 8),
                                                          "Overlay", "PadY", typ=int))
            win.addRow("Dock width", dlg._text_edit(wcfg.get("DockWidth", 260),
                                                    "Overlay", "DockWidth", typ=int))
            win.addRow("Dock top", dlg._text_edit(wcfg.get("DockTop", 140),
                                                  "Overlay", "DockTop", typ=int))

            from core.palette import OVERLAY_THEME_CHOICES

            typo = section("TYPE")
            typo.addRow("Colour theme",
                        dlg._choice_combo(wcfg.get("ColourTheme", "elite-orange"),
                                          "Overlay", "ColourTheme",
                                          [v for _n, v in OVERLAY_THEME_CHOICES]))
            typo.addRow("Shadow offset (px)",
                        dlg._text_edit(wcfg.get("ShadowOffset", 1), "Overlay",
                                       "ShadowOffset", typ=int))
            typo.addRow("Shadow strength",
                        dlg._text_edit(wcfg.get("ShadowStrength", 0.85),
                                       "Overlay", "ShadowStrength", typ=float))
            typo.addRow("Font family",
                        dlg._text_edit(wcfg.get("FontFamily", ""), "Overlay",
                                       "FontFamily",
                                       placeholder=(", ".join(self._client.fonts)
                                                    if self._client and self._client.fonts
                                                    else "blank for the default")))
            for label, key, default in (("Title size", "TitleSize", 12),
                                        ("Body size", "BodySize", 13)):
                typo.addRow(label,
                            dlg._text_edit(self._layout_cfg.get(key, default),
                                           "OverlayPanels", key, typ=int))
            for label, key, default in (("Title colour", "TitleColour", "#7aa2d2"),
                                        ("Label colour", "LabelColour", "#9aa4b2"),
                                        ("Value colour", "ValueColour", "#cfd6e4")):
                typo.addRow(label,
                            dlg._text_edit(self._layout_cfg.get(key, default),
                                           "OverlayPanels", key))

            panels = section("PANELS")
            panels.addRow("When a panel is hidden",
                          dlg._choice_combo(self._layout_cfg.get("HideMode", "reserve"),
                                            "OverlayPanels", "HideMode",
                                            op.HIDE_MODES))

            # One row per panel, three pickers side by side, inside a scroll
            # area.  Three separate form rows each was 36 rows on a page that
            # does not scroll, which overlapped into unreadable text once more
            # than a couple of components contributed panels.
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 4, 0, 0)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(4)
            for col, heading in enumerate(("Panel", "Position", "Zone", "Mode",
                                           "Shows")):
                head = QLabel(heading)
                head.setProperty("role", "dim")
                grid.addWidget(head, 0, col)
            for r, (pid, zone, mode, order, scope, scoped) in enumerate(
                    self._panel_rows(), 1):
                grid.addWidget(QLabel(pid), r, 0)
                grid.addWidget(dlg._choice_combo(str(min(max(order, 1), 9)),
                                                 "OverlayPanels",
                                                 op.placement_keys(pid)["order"],
                                                 op.POSITIONS), r, 1)
                grid.addWidget(dlg._choice_combo(zone, "OverlayPanels",
                                                 op.placement_keys(pid)["zone"],
                                                 op.ZONES), r, 2)
                grid.addWidget(dlg._choice_combo(mode, "OverlayPanels",
                                                 op.placement_keys(pid)["mode"],
                                                 op.MODES), r, 3)
                # Left blank where the activity has no career figures: a
                # dropdown choosing between career and session on something
                # that only has one of them is a control that does nothing.
                if scoped:
                    grid.addWidget(dlg._choice_combo(
                        scope, "OverlayPanels",
                        op.placement_keys(pid)["scope"], op.SCOPES), r, 4)
            grid.setColumnStretch(0, 1)

            lay.addWidget(grid_host)

            note = QLabel(
                "Zones: left / centre / right are the three columns of the top "
                "bar; dock-left and dock-right are windows against the side "
                "edges, each a single stacked column. Modes: on, off, auto — auto lets "
                "the panel's own component decide when it applies. Hidden "
                "panels either collapse (denser, panels below move) or reserve "
                "(steadier, leaves gaps).\n\n"
                "Margin is the gap between the monitor edge and the overlay "
                "window; padding is the gap inside it, between the window edge "
                "and the text. Dock top is the same margin for the side "
                "windows.\n\n"
                "Windows and X11 only. No overlay draws over exclusive "
                "fullscreen \u2014 run the game borderless windowed.")
            note.setWordWrap(True)
            note.setProperty("role", "dim")
            lay.addWidget(note)
            lay.addStretch(1)
            return page

        return ("pref-tab-overlay", "Overlay", _build)

    def tui_preferences_tab(self):
        def _compose():
            from textual.widgets import Label, Select, Input
            from textual.containers import Horizontal

            bools = [("Off", "false"), ("On", "true")]
            wcfg = self._core.load_setting("Overlay", WINDOW_DEFAULTS, warn=False)

            def row(label: str, widget):
                with Horizontal(classes="pref-row"):
                    yield Label(label, classes="key")
                    yield widget

            yield Label("STREAMER STATS OVERLAY  \u2014  EXPERIMENTAL",
                        classes="pref-section")
            with Horizontal(classes="pref-row"):
                yield Label("Status", classes="key")
                yield Label(self._status_line())
            yield from row("Show overlay",
                           Select(bools,
                                  value="true" if wcfg.get("Enabled") else "false",
                                  id="ov-enabled", classes="pref-bool-sel",
                                  allow_blank=False))
            yield from row("Anchor",
                           Select([(a.replace("-", " ").title(), a) for a in _ANCHORS],
                                  value=str(wcfg.get("Anchor", "top-centre")),
                                  id="ov-anchor", classes="pref-choice-lg",
                                  allow_blank=False))
            yield from row("Monitor", Input(value=str(wcfg.get("Monitor", 0)),
                                            id="ov-monitor", classes="pref-input"))
            yield from row("Width", Input(value=str(wcfg.get("Width", 720)),
                                          id="ov-width", classes="pref-input"))
            yield from row("Opacity", Input(value=str(wcfg.get("Opacity", 0.85)),
                                            id="ov-opacity", classes="pref-input"))
            yield from row("Scale", Input(value=str(wcfg.get("Scale", 1.0)),
                                          id="ov-scale", classes="pref-input"))

            yield from row("Margin from screen X",
                           Input(value=str(wcfg.get("MarginX", wcfg.get("OffsetX", 0))),
                                 id="ov-marginx", classes="pref-input"))
            yield from row("Margin from screen Y",
                           Input(value=str(wcfg.get("MarginY", wcfg.get("OffsetY", 40))),
                                 id="ov-marginy", classes="pref-input"))
            yield from row("Padding inside X", Input(value=str(wcfg.get("PadX", 16)),
                                                     id="ov-padx", classes="pref-input"))
            yield from row("Padding inside Y", Input(value=str(wcfg.get("PadY", 8)),
                                                     id="ov-pady", classes="pref-input"))

            from core.palette import OVERLAY_THEME_CHOICES

            yield from row("Dock width", Input(value=str(wcfg.get("DockWidth", 260)),
                                               id="ov-dockw", classes="pref-input"))
            yield from row("Dock top", Input(value=str(wcfg.get("DockTop", 140)),
                                             id="ov-docktop", classes="pref-input"))

            yield Label("TYPE", classes="pref-section")
            yield from row("Colour theme",
                           Select([(n, v) for n, v in OVERLAY_THEME_CHOICES],
                                  value=str(wcfg.get("ColourTheme", "elite-orange")),
                                  id="ov-theme", classes="pref-choice-lg",
                                  allow_blank=False))
            yield from row("Shadow offset (px)",
                           Input(value=str(wcfg.get("ShadowOffset", 1)),
                                 id="ov-shadowoff", classes="pref-input"))
            yield from row("Shadow strength",
                           Input(value=str(wcfg.get("ShadowStrength", 0.85)),
                                 id="ov-shadowstr", classes="pref-input"))
            yield from row("Font family",
                           Input(value=str(wcfg.get("FontFamily", "")),
                                 placeholder="blank for the default",
                                 id="ov-font", classes="pref-input"))
            for _lbl, _id, _key, _dflt in (
                    ("Title size", "ov-titlesize", "TitleSize", 12),
                    ("Body size", "ov-bodysize", "BodySize", 13),
                    ("Title colour", "ov-titlecol", "TitleColour", "#7aa2d2"),
                    ("Label colour", "ov-labelcol", "LabelColour", "#9aa4b2"),
                    ("Value colour", "ov-valuecol", "ValueColour", "#cfd6e4")):
                yield from row(_lbl,
                               Input(value=str(self._layout_cfg.get(_key, _dflt)),
                                     id=_id, classes="pref-input"))

            yield Label("PANELS", classes="pref-section")
            yield from row("When a panel is hidden",
                           Select([(m.title(), m) for m in op.HIDE_MODES],
                                  value=str(self._layout_cfg.get("HideMode", "reserve")),
                                  id="ov-hidemode", classes="pref-choice",
                                  allow_blank=False))
            # Pickers, not labels.  A read-only row telling the commander what
            # a setting is, in a window whose purpose is changing settings, is
            # the worst of both.
            for pid, zone, mode, order, scope, scoped in self._panel_rows():
                yield from row(f"{pid} position",
                               Select([(n, n) for n in op.POSITIONS],
                                      value=str(min(max(order, 1), 9)),
                                      id=f"ovp-{pid}-order",
                                      classes="pref-bool-sel", allow_blank=False))
                yield from row(f"{pid} zone",
                               Select([(z.title(), z) for z in op.ZONES],
                                      value=zone, id=f"ovp-{pid}-zone",
                                      classes="pref-choice", allow_blank=False))
                yield from row(f"{pid} mode",
                               Select([(m.title(), m) for m in op.MODES],
                                      value=mode, id=f"ovp-{pid}-mode",
                                      classes="pref-choice", allow_blank=False))
                if scoped:
                    yield from row(f"{pid} shows",
                                   Select(list(op.SCOPE_CHOICES), value=scope,
                                          id=f"ovp-{pid}-scope",
                                          classes="pref-choice-lg",
                                          allow_blank=False))

            yield Label("Zones: left/centre/right (top bar), dock-left, "
                        "dock-right (side windows). Modes: on, off, auto. "
                        "Hidden panels collapse (denser) or reserve (steadier). "
                        "Windows and X11 only; nothing draws over exclusive "
                        "fullscreen.", classes="pref-note")

        return ("pref-tab-overlay", "Overlay", _compose)

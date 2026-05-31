"""
gui/app.py — GTK4 dashboard window for ED Linux Dash.

Canvas sizing: connects to notify::width and notify::height on the canvas so
we always know the true available pixel dimensions after each layout pass.

Reflow: layout is treated as immutable during normal runtime — blocks are only
repositioned on startup or when the user explicitly resets the layout.  A
debounced resize handler coalesces burst signals into a single reflow call.
The _reflow_tick fallback timer fires only until the canvas settles, then
disarms itself permanently to avoid recurring GTK scene-graph invalidation.
"""

import os
import signal
from pathlib import Path

# GTK4 defaults to an OpenGL-backed scene graph renderer (GL/Vulkan).
# On many Linux setups (compositors with no GPU, Xvfb, VMs, or drivers that
# expose GL but fail at context creation) this produces:
#   gdk_gl_context_make_current() failed
# Forcing the Cairo renderer avoids the GPU path entirely with no visual
# difference for a text-and-grid dashboard.  Must be set before gi import.
os.environ.setdefault("GSK_RENDERER", "cairo")

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib, Gdk
except ImportError:
    raise ImportError(
        "PyGObject not found.\n"
        "  Arch/Manjaro:  pacman -S python-gobject gtk4\n"
        "  pip:           pip install PyGObject"
    )

from gui.helpers  import apply_theme, bootstrap_fonts, make_label
from gui.grid     import BlockGrid
from gui.menu     import EdmdMenuBar
from gui.blocks   import (
    CommanderBlock,
    CrewSlfBlock,
    MissionsBlock,
    AlertsBlock,
    CargoBlock,
    EngineeringBlock,
    AssetsBlock,
    ColonisationBlock,
    CareerBlock,
    NavigationBlock,
    ExplorationBlock,
    ExobiologyBlock,
)

GLib.set_prgname("edld")
GLib.set_application_name("EDLD")

# Built-in block registry — (name, BlockWidget subclass, display title)
# The former "Session Stats" block has been consolidated into "Career":
# its Summary tab (with reset button) is now the Career block's first
# tab, and Career's activity tabs show lifetime data.  Navigation
# (FSD / Neutron / Carrier) fills the col-0 slot that used to hold it.
_BUILTIN_REGISTRY = [
    ("commander",     CommanderBlock,     "Commander"),
    ("crew_slf",      CrewSlfBlock,       "Crew / SLF"),
    ("missions",      MissionsBlock,      "Massacre Mission Stack"),
    ("alerts",        AlertsBlock,        "Alerts"),
    ("cargo",         CargoBlock,         "Cargo"),
    ("engineering",   EngineeringBlock,   "Engineering"),
    ("assets",        AssetsBlock,        "Assets"),
    ("colonisation",  ColonisationBlock,  "Colonisation"),
    ("career",        CareerBlock,        "Career"),
    ("navigation",    NavigationBlock,    "Navigation"),
    ("exploration",   ExplorationBlock,   "Exploration"),
    ("exobiology",    ExobiologyBlock,    "Exobiology"),
]


def _build_registry(core) -> list[tuple[str, type, str]]:
    """Build the full block registry: builtins + any plugin blocks.

    Plugin blocks are registered by setting BLOCK_WIDGET_CLASS on a BasePlugin
    subclass.  The plugin's BLOCK_WIDGET_CLASS must be a BlockWidget subclass;
    it receives the core reference via its __init__ just like other components.
    Plugin names must not clash with builtin names — duplicates are skipped
    with a warning so a rogue plugin cannot hijack a builtin block.
    """
    registry = list(_BUILTIN_REGISTRY)
    builtin_names = {name for name, _, _ in _BUILTIN_REGISTRY}

    plugins = getattr(core, "_plugins", {})
    for plugin_name, plugin in plugins.items():
        cls = getattr(plugin, "BLOCK_WIDGET_CLASS", None)
        if cls is None:
            continue
        if plugin_name in builtin_names:
            from core.emit import Terminal
            print(
                f"{Terminal.WARN}Warning:{Terminal.END} Plugin {plugin_name!r} "
                f"tried to register a block with a builtin name — skipped."
            )
            continue
        display = getattr(plugin, "PLUGIN_DISPLAY", plugin_name)
        registry.append((plugin_name, cls, display))

    return registry


class EdmdWindow(Gtk.ApplicationWindow):

    POLL_MS   = 100
    TICK_MS   = 5000   # Heartbeat: safety net for blocks with no event-driven refresh.
                       # Most blocks update via _poll_queue on data events; this fires
                       # at most once every 5 seconds to catch anything that slipped through.
    REFLOW_MS = 500    # Canvas size fallback poll — fires only until the canvas settles
                       # after startup, then disarms.  Handles tiling WMs and the case
                       # where notify::width fires before the scroll widget has realised.

    def __init__(self, app, core, program: str, version: str):
        super().__init__(application=app, title=f"{program} v{version}")
        self._core    = core
        self._program = program
        self._version = version

        self.set_default_size(1280, 760)
        self.add_css_class("edld-window")

        # Build registry now — plugins are already loaded by this point
        self._registry      = _build_registry(core)
        self._grid          = BlockGrid(canvas_width=1280, canvas_height=760)
        self._blocks: dict  = {}
        self._is_fullscreen = False
        self._last_canvas_w  = 0
        self._last_canvas_h  = 0
        self._reflow_armed   = True   # True until canvas settles; _reflow_tick disarms itself.
        self._reflow_pending = False  # True while a debounced reflow is queued.

        # Dirty-tracking: only refresh blocks that have received a data change.
        # The tick is a heartbeat safety net — not the primary refresh driver.
        self._dirty: set[str] = set()

        self._build_ui()
        self._build_and_place_blocks()
        self._refresh_all()

        GLib.timeout_add(self.POLL_MS,   self._poll_queue)
        GLib.timeout_add(self.TICK_MS,   self._tick)
        GLib.timeout_add(self.REFLOW_MS, self._reflow_tick)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("root-box")
        self.set_child(root)

        # ── Combined HeaderBar: menus left | title centre | controls right ────
        hb = Gtk.HeaderBar()
        # Hide Adwaita CSD buttons — we supply our own fully-styled controls.
        hb.set_show_title_buttons(False)
        hb.add_css_class("edld-header")
        self.set_titlebar(hb)
        self._headerbar = hb

        # Centred title
        self._title_lbl = make_label(
            f"{self._program}  v{self._version}",
            css_class="header-title"
        )
        self._title_lbl.set_halign(Gtk.Align.CENTER)
        hb.set_title_widget(self._title_lbl)

        # ── Custom window controls (right side, left-to-right: fs | min | max | close)
        def _wctl(icon, tooltip, handler, css="wctl-btn"):
            b = Gtk.Button()
            b.set_icon_name(icon)
            b.set_tooltip_text(tooltip)
            b.connect("clicked", handler)
            b.add_css_class(css)
            return b

        self._fs_button = _wctl(
            "view-fullscreen-symbolic", "Toggle fullscreen (F11)",
            lambda *_: self.toggle_fullscreen()
        )
        self._min_button = _wctl(
            "window-minimize-symbolic", "Minimise",
            lambda *_: self.minimize()
        )
        self._max_button = _wctl(
            "window-maximize-symbolic", "Maximise",
            lambda *_: self._toggle_maximise()
        )
        self._close_button = _wctl(
            "window-close-symbolic", "Close  (Alt+F4)",
            lambda *_: self.close(),
            css="wctl-btn wctl-close"
        )

        # Pack right-to-left (pack_end reverses order)
        for btn in (self._close_button, self._max_button,
                    self._min_button, self._fs_button):
            hb.pack_end(btn)

        # Keep max button icon in sync with window state
        self.connect("notify::maximized", self._on_maximized_changed)

        # Menu buttons packed into left side of HeaderBar
        block_names = [name for name, _, _ in self._registry]
        self._menubar = EdmdMenuBar(self, block_names)
        for btn in self._menubar.buttons():
            hb.pack_start(btn)

        # ── Canvas ────────────────────────────────────────────────────────────
        self._canvas = Gtk.Fixed()
        self._canvas.add_css_class("dashboard-canvas")
        self._canvas.set_hexpand(True)
        self._canvas.set_vexpand(True)

        self._canvas.connect("realize",        self._on_canvas_realize)
        self._canvas.connect("notify::width",  self._on_canvas_size_changed)
        self._canvas.connect("notify::height", self._on_canvas_size_changed)

        # Wrap in a ScrolledWindow so that when vertical space is very limited
        # (e.g. a narrow i3 horizontal split) the dashboard scrolls rather than
        # compressing blocks to an unreadable size.
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_hexpand(True)
        self._scroll.set_vexpand(True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.add_css_class("dashboard-scroll")
        self._scroll.set_child(self._canvas)
        root.append(self._scroll)

        # Also connect the scroll viewport so resize events propagate
        # correctly when Gtk.Fixed is inside ScrolledWindow.
        self._scroll.connect("notify::width",  self._on_canvas_size_changed)
        self._scroll.connect("notify::height", self._on_canvas_size_changed)

        # Key handler for F11 fullscreen
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        # Pre-teardown cleanup — zero any progress bars before GTK destroys widgets
        self.connect("close-request", self._on_close_request)

    # ── Canvas resize → reflow ────────────────────────────────────────────────

    def _on_canvas_realize(self, canvas) -> None:
        # Trigger one poll after realize so we get real dims on first map.
        GLib.timeout_add(50, self._poll_canvas_size)

    def _on_canvas_size_changed(self, canvas, _param) -> None:
        """notify::width or notify::height — fires when the viewport changes."""
        w = self._scroll.get_width()
        h = self._scroll.get_height()
        if w != self._last_canvas_w or h != self._last_canvas_h:
            self._apply_canvas_size(w, h)

    def _read_canvas_size(self) -> tuple[int, int]:
        """Read the best available canvas dimensions.

        On Windows, ScrolledWindow.get_width() may return a stale or zero value
        during a maximize/fullscreen transition.  Fall back to the window's own
        allocated width as a reliable alternative.
        """
        w = self._scroll.get_width()
        h = self._scroll.get_height()
        if w < 100:
            # Scroll not yet realised or returning stale value — use window dims
            w = self.get_width()
            h = self.get_height()
            # Subtract estimated chrome heights (menu bar ~34px, title bar 0 on Adwaita)
            if hasattr(self, "_menu") and self._menu.get_visible():
                h = max(h - 34, 50)
        return w, h

    def _reflow_tick(self) -> bool:
        """Startup fallback — fires every REFLOW_MS until the canvas has a real size,
        then disarms permanently.  Handles tiling WMs and the startup race where
        notify::width fires before the scroll widget has realised (get_width()
        returns 0 and the later real-size signal never re-fires).
        Once _last_canvas_w > 0 the notify signals take over; this never fires again.
        """
        if not self._reflow_armed:
            return False  # disarmed — stop the repeating timer
        w, h = self._read_canvas_size()
        if w > 0 and h > 0:
            self._apply_canvas_size(w, h)
            if self._last_canvas_w > 0:
                self._reflow_armed = False   # canvas has settled — disarm
                return False
        return True  # still waiting for a valid size

    def _poll_canvas_size(self) -> bool:
        """One-shot after realize settle."""
        w, h = self._read_canvas_size()
        self._apply_canvas_size(w, h)
        return False

    def _apply_canvas_size(self, w: int, h: int) -> None:
        """Apply both dimensions — only reflows if something actually changed.

        Debounced: rapid resize signals (e.g. from dragging a window edge) are
        coalesced into a single reflow 150ms after the last event, preventing
        GTK from invalidating the scene graph on every intermediate pixel.
        """
        if w < 100 or h < 50:
            return
        if w == self._last_canvas_w and h == self._last_canvas_h:
            return
        self._last_canvas_w = w
        self._last_canvas_h = h
        self._grid.update_canvas_width(w)
        self._grid.update_canvas_height(h)
        if not self._reflow_pending:
            self._reflow_pending = True
            GLib.timeout_add(150, self._do_reflow)

    def _do_reflow(self) -> bool:
        """Deferred reflow — called once 150ms after the last resize event."""
        self._reflow_pending = False
        self._replace_all_blocks()
        return False  # one-shot

    # ── Block construction & placement ────────────────────────────────────────

    def _build_and_place_blocks(self) -> None:
        # Suppress Gtk.Fixed minimum-size propagation to the WM.
        # Without this, placing blocks with set_size_request causes Fixed to
        # report a minimum window size equal to the full layout extent —
        # which gets set as WM_NORMAL_HINTS min_height, preventing tiling WMs
        # from shrinking the window below the layout height (breaking vertical reflow).
        self._canvas.set_size_request(1, 1)

        # Build and place only the windows the current assignment shows.  A
        # window disabled in Preferences > Display (or not yet part of the
        # default layout) is simply not constructed, so it can't pile up at the
        # grid's fallback origin.
        from core import layout_model
        assigned = {b for b in layout_model.load_assignment().values() if b}

        for name, cls, _display in self._registry:
            if name not in assigned:
                continue
            # Honour DEFAULT_COL/ROW/WIDTH/HEIGHT declared on the block class.
            # Only applies when there is no saved layout entry for this block.
            if hasattr(cls, "DEFAULT_COL"):
                self._grid.register_plugin_default(
                    name,
                    getattr(cls, "DEFAULT_COL",    0),
                    getattr(cls, "DEFAULT_ROW",    0),
                    getattr(cls, "DEFAULT_WIDTH",  8),
                    getattr(cls, "DEFAULT_HEIGHT", 8),
                )
            block = cls(self._core)
            widget = block.build_widget(name, self._grid, self)
            self._blocks[name] = (block, widget)

            cell = self._grid.cell_for(name)
            x, y, w, h = self._grid.pixel_rect(cell)
            self._canvas.put(widget, x, y)
            widget.set_size_request(max(44, w), max(4, h))

    def _replace_all_blocks(self) -> None:
        """Reposition and resize all blocks after canvas resize or layout reset."""
        for name, (block, widget) in self._blocks.items():
            cell = self._grid.cell_for(name)
            x, y, w, h = self._grid.pixel_rect(cell)
            self._canvas.move(widget, x, y)
            # Enforce minimum 44px width so internal widgets (e.g. ProgressBar
            # with set_size_request(40,4)) never receive a negative allocation.
            pw, ph = max(44, w), max(4, h)
            widget.set_size_request(pw, ph)
            block.on_resize(pw, ph)

        # On Windows, Gtk.Fixed constrains pointer hit-testing to its
        # set_size_request extent.  Update it to the actual scroll viewport
        # so drag events are accepted across the full enlarged canvas.
        sw = self._scroll.get_width()
        sh = self._scroll.get_height()
        if sw > 1 and sh > 1:
            self._canvas.set_size_request(sw, sh)

    # ── Block visibility ──────────────────────────────────────────────────────

    def set_block_visible(self, name: str, visible: bool) -> None:
        entry = self._blocks.get(name)
        if entry:
            _, widget = entry
            widget.set_visible(visible)

    # ── Layout reset ──────────────────────────────────────────────────────────

    def reset_layout(self) -> None:
        self._grid.reset()
        self._replace_all_blocks()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        for block, _ in self._blocks.values():
            block.refresh()

    def _refresh_block(self, name: str) -> None:
        """Refresh a block immediately. Only used by _tick heartbeat."""
        entry = self._blocks.get(name)
        if entry:
            block, _ = entry
            block.refresh()

    def _mark_dirty(self, name: str) -> None:
        """Mark a block as needing refresh. Flushed at end of each poll cycle."""
        if name in self._blocks:
            self._dirty.add(name)

    def _flush_dirty(self) -> None:
        """Refresh all dirty blocks once, then clear. Called once per poll cycle."""
        for name in self._dirty:
            self._refresh_block(name)
        self._dirty.clear()

    # ── Fullscreen ────────────────────────────────────────────────────────────

    def toggle_fullscreen(self) -> None:
        if self._is_fullscreen:
            self.unfullscreen()
            self._fs_button.set_icon_name("view-fullscreen-symbolic")
            self._fs_button.set_tooltip_text("Toggle fullscreen (F11)")
            self._is_fullscreen = False
        else:
            self.fullscreen()
            self._fs_button.set_icon_name("view-restore-symbolic")
            self._fs_button.set_tooltip_text("Exit fullscreen (F11)")
            self._is_fullscreen = True
        # Force reflow 200ms after fullscreen animation settles.
        GLib.timeout_add(200, self._poll_canvas_size)

    def _toggle_maximise(self) -> None:
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def _on_maximized_changed(self, *_) -> None:
        if self.is_maximized():
            self._max_button.set_icon_name("window-restore-symbolic")
            self._max_button.set_tooltip_text("Restore")
        else:
            self._max_button.set_icon_name("window-maximize-symbolic")
            self._max_button.set_tooltip_text("Maximise")
        # Force reflow 200ms after maximize/restore animation settles.
        GLib.timeout_add(200, self._poll_canvas_size)

    def _on_close_request(self, *_) -> bool:
        """Zero progress bars before GTK tears down the widget tree."""
        entry = self._blocks.get("commander")
        if entry:
            block, _ = entry
            if hasattr(block, "cleanup"):
                block.cleanup()
        return False   # False = allow window to close

    def _on_key_pressed(self, ctrl, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_F11:
            self.toggle_fullscreen()
            return True
        return False

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self) -> bool:
        # Drain the entire queue first, marking blocks dirty as we go.
        # This coalesces bursts of updates (e.g. Status.json firing
        # vessel_update + slf_update + plugin_refresh in one 500ms window)
        # so each affected block repaints at most once per 100ms poll cycle.
        try:
            while True:
                msg_type, payload = self._core.gui_queue.get_nowait()

                if msg_type in ("cmdr_update", "vessel_update"):
                    self._mark_dirty("commander")
                elif msg_type in ("crew_update", "slf_update"):
                    self._mark_dirty("crew_slf")
                elif msg_type == "mission_update":
                    self._mark_dirty("missions")
                elif msg_type == "stats_update":
                    # Session counter / reset events repaint the Career
                    # block, which absorbed the deprecated Session Stats
                    # block's Summary content.
                    self._mark_dirty("career")
                elif msg_type == "state_update":
                    # Generic state change — keep Career's session-scoped
                    # Summary tab, Navigation's source-system pre-fill, and
                    # the session-management surface (now in Alerts footer)
                    # live.
                    self._mark_dirty("career")
                    self._mark_dirty("navigation")
                    self._mark_dirty("alerts")
                elif msg_type == "holdings_update":
                    self._mark_dirty("assets")
                elif msg_type == "exploration_update":
                    self._mark_dirty("exploration")
                elif msg_type == "exobiology_update":
                    self._mark_dirty("exobiology")
                elif msg_type == "alerts_update":
                    self._mark_dirty("alerts")
                elif msg_type == "career_update":
                    self._mark_dirty("career")
                elif msg_type == "ksw_status":
                    # Status-flush events from the session-management plugin —
                    # refresh the Alerts block since its footer now owns the
                    # session-management UI.
                    self._mark_dirty("alerts")
                elif msg_type == "capi_updated":
                    for _n in ("assets", "commander", "cargo", "crew_slf", "navigation"):
                        self._mark_dirty(_n)
                elif msg_type == "all_update":
                    for _n in self._blocks:
                        self._mark_dirty(_n)
                elif msg_type == "update_notice":
                    self._on_update_notice(payload)
                elif msg_type == "plugin_refresh":
                    self._mark_dirty(payload)

        except Exception:
            pass

        # Flush: each dirty block renders exactly once this cycle.
        self._flush_dirty()
        return True

    def _tick(self) -> bool:
        # Heartbeat: give activity_combat a chance to check no-kill timeout.
        combat = getattr(self._core, "_plugins", {}).get("combat")
        if combat and hasattr(combat, "tick"):
            try:
                combat.tick(self._core.state)
            except Exception:
                pass
        # Mark all registered blocks dirty. The flush at the end of the next
        # _poll_queue call renders each once. Blocks already dirty from
        # a data event are not double-rendered — set.add() is idempotent.
        # At TICK_MS=5000 this fires at most once every 5 seconds, acting as
        # a safety net for blocks that have no event-driven refresh path.
        for name, _, _ in self._registry:
            self._mark_dirty(name)
        return True

    # ── Update notice ─────────────────────────────────────────────────────────

    def _on_update_notice(self, payload) -> None:
        # payload is ("release", version_str) or ("commits", count_str)
        if isinstance(payload, tuple):
            kind, value = payload
        else:
            # Legacy string format fallback
            kind, value = "release", payload

        url = "github.com/drworman/EDLD/releases/latest"
        if kind == "release":
            label = f"\u2b06 v{value} available  —  {url}"
        else:
            label = f"\u2b06 {value} new commit(s) on main  —  {url}"

        self._title_lbl.set_label(
            f"{self._program}  v{self._version}  ·  {label}"
        )
        self._title_lbl.add_css_class("update-available")


# ── Application ───────────────────────────────────────────────────────────────

class EdmdApp(Gtk.Application):

    def __init__(self, core, program: str, version: str):
        super().__init__(application_id="com.drworman.edld")
        self._core    = core
        self._program = program
        self._version = version
        self._theme       = core.cfg.ui_cfg.get("Theme",      "default")
        self._font_size   = core.cfg.ui_cfg.get("FontSize",   14)
        self._font_family = core.cfg.ui_cfg.get("FontFamily", "JetBrains Mono")

    def do_activate(self) -> None:
        # Switch GTK theme to "Default" (minimal, no Adwaita CSD graphics)
        # before loading our CSS. This removes Adwaita's baked-in button
        # gradients so our window control colours actually take effect.
        try:
            settings = Gtk.Settings.get_default()
            if settings:
                settings.set_property("gtk-theme-name", "Default")
            bootstrap_fonts()
            apply_theme(self._theme, self._font_size, self._font_family)
            win = EdmdWindow(
                app=self,
                core=self._core,
                program=self._program,
                version=self._version,
            )
            win.present()
        except Exception:
            # GLib swallows exceptions raised in do_activate, printing nothing and
            # leaving the app running with no window. Re-raise after printing so the
            # traceback is visible on stderr and the process exits cleanly.
            import traceback, sys
            traceback.print_exc()
            sys.exit(1)

        signal.signal(signal.SIGINT, lambda *_: self.quit())
        GLib.timeout_add(200, lambda: True)

"""
tui/app.py — Textual TUI application for EDLD.

Three-column layout built from the shared layout model (see
core/layout_model.py):

  Left   : Assets  |  Engineering  |  Colonisation
  Centre : Commander  |  Crew/SLF  |  Alerts  |  Cargo
  Right  : Massacre Mission Stack  |  Navigation  |  Career

Hotkeys
  ctrl+q  Quit
  ctrl+r  Reset session counters
  ctrl+l  Clear alerts
  ctrl+o  Options / theme picker
  ctrl+k  Toggle session-management overlay
"""
from __future__ import annotations
import queue
from pathlib import Path
from typing  import TYPE_CHECKING

from textual.app       import App, ComposeResult
from textual.binding   import Binding
from textual.widgets    import Header, Footer, Label
from textual.containers import Horizontal, Vertical, VerticalScroll

from tui.preferences   import PreferencesScreen
from tui.confirm_modal import ConfirmModal
from tui.blocks.career import CareerBlock
from tui.blocks.ship_info   import ShipInfoBlock
from tui.blocks.objectives  import ObjectivesBlock
from tui.blocks.status      import StatusBlock
from tui.blocks.navigation import NavigationBlock
from tui.blocks.commander     import CommanderBlock
from tui.blocks.exploration   import ExplorationBlock
from tui.theme import build_css, BLOCK_DOM_ID
from core.layout_model import load_assignment, tui_columns, COLUMNS

if TYPE_CHECKING:
    from core.core_api import CoreAPI

# ── Event → block-id dispatch table ──────────────────────────────────────────

_MSG_DISPATCH: dict[str, list[str]] = {
    "career_update":      ["block-career"],
    # Session counter / reset events repaint the Session window.
    "stats_update":       ["block-career"],
    # Generic state changes — keep Career's wealth rows and the Session
    # window live, plus Navigation's Carrier tab readout.
    "state_update":       ["block-career", "block-career", "block-nav"],
    # Colonisation now renders in the Cargo window's second tab.
    "colonisation_update":["block-objectives"],
    "crew_update":        ["block-status"],
    "slf_update":         ["block-status"],
    "vessel_update":      ["block-commander", "block-ship"],
    "ship_health_update": ["block-ship"],
    "location_update":    ["block-commander", "block-nav"],
    # Missions now render inside the Session window's Missions tab.
    "mission_update":     ["block-objectives"],
    "cargo_update":       ["block-ship"],
    # Assets folded into the Commander window's tabs.
    "assets_update":      ["block-commander"],
    "exploration_update": ["block-exploration", "block-career"],
    # Exobiology nests inside the Exploration window.
    "exobiology_update":  ["block-exploration", "block-career"],
    "materials_update":   ["block-ship"],
    "alert_update":       ["block-status"],
    "pp_update":          ["block-career", "block-career", "block-commander"],
    "cmdr_update":        ["block-commander"],
    "capi_updated":       ["block-commander", "block-status",
                           "block-ship", "block-nav"],
    # update_notice has no block target — handled directly in _poll_queue
}

_PLUGIN_TO_BLOCK: dict[str, str] = {
    "crew_slf":      "block-status",
    "alerts":        "block-status",
    "cargo":         "block-ship",
    "engineering":   "block-ship",
    "ship_health":   "block-ship",
    "assets":        "block-commander",
    "colonisation":  "block-objectives",
    "career":        "block-career",
    "navigation":    "block-nav",
    "status":       "block-status",
    "commander":     "block-commander",
    "session_stats": "block-career",
    "ship_info":     "block-ship",
}

# Window name → TUI block class.  compose() builds the dashboard from the shared
# layout model, instantiating these by name in the positions the model returns.
_BLOCK_CLASSES = {
    "commander":    CommanderBlock,
    "status":       StatusBlock,
    "navigation":   NavigationBlock,
    "career":       CareerBlock,
    "ship_info":    ShipInfoBlock,
    "objectives":   ObjectivesBlock,
    "exploration":  ExplorationBlock,
}

# Layout-model column → Textual column container id.
_COLUMN_DOM = {"A": "col-left", "B": "col-centre", "C": "col-right"}



# ── Main app ──────────────────────────────────────────────────────────────────

class EdldTui(App):
    """EDLD Textual dashboard."""

    BINDINGS = [
        Binding("ctrl+q", "quit",           "Quit"),
        Binding("ctrl+r", "reset_session",  "Reset Session"),
        Binding("ctrl+l", "clear_alerts",   "Clear Alerts"),
        Binding("ctrl+o", "options",        "Options"),
        Binding("ctrl+k", "toggle_ksw",     "Session Mgmt", show=True),
        Binding("ctrl+t", "kill_session",   "Quit Game",    show=True),
    ]

    def __init__(self, core: "CoreAPI", program: str, version: str,
                 theme: str = "default") -> None:
        super().__init__()
        self._core    = core
        self._program = program
        self._version = version
        self._theme   = theme
        self.CSS      = build_css(theme)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("", id="update-notice-bar")
        # Columns, block selection, and vertical order all come from the shared
        # layout model (the same source the Display tab
        # use), so the two UIs stay in lockstep and windows can be reassigned.
        cols = tui_columns(load_assignment())
        with Horizontal(id="dashboard"):
            for col in COLUMNS:
                with Vertical(id=_COLUMN_DOM[col]):
                    for block_name, _pct in cols[col]:
                        cls = _BLOCK_CLASSES.get(block_name)
                        if cls is not None:
                            yield cls(self._core, id=BLOCK_DOM_ID[block_name])
        yield Footer()

    def on_mount(self) -> None:
        self._base_title = f"{self._program}  v{self._version}"
        self.title = self._base_title
        self._refresh_all()
        self.set_interval(0.25, self._poll_queue)
        # Let any component self-register TUI hooks (hotkeys, etc.)
        for plugin in self._core._plugins.values():
            fn = getattr(plugin, "register_tui_app", None)
            if callable(fn):
                try:
                    fn(self)
                except Exception:
                    pass

    # ── Queue polling ─────────────────────────────────────────────────────────

    def on_key(self, event) -> None:
        """Delegate keypresses to components that registered hotkeys."""
        table = getattr(self, "_component_keys", {})
        # Normalise: Textual reports ctrl+k as "ctrl+k"
        key = event.key
        handler = table.get(key)
        if handler:
            try:
                handler()
                event.stop()
            except Exception:
                pass

    def _poll_queue(self) -> None:
        dirty: set[str] = set()
        try:
            while True:
                msg_type, payload = self._core.gui_queue.get_nowait()
                targets = _MSG_DISPATCH.get(msg_type)
                if targets is None:
                    if msg_type == "plugin_refresh" and isinstance(payload, str):
                        bid = _PLUGIN_TO_BLOCK.get(payload)
                        if bid:
                            dirty.add(bid)
                        else:
                            dirty.update(self._all_block_ids())
                    elif msg_type == "update_notice":
                        self._on_update_notice(payload)
                    elif msg_type == "ksw_status":
                        self._on_ksw_status(payload)
                    else:
                        dirty.update(self._all_block_ids())
                else:
                    dirty.update(targets)
        except queue.Empty:
            pass
        for bid in dirty:
            self._refresh_block(bid)

    def _on_update_notice(self, payload) -> None:
        """Show a version-available notice in the bar below the header."""
        if isinstance(payload, tuple):
            kind, value = payload
        else:
            kind, value = "release", payload
        url = "github.com/drworman/EDLD/releases/latest"
        if kind == "release":
            msg = f"⬆ v{value} available — {url}"
        else:
            msg = f"⬆ {value} new commit(s) on main — {url}"
        try:
            bar = self.query_one("#update-notice-bar", Label)
            bar.update(f"[bold yellow]{msg}[/bold yellow]")
            bar.styles.height = 1   # make visible — Textual doesn't support :not(:empty)
        except Exception:
            pass

    def _on_ksw_status(self, symbol: str) -> None:
        """Embed the session status indicator in the header title string."""
        try:
            base = getattr(self, "_base_title", self.title)
            self.title = f"{base}  {symbol}"
        except Exception:
            pass

    def _refresh_block(self, block_id: str) -> None:
        try:
            block = self.query_one(f"#{block_id}")
            if hasattr(block, "refresh_data"):
                block.refresh_data()
        except Exception:
            pass

    def _refresh_all(self) -> None:
        for bid in self._all_block_ids():
            self._refresh_block(bid)

    def _all_block_ids(self) -> list[str]:
        """Every window's DOM id, derived rather than listed by hand.

        The hand-written list had drifted again: it named block-ship-health,
        which no longer exists, and repeated two ids.  Deriving it from
        BLOCK_DOM_ID means adding or renaming a window cannot leave a window
        that never refreshes.
        """
        return list(BLOCK_DOM_ID.values())

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_quit(self) -> None:
        self.exit()

    def action_reset_session(self) -> None:
        self._core.plugin_call("session_stats", "on_new_session", 0)
        self._refresh_block("block-career")

    def action_clear_alerts(self) -> None:
        self._core.plugin_call("alerts", "clear_alerts")

    def action_toggle_ksw(self) -> None:
        """Toggles session management if the component is loaded."""
        plugin = self._core._plugins.get("ksw")
        if plugin:
            fn = getattr(plugin, "_tui_toggle", None)
            if callable(fn):
                fn(self)

    def action_kill_session(self) -> None:
        """Manually terminate the game session (Solo only), behind a confirm prompt."""
        if self._core._plugins.get("ksw") is None:
            return

        def _on_confirm(ok: bool | None) -> None:
            if ok:
                self._core.plugin_call("ksw", "flush_session", "Manual activation (TUI)")

        self.push_screen(
            ConfirmModal(
                "Terminate game session?",
                "Quits Elite Dangerous now. Solo mode only — ignored in Open / Private Group.",
            ),
            _on_confirm,
        )

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Disable the session-management bindings when the plugin is not loaded."""
        if action in ("toggle_ksw", "kill_session"):
            return self._core._plugins.get("ksw") is not None
        return True

    def action_options(self) -> None:
        self.push_screen(PreferencesScreen(self._core))


def run_tui(core: "CoreAPI", program: str, version: str, theme: str = "default") -> None:
    """Entry point: build and run the Textual app synchronously."""
    app = EdldTui(core, program, version, theme=theme)
    app.run()

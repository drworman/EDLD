"""
gui/app.py — PySide6 desktop application for EDLD.

Three-column layout built from the shared layout model (see
core/layout_model.py), so the desktop window and the terminal dashboard show
the same windows in the same positions and the Display preferences tab drives
both:

  Left   : Career  |  Cargo  |  Massacre Mission Stack
  Centre : Commander  |  Crew/SLF  |  Alerts  |  Exploration
  Right  : Navigation  |  Colonisation  |  Exobiology

(the defaults — any of it reassignable from Preferences → Display.)

The event dispatch table is a copy of the TUI's, keyed by the same message
names the components put on ``core.gui_queue``.  A component that emits a new
message type refreshes the same windows in both front ends.

Hotkeys match the TUI where the platform allows it:

  Ctrl+Q  Quit           Ctrl+R  Reset session counters
  Ctrl+L  Clear alerts    Ctrl+O  Preferences
  Ctrl+K  Session-management overlay
  Ctrl+T  Quit game session
  F11     Full screen

Window controls are the operating system's own: the window is a plain
QMainWindow with no frameless trickery, so minimise, maximise, restore, snap,
tiling and the platform close button all behave exactly as the user's desktop
expects on Linux, Windows and macOS.
"""

from __future__ import annotations

import queue
import sys
import webbrowser
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.layout_model import COLUMNS, load_assignment, tui_columns
from core.palette import rgb
from gui.about import AboutDialog
from gui.funding import SupportBar
from gui.preferences import PreferencesDialog
from gui.theme import stylesheet

from gui.blocks.alerts       import AlertsBlock
from gui.blocks.assets       import AssetsBlock
from gui.blocks.career       import CareerBlock
from gui.blocks.cargo        import CargoBlock
from gui.blocks.colonisation import ColonisationBlock
from gui.blocks.commander    import CommanderBlock
from gui.blocks.crew_slf     import CrewSlfBlock
from gui.blocks.engineering  import EngineeringBlock
from gui.blocks.exobiology   import ExobiologyBlock
from gui.blocks.exploration  import ExplorationBlock
from gui.blocks.missions     import MissionsBlock
from gui.blocks.navigation   import NavigationBlock
from gui.blocks.session      import SessionBlock
from gui.blocks.ship_health  import ShipHealthBlock

if TYPE_CHECKING:
    from core.core_api import CoreAPI

# ── Event → block-id dispatch table ──────────────────────────────────────────
# Mirrors tui/app.py._MSG_DISPATCH exactly.

_MSG_DISPATCH: dict[str, list[str]] = {
    "career_update":      ["block-career"],
    # Session counter / reset events repaint the Session window.
    "stats_update":       ["block-session"],
    # Generic state changes — keep Career's wealth rows and the Session
    # window live, plus Navigation's Carrier tab readout.
    "state_update":       ["block-career", "block-session", "block-nav"],
    "colonisation_update": ["block-colon"],
    "crew_update":        ["block-crew"],
    "slf_update":         ["block-crew"],
    "vessel_update":      ["block-commander", "block-ship-health"],
    "ship_health_update": ["block-ship-health"],
    "location_update":    ["block-commander", "block-nav"],
    "mission_update":     ["block-missions"],
    "cargo_update":       ["block-cargo"],
    "assets_update":      ["block-assets"],
    "exploration_update": ["block-exploration", "block-session"],
    "exobiology_update":  ["block-exobiology", "block-session"],
    "materials_update":   ["block-eng"],
    "alert_update":       ["block-alerts"],
    "pp_update":          ["block-career", "block-session", "block-commander"],
    "cmdr_update":        ["block-commander"],
    "capi_updated":       ["block-commander", "block-crew", "block-assets",
                           "block-cargo", "block-nav"],
    # update_notice has no block target — handled directly in _poll_queue
}

_PLUGIN_TO_BLOCK: dict[str, str] = {
    "career":        "block-career",
    "navigation":    "block-nav",
    "colonisation":  "block-colon",
    "crew_slf":      "block-crew",
    "commander":     "block-commander",
    "missions":      "block-missions",
    "cargo":         "block-cargo",
    "assets":        "block-assets",
    "engineering":   "block-eng",
    "alerts":        "block-alerts",
    "session_stats": "block-session",
    "ship_health":   "block-ship-health",
}

# Window name → GUI block class.
_BLOCK_CLASSES = {
    "assets":       AssetsBlock,
    "engineering":  EngineeringBlock,
    "colonisation": ColonisationBlock,
    "commander":    CommanderBlock,
    "crew_slf":     CrewSlfBlock,
    "alerts":       AlertsBlock,
    "cargo":        CargoBlock,
    "missions":     MissionsBlock,
    "navigation":   NavigationBlock,
    "career":       CareerBlock,
    "session":      SessionBlock,
    "ship_health":  ShipHealthBlock,
    "exploration":  ExplorationBlock,
    "exobiology":   ExobiologyBlock,
}

# Window name → block id.  Same ids the TUI uses, so the dispatch table above
# is a literal copy rather than a translation.
BLOCK_ID = {
    "assets":       "block-assets",
    "engineering":  "block-eng",
    "colonisation": "block-colon",
    "commander":    "block-commander",
    "crew_slf":     "block-crew",
    "alerts":       "block-alerts",
    "cargo":        "block-cargo",
    "missions":     "block-missions",
    "navigation":   "block-nav",
    "career":       "block-career",
    "session":      "block-session",
    "ship_health":  "block-ship-health",
    "exploration":  "block-exploration",
    "exobiology":   "block-exobiology",
}

#: Queue poll interval.  Matches the TUI's 0.25 s so both front ends impose
#: the same load on the components feeding them.
_POLL_MS = 250


class EdldWindow(QMainWindow):
    """The EDLD desktop dashboard."""

    def __init__(self, core: "CoreAPI", program: str, version: str,
                 author: str, github_repo: str,
                 theme: str = "default") -> None:
        super().__init__()
        self._core = core
        self._program = program
        self._version = version
        self._author = author
        self._github_repo = github_repo
        self._theme = theme
        self._blocks: dict[str, object] = {}

        self._base_title = f"{program}  v{version}"
        self.setWindowTitle(self._base_title)
        self.setStyleSheet(stylesheet(theme))
        self.resize(1600, 950)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Update-notice bar, hidden until something arrives for it.
        self._notice = QLabel("")
        self._notice.setObjectName("updateNotice")
        self._notice.setVisible(False)
        self._notice.setTextFormat(Qt.RichText)
        self._notice.setOpenExternalLinks(True)
        outer.addWidget(self._notice)

        outer.addWidget(self._build_dashboard(), 1)

        self._support = SupportBar(theme=theme, program=program)
        outer.addWidget(self._support)

        self.setCentralWidget(central)
        self._build_menus()
        self.statusBar().showMessage("Monitoring journal…")

        # Let any component self-register GUI hooks.
        for plugin in self._core._plugins.values():
            fn = getattr(plugin, "register_gui_app", None)
            if callable(fn):
                try:
                    fn(self)
                except Exception:
                    pass

        self._refresh_all()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_queue)
        self._timer.start(_POLL_MS)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_dashboard(self) -> QWidget:
        """Build the three columns from the shared layout model.

        Columns are QSplitters so a commander can drag a boundary to give a
        window more room — the desktop equivalent of the size classes the TUI
        derives from CLASS_WEIGHT.  Initial sizes come from the model's own
        percentages, so an unmodified window opens with the same proportions
        the terminal dashboard uses.
        """
        cols = tui_columns(load_assignment())

        outer = QSplitter(Qt.Horizontal)
        outer.setChildrenCollapsible(False)
        outer.setHandleWidth(3)

        for col in COLUMNS:
            column = QSplitter(Qt.Vertical)
            column.setChildrenCollapsible(False)
            column.setHandleWidth(3)
            sizes: list[int] = []
            for block_name, pct in cols[col]:
                cls = _BLOCK_CLASSES.get(block_name)
                if cls is None:
                    continue
                block = cls(self._core, theme=self._theme)
                self._blocks[BLOCK_ID[block_name]] = block
                column.addWidget(block)
                sizes.append(max(1, int(pct)) * 10)
            if sizes:
                column.setSizes(sizes)
            outer.addWidget(column)

        outer.setSizes([100, 100, 100])
        return outer

    # ── Menus ─────────────────────────────────────────────────────────────────

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        prefs = QAction("&Preferences…", self)
        prefs.setShortcut(QKeySequence("Ctrl+O"))
        prefs.triggered.connect(self.action_options)
        file_menu.addAction(prefs)
        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.setMenuRole(QAction.QuitRole)   # macOS puts this in the app menu
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        session_menu = bar.addMenu("&Session")
        reset = QAction("&Reset Session Counters", self)
        reset.setShortcut(QKeySequence("Ctrl+R"))
        reset.triggered.connect(self.action_reset_session)
        session_menu.addAction(reset)
        clear = QAction("Clear &Alerts", self)
        clear.setShortcut(QKeySequence("Ctrl+L"))
        clear.triggered.connect(self.action_clear_alerts)
        session_menu.addAction(clear)
        session_menu.addSeparator()
        self._ksw_toggle = QAction("Session &Management", self)
        self._ksw_toggle.setShortcut(QKeySequence("Ctrl+K"))
        self._ksw_toggle.triggered.connect(self.action_toggle_ksw)
        session_menu.addAction(self._ksw_toggle)
        self._ksw_kill = QAction("&Terminate Game Session…", self)
        self._ksw_kill.setShortcut(QKeySequence("Ctrl+T"))
        self._ksw_kill.triggered.connect(self.action_kill_session)
        session_menu.addAction(self._ksw_kill)

        # Both session-management entries are disabled when the component is
        # not loaded, matching the TUI's check_action() gate.
        has_ksw = self._core._plugins.get("ksw") is not None
        self._ksw_toggle.setEnabled(has_ksw)
        self._ksw_kill.setEnabled(has_ksw)

        view_menu = bar.addMenu("&View")
        full = QAction("&Full Screen", self)
        full.setShortcut(QKeySequence("F11"))
        full.setCheckable(True)
        full.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(full)
        support_act = QAction("Show &Support Bar", self)
        support_act.setCheckable(True)
        support_act.setChecked(True)
        support_act.triggered.connect(self._support.setVisible)
        view_menu.addAction(support_act)

        help_menu = bar.addMenu("&Help")
        repo = QAction("Project on &GitHub", self)
        repo.triggered.connect(
            lambda: webbrowser.open(f"https://github.com/{self._github_repo}"))
        help_menu.addAction(repo)
        help_menu.addSeparator()
        about = QAction("&About", self)
        about.setMenuRole(QAction.AboutRole)     # macOS puts this in the app menu
        about.triggered.connect(self.action_about)
        help_menu.addAction(about)

    def _toggle_fullscreen(self, checked: bool) -> None:
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    # ── Queue polling ─────────────────────────────────────────────────────────

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
                            dirty.update(self._blocks)
                    elif msg_type == "update_notice":
                        self._on_update_notice(payload)
                    elif msg_type == "ksw_status":
                        self._on_ksw_status(payload)
                    else:
                        dirty.update(self._blocks)
                else:
                    dirty.update(targets)
        except queue.Empty:
            pass
        for bid in dirty:
            self._refresh_block(bid)

    def _on_update_notice(self, payload) -> None:
        """Show a version-available notice in the bar below the menu."""
        if isinstance(payload, tuple):
            kind, value = payload
        else:
            kind, value = "release", payload
        url = f"https://github.com/{self._github_repo}/releases/latest"
        c = rgb(self._theme)
        if kind == "release":
            msg = f"⬆ v{value} available"
        else:
            msg = f"⬆ {value} new commit(s) on main"
        self._notice.setText(
            f'{msg} — <a href="{url}" style="color:{c["accent"]}">{url}</a>')
        self._notice.setVisible(True)

    def _on_ksw_status(self, symbol: str) -> None:
        """Embed the session status indicator in the window title."""
        self.setWindowTitle(f"{self._base_title}  {symbol}")

    def _refresh_block(self, block_id: str) -> None:
        block = self._blocks.get(block_id)
        if block is None:
            return
        try:
            block.refresh_data()
        except Exception:
            # A block that throws must not take the dashboard down with it;
            # the same guard the TUI applies around refresh_data().
            pass

    def _refresh_all(self) -> None:
        for bid in list(self._blocks):
            self._refresh_block(bid)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_reset_session(self) -> None:
        self._core.plugin_call("session_stats", "on_new_session", 0)
        self._refresh_block("block-session")

    def action_clear_alerts(self) -> None:
        self._core.plugin_call("alerts", "clear_alerts")
        self._refresh_block("block-alerts")

    def action_toggle_ksw(self) -> None:
        """Toggle session management if the component is loaded."""
        plugin = self._core._plugins.get("ksw")
        if plugin:
            fn = getattr(plugin, "_gui_toggle", None) or getattr(plugin, "_tui_toggle", None)
            if callable(fn):
                try:
                    fn(self)
                except Exception:
                    pass

    def action_kill_session(self) -> None:
        """Terminate the game session (Solo only), behind a confirm prompt."""
        if self._core._plugins.get("ksw") is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Terminate game session?")
        box.setIcon(QMessageBox.Warning)
        box.setText("Terminate game session?")
        box.setInformativeText(
            "Quits Elite Dangerous now. Solo mode only — ignored in "
            "Open / Private Group.")
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() == QMessageBox.Ok:
            self._core.plugin_call("ksw", "flush_session",
                                   "Manual activation (GUI)")

    def action_options(self) -> None:
        dlg = PreferencesDialog(self._core, theme=self._theme, parent=self)
        dlg.exec()

    def action_about(self) -> None:
        AboutDialog(self, self._program, self._version, self._author,
                    self._github_repo, theme=self._theme).exec()

    def apply_theme(self, theme: str) -> None:
        """Restyle the whole window — used for the Appearance tab's preview."""
        self._theme = theme
        self.setStyleSheet(stylesheet(theme))


def run_gui(core: "CoreAPI", program: str, version: str, author: str,
            github_repo: str, theme: str = "default") -> int:
    """Entry point: build and run the Qt application synchronously."""
    QGuiApplication.setDesktopFileName("edld")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(program)
    app.setApplicationDisplayName(program)
    app.setApplicationVersion(version)
    app.setOrganizationName(author)

    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    window = EdldWindow(core, program, version, author, github_repo,
                        theme=theme)
    if icon is not None:
        window.setWindowIcon(icon)
    window.show()
    return app.exec()


def _load_app_icon() -> QIcon | None:
    """Best-effort window icon.

    Frozen builds carry the icon next to the bundled data; a source checkout
    has it in images/.  Neither is fatal — a missing icon just leaves the
    platform default.
    """
    from pathlib import Path

    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(getattr(sys, "_MEIPASS", ".")))
    roots.append(Path(__file__).resolve().parents[1])

    for root in roots:
        for rel in ("packaging/icons/edld.png", "images/edld_avatar_512.png"):
            p = root / rel
            if p.is_file():
                return QIcon(str(p))
    return None

"""
gui/preferences.py — Preferences dialog (Qt).

The Qt counterpart of ``tui/preferences.py``, carrying the same six tabs:

  General       — journal folder, UTC, display toggles, inactivity alerts
  Notifications — per-event log levels (0–3)
  Discord       — webhook, user ID, display options
  Appearance    — theme selection
  Data          — CAPI, EDDN, EDSM, EDAstro, Inara, Raven Colonial
  Display       — window layout (position → window assignment)

Changes are collected in a pending dict and written to config.toml on Apply,
using the same ``config_to_toml`` writer and the same ``_RESTART_KEYS`` table
as the TUI, so the two screens produce byte-identical config files for the
same edits.  Settings marked ⚠ require a restart; the dialog restarts the
process via ``os.execv`` using ``core.launch_argv`` when Apply is confirmed.

Components may inject their own tab by implementing ``gui_preferences_tab()``,
mirroring the TUI's ``tui_preferences_tab()`` hook.  A component that
implements only the TUI hook simply doesn't appear here, which is the correct
behaviour for one that builds Textual widgets.
"""

from __future__ import annotations

import os
import sys
import tomllib
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import config_to_toml
from core.palette import THEME_CHOICES, list_custom_themes
from gui.theme import stylesheet

if TYPE_CHECKING:
    from core.core_api import CoreAPI

# ── Notification event registry ───────────────────────────────────────────────

_NOTIFY_EVENTS = [
    ("RewardEvent",      "Kill (bounty / combat bond)"),
    ("FighterDamage",    "Fighter hull damage"),
    ("FighterLost",      "Fighter destroyed"),
    ("ShieldEvent",      "Ship shields dropped / raised"),
    ("HullEvent",        "Ship hull damaged"),
    ("Died",             "Ship destroyed"),
    ("CargoLost",        "Cargo stolen"),
    ("LowCargoValue",    "Pirate declined to attack"),
    ("PoliceScan",       "Security vessel scan"),
    ("PoliceAttack",     "Security vessel attack"),
    ("FuelStatus",       "Fuel level (routine)"),
    ("FuelWarning",      "Fuel warning"),
    ("FuelCritical",     "Fuel critical"),
    ("MissionUpdate",    "Mission accepted / completed / redirected"),
    ("AllMissionsReady", "All massacre missions ready to hand in"),
    ("MeritEvent",       "Individual merit gain"),
    ("InactiveAlert",    "Inactivity alert"),
    ("RateAlert",        "Kill rate alert"),
    ("InboundScan",      "Incoming cargo scan"),
]

_LEVELS = [
    ("0  Off",       "0"),
    ("1  Terminal",  "1"),
    ("2  + Discord", "2"),
    ("3  + Ping",    "3"),
]

# Restart-required keys per config section.  Kept identical to the TUI's table.
_RESTART_KEYS: dict[str, set[str]] = {
    "Settings": {"JournalFolder"},
    "Discord":  {"WebhookURL", "UserID", "Identity",
                 "ForumChannel", "ThreadCmdrNames", "Timestamp"},
    "UI":       {"Theme"},
    "EDDN":     {"Enabled", "TestMode"},
    "EDSM":     {"Enabled", "ApiKey"},
    "EDAstro":  {"Enabled", "UploadCarrierEvents"},
    "Inara":    {"Enabled", "ApiKey"},
}


def _scroll_page() -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(10, 10, 10, 10)
    lay.setSpacing(6)
    area.setWidget(host)
    return area, lay


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "section")
    return lbl


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "dim")
    lbl.setWordWrap(True)
    return lbl


class PreferencesDialog(QDialog):
    """Modal preferences dialog — Ctrl+O to open, Escape to cancel."""

    def __init__(self, core: "CoreAPI", theme: str = "default",
                 parent=None) -> None:
        super().__init__(parent)
        self._core = core
        self._cfg = core.cfg
        self._theme = theme
        self._pending: dict[tuple[str, str], object] = {}
        self._restart_required = False
        self._display_selects: dict[str, QComboBox] = {}

        self.setWindowTitle("Preferences")
        self.setMinimumSize(660, 520)
        self.setStyleSheet(stylesheet(theme))
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._tab_general(),  "General")
        self._tabs.addTab(self._tab_notif(),    "Notifications")
        self._tabs.addTab(self._tab_discord(),  "Discord")
        self._tabs.addTab(self._tab_appearance(), "Appearance")
        self._tabs.addTab(self._tab_data(),     "Data")
        self._tabs.addTab(self._tab_display(),  "Display")
        for tab_id, tab_label, builder in self._extra_tabs():
            try:
                widget = builder()
                if widget is not None:
                    self._tabs.addTab(widget, tab_label)
            except Exception:
                pass
        lay.addWidget(self._tabs, 1)

        bottom = QHBoxLayout()
        self._restart_note = QLabel("")
        self._restart_note.setProperty("role", "dim")
        bottom.addWidget(self._restart_note, 1)
        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        apply_btn = buttons.addButton("Apply & Save", QDialogButtonBox.AcceptRole)
        apply_btn.setProperty("role", "primary")
        cancel.clicked.connect(self.reject)
        apply_btn.clicked.connect(self._apply_changes)
        bottom.addWidget(buttons, 0)
        lay.addLayout(bottom)

    # ── Widget factories that record on change ────────────────────────────────

    def _bool_combo(self, current: bool, section: str, key: str) -> QComboBox:
        box = QComboBox()
        box.addItem("Off", "false")
        box.addItem("On", "true")
        box.setCurrentIndex(1 if current else 0)
        box.currentIndexChanged.connect(
            lambda _i, s=section, k=key, b=box:
            self._record(s, k, b.currentData() == "true")
        )
        return box

    def _text_edit(self, value: str, section: str, key: str,
                   typ: type = str, password: bool = False,
                   placeholder: str = "") -> QLineEdit:
        edit = QLineEdit(str(value))
        if password:
            edit.setEchoMode(QLineEdit.Password)
        if placeholder:
            edit.setPlaceholderText(placeholder)

        def _changed(text: str) -> None:
            val = text.strip()
            try:
                coerced = typ(val) if val else (0 if typ is int else "")
            except (ValueError, TypeError):
                return
            self._record(section, key, coerced)

        edit.textChanged.connect(_changed)
        return edit

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _tab_general(self) -> QWidget:
        s = self._cfg.app_settings
        page, lay = _scroll_page()

        lay.addWidget(_section("SESSION"))
        form = QFormLayout()
        form.addRow("Journal Folder  ⚠",
                    self._text_edit(s.get("JournalFolder", ""), "Settings",
                                    "JournalFolder"))
        form.addRow("Use UTC Timestamps",
                    self._bool_combo(s.get("UseUTC", False), "Settings", "UseUTC"))
        lay.addLayout(form)

        lay.addWidget(_section("DISPLAY"))
        form2 = QFormLayout()
        form2.addRow("Truncate Names (chars)",
                     self._text_edit(s.get("TruncateNames", 30), "Settings",
                                     "TruncateNames", int))
        form2.addRow("Show Pirate Names",
                     self._bool_combo(s.get("PirateNames", False), "Settings",
                                      "PirateNames"))
        form2.addRow("Show Credit Value per Kill",
                     self._bool_combo(s.get("BountyValue", False), "Settings",
                                      "BountyValue"))
        form2.addRow("Show Victim Faction per Kill",
                     self._bool_combo(s.get("BountyFaction", False), "Settings",
                                      "BountyFaction"))
        form2.addRow("Extended Kill Stats",
                     self._bool_combo(s.get("ExtendedStats", False), "Settings",
                                      "ExtendedStats"))
        lay.addLayout(form2)

        lay.addWidget(_section("INACTIVITY ALERTS"))
        form3 = QFormLayout()
        form3.addRow("Alert After N Minutes Without Kill",
                     self._text_edit(s.get("WarnNoKills", 20), "Settings",
                                     "WarnNoKills", int))
        form3.addRow("Alert When Kill Rate Below (kills/hr)",
                     self._text_edit(s.get("WarnKillRate", 20), "Settings",
                                     "WarnKillRate", int))
        form3.addRow("Alert Cooldown (minutes)",
                     self._text_edit(s.get("WarnCooldown", 15), "Settings",
                                     "WarnCooldown", int))
        lay.addLayout(form3)
        lay.addStretch(1)
        return page

    def _tab_notif(self) -> QWidget:
        nl = self._cfg.notify_levels
        page, lay = _scroll_page()
        form = QFormLayout()
        for key, description in _NOTIFY_EVENTS:
            current = str(nl.get(key, 2))
            box = QComboBox()
            for label, value in _LEVELS:
                box.addItem(label, value)
            idx = next((i for i, (_l, v) in enumerate(_LEVELS) if v == current), 2)
            box.setCurrentIndex(idx)
            box.currentIndexChanged.connect(
                lambda _i, k=key, b=box:
                self._record("LogLevels", k, int(b.currentData()))
            )
            form.addRow(description, box)
        lay.addLayout(form)
        lay.addStretch(1)
        return page

    def _tab_discord(self) -> QWidget:
        d = self._cfg.discord_cfg
        page, lay = _scroll_page()

        lay.addWidget(_section("CONNECTION  (⚠ restart required)"))
        form = QFormLayout()
        form.addRow("Webhook URL",
                    self._text_edit(d.get("WebhookURL", ""), "Discord",
                                    "WebhookURL", password=True))
        form.addRow("User ID (for @mention)",
                    self._text_edit(d.get("UserID", 0), "Discord", "UserID", int))
        lay.addLayout(form)

        lay.addWidget(_section("OPTIONS"))
        form2 = QFormLayout()
        form2.addRow("Use EDLD name and avatar  ⚠",
                     self._bool_combo(d.get("Identity", False), "Discord",
                                      "Identity"))
        form2.addRow("Prefix messages with CMDR name",
                     self._bool_combo(d.get("PrependCmdrName", False), "Discord",
                                      "PrependCmdrName"))
        form2.addRow("Append timestamp to messages  ⚠",
                     self._bool_combo(d.get("Timestamp", False), "Discord",
                                      "Timestamp"))
        form2.addRow("Forum channel thread mode  ⚠",
                     self._bool_combo(d.get("ForumChannel", False), "Discord",
                                      "ForumChannel"))
        form2.addRow("Use CMDR name as thread title  ⚠",
                     self._bool_combo(d.get("ThreadCmdrNames", False), "Discord",
                                      "ThreadCmdrNames"))
        lay.addLayout(form2)
        lay.addStretch(1)
        return page

    def _tab_appearance(self) -> QWidget:
        ui = self._cfg.ui_cfg
        page, lay = _scroll_page()
        lay.addWidget(_section("THEME  (⚠ restart required to persist)"))
        lay.addWidget(_note(
            "The dashboard restyles immediately when a theme is chosen; the "
            "choice is written to config.toml on Apply."))

        box = QComboBox()
        options = list(THEME_CHOICES)
        for tid, stem in list_custom_themes():
            options.append((f"Custom: {stem}", tid))
        for label, value in options:
            box.addItem(label, value)

        # Guard: if the stored theme value does not exist in the options list
        # (a custom theme file that has been removed, or a typo in
        # config.toml), fall back to "default" rather than leaving the combo
        # on an arbitrary entry.
        current = ui.get("Theme", "default")
        valid = {v for _l, v in options}
        sel = current if current in valid else "default"
        box.setCurrentIndex(next(i for i, (_l, v) in enumerate(options) if v == sel))

        def _theme_changed() -> None:
            val = str(box.currentData())
            self._record("UI", "Theme", val)
            # Immediate preview, matching the TUI's live restyle.
            win = self.window().parent() or self.parent()
            applier = getattr(parent_window(self), "apply_theme", None)
            if callable(applier):
                applier(val)
            self.setStyleSheet(stylesheet(val))

        box.currentIndexChanged.connect(lambda _i: _theme_changed())
        lay.addWidget(box)
        lay.addStretch(1)
        return page

    def _tab_data(self) -> QWidget:
        cfg = self._cfg
        eddn, edsm = cfg.eddn_cfg, cfg.edsm_cfg
        edastro, inara = cfg.edastro_cfg, cfg.inara_cfg
        page, lay = _scroll_page()

        lay.addWidget(_section("FRONTIER CAPI  (Companion API)"))
        lay.addWidget(_note(
            "Provides authoritative fleet data from Frontier. Authenticates "
            "via your Frontier account in a browser window."))
        self._capi_status = QLabel(self._get_capi_status())
        self._capi_status.setProperty("role", "dim")
        lay.addWidget(self._capi_status)
        row = QHBoxLayout()
        connect = QPushButton("Connect")
        connect.setProperty("role", "primary")
        connect.clicked.connect(self._capi_connect)
        disconnect = QPushButton("Disconnect")
        disconnect.clicked.connect(self._capi_disconnect)
        row.addWidget(connect)
        row.addWidget(disconnect)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(_section("EDDN  (Elite Dangerous Data Network)  ⚠"))
        f1 = QFormLayout()
        f1.addRow("Enable EDDN",
                  self._bool_combo(eddn.get("Enabled", False), "EDDN", "Enabled"))
        f1.addRow("Test Mode",
                  self._bool_combo(eddn.get("TestMode", False), "EDDN", "TestMode"))
        lay.addLayout(f1)

        lay.addWidget(_section("EDSM  (Elite Dangerous Star Map)  ⚠"))
        f2 = QFormLayout()
        f2.addRow("Enable EDSM",
                  self._bool_combo(edsm.get("Enabled", False), "EDSM", "Enabled"))
        f2.addRow("EDSM API Key",
                  self._text_edit(edsm.get("ApiKey", ""), "EDSM", "ApiKey",
                                  password=True))
        lay.addLayout(f2)

        lay.addWidget(_section("EDAstro  ⚠"))
        f3 = QFormLayout()
        f3.addRow("Enable EDAstro",
                  self._bool_combo(edastro.get("Enabled", False), "EDAstro",
                                   "Enabled"))
        f3.addRow("Include Carrier Events",
                  self._bool_combo(edastro.get("UploadCarrierEvents", False),
                                   "EDAstro", "UploadCarrierEvents"))
        lay.addLayout(f3)

        lay.addWidget(_section("Inara  ⚠"))
        f4 = QFormLayout()
        f4.addRow("Enable Inara",
                  self._bool_combo(inara.get("Enabled", False), "Inara", "Enabled"))
        f4.addRow("Inara API Key",
                  self._text_edit(inara.get("ApiKey", ""), "Inara", "ApiKey",
                                  password=True))
        lay.addLayout(f4)

        lay.addWidget(_section("RAVEN COLONIAL"))
        lay.addWidget(_note(
            "Sync colonisation project supply needs and deliveries to "
            "ravencolonial.com. Leave blank to disable (local tracking still "
            "works)."))
        f5 = QFormLayout()
        colon_cfg = cfg.colonisation_cfg
        f5.addRow("Raven Colonial API Key",
                  self._text_edit(colon_cfg.get("ApiKey", ""), "Colonisation",
                                  "ApiKey", password=True,
                                  placeholder="optional — from ravencolonial.com"))
        lay.addLayout(f5)
        lay.addStretch(1)
        return page

    def _tab_display(self) -> QWidget:
        from core import layout_model as LM
        page, lay = _scroll_page()
        lay.addWidget(_note(
            "Choose which window appears in each position. Only windows of a "
            "matching size fit a position; choosing one already shown "
            "elsewhere moves it. Layout changes apply on restart."))

        asn = LM.load_assignment()
        avail = set(LM.BLOCK_CLASS)
        last_col = None
        form: QFormLayout | None = None
        for info in LM.summary(asn, avail):
            if info["column"] != last_col:
                lay.addWidget(_section(f"{info['column'].upper()} COLUMN"))
                form = QFormLayout()
                lay.addLayout(form)
                last_col = info["column"]

            box = QComboBox()
            box.addItem("(empty)", "")
            for b in info["eligible"]:
                box.addItem(LM.block_display(b), b)
            value = info["block"] if (info["block"] and
                                      info["block"] in info["eligible"]) else ""
            idx = box.findData(value)
            box.setCurrentIndex(idx if idx >= 0 else 0)
            self._display_selects[info["slot"]] = box
            if form is not None:
                form.addRow(f"{info['slot']}  ·  {info['class_label']}", box)
        lay.addStretch(1)
        return page

    # ── Component-injected preference tabs ────────────────────────────────────

    def _extra_tabs(self) -> list[tuple[str, str, object]]:
        """Ask loaded components if they want to inject a preferences tab.

        A component may expose ``gui_preferences_tab()`` returning
        ``(tab_id, tab_label, builder)`` where ``builder()`` returns a QWidget.
        Only called for components that implement the method — invisible to
        all other code.
        """
        result = []
        for plugin in self._core._plugins.values():
            fn = getattr(plugin, "gui_preferences_tab", None)
            if callable(fn):
                try:
                    entry = fn()
                    if entry:
                        result.append(entry)
                except Exception:
                    pass
        return result

    # ── Change collection ─────────────────────────────────────────────────────

    def _record(self, section: str, key: str, value: object) -> None:
        self._pending[(section, key)] = value
        restart = key in _RESTART_KEYS.get(section, set())
        if restart and not self._restart_required:
            self._restart_required = True
            self._restart_note.setText("⚠  Restart required for some changes")

    # ── CAPI helpers ──────────────────────────────────────────────────────────

    def _capi_provider(self):
        try:
            dp = getattr(self._core, "data", None)
            return dp.capi if dp else None
        except Exception:
            return None

    def _get_capi_status(self) -> str:
        capi = self._capi_provider()
        if capi is None:
            return "CAPI provider not available"
        try:
            status = capi.auth_status()
            connected = status.get("connected", False)
            cmdr = status.get("cmdr", "")
            result = status.get("auth_result", "")
            if result == "auth_running":
                return "Waiting for browser authentication…"
            if connected:
                suffix = f" — {cmdr}" if cmdr else ""
                return f"Connected{suffix}"
            return "Not connected"
        except Exception:
            return "Status unavailable"

    def _capi_connect(self) -> None:
        capi = self._capi_provider()
        if capi is None:
            return
        try:
            capi._auth_result = "auth_running"
            capi.authenticate()
            self._capi_status.setText("Waiting for browser authentication…")
        except Exception:
            pass

    def _capi_disconnect(self) -> None:
        capi = self._capi_provider()
        if capi is None:
            return
        try:
            capi.disconnect()
            self._capi_status.setText("Not connected")
        except Exception:
            pass

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _collect_window_assignment(self):
        """Read the Display tab's combos into a validated assignment."""
        from core import layout_model as LM
        if not self._display_selects:
            return None
        raw = {}
        for sid in LM.slot_ids():
            box = self._display_selects.get(sid)
            if box is None:
                return None
            v = box.currentData()
            raw[sid] = v if (isinstance(v, str) and v) else None
        return LM.normalize_assignment(raw)

    def _apply_changes(self) -> None:
        from core import layout_model as LM

        new_asn = self._collect_window_assignment()
        windows_changed = new_asn is not None and new_asn != LM.load_assignment()

        if not self._pending and not windows_changed:
            self.reject()
            return

        if self._pending:
            config_path = self._cfg.config_path
            try:
                raw = config_path.read_text(encoding="utf-8")
                config = tomllib.loads(raw)
            except Exception as exc:
                self._show_error(f"Could not read config.toml: {exc}")
                return

            profile = self._cfg.config_profile
            for (section, key), value in self._pending.items():
                if profile:
                    target = config.setdefault(profile, {}).setdefault(section, {})
                else:
                    target = config.setdefault(section, {})
                target[key] = value

            try:
                new_toml = config_to_toml(config)
                config_path.write_text(new_toml, encoding="utf-8")
            except Exception as exc:
                self._show_error(f"Could not write config.toml: {exc}")
                return

        if windows_changed:
            LM.save_assignment(new_asn)

        if self._restart_required or windows_changed:
            launch_argv = getattr(self._core, "launch_argv", None) or sys.argv
            os.execv(sys.executable, [sys.executable] + list(launch_argv))
        else:
            try:
                self._cfg.refresh(terminal_print=False)
            except Exception:
                pass
            self.accept()

    def _show_error(self, msg: str) -> None:
        self._restart_note.setText(msg)


def parent_window(widget):
    """Walk up to the top-level window that owns ``widget``."""
    w = widget
    while w is not None:
        parent = w.parent()
        if parent is None:
            return w
        w = parent
    return None

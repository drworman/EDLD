"""
tui/preferences.py — TUI preferences screen for EDLD.

Mirrors the five tabs of gui/preferences.py:
  General       — journal folder, UTC, display toggles, inactivity alerts
  Notifications — per-event log levels (0–3)
  Discord       — webhook, user ID, display options
  Appearance    — theme selection
  Data          — EDDN, EDSM, EDAstro, Inara integrations

Changes are collected in a pending dict and written to config.toml on Apply.
Settings marked ⚠ require a restart; the screen restarts the process via
os.execv using core.launch_argv when Apply is confirmed.
"""
from __future__ import annotations
import os
from pathlib import Path
import sys
import tomllib
from core.config import config_to_toml
from typing import TYPE_CHECKING

from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import ModalScreen
from textual.widgets    import (
    Label, Button, Input, TabbedContent, TabPane, Select,
)
from textual.containers import Horizontal, Vertical, VerticalScroll

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

_LEVEL_SELECT: list[tuple[str, str]] = [
    ("0  Off",                  "0"),
    ("1  Terminal only",        "1"),
    ("2  Terminal + Discord",   "2"),
    ("3  Terminal + Discord + Ping", "3"),
]

# Restart-required keys per config section — mirrors gui/preferences.py
_RESTART_KEYS: dict[str, set[str]] = {
    "Settings": {"JournalFolder"},
    "Discord":  {"WebhookURL", "UserID", "Identity",
                 "ForumChannel", "ThreadCmdrNames", "Timestamp"},
    "UI":       {"Theme", "FontSize"},
    "EDDN":     {"Enabled", "TestMode"},
    "EDSM":     {"Enabled", "ApiKey"},
    "EDAstro":  {"Enabled", "UploadCarrierEvents"},
    "Inara":    {"Enabled", "ApiKey"},
}


# ── Screen ────────────────────────────────────────────────────────────────────

class PreferencesScreen(ModalScreen):
    """Full-screen preferences overlay — Ctrl+O to open, Escape to cancel."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("ctrl+o", "dismiss", "Close"),
    ]

    def __init__(self, core: "CoreAPI", **kw) -> None:
        super().__init__(**kw)
        self._core    = core
        self._cfg     = core.cfg
        self._pending: dict[tuple[str, str], object] = {}
        self._restart_required = False
        # Pre-compute plugin-injected tabs before compose() runs so that
        # the compose generator is pure widget-yielding with no plugin I/O.
        self._cached_extra_tabs = self._extra_tabs()

    def compose(self) -> ComposeResult:
        cfg = self._cfg
        s   = cfg.app_settings
        d   = cfg.discord_cfg
        nl  = cfg.notify_levels
        ui  = cfg.ui_cfg

        with Vertical(id="prefs-outer"):
            yield Label(" PREFERENCES ", classes="block-title")

            with TabbedContent(id="pref-tabs"):

                # ── General ───────────────────────────────────────────────────
                with TabPane("General", id="pref-tab-general"):
                    with VerticalScroll():
                        yield Label("SESSION", classes="pref-section")
                        with Horizontal(classes="pref-row"):
                            yield Label("Journal Folder  ⚠", classes="key")
                            yield Input(value=str(s.get("JournalFolder", "")),
                                        id="g-journal", classes="pref-input")
                        with Horizontal(classes="pref-row"):
                            yield Label("Use UTC Timestamps", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if s.get("UseUTC", False) else "false",
                                    id="g-utc", classes="pref-bool-sel", allow_blank=False)
                        yield Label("DISPLAY", classes="pref-section")
                        with Horizontal(classes="pref-row"):
                            yield Label("Truncate Names (chars)", classes="key")
                            yield Input(value=str(s.get("TruncateNames", 30)),
                                        id="g-trunc", restrict="0123456789",
                                        max_length=3, classes="pref-input-sm")
                        with Horizontal(classes="pref-row"):
                            yield Label("Show Pirate Names", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if s.get("PirateNames", False) else "false",
                                    id="g-pirate", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Show Credit Value per Kill", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if s.get("BountyValue", False) else "false",
                                    id="g-bounty-val", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Show Victim Faction per Kill", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if s.get("BountyFaction", False) else "false",
                                    id="g-bounty-fac", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Extended Kill Stats", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if s.get("ExtendedStats", False) else "false",
                                    id="g-extended", classes="pref-bool-sel", allow_blank=False)
                        yield Label("INACTIVITY ALERTS", classes="pref-section")
                        with Horizontal(classes="pref-row"):
                            yield Label("Alert After N Minutes Without Kill", classes="key")
                            yield Input(value=str(s.get("WarnNoKills", 20)),
                                        id="g-warn-kills", restrict="0123456789",
                                        max_length=3, classes="pref-input-sm")
                        with Horizontal(classes="pref-row"):
                            yield Label("Alert When Kill Rate Below (kills/hr)", classes="key")
                            yield Input(value=str(s.get("WarnKillRate", 20)),
                                        id="g-warn-rate", restrict="0123456789",
                                        max_length=3, classes="pref-input-sm")
                        with Horizontal(classes="pref-row"):
                            yield Label("Alert Cooldown (minutes)", classes="key")
                            yield Input(value=str(s.get("WarnCooldown", 15)),
                                        id="g-warn-cd", restrict="0123456789",
                                        max_length=3, classes="pref-input-sm")

                # ── Notifications ─────────────────────────────────────────────
                with TabPane("Notifications", id="pref-tab-notif"):
                    with VerticalScroll():
                        for key, description in _NOTIFY_EVENTS:
                            current = str(nl.get(key, 2))
                            with Horizontal(classes="pref-row"):
                                yield Label(description, classes="key")
                                yield Select(
                                    [("0  Off",         "0"),
                                     ("1  Terminal",    "1"),
                                     ("2  + Discord",   "2"),
                                     ("3  + Ping",      "3")],
                                    value=current,
                                    id=f"notif-{key}",
                                    classes="pref-notif-sel",
                                    allow_blank=False,
                                )

                # ── Discord ───────────────────────────────────────────────────
                with TabPane("Discord", id="pref-tab-discord"):
                    with VerticalScroll():
                        yield Label("CONNECTION  (⚠ restart required)",
                                    classes="pref-section")
                        with Horizontal(classes="pref-row"):
                            yield Label("Webhook URL", classes="key")
                            yield Input(value=str(d.get("WebhookURL", "")),
                                        id="dc-webhook", password=True,
                                        classes="pref-input")
                        with Horizontal(classes="pref-row"):
                            yield Label("User ID (for @mention)", classes="key")
                            yield Input(value=str(d.get("UserID", 0)),
                                        id="dc-uid", restrict="0123456789",
                                        classes="pref-input")
                        yield Label("OPTIONS", classes="pref-section")
                        with Horizontal(classes="pref-row"):
                            yield Label("Use EDLD name and avatar  ⚠", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if d.get("Identity", False) else "false",
                                    id="dc-identity", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Prefix messages with CMDR name", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if d.get("PrependCmdrName", False) else "false",
                                    id="dc-prepend", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Append timestamp to messages  ⚠", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if d.get("Timestamp", False) else "false",
                                    id="dc-timestamp", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Forum channel thread mode  ⚠", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if d.get("ForumChannel", False) else "false",
                                    id="dc-forum", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Use CMDR name as thread title  ⚠", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if d.get("ThreadCmdrNames", False) else "false",
                                    id="dc-threads", classes="pref-bool-sel", allow_blank=False)

                # ── Appearance ────────────────────────────────────────────────
                with TabPane("Appearance", id="pref-tab-appearance"):
                    with VerticalScroll():
                        yield Label("THEME  (⚠ restart required to persist; "
                                    "previews immediately)", classes="pref-section")
                        from tui.theme import list_custom_themes
                        theme_opts: list[tuple[str, str]] = [
                            ("EDLD Default",        "default"),
                            ("EDLD Default Dark",   "default-dark"),
                            ("EDLD Default Green",  "default-green"),
                            ("EDLD Default Blue",   "default-blue"),
                            ("EDLD Default Purple", "default-purple"),
                            ("EDLD Default Red",    "default-red"),
                            ("EDLD Default Yellow", "default-yellow"),
                            ("EDLD Default Light",  "default-light"),
                        ]
                        for tid, stem in list_custom_themes():
                            theme_opts.append((f"Custom: {stem}", tid))
                        current_theme = ui.get("Theme", "default")
                        select_opts   = [(lbl, val) for lbl, val in theme_opts]
                        # Guard: if the stored theme value does not exist in the
                        # options list (e.g. a custom theme file that has been
                        # removed, or a typo in config.toml), fall back to
                        # "default" rather than letting Textual raise
                        # InvalidSelectValueError and crash the preferences screen.
                        valid_values = {val for _, val in select_opts}
                        sel_val = current_theme if current_theme in valid_values else "default"
                        yield Select(
                            select_opts,
                            value=sel_val,
                            id="app-theme",
                            classes="pref-select",
                        )

                # ── Data & Integrations ───────────────────────────────────────
                with TabPane("Data", id="pref-tab-data"):
                    eddn    = cfg.eddn_cfg
                    edsm    = cfg.edsm_cfg
                    edastro = cfg.edastro_cfg
                    inara   = cfg.inara_cfg
                    with VerticalScroll():
                        yield Label("FRONTIER CAPI  (Companion API)",
                                    classes="pref-section")
                        yield Label(
                            "Provides authoritative fleet data from Frontier.\n"
                            "Authenticates via your Frontier account in a browser window.",
                            classes="pref-note",
                        )
                        yield Label(self._get_capi_status(), id="capi-status",
                                    classes="pref-note")
                        with Horizontal(classes="pref-row"):
                            yield Label("Account", classes="key")
                            yield Button("Connect",    id="btn-capi-connect",
                                         variant="primary")
                            yield Button("Disconnect", id="btn-capi-disconnect",
                                         variant="default")
                        yield Label("EDDN  (Elite Dangerous Data Network)  ⚠",
                                    classes="pref-section")
                        with Horizontal(classes="pref-row"):
                            yield Label("Enable EDDN", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if eddn.get("Enabled", False) else "false",
                                    id="eddn-enabled", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Test Mode", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if eddn.get("TestMode", False) else "false",
                                    id="eddn-test", classes="pref-bool-sel", allow_blank=False)

                        yield Label("EDSM  (Elite Dangerous Star Map)  ⚠",
                                    classes="pref-section")
                        with Horizontal(classes="pref-row"):
                            yield Label("Enable EDSM", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if edsm.get("Enabled", False) else "false",
                                    id="edsm-enabled", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("EDSM API Key", classes="key")
                            yield Input(value=str(edsm.get("ApiKey", "")),
                                        password=True, id="edsm-key",
                                        classes="pref-input")

                        yield Label("EDAstro  ⚠", classes="pref-section")
                        with Horizontal(classes="pref-row"):
                            yield Label("Enable EDAstro", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if edastro.get("Enabled", False) else "false",
                                    id="edastro-enabled", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Include Carrier Events", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if edastro.get("UploadCarrierEvents", False) else "false",
                                    id="edastro-carrier", classes="pref-bool-sel", allow_blank=False)

                        yield Label("Inara  ⚠", classes="pref-section")
                        with Horizontal(classes="pref-row"):
                            yield Label("Enable Inara", classes="key")
                            yield Select(
                                    [("Off", "false"), ("On", "true")],
                                    value="true" if inara.get("Enabled", False) else "false",
                                    id="inara-enabled", classes="pref-bool-sel", allow_blank=False)
                        with Horizontal(classes="pref-row"):
                            yield Label("Inara API Key", classes="key")
                            yield Input(value=str(inara.get("ApiKey", "")),
                                        password=True, id="inara-key",
                                        classes="pref-input")

                        yield Label("RAVEN COLONIAL", classes="pref-section")
                        yield Label(
                            "Sync colonisation project supply needs and\n"
                            "deliveries to ravencolonial.com.  Leave blank\n"
                            "to disable (local tracking still works).",
                            classes="pref-note",
                        )
                        colon_cfg = cfg.colonisation_cfg
                        with Horizontal(classes="pref-row"):
                            yield Label("Raven Colonial API Key", classes="key")
                            yield Input(
                                value=str(colon_cfg.get("ApiKey", "")),
                                password=True, id="raven-key",
                                placeholder="optional — from ravencolonial.com",
                                classes="pref-input",
                            )

                # ── Display (window layout) ──────────────────────────────────
                with TabPane("Display", id="pref-tab-display"):
                    with VerticalScroll():
                        from core import layout_model as _LM
                        yield Label(
                            "Choose which window appears in each position.  Only windows of a "
                            "matching size fit a position; choosing one already shown elsewhere "
                            "moves it.  Layout changes apply on restart.",
                            classes="pref-note",
                        )
                        _asn   = _LM.load_assignment()
                        _avail = set(_LM.BLOCK_CLASS)
                        _last_col = None
                        for _info in _LM.summary(_asn, _avail):
                            if _info["column"] != _last_col:
                                yield Label(f"{_info['column'].upper()} COLUMN", classes="pref-section")
                                _last_col = _info["column"]
                            _opts = [("(empty)", "")] + [
                                (_LM.block_display(b), b) for b in _info["eligible"]
                            ]
                            _val = _info["block"] if (_info["block"] and _info["block"] in _info["eligible"]) else ""
                            # Width this select to its own longest option, plus
                            # chrome for the border, the ▼ arrow, the dropdown's
                            # own border and per-option padding, so every option
                            # stays on a single line.
                            _selw = max(len(_lbl) for _lbl, _ in _opts) + 10
                            with Horizontal(classes="pref-row"):
                                yield Label(f"{_info['slot']}  ·  {_info['class_label']}", classes="key")
                                _sel = Select(_opts, value=_val, id=f"disp-{_info['slot']}",
                                              classes="pref-bool-sel", allow_blank=False)
                                _sel.styles.width = _selw
                                yield _sel

                # ── Component-injected tabs (e.g. optional private components)
                for tab_id, tab_label, tab_composer in self._cached_extra_tabs:
                    with TabPane(tab_label, id=tab_id):
                        with VerticalScroll():
                            yield from tab_composer()

            with Horizontal(id="pref-btn-row"):
                yield Label("", id="pref-restart-note")
                yield Button("Cancel",       id="btn-pref-cancel",  variant="default")
                yield Button("Apply & Save", id="btn-pref-apply",   variant="primary")

    def on_mount(self) -> None:
        self.query_one("#pref-tabs", TabbedContent).focus()
        # Force a full compositor refresh after mount so the modal overlay
        # renders correctly over the dashboard layer on all terminals.
        # self.app.refresh() repaints base screen + modal together.
        self.app.set_timer(0.1, lambda: self.app.refresh(layout=True))

    # ── Change collection ─────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        wid = str(event.input.id or "")
        for plugin in self._core._plugins.values():
            fn = getattr(plugin, "collect_tui_prefs", None)
            if callable(fn):
                try:
                    if fn(wid, str(event.value)):
                        event.stop()
                        return
                except Exception:
                    pass
        self._collect_input(event.input)

    def on_select_changed(self, event: Select.Changed) -> None:
        wid = str(event.select.id or "")
        # Let components handle their own widgets first
        for plugin in self._core._plugins.values():
            fn = getattr(plugin, "collect_tui_prefs", None)
            if callable(fn):
                try:
                    if fn(wid, str(event.value)):
                        event.stop()
                        return
                except Exception:
                    pass
        if wid == "app-theme":
            val = str(event.value)
            self._record("UI", "Theme", val)
            # Immediate preview
            try:
                from tui.theme import build_css
                app = self.app
                app.CSS = build_css(val)
                app.refresh_css()
            except Exception:
                pass

        _BOOL_MAP: dict[str, tuple[str, str]] = {
            "g-utc":          ("Settings",  "UseUTC"),
            "g-pirate":       ("Settings",  "PirateNames"),
            "g-bounty-val":   ("Settings",  "BountyValue"),
            "g-bounty-fac":   ("Settings",  "BountyFaction"),
            "g-extended":     ("Settings",  "ExtendedStats"),
            "dc-identity":    ("Discord",   "Identity"),
            "dc-prepend":     ("Discord",   "PrependCmdrName"),
            "dc-timestamp":   ("Discord",   "Timestamp"),
            "dc-forum":       ("Discord",   "ForumChannel"),
            "dc-threads":     ("Discord",   "ThreadCmdrNames"),
            "eddn-enabled":   ("EDDN",      "Enabled"),
            "eddn-test":      ("EDDN",      "TestMode"),
            "edsm-enabled":   ("EDSM",      "Enabled"),
            "edastro-enabled":("EDAstro",   "Enabled"),
            "edastro-carrier":("EDAstro",   "UploadCarrierEvents"),
            "inara-enabled":  ("Inara",     "Enabled"),
        }
        if wid in _BOOL_MAP:
            section, key = _BOOL_MAP[wid]
            self._record(section, key, event.value == "true")
            return
        elif wid.startswith("notif-"):
            event_key = wid[6:]
            try:
                self._record("LogLevels", event_key, int(str(event.value)))
            except (ValueError, TypeError):
                pass

    def _collect_input(self, widget: Input) -> None:
        wid = str(widget.id or "")
        val = widget.value.strip()

        mapping: dict[str, tuple[str, str, type]] = {
            "g-journal":    ("Settings",  "JournalFolder",  str),
            "g-trunc":      ("Settings",  "TruncateNames",  int),
            "g-warn-kills": ("Settings",  "WarnNoKills",    int),
            "g-warn-rate":  ("Settings",  "WarnKillRate",   int),
            "g-warn-cd":    ("Settings",  "WarnCooldown",   int),
            "dc-webhook":   ("Discord",   "WebhookURL",     str),
            "dc-uid":       ("Discord",   "UserID",         int),
            "edsm-key":     ("EDSM",      "ApiKey",         str),
            "inara-key":    ("Inara",        "ApiKey",         str),
            "raven-key":    ("Colonisation", "ApiKey",         str),
        }
        if wid in mapping:
            section, key, typ = mapping[wid]
            try:
                coerced = typ(val) if val else (0 if typ is int else "")
            except (ValueError, TypeError):
                return
            self._record(section, key, coerced)
            return


    def _record(self, section: str, key: str, value: object) -> None:
        self._pending[(section, key)] = value
        restart = key in _RESTART_KEYS.get(section, set())
        if restart and not self._restart_required:
            self._restart_required = True
            try:
                self.query_one("#pref-restart-note", Label).update(
                    "⚠  Restart required for some changes"
                )
            except Exception:
                pass

    # ── Buttons ───────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = str(event.button.id or "")
        if bid == "btn-pref-cancel":
            self.dismiss(None)
        elif bid == "btn-pref-apply":
            self._apply_changes()
        elif bid == "btn-capi-connect":
            self._capi_connect()
        elif bid == "btn-capi-disconnect":
            self._capi_disconnect()

    # ── Component-injected preference tabs ────────────────────────────────────

    def _extra_tabs(self) -> list[tuple[str, str, callable]]:
        """Ask loaded components if they want to inject a preferences tab.

        A component may expose a tui_preferences_tab() method returning
        (tab_id: str, tab_label: str, composer: callable) or None.
        Only called for components that implement the method — invisible to all
        other code.
        """
        result = []
        for plugin in self._core._plugins.values():
            fn = getattr(plugin, "tui_preferences_tab", None)
            if callable(fn):
                print(f"[EDLD] _extra_tabs: found tui_preferences_tab on {plugin.PLUGIN_NAME!r}")
                try:
                    entry = fn()
                    if entry:
                        result.append(entry)
                except Exception as _e:
                    import traceback as _tb
                    print(f"[EDLD] _extra_tabs error for {plugin.PLUGIN_NAME!r}: {_e}")
                    _tb.print_exc()
        return result

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
            return "[dim]CAPI provider not available[/dim]"
        try:
            status    = capi.auth_status()
            connected = status.get("connected", False)
            cmdr      = status.get("cmdr", "")
            result    = status.get("auth_result", "")
            if result == "auth_running":
                return "[yellow]Waiting for browser authentication…[/yellow]"
            if connected:
                suffix = f" — {cmdr}" if cmdr else ""
                return f"[green]Connected[/green]{suffix}"
            return "[dim]Not connected[/dim]"
        except Exception:
            return "[dim]Status unavailable[/dim]"

    def _capi_connect(self) -> None:
        capi = self._capi_provider()
        if capi is None:
            return
        try:
            capi._auth_result = "auth_running"
            capi.authenticate()
            self.query_one("#capi-status", Label).update(
                "[yellow]Waiting for browser authentication…[/yellow]"
            )
        except Exception:
            pass

    def _capi_disconnect(self) -> None:
        capi = self._capi_provider()
        if capi is None:
            return
        try:
            capi.disconnect()
            self.query_one("#capi-status", Label).update("[dim]Not connected[/dim]")
        except Exception:
            pass

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _collect_window_assignment(self):
        """Read the Display tab's selects into a validated assignment, or None
        if the Display tab isn't present."""
        from core import layout_model as LM
        raw = {}
        for sid in LM.slot_ids():
            try:
                sel = self.query_one(f"#disp-{sid}", Select)
            except Exception:
                return None
            v = sel.value
            raw[sid] = v if (isinstance(v, str) and v) else None
        return LM.normalize_assignment(raw)

    def _apply_changes(self) -> None:
        from core import layout_model as LM

        new_asn = self._collect_window_assignment()
        windows_changed = new_asn is not None and new_asn != LM.load_assignment()

        if not self._pending and not windows_changed:
            self.dismiss(None)
            return

        if self._pending:
            config_path = self._cfg.config_path
            try:
                raw    = config_path.read_text(encoding="utf-8")
                config = tomllib.loads(raw)
            except Exception as exc:
                self._show_error(f"Could not read config.toml:\n{exc}")
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
                self._show_error(f"Could not write config.toml:\n{exc}")
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
            self.dismiss(None)

    def _show_error(self, msg: str) -> None:
        # Show briefly in the restart note label
        try:
            self.query_one("#pref-restart-note", Label).update(f"[red]{msg}[/red]")
        except Exception:
            pass


# ── TOML writer (standalone — no gui/ dependency) ────────────────────────────

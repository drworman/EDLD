"""
gui/preferences.py — Preferences window for EDLD.

Tabbed GTK4 dialog covering:
  General      — journal folder, UTC toggle, name truncation, inactivity config
  Notifications — per-event log level grid (0–3)
  Discord      — webhook URL, user ID, display options
  Appearance   — theme selector

Hot-reloadable settings take effect immediately on save.
Settings marked ❌ require a restart — shown with a ⚠ indicator.

Writes changes to config.toml using tomllib (read) + manual string assembly (write).
Requires Python 3.11+ (tomllib stdlib).
"""

import tomllib
from core.config import config_to_toml
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")


# ── Notification level labels ─────────────────────────────────────────────────

LEVEL_LABELS = ["Off", "Terminal only", "Terminal + Discord", "Terminal + Discord + Ping"]

NOTIFY_EVENTS = [
    ("RewardEvent",      "Kill (bounty / combat bond)"),
    ("FighterDamage",    "Fighter hull damage (~20% steps)"),
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
    ("AllMissionsReady", "All massacre missions ready to turn in"),
    ("MeritEvent",       "Individual merit gain"),
    ("InactiveAlert",    "Inactivity alert"),
    ("RateAlert",        "Kill rate alert"),
    ("InboundScan",      "Incoming cargo scan"),
]

THEMES = [
    "default", "default-blue", "default-green", "default-purple",
    "default-red", "default-yellow", "default-light",
]


class PreferencesWindow(Gtk.Window):
    """Tabbed preferences window."""

    def __init__(self, parent, core):
        super().__init__(title="EDLD Preferences")
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(540, 560)
        self.set_resizable(True)
        self.add_css_class("prefs-window")

        self._core    = core
        self._cfg     = core.cfg
        # Changes are split by whether they need a restart or are hot-reloadable.
        # Keys mirror the section/key structure written to config.toml.
        self._hot:     dict = {}   # section → {key: value}  — hot-reload on apply
        self._restart: dict = {}   # section → {key: value}  — needs os.execv after apply
        self._restart_banner: Gtk.InfoBar | None = None

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(outer)

        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        notebook.add_css_class("prefs-notebook")
        outer.append(notebook)

        self._build_general_tab(notebook)
        self._build_notifications_tab(notebook)
        self._build_discord_tab(notebook)
        self._build_appearance_tab(notebook)
        self._build_data_tab(notebook)

        # Restart-required banner (hidden until a restart-required field changes)
        banner = Gtk.InfoBar()
        banner.set_message_type(Gtk.MessageType.WARNING)
        banner.set_revealed(False)
        banner.set_show_close_button(False)
        banner_lbl = Gtk.Label(
            label="⚠  Some changes require a restart — the app will restart automatically on Apply."
        )
        banner_lbl.set_xalign(0.0)
        banner_lbl.add_css_class("prefs-restart-banner")
        banner.add_child(banner_lbl)
        outer.append(banner)
        self._restart_banner = banner

        # Button row
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_top(8)
        btn_row.set_margin_bottom(12)
        btn_row.set_margin_end(12)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: self.close())
        cancel_btn.add_css_class("prefs-btn")
        btn_row.append(cancel_btn)

        apply_btn = Gtk.Button(label="Apply & Save")
        apply_btn.add_css_class("prefs-btn-apply")
        apply_btn.connect("clicked", self._on_apply)
        btn_row.append(apply_btn)

        outer.append(btn_row)

    # ── Tab builders ──────────────────────────────────────────────────────────

    def _tab(self, notebook: Gtk.Notebook, label: str) -> Gtk.Box:
        """Add a tab and return its scrollable content box."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        scroll.set_child(box)
        notebook.append_page(scroll, Gtk.Label(label=label))
        return box

    def _section_label(self, text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0.0)
        lbl.add_css_class("section-header")
        return lbl

    def _row(self, key_text: str, widget: Gtk.Widget,
             restart_required: bool = False) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_bottom(2)
        lbl = Gtk.Label(label=key_text)
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        lbl.add_css_class("prefs-key")
        row.append(lbl)
        if restart_required:
            warn = Gtk.Label(label="⚠")
            warn.set_tooltip_text("Requires restart to take effect")
            warn.add_css_class("prefs-restart-warn")
            row.append(warn)
        row.append(widget)
        return row

    # ── General tab ───────────────────────────────────────────────────────────

    def _build_general_tab(self, nb: Gtk.Notebook) -> None:
        box = self._tab(nb, "General")
        s   = self._cfg.app_settings

        box.append(self._section_label("Session"))

        # Journal folder
        jf_entry = Gtk.Entry()
        jf_entry.set_text(s.get("JournalFolder", ""))
        jf_entry.set_hexpand(True)
        jf_entry.set_width_chars(28)
        jf_entry.connect("changed", lambda w: self._track("JournalFolder", w.get_text()))
        box.append(self._row("Journal Folder", jf_entry, restart_required=True))

        # UTC toggle
        utc_sw = Gtk.Switch()
        utc_sw.set_active(bool(s.get("UseUTC", False)))
        utc_sw.set_valign(Gtk.Align.CENTER)
        utc_sw.connect("state-set", lambda w, v: self._track("UseUTC", v))
        box.append(self._row("Use UTC Timestamps", utc_sw))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self._section_label("Display"))

        # Truncate names
        trunc_spin = Gtk.SpinButton.new_with_range(10, 100, 1)
        trunc_spin.set_value(int(s.get("TruncateNames", 30)))
        trunc_spin.set_valign(Gtk.Align.CENTER)
        trunc_spin.connect("value-changed", lambda w: self._track("TruncateNames", int(w.get_value())))
        box.append(self._row("Truncate Names (chars)", trunc_spin))

        # Pirate names
        pn_sw = Gtk.Switch()
        pn_sw.set_active(bool(s.get("PirateNames", False)))
        pn_sw.set_valign(Gtk.Align.CENTER)
        pn_sw.connect("state-set", lambda w, v: self._track("PirateNames", v))
        box.append(self._row("Show Pirate Names", pn_sw))

        # Bounty value
        bv_sw = Gtk.Switch()
        bv_sw.set_active(bool(s.get("BountyValue", False)))
        bv_sw.set_valign(Gtk.Align.CENTER)
        bv_sw.connect("state-set", lambda w, v: self._track("BountyValue", v))
        box.append(self._row("Show Credit Value per Kill", bv_sw))

        # Bounty faction
        bf_sw = Gtk.Switch()
        bf_sw.set_active(bool(s.get("BountyFaction", False)))
        bf_sw.set_valign(Gtk.Align.CENTER)
        bf_sw.connect("state-set", lambda w, v: self._track("BountyFaction", v))
        box.append(self._row("Show Victim Faction per Kill", bf_sw))

        # Extended stats
        es_sw = Gtk.Switch()
        es_sw.set_active(bool(s.get("ExtendedStats", False)))
        es_sw.set_valign(Gtk.Align.CENTER)
        es_sw.connect("state-set", lambda w, v: self._track("ExtendedStats", v))
        box.append(self._row("Extended Kill Stats", es_sw))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self._section_label("Inactivity Alerts"))

        # WarnNoKills
        wnk_spin = Gtk.SpinButton.new_with_range(1, 120, 1)
        wnk_spin.set_value(int(s.get("WarnNoKills", 20)))
        wnk_spin.set_valign(Gtk.Align.CENTER)
        wnk_spin.connect("value-changed", lambda w: self._track("WarnNoKills", int(w.get_value())))
        box.append(self._row("Alert After N Minutes Without Kill", wnk_spin))

        # WarnKillRate
        wkr_spin = Gtk.SpinButton.new_with_range(1, 200, 1)
        wkr_spin.set_value(int(s.get("WarnKillRate", 20)))
        wkr_spin.set_valign(Gtk.Align.CENTER)
        wkr_spin.connect("value-changed", lambda w: self._track("WarnKillRate", int(w.get_value())))
        box.append(self._row("Alert When Kill Rate Below (kills/hr)", wkr_spin))

        # WarnCooldown
        wcd_spin = Gtk.SpinButton.new_with_range(1, 120, 1)
        wcd_spin.set_value(int(s.get("WarnCooldown", 15)))
        wcd_spin.set_valign(Gtk.Align.CENTER)
        wcd_spin.connect("value-changed", lambda w: self._track("WarnCooldown", int(w.get_value())))
        box.append(self._row("Alert Cooldown (minutes)", wcd_spin))

    # ── Notifications tab ─────────────────────────────────────────────────────

    def _build_notifications_tab(self, nb: Gtk.Notebook) -> None:
        box = self._tab(nb, "Notifications")
        levels = self._cfg.notify_levels

        box.append(self._section_label("Notification Levels"))

        note = Gtk.Label(label="0 = Off   1 = Terminal   2 = + Discord   3 = + Ping")
        note.set_xalign(0.0)
        note.add_css_class("prefs-note")
        box.append(note)

        for key, description in NOTIFY_EVENTS:
            spin = Gtk.SpinButton.new_with_range(0, 3, 1)
            spin.set_value(int(levels.get(key, 2)))
            spin.set_width_chars(2)
            spin.set_valign(Gtk.Align.CENTER)
            spin.connect("value-changed",
                         lambda w, k=key: self._track_notify(k, int(w.get_value())))
            box.append(self._row(description, spin))

    # ── Discord tab ───────────────────────────────────────────────────────────

    def _build_discord_tab(self, nb: Gtk.Notebook) -> None:
        box = self._tab(nb, "Discord")
        d   = self._cfg.discord_cfg

        box.append(self._section_label("Connection"))

        wh_entry = Gtk.Entry()
        wh_entry.set_text(d.get("WebhookURL", ""))
        wh_entry.set_hexpand(True)
        wh_entry.set_width_chars(32)
        wh_entry.set_visibility(False)   # treat as sensitive
        wh_entry.connect("changed", lambda w: self._track_discord("WebhookURL", w.get_text()))
        box.append(self._row("Webhook URL", wh_entry, restart_required=True))

        uid_entry = Gtk.Entry()
        uid_entry.set_text(str(d.get("UserID", 0)))
        uid_entry.set_width_chars(20)
        uid_entry.connect("changed", lambda w: self._track_discord("UserID", w.get_text()))
        box.append(self._row("User ID (for @mention)", uid_entry, restart_required=True))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self._section_label("Options"))

        for key, label, hot in [
            ("Identity",        "Use EDLD name and avatar",    False),
            ("PrependCmdrName", "Prefix messages with CMDR name", True),
            ("Timestamp",       "Append timestamp to messages", False),
            ("ForumChannel",    "Forum channel thread mode",    False),
            ("ThreadCmdrNames", "Use CMDR name as thread title", False),
        ]:
            sw = Gtk.Switch()
            sw.set_active(bool(d.get(key, False)))
            sw.set_valign(Gtk.Align.CENTER)
            sw.connect("state-set", lambda w, v, k=key: self._track_discord(k, v))
            box.append(self._row(label, sw, restart_required=not hot))

    # ── Appearance tab ────────────────────────────────────────────────────────

    def _build_appearance_tab(self, nb: Gtk.Notebook) -> None:
        box = self._tab(nb, "Appearance")
        current_theme = self._cfg.ui_cfg.get("Theme", "default")

        box.append(self._section_label("Theme"))

        note = Gtk.Label(label="Theme changes take effect on next launch.")
        note.set_xalign(0.0)
        note.add_css_class("prefs-note")
        box.append(note)

        combo = Gtk.ComboBoxText()
        for t in THEMES:
            combo.append_text(t)
        # Add any custom themes found on disk
        from gui.helpers import THEMES_DIR
        custom_dir = THEMES_DIR / "custom"
        if custom_dir.is_dir():
            for f in sorted(custom_dir.glob("*.css")):
                combo.append_text(f"custom/{f.stem}")

        # Select current
        all_themes = THEMES + [
            f"custom/{f.stem}"
            for f in sorted((THEMES_DIR / "custom").glob("*.css"))
            if (THEMES_DIR / "custom").is_dir()
        ]
        try:
            combo.set_active(all_themes.index(current_theme))
        except ValueError:
            combo.set_active(0)

        combo.connect("changed",
                      lambda w: self._track_gui("Theme", w.get_active_text() or "default"))
        box.append(self._row("Active Theme", combo, restart_required=True))

        box.append(self._section_label("Font"))

        font_note = Gtk.Label(label="Font changes take effect on next launch.")
        font_note.set_xalign(0.0)
        font_note.add_css_class("prefs-note")
        box.append(font_note)

        # Font family — monospace only
        current_family = self._cfg.ui_cfg.get("FontFamily", "JetBrains Mono")
        from gui.helpers import list_monospace_fonts
        mono_fonts = list_monospace_fonts()
        # Always include JetBrains Mono as the first option even if not yet
        # installed (install.sh may not have run yet on this machine).
        if "JetBrains Mono" not in mono_fonts:
            mono_fonts = ["JetBrains Mono"] + mono_fonts

        family_combo = Gtk.ComboBoxText()
        for fam in mono_fonts:
            family_combo.append_text(fam)
        try:
            family_combo.set_active(mono_fonts.index(current_family))
        except ValueError:
            family_combo.set_active(0)
        family_combo.connect(
            "changed",
            lambda w: self._track_gui("FontFamily", w.get_active_text() or "JetBrains Mono"),
        )
        box.append(self._row("Font Family", family_combo, restart_required=True))

        # Font size
        current_font_size = self._cfg.ui_cfg.get("FontSize", 14)
        font_spin = Gtk.SpinButton.new_with_range(10, 24, 1)
        font_spin.set_value(current_font_size)
        font_spin.connect("value-changed",
                          lambda w: self._track_gui("FontSize", int(w.get_value())))
        box.append(self._row("Font Size (px)", font_spin, restart_required=True))

    # ── Change tracking ───────────────────────────────────────────────────────
    #
    # RESTART_REQUIRED keys — must match restart_required=True in the tab builders.
    # Any change to these triggers os.execv on Apply.
    #
    _RESTART_KEYS: dict[str, set[str]] = {
        "Settings": {"JournalFolder"},
        "Discord":  {"WebhookURL", "UserID", "Identity",
                     "ForumChannel", "ThreadCmdrNames", "Timestamp"},
        "UI":       {"Theme", "FontSize"},
        "EDDN":     {"Enabled", "UploaderID", "TestMode"},
        "EDSM":     {"Enabled", "CommanderName", "ApiKey"},
        "EDAstro":  {"Enabled", "UploadCarrierEvents"},
        "Inara":    {"Enabled", "ApiKey", "CommanderName"},
        "CAPI":     set(),   # no restart-required keys; managed live
    }

    def _record(self, section: str, key: str, value) -> None:
        """Route a change to _restart or _hot depending on the key."""
        if key in self._RESTART_KEYS.get(section, set()):
            self._restart.setdefault(section, {})[key] = value
            if self._restart_banner:
                self._restart_banner.set_revealed(True)
        else:
            self._hot.setdefault(section, {})[key] = value

    def _track(self, key: str, value) -> None:
        self._record("Settings", key, value)

    def _track_notify(self, key: str, value: int) -> None:
        self._record("LogLevels", key, value)

    def _track_discord(self, key: str, value) -> None:
        self._record("Discord", key, value)

    def _track_gui(self, key: str, value) -> None:
        self._record("UI", key, value)

    def _track_eddn(self, key: str, value) -> None:
        self._record("EDDN", key, value)

    def _track_edsm(self, key: str, value) -> None:
        self._record("EDSM", key, value)

    def _track_edastro(self, key: str, value) -> None:
        self._record("EDAstro", key, value)

    def _track_inara(self, key: str, value) -> None:
        self._record("Inara", key, value)

    def _track_capi(self, key: str, value) -> None:
        self._record("CAPI", key, value)

    # ── Data & Integrations tab ───────────────────────────────────────────────

    def _build_data_tab(self, nb: Gtk.Notebook) -> None:
        box = self._tab(nb, "Data & Integrations")

        note = Gtk.Label(
            label="These settings require a restart to take effect.  ⚠ will confirm."
        )
        note.set_xalign(0.0)
        note.add_css_class("prefs-note")
        box.append(note)

        # ── CAPI (top — primary data provider) ───────────────────────────────
        self._build_capi_section(box)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── EDDN ─────────────────────────────────────────────────────────────
        box.append(self._section_label("EDDN  (Elite Dangerous Data Network)"))

        eddn_note = Gtk.Label(
            label="Contribute exploration, market, and outfitting data to the\n"
                  "shared EDDN network used by third-party tools and sites."
        )
        eddn_note.set_xalign(0.0)
        eddn_note.add_css_class("prefs-note")
        box.append(eddn_note)

        eddn_cfg = self._cfg.eddn_cfg

        eddn_sw = Gtk.Switch()
        eddn_sw.set_active(bool(eddn_cfg.get("Enabled", False)))
        eddn_sw.set_valign(Gtk.Align.CENTER)
        eddn_sw.connect("state-set", lambda w, v: self._track_eddn("Enabled", v))
        box.append(self._row("Enable EDDN", eddn_sw, restart_required=True))

        uploader_entry = Gtk.Entry()
        uploader_entry.set_text(eddn_cfg.get("UploaderID", ""))
        uploader_entry.set_hexpand(True)
        uploader_entry.set_width_chars(24)
        uploader_entry.set_placeholder_text("defaults to commander name")
        uploader_entry.connect(
            "changed", lambda w: self._track_eddn("UploaderID", w.get_text())
        )
        box.append(self._row("Uploader ID", uploader_entry, restart_required=True))

        eddn_test_sw = Gtk.Switch()
        eddn_test_sw.set_active(bool(eddn_cfg.get("TestMode", False)))
        eddn_test_sw.set_valign(Gtk.Align.CENTER)
        eddn_test_sw.connect("state-set", lambda w, v: self._track_eddn("TestMode", v))
        box.append(self._row("Test Mode (sends to /test schemas)", eddn_test_sw,
                              restart_required=True))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── EDSM ─────────────────────────────────────────────────────────────
        box.append(self._section_label("EDSM  (Elite Dangerous Star Map)"))

        edsm_note = Gtk.Label(
            label="Upload your flight log and discoveries to edsm.net.\n"
                  "Requires an EDSM account.  Generate your API key at:\n"
                  "https://www.edsm.net/en/settings/api"
        )
        edsm_note.set_xalign(0.0)
        edsm_note.add_css_class("prefs-note")
        box.append(edsm_note)

        edsm_cfg = self._cfg.edsm_cfg

        edsm_sw = Gtk.Switch()
        edsm_sw.set_active(bool(edsm_cfg.get("Enabled", False)))
        edsm_sw.set_valign(Gtk.Align.CENTER)
        edsm_sw.connect("state-set", lambda w, v: self._track_edsm("Enabled", v))
        box.append(self._row("Enable EDSM", edsm_sw, restart_required=True))

        cmdr_entry = Gtk.Entry()
        cmdr_entry.set_text(edsm_cfg.get("CommanderName", ""))
        cmdr_entry.set_hexpand(True)
        cmdr_entry.set_width_chars(24)
        cmdr_entry.set_placeholder_text("your EDSM commander name")
        cmdr_entry.connect(
            "changed", lambda w: self._track_edsm("CommanderName", w.get_text())
        )
        box.append(self._row("EDSM Commander Name", cmdr_entry, restart_required=True))

        edsm_key_entry = Gtk.Entry()
        edsm_key_entry.set_text(edsm_cfg.get("ApiKey", ""))
        edsm_key_entry.set_hexpand(True)
        edsm_key_entry.set_width_chars(24)
        edsm_key_entry.set_visibility(False)
        edsm_key_entry.set_placeholder_text("your EDSM API key")
        edsm_key_entry.connect(
            "changed", lambda w: self._track_edsm("ApiKey", w.get_text())
        )
        box.append(self._row("EDSM API Key", edsm_key_entry, restart_required=True))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── EDAstro ───────────────────────────────────────────────────────────
        box.append(self._section_label("EDAstro"))

        edastro_note = Gtk.Label(
            label="Upload exploration, carrier, and Odyssey data to edastro.com.\n"
                  "Anonymous — no account or API key required."
        )
        edastro_note.set_xalign(0.0)
        edastro_note.add_css_class("prefs-note")
        box.append(edastro_note)

        edastro_cfg = self._cfg.edastro_cfg

        edastro_sw = Gtk.Switch()
        edastro_sw.set_active(bool(edastro_cfg.get("Enabled", False)))
        edastro_sw.set_valign(Gtk.Align.CENTER)
        edastro_sw.connect("state-set", lambda w, v: self._track_edastro("Enabled", v))
        box.append(self._row("Enable EDAstro", edastro_sw, restart_required=True))

        carrier_sw = Gtk.Switch()
        carrier_sw.set_active(bool(edastro_cfg.get("UploadCarrierEvents", False)))
        carrier_sw.set_valign(Gtk.Align.CENTER)
        carrier_sw.connect(
            "state-set", lambda w, v: self._track_edastro("UploadCarrierEvents", v)
        )
        box.append(self._row(
            "Include Carrier Events  (shares carrier location)",
            carrier_sw,
            restart_required=True,
        ))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Inara ─────────────────────────────────────────────────────────────
        box.append(self._section_label("Inara"))

        inara_note = Gtk.Label(
            label="Update your Inara profile with flight log, ranks, credits,\n"
                  "missions, and ship loadout.  Requires an Inara account.\n"
                  "Get your API key at:  inara.cz  → Settings → API"
        )
        inara_note.set_xalign(0.0)
        inara_note.add_css_class("prefs-note")
        box.append(inara_note)

        inara_cfg = self._cfg.inara_cfg

        inara_sw = Gtk.Switch()
        inara_sw.set_active(bool(inara_cfg.get("Enabled", False)))
        inara_sw.set_valign(Gtk.Align.CENTER)
        inara_sw.connect("state-set", lambda w, v: self._track_inara("Enabled", v))
        box.append(self._row("Enable Inara", inara_sw, restart_required=True))

        inara_cmdr_entry = Gtk.Entry()
        inara_cmdr_entry.set_text(inara_cfg.get("CommanderName", ""))
        inara_cmdr_entry.set_hexpand(True)
        inara_cmdr_entry.set_width_chars(24)
        inara_cmdr_entry.set_placeholder_text("your in-game commander name")
        inara_cmdr_entry.connect(
            "changed", lambda w: self._track_inara("CommanderName", w.get_text().strip())
        )
        box.append(self._row("Commander Name", inara_cmdr_entry, restart_required=True))

        inara_key_entry = Gtk.Entry()
        inara_key_entry.set_text(inara_cfg.get("ApiKey", ""))
        inara_key_entry.set_hexpand(True)
        inara_key_entry.set_width_chars(24)
        inara_key_entry.set_visibility(False)
        inara_key_entry.set_placeholder_text("your Inara API key")
        inara_key_entry.connect(
            "changed", lambda w: self._track_inara("ApiKey", w.get_text().strip())
        )
        box.append(self._row("Inara API Key", inara_key_entry, restart_required=True))

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Raven Colonial ────────────────────────────────────────────────────
        box.append(self._section_label("Raven Colonial"))

        raven_note = Gtk.Label(
            label="Sync colonisation construction progress to ravencolonial.com\n"
                  "so other commanders can see your project's live supply needs.\n"
                  "Get your API key at:  ravencolonial.com  → Account Settings"
        )
        raven_note.set_xalign(0.0)
        raven_note.add_css_class("prefs-note")
        box.append(raven_note)

        colon_cfg = self._cfg.colonisation_cfg

        raven_key_entry = Gtk.Entry()
        raven_key_entry.set_text(colon_cfg.get("ApiKey", ""))
        raven_key_entry.set_hexpand(True)
        raven_key_entry.set_width_chars(24)
        raven_key_entry.set_visibility(False)
        raven_key_entry.set_placeholder_text("your Raven Colonial API key (optional)")
        raven_key_entry.connect(
            "changed",
            lambda w: self._record("Colonisation", "ApiKey", w.get_text().strip()),
        )
        box.append(self._row("Raven Colonial API Key", raven_key_entry))

    # ── CAPI section ─────────────────────────────────────────────────────────

    def _build_capi_section(self, box: "Gtk.Box") -> None:
        """Frontier Companion API auth UI — Connect button + status row."""
        box.append(self._section_label("Frontier CAPI"))

        note = Gtk.Label(
            label=(
                "Provides authoritative fleet data directly from Frontier.\n"
                "Authenticates via your Frontier account in a browser window.\n"
                "Tokens are stored locally and never sent anywhere else."
            )
        )
        note.set_xalign(0.0)
        note.set_wrap(True)
        note.add_css_class("prefs-note")
        box.append(note)

        # Status label — updated live by _capi_refresh_status()
        self._capi_status_lbl = Gtk.Label(label="Checking…")
        self._capi_status_lbl.set_xalign(0.0)
        self._capi_status_lbl.add_css_class("prefs-note")

        # Connect / Disconnect button
        self._capi_btn = Gtk.Button(label="Connect")
        self._capi_btn.set_valign(Gtk.Align.CENTER)
        self._capi_btn.connect("clicked", self._on_capi_connect)

        # Disconnect button (shown when connected)
        self._capi_disc_btn = Gtk.Button(label="Disconnect")
        self._capi_disc_btn.set_valign(Gtk.Align.CENTER)
        self._capi_disc_btn.add_css_class("destructive-action")
        self._capi_disc_btn.connect("clicked", self._on_capi_disconnect)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.append(self._capi_btn)
        btn_box.append(self._capi_disc_btn)
        btn_box.set_valign(Gtk.Align.CENTER)

        box.append(self._row("Status", self._capi_status_lbl))
        box.append(self._row("Account", btn_box))

        # Poll status once now, then schedule periodic refresh while window is open
        self._capi_refresh_status()
        GLib.timeout_add(2000, self._capi_poll_status)

    def _capi_provider(self):
        """Return core.data.capi if available, else None."""
        try:
            dp = getattr(self._core, "data", None)
            return dp.capi if dp else None
        except Exception:
            return None

    def _capi_refresh_status(self) -> None:
        """Pull current auth status from DataProvider.capi and update labels."""
        import time, datetime
        capi = self._capi_provider()

        if capi is None:
            self._capi_status_lbl.set_label("Data provider not available")
            self._capi_btn.set_sensitive(False)
            self._capi_disc_btn.set_visible(False)
            return

        status    = capi.auth_status()
        connected = status.get("connected", False)
        cmdr      = status.get("cmdr")
        expiry    = status.get("expiry")
        result    = status.get("auth_result")

        if result == "auth_running":
            self._capi_status_lbl.set_label("Waiting for browser authentication…")
            self._capi_btn.set_sensitive(False)
            self._capi_disc_btn.set_visible(False)
        elif connected:
            exp_str = ""
            if expiry:
                mins = max(0, int((expiry - time.time()) / 60))
                exp_str = f"  (token refreshes in {mins}m)"
            last_ep = capi.last_poll("profile")
            last_str = ""
            if last_ep:
                t = datetime.datetime.fromtimestamp(last_ep).strftime("%H:%M:%S")
                last_str = f"  ·  last poll {t}"
            lbl = f"Connected{(' — CMDR ' + cmdr) if cmdr else ''}{exp_str}{last_str}"
            self._capi_status_lbl.set_label(lbl)
            self._capi_btn.set_label("Re-authenticate")
            self._capi_btn.set_sensitive(True)
            self._capi_disc_btn.set_visible(True)
        else:
            self._capi_status_lbl.set_label("Not connected")
            self._capi_btn.set_label("Connect")
            self._capi_btn.set_sensitive(True)
            self._capi_disc_btn.set_visible(False)

    def _capi_poll_status(self) -> bool:
        """GLib timer callback — refresh status every 2 s while window is open."""
        try:
            if self.get_visible():
                self._capi_refresh_status()
                return True   # keep timer running
        except Exception:
            pass
        return False   # window gone, stop timer

    def _on_capi_connect(self, *_) -> None:
        capi = self._capi_provider()
        if capi:
            capi._auth_result = "auth_running"
            capi.authenticate()
            self._capi_btn.set_sensitive(False)
            self._capi_status_lbl.set_label("Waiting for browser authentication…")

    def _on_capi_disconnect(self, *_) -> None:
        capi = self._capi_provider()
        if capi:
            capi.disconnect()
        self._capi_refresh_status()

    # ── Apply & Save ──────────────────────────────────────────────────────────

    def _on_apply(self, *_) -> None:
        """Write all pending changes to config.toml.

        Hot changes take effect immediately via cfg.refresh().
        Restart-required changes trigger os.execv with the original launch argv
        so the new process inherits the same flags (-g, -p, etc.).
        """
        import os

        all_changes: dict = {}
        for section, kvs in {**self._hot, **self._restart}.items():
            all_changes.setdefault(section, {}).update(kvs)

        if not all_changes:
            self.close()
            return

        config_path = self._cfg.config_path
        try:
            raw = config_path.read_text(encoding="utf-8")
            config = tomllib.loads(raw)
        except Exception as e:
            self._show_error(f"Could not read config.toml:\n{e}")
            return

        # Merge into the active profile section if one is set, otherwise global
        profile = self._cfg.config_profile
        for section, kvs in all_changes.items():
            if profile:
                # Write into [PROFILE.Section] — create both levels if needed
                profile_dict = config.setdefault(profile, {})
                target = profile_dict.setdefault(section, {})
            else:
                target = config.setdefault(section, {})
            for k, v in kvs.items():
                if k == "UserID":
                    try: v = int(v)
                    except (ValueError, TypeError): v = 0
                target[k] = v

        try:
            new_toml = config_to_toml(config)
            config_path.write_text(new_toml, encoding="utf-8")
        except Exception as e:
            self._show_error(f"Could not write config.toml:\n{e}")
            return

        needs_restart = bool(self._restart)

        self._hot.clear()
        self._restart.clear()

        if needs_restart:
            # Restart the entire process with identical launch arguments.
            # os.execv replaces this process in-place; the new instance reads
            # the freshly written config and picks up all changes cleanly.
            import sys as _sys
            launch_argv = getattr(self._core, "launch_argv", None) or _sys.argv
            python = _sys.executable
            # launch_argv[0] is the script path (e.g. edld.py); must be kept
            # as the first argument after the interpreter, not dropped.
            # Correct form: execv(python, [python, edld.py, -g, -p, EDP1, ...])
            os.execv(python, [python] + list(launch_argv))
        else:
            # Hot-reload only — no restart needed
            try:
                self._cfg.refresh(terminal_print=False)
            except Exception:
                pass
            self.close()

    def _show_error(self, msg: str) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=msg,
        )
        dlg.connect("response", lambda d, *_: d.close())
        dlg.present()


# ── Restart helper ────────────────────────────────────────────────────────────

def import_python_executable() -> str:
    """Return the Python interpreter path for os.execv restart."""
    import sys
    return sys.executable


# ── TOML writer ──────────────────────────────────────────────────────────────

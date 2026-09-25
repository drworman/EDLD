"""
components/server.py — the Server tab in Preferences, for the EDAM client.

The same page in the terminal dashboard and the desktop window: the server's
settings, what it is doing right now, the paired devices, and a button that
shows a pairing QR code.  Pairing here and ``edld --pair`` share one
implementation (core.server.cli.new_pairing), so all three show the same code
the same way.

The server itself is started by edld.py once the journal bootstrap is done,
and handed to CoreAPI as ``core.server``.  This component only looks at it; it
works with the server off too, since pairing tickets and the device list are
files — a code shown while the server is off is still good once it starts.
"""

from __future__ import annotations

from pathlib import Path

from core.config import CFG_DEFAULTS_SERVER
from core.plugin_loader import BasePlugin

#: Widget id -> (section, key, type), for the TUI's save path.  The GUI records
#: the same keys through the dialog's own helpers.
_BINDINGS = {
    "srv-enabled":     ("Server", "Enabled",         bool),
    "srv-port":        ("Server", "Port",            int),
    "srv-bind":        ("Server", "BindAddress",     str),
    "srv-external":    ("Server", "ExternalHost",    str),
    "srv-allow-end":   ("Server", "AllowEndSession", bool),
    "srv-portmap":     ("Server", "PortMapping",     bool),
    "srv-duck-domain": ("Server", "DuckDNSDomain",   str),
    "srv-duck-token":  ("Server", "DuckDNSToken",    str),
}

_NOTE = ("Changes to these settings take effect when EDLD restarts. "
         "Pairing and unpairing take effect at once.")


class ServerPlugin(BasePlugin):
    PLUGIN_NAME        = "server"
    PLUGIN_DISPLAY     = "Server (EDAM)"
    PLUGIN_VERSION     = "0.1"
    PLUGIN_DESCRIPTION = "Serve paired EDAM phones and tablets"
    SUBSCRIBED_EVENTS: list[str] = []

    # ── what the pages read ───────────────────────────────────────────────────

    def _settings(self) -> dict:
        return self.core.load_setting("Server", CFG_DEFAULTS_SERVER, warn=False)

    def _directory(self) -> Path:
        d = getattr(self.core, "server_dir", None)
        if d:
            return Path(d)
        from core.state import EDLD_DATA_DIR
        profile = getattr(getattr(self.core, "cfg", None), "config_profile", None)
        return EDLD_DATA_DIR / "server" / (profile or "default")

    def _name(self) -> str:
        n = getattr(self.core, "server_name", None)
        if n:
            return n
        from core.server.identity import default_server_name
        return default_server_name(None)

    def status_lines(self) -> list[str]:
        srv = getattr(self.core, "server", None)
        if srv is not None:
            try:
                return srv.status_lines()
            except Exception as exc:
                return [f"Status unavailable: {type(exc).__name__}: {exc}"]
        if self._settings().get("Enabled"):
            return ["Server is enabled but not running — see the Alerts pane "
                    "or the log for why."]
        return ["Server is off. Turn it on below and restart EDLD, or start "
                "EDLD with -s."]

    def devices(self) -> list[dict]:
        from core.server.pairing import DeviceRegistry
        return DeviceRegistry(self._directory()).all()

    def device_lines(self) -> list[str]:
        from core.server.identity import short_id
        devs = self.devices()
        if not devs:
            return ["No paired devices."]
        return [f"{short_id(d['fingerprint'])}  {d.get('name', '')}  "
                f"(last seen {str(d.get('lastSeen', '?'))[:16].replace('T', ' ')})"
                for d in devs]

    # ── actions, shared by both pages ─────────────────────────────────────────

    def pair(self, external: str | None = None):
        from core.server.cli import new_pairing
        settings = dict(self._settings())
        return new_pairing(self._directory(), settings, self._name(),
                           external=external, write_png=False)

    def unpair(self, ident: str) -> str:
        from core.server.identity import short_id
        from core.server.pairing import DeviceRegistry
        ident = (ident or "").strip()
        if not ident:
            return "Enter the ID shown in the device list."
        gone = DeviceRegistry(self._directory()).remove(ident)
        if gone is None:
            return f"No single paired device matches {ident!r}."
        return (f"Unpaired {gone.get('name')} ({short_id(gone['fingerprint'])}). "
                f"It is disconnected within a few seconds.")

    # ── TUI ───────────────────────────────────────────────────────────────────

    def preferences_bindings(self) -> dict:
        return dict(_BINDINGS)

    def preferences_action(self, bid: str, values: dict | None = None) -> str | None:
        from rich.markup import escape
        values = values or {}
        if bid == "btn-srv-pair":
            try:
                info = self.pair(external=values.get("srv-external"))
            except Exception as exc:
                return escape(f"Could not open pairing: {type(exc).__name__}: {exc}")
            qr = info.qr_text() or "(install segno to see a QR code here)"
            return escape(
                f"{qr}\n"
                f"Code {info.code} — valid until {info.until}, one use\n"
                f"Addresses: {', '.join(info.hosts) or '(none found)'}\n"
                f"In EDAM: Add computer → scan this, or paste:\n{info.link}")
        if bid == "btn-srv-refresh":
            return escape("\n".join(self.status_lines() + [""] + self.device_lines()))
        if bid == "btn-srv-unpair":
            return escape(self.unpair(values.get("srv-unpair-id", "")))
        return None

    def tui_preferences_tab(self):
        s = self._settings()

        def _compose():
            from rich.markup import escape
            from textual.containers import Horizontal
            from textual.widgets import Button, Input, Label, Select

            bools = [("Off", "false"), ("On", "true")]

            def b(v):
                return "true" if v else "false"

            yield Label("STATUS", classes="pref-section")
            yield Label(escape("\n".join(self.status_lines())), id="btn-srv-refresh-result")
            yield Label("PAIRED DEVICES", classes="pref-section")
            yield Label(escape("\n".join(self.device_lines())))
            with Horizontal(classes="pref-row"):
                yield Button("Refresh", id="btn-srv-refresh")
                yield Input(placeholder="device ID", id="srv-unpair-id",
                            classes="pref-input")
                yield Button("Unpair", id="btn-srv-unpair")
            yield Label("", id="btn-srv-unpair-result")

            yield Label("PAIR A DEVICE", classes="pref-section")
            yield Button("Show pairing code", id="btn-srv-pair")
            yield Label("", id="btn-srv-pair-result")

            yield Label("SETTINGS", classes="pref-section")
            for wid, label, kind in (
                ("srv-enabled",     "Run the server",               "bool"),
                ("srv-port",        "Port",                         "text"),
                ("srv-bind",        "Bind address (blank: all)",    "text"),
                ("srv-external",    "Address away from home",       "text"),
                ("srv-portmap",     "Forward the port (UPnP/NAT-PMP)", "bool"),
                ("srv-duck-domain", "DuckDNS domain",               "text"),
                ("srv-duck-token",  "DuckDNS token",                "secret"),
                ("srv-allow-end",   "Devices may end the session (Solo)", "bool"),
            ):
                key = _BINDINGS[wid][1]
                with Horizontal(classes="pref-row"):
                    yield Label(label, classes="key")
                    if kind == "bool":
                        yield Select(bools, value=b(s.get(key)), id=wid,
                                     classes="pref-bool-sel", allow_blank=False)
                    else:
                        yield Input(value=str(s.get(key, "")), id=wid,
                                    classes="pref-input", password=kind == "secret")
            yield Label(_NOTE)

        return ("pref-tab-server", "Server", _compose)

    # ── GUI ───────────────────────────────────────────────────────────────────

    def gui_preferences_tab(self):
        # Discovery takes no arguments; only the builder receives the dialog.
        def _build(dlg):
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QPixmap
            from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel,
                                           QLineEdit, QListWidget, QPushButton,
                                           QScrollArea, QVBoxLayout, QWidget)

            s = self._settings()
            page = QScrollArea()
            page.setWidgetResizable(True)
            page.setFrameShape(QScrollArea.NoFrame)
            content = QWidget()
            page.setWidget(content)
            lay = QVBoxLayout(content)
            lay.setContentsMargins(10, 10, 10, 10)
            lay.setSpacing(6)

            def section(title: str) -> None:
                lbl = QLabel(title)
                lbl.setProperty("role", "section")
                lay.addWidget(lbl)

            section("Status")
            status = QLabel("\n".join(self.status_lines()))
            status.setWordWrap(True)
            lay.addWidget(status)

            section("Paired devices")
            devices = QListWidget()
            devices.setMaximumHeight(120)
            lay.addWidget(devices)
            row = QHBoxLayout()
            refresh_btn = QPushButton("Refresh")
            unpair_btn = QPushButton("Unpair selected")
            row.addWidget(refresh_btn)
            row.addWidget(unpair_btn)
            row.addStretch(1)
            lay.addLayout(row)
            result = QLabel("")
            result.setWordWrap(True)
            lay.addWidget(result)

            def refresh() -> None:
                status.setText("\n".join(self.status_lines()))
                devices.clear()
                from core.server.identity import short_id
                for d in self.devices():
                    devices.addItem(f"{short_id(d['fingerprint'])}  {d.get('name', '')}"
                                    f"  (last seen {str(d.get('lastSeen', '?'))[:16].replace('T', ' ')})")

            def unpair() -> None:
                item = devices.currentItem()
                if item is None:
                    result.setText("Select a device first.")
                    return
                result.setText(self.unpair(item.text().split()[0]))
                refresh()

            refresh_btn.clicked.connect(refresh)
            unpair_btn.clicked.connect(unpair)
            refresh()

            section("Pair a device")
            pair_btn = QPushButton("Show pairing code")
            lay.addWidget(pair_btn)
            qr = QLabel()
            qr.setAlignment(Qt.AlignCenter)
            lay.addWidget(qr)
            details = QLabel("")
            details.setWordWrap(True)
            details.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(details)

            form_holder = QWidget()
            form = QFormLayout(form_holder)
            external_edit: QLineEdit = dlg._text_edit(
                s.get("ExternalHost", ""), "Server", "ExternalHost", str,
                placeholder="yourname.duckdns.org")

            def show_pairing() -> None:
                try:
                    info = self.pair(external=external_edit.text())
                except Exception as exc:
                    details.setText(f"Could not open pairing: {type(exc).__name__}: {exc}")
                    return
                png = info.qr_png_bytes(scale=6)
                pix = QPixmap()
                if png and pix.loadFromData(png, "PNG"):
                    qr.setPixmap(pix)
                else:
                    qr.setText("(install segno to see a QR code here)")
                details.setText(
                    f"Code {info.code} — valid until {info.until}, one use\n"
                    f"Addresses: {', '.join(info.hosts) or '(none found)'}\n"
                    f"In EDAM: Add computer → scan this, or paste:\n{info.link}")

            pair_btn.clicked.connect(show_pairing)

            section("Settings")
            lay.addWidget(form_holder)
            form.addRow("Run the server",
                        dlg._bool_combo(bool(s.get("Enabled")), "Server", "Enabled"))
            form.addRow("Port", dlg._text_edit(s.get("Port", 28510), "Server", "Port", int))
            form.addRow("Bind address (blank: all)",
                        dlg._text_edit(s.get("BindAddress", ""), "Server", "BindAddress", str))
            form.addRow("Address away from home", external_edit)
            form.addRow("Forward the port (UPnP/NAT-PMP)",
                        dlg._bool_combo(bool(s.get("PortMapping")), "Server", "PortMapping"))
            form.addRow("DuckDNS domain",
                        dlg._text_edit(s.get("DuckDNSDomain", ""), "Server",
                                       "DuckDNSDomain", str, placeholder="yourname"))
            form.addRow("DuckDNS token",
                        dlg._text_edit(s.get("DuckDNSToken", ""), "Server",
                                       "DuckDNSToken", str, password=True))
            form.addRow("Devices may end the session (Solo)",
                        dlg._bool_combo(bool(s.get("AllowEndSession")), "Server",
                                        "AllowEndSession"))
            note = QLabel(_NOTE)
            note.setWordWrap(True)
            note.setProperty("role", "dim")
            lay.addWidget(note)
            lay.addStretch(1)
            return page

        return ("pref-tab-server", "Server", _build)

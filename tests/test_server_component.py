"""
tests/test_server_component.py — the Server preferences page, in both front ends.

The contract checks mirror tests/test_preferences_contract.py for this
component: a builder call the real dialog would reject is swallowed by the tab
loop and the page silently does not exist.  Then both pages are actually built
— the Textual one mounted in an app, the Qt one offscreen — and the pairing
button is pressed, because a page that composes but whose button throws is the
same silent failure one click later.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("cryptography")

from core.config import CFG_DEFAULTS_SERVER  # noqa: E402
from core.server import pairing  # noqa: E402
from components.server import ServerPlugin, _BINDINGS  # noqa: E402
from tests.test_preferences_contract import _signature_of  # noqa: E402

SRC = ROOT / "components" / "server.py"


def _plugin(tmp_path, **settings):
    cfg = {**CFG_DEFAULTS_SERVER, "BindAddress": "192.168.1.20", **settings}
    core = SimpleNamespace(
        load_setting=lambda section, defaults, warn=True, include_extra=False: dict(cfg),
        server_dir=tmp_path / "server", server_name="EDLD test", server=None,
    )
    p = ServerPlugin()
    p.core = core
    return p


# ── contract ──────────────────────────────────────────────────────────────────

def test_bindings_cover_every_server_setting():
    assert {k for _s, k, _t in _BINDINGS.values()} == set(CFG_DEFAULTS_SERVER)
    assert all(s == "Server" for s, _k, _t in _BINDINGS.values())


def test_gui_builder_calls_bind_against_the_real_helpers():
    gui = ROOT / "gui" / "preferences.py"
    sigs = {n: _signature_of(gui, f"PreferencesDialog.{n}")
            for n in ("_bool_combo", "_text_edit")}
    checked = 0
    for node in ast.walk(ast.parse(SRC.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in sigs and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "dlg":
            sigs[node.func.attr].bind(*[None] * len(node.args),
                                      **{k.arg: None for k in node.keywords if k.arg})
            checked += 1
    assert checked == 8


def test_tabs_are_discoverable_without_arguments():
    p = ServerPlugin()
    p.core = SimpleNamespace(load_setting=lambda *a, **k: dict(CFG_DEFAULTS_SERVER))
    assert p.gui_preferences_tab()[0] == p.tui_preferences_tab()[0] == "pref-tab-server"


# ── actions ───────────────────────────────────────────────────────────────────

def test_pair_action_opens_a_ticket_the_link_matches(tmp_path):
    p = _plugin(tmp_path, ExternalHost="cmdr.duckdns.org")
    out = p.preferences_action("btn-srv-pair", {"srv-external": "cmdr.duckdns.org"})
    assert "cmdr.duckdns.org:28510" in out and "192.168.1.20:28510" in out
    link = out.strip().splitlines()[-1]
    code = link.split("&c=")[1].split("&")[0]
    assert pairing.check_ticket(tmp_path / "server", code) == (True, "")


def test_unsaved_external_address_is_used(tmp_path):
    p = _plugin(tmp_path)
    out = p.preferences_action("btn-srv-pair", {"srv-external": "typed.example:443"})
    assert "typed.example:443" in out


def test_duckdns_name_is_the_fallback_address(tmp_path):
    p = _plugin(tmp_path, DuckDNSDomain="cmdr")
    assert "cmdr.duckdns.org:28510" in p.pair().hosts


def test_ipv6_address_survives_rich_markup(tmp_path):
    p = _plugin(tmp_path, BindAddress="2001:db8::5")
    out = p.preferences_action("btn-srv-pair", {})
    from rich.text import Text
    # What the Label will actually show once Rich has read it as markup.
    assert "[2001:db8::5]:28510" in Text.from_markup(out).plain


def test_unpair_and_refresh(tmp_path):
    p = _plugin(tmp_path)
    reg = pairing.DeviceRegistry(tmp_path / "server")
    reg.add("hNzebMq-rest", "Y2VydA==", "Pixel")
    assert "Pixel" in p.preferences_action("btn-srv-refresh", {})
    assert "Server is off" in p.preferences_action("btn-srv-refresh", {})
    assert "Unpaired Pixel" in p.preferences_action("btn-srv-unpair",
                                                    {"srv-unpair-id": "hNzeb"})
    assert "No paired devices" in p.preferences_action("btn-srv-refresh", {})
    assert p.preferences_action("btn-something-else", {}) is None


# ── the pages, built for real ─────────────────────────────────────────────────

def test_tui_page_composes(tmp_path):
    pytest.importorskip("textual")
    from textual.app import App
    from textual.containers import VerticalScroll
    from textual.widgets import Button, Input, Select

    p = _plugin(tmp_path)
    _id, _label, compose = p.tui_preferences_tab()

    class Host(App):
        def compose(self):
            with VerticalScroll():
                yield from compose()

    async def run():
        app = Host()
        async with app.run_test() as pilot:
            ids = {w.id for w in app.query(Input)} | {w.id for w in app.query(Select)}
            assert set(_BINDINGS) <= ids
            assert app.query_one("#srv-duck-token", Input).password
            assert app.query_one("#btn-srv-pair", Button)
            await pilot.pause()

    asyncio.run(run())


def test_gui_page_builds_and_pairs(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from gui.preferences import PreferencesDialog

    app = QApplication.instance() or QApplication([])
    recorded = {}

    class Dlg:
        _bool_combo = PreferencesDialog._bool_combo
        _text_edit = PreferencesDialog._text_edit

        def _record(self, section, key, value):
            recorded[(section, key)] = value

    p = _plugin(tmp_path)
    page = p.gui_preferences_tab()[2](Dlg())
    btn = next(b for b in page.findChildren(QPushButton) if b.text() == "Show pairing code")
    btn.click()
    app.processEvents()
    pix = [l for l in page.findChildren(QLabel) if l.pixmap() and not l.pixmap().isNull()]
    assert pix, "the QR code was not drawn"
    assert any("valid until" in l.text() for l in page.findChildren(QLabel))
    assert (tmp_path / "server" / pairing.TICKET_FILE).exists()

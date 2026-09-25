"""
tests/test_deposit_screen.py — the deposit window actually mounts.

Textual validates a Select's value when the widget mounts, not when it is
constructed. A bad value therefore raises nothing at build time and then throws
inside a mount handler, where an unhandled exception takes the whole
application down — so a broken field presented as EDLD vanishing on a keypress.

Every field is blank on a new deposit, which made that certain the first time
anyone pressed Ctrl+D on unrecorded ground. Constructing the screen is not
enough to catch it; these tests run it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("textual")

from core.deposit_form import FIELDS, prefill

STORED = {"commodity": "helium3", "commodity_display": "Helium-3",
          "amount": "High", "density_observed": "Medium",
          "rigs": 4, "signal_no": 3, "is_test": 1}


class _Plugin:
    def __init__(self, form, heading):
        self._form, self._heading = form, heading
        self.submitted = None

    def form_for_here(self):
        return self._form, self._heading

    def submit_form(self, values):
        self.submitted = values
        return "updated abc123def456"


def _mount(form, heading):
    """Push the screen in a headless app and return the plugin it was given."""
    from textual.app import App

    from tui.deposit_screen import DepositScreen

    plugin = _Plugin(form, heading)

    class _Harness(App):
        def on_mount(self) -> None:
            self.push_screen(DepositScreen(None, plugin))

    async def run():
        app = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            return app.screen

    asyncio.run(run())
    return plugin


def test_the_window_mounts_for_a_new_deposit():
    """Every field blank — the case that crashed."""
    _mount(prefill(None), "New deposit at 1.00000, 2.00000")


def test_the_window_mounts_for_an_existing_deposit():
    _mount(prefill(STORED), "Editing Helium-3 (abc123def456)")


def test_the_window_mounts_with_a_partially_filled_deposit():
    """A real deposit usually has some fields and not others; a blank choice
    beside a filled one is the mix most likely to be hit."""
    partial = dict(STORED)
    partial.update(amount="", density_observed="High", rigs=None,
                   signal_no=None, is_test=0)
    _mount(prefill(partial), "Editing Helium-3 (abc123def456)")


@pytest.mark.parametrize("key", [f.key for f in FIELDS if f.kind == "choice"])
def test_each_choice_field_mounts_blank_on_its_own(key):
    form = prefill(STORED)
    form[key] = ""
    _mount(form, "Editing Helium-3 (abc123def456)")


def test_no_select_is_given_an_explicit_none():
    """The blank sentinel has moved between Textual releases — Select.NULL in
    some, Select.BLANK in others, and in at least one version BLANK is a plain
    False the validator then rejects. Omitting the argument uses whichever
    default that release considers blank."""
    import ast

    src = (ROOT / "tui" / "deposit_screen.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Select"):
            continue
        for kw in node.keywords:
            if kw.arg == "value":
                assert not (isinstance(kw.value, ast.Constant)
                            and kw.value.value is None), \
                    "Select value=None raises InvalidSelectValueError on mount"


@pytest.mark.parametrize("stored,label", [
    ("high", "lower case"),
    ("HIGH", "upper case"),
    ("Very High", "a value from somebody else's sheet"),
    ("vhigh", "an abbreviation"),
    ("", "blank"),
    (None, "missing"),
])
def test_a_stored_amount_outside_the_vocabulary_does_not_crash(stored, label):
    """Deposits imported from a shared sheet are written as the sheet spells
    them, and a sheet is a document people edit by hand. A value that is not an
    option takes the window down exactly the way None did — on whoever opens it
    next, not on whoever typed it."""
    form = prefill({**STORED, "amount": stored})
    _mount(form, "Editing Helium-3 (abc123def456)")


def test_a_recognisable_value_is_still_selected():
    """Case-insensitive, so a lower-case import still shows the right option
    rather than silently reading as blank."""
    from core.deposit_form import clean

    assert clean({"amount": "high"}).values["amount"] == "High"


def test_the_store_refuses_vocabulary_it_does_not_know(tmp_path):
    """Dropped rather than kept: a wrong value is worse than a blank one a
    later sighting can fill in."""
    from core.mining_db import MiningDB

    db = MiningDB(tmp_path / "m.db")
    db.upsert_body(1, 2, radius_m=1.5e6)
    db.import_deposits([{
        "deposit_id": "aaa", "system_address": 1, "body_id": 2,
        "commodity": "monazite", "latitude": 1.0, "longitude": 2.0,
        "amount": "Very High", "density_observed": "high",
        "last_confirmed": "2026-09-01T00:00:00Z"}])
    row = db.deposits_on(1, 2)[0]
    assert row["amount"] == "", "unrecognised amount is dropped"
    assert row["density_observed"] == "High", "recognisable one is normalised"


def test_the_form_shows_a_just_refined_deposit_as_an_edit(tmp_path, monkeypatch):
    """A refine queues its deposit and does not write it until the confirm
    interval passes, so Ctrl+D moments after mining the first unit offered to
    add a deposit that was already on its way in."""
    import ast

    src = (ROOT / "components" / "surface_mining.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "form_for_here")
    body = ast.get_source_segment(src, fn) or ""
    assert "_flush_pending(force=True)" in body


# ── the form and the store agree on what a deposit has ────────────────────────

def test_every_field_the_form_produces_is_one_the_store_accepts():
    """The form produced signal_no and annotate_deposit had no such parameter,
    so filling that field in and pressing Save raised TypeError — after the
    commander had typed everything else. Nothing validates this pairing at
    import time; only a test does."""
    import inspect

    from core.deposit_form import FIELDS, clean
    from core.mining_db import MiningDB

    sample = {f.key: ("High" if f.kind == "choice" else
                      "1" if f.kind == "int" else
                      "true" if f.kind == "bool" else "Silver")
              for f in FIELDS}
    produced = set(clean(sample).values)
    accepted = set(inspect.signature(MiningDB.annotate_deposit).parameters)

    # commodity is handled separately: it sets a new deposit's identity and is
    # deliberately refused on an edit.
    produced -= {"commodity", "commodity_display"}
    assert produced <= accepted, \
        f"the form produces {sorted(produced - accepted)}, which the store rejects"


def test_saving_every_field_at_once_actually_writes(tmp_path, monkeypatch):
    """End to end through the component, with nothing left blank — the shape
    of the save that failed."""
    import importlib.util
    import time as _t

    import core.mining_db as mdb
    import core.state as state_mod
    from core.surface_survey import POSITIONS, Position

    monkeypatch.setattr(state_mod, "EDLD_DATA_DIR", tmp_path)
    monkeypatch.setattr(state_mod, "shared_data_dir", lambda: tmp_path)
    monkeypatch.setattr(mdb, "_instance", None)

    spec = importlib.util.spec_from_file_location(
        "sm_save", ROOT / "components" / "surface_mining.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Core:
        _plugins: dict = {}

        def register_session_provider(self, p):
            pass

        def load_setting(self, section, defaults, warn=False, include_extra=False):
            d = dict(defaults)
            d["AutoConfirm"] = False
            return d

    p = mod.SurfaceMiningPlugin()
    p.on_load(_Core())
    p._system_address, p._body_id = 1234, 7
    p._db.upsert_body(1234, 7, radius_m=1.5e6)
    POSITIONS.clear()
    POSITIONS.add(Position(ts=_t.time(), latitude=10.0, longitude=20.0,
                           heading=0.0, body_name="B", radius_m=1.5e6,
                           in_srv=True))

    assert "recorded" in p.submit_form({"commodity": "Low Temp. Diamonds"})
    msg = p.submit_form({"amount": "High", "density_observed": "Medium",
                         "rigs": "2", "signal_no": "11", "is_test": ""})
    assert "updated" in msg, msg

    row = p._db.deposits_on(1234, 7)[0]
    assert row["amount"] == "High"
    assert row["density_observed"] == "Medium"
    assert row["rigs"] == 2
    assert row["signal_no"] == 11


def test_the_window_has_the_styles_it_asks_for():
    """Three classes it used did not exist, so the dialog had no width and
    filled the terminal with a 45% label column."""
    css = (ROOT / "tui" / "theme.py").read_text(encoding="utf-8")
    src = (ROOT / "tui" / "deposit_screen.py").read_text(encoding="utf-8")
    import re

    used = set(re.findall(r'classes="([a-z-]+)"', src))
    used |= set(re.findall(r'id="(deposit-dialog)"', src))
    for name in sorted(used):
        assert f".{name}" in css or f"#{name}" in css, \
            f"{name} is not styled anywhere"


# ── notes ─────────────────────────────────────────────────────────────────────

def _drive(form, steps):
    """Run the screen and hand ``steps(pilot, screen)`` the live objects."""
    from textual.app import App

    from tui.deposit_screen import DepositScreen

    plugin = _Plugin(form, "Editing Helium-3 (abc123def456)")
    out = {}

    class _Harness(App):
        def on_mount(self) -> None:
            self.push_screen(DepositScreen(None, plugin))

    async def run():
        app = _Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            out["screen"] = app.screen
            await steps(pilot, app.screen)
            await pilot.pause()
            out["top"] = app.screen

    asyncio.run(run())
    return plugin, out


def test_the_note_box_opens_holding_the_stored_note():
    from textual.widgets import TextArea

    seen = {}

    async def steps(pilot, screen):
        area = screen.query_one("#dep-notes", TextArea)
        seen["text"] = area.text
        seen["wrap"] = getattr(area, "soft_wrap", True)

    _drive(prefill({**STORED, "notes": "line one\nline two"}), steps)
    assert seen["text"] == "line one\nline two"
    assert seen["wrap"] is True


def test_save_sends_what_is_in_the_note_box():
    from textual.widgets import TextArea

    async def steps(pilot, screen):
        screen.query_one("#dep-notes", TextArea).load_text("north ridge\nno SRV")
        screen.query_one("#dep-save").press()

    plugin, _ = _drive(prefill(STORED), steps)
    assert plugin.submitted["notes"] == "north ridge\nno SRV"
    # The other fields still arrive alongside it.
    assert plugin.submitted["amount"] == "High"


def test_escape_from_the_note_box_closes_the_window():
    """A focused TextArea must not swallow Escape, or the window would only
    close from the mouse once somebody had clicked into the note."""
    from textual.widgets import TextArea

    async def steps(pilot, screen):
        screen.query_one("#dep-notes", TextArea).focus()
        await pilot.pause()
        await pilot.press("escape")

    _, out = _drive(prefill(STORED), steps)
    assert out["top"] is not out["screen"]

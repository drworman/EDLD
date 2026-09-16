"""
tests/test_preferences_contract.py — The component/front-end call contract.

The Survey preferences tab failed to appear in GUI mode three separate times,
and every failure was the same shape: the component called something the GUI
side did not offer in the form it was offered, the tab loop caught the
exception, and the page silently did not exist. TUI kept working throughout,
because it reaches the same settings by a different route — which is exactly
what made it look like a rendering problem rather than a broken call.

  1. ``gui_preferences_tab()`` returned None for the no-argument discovery call.
  2. The component was never registered as a session provider, so its rows were
     never requested by either front end.
  3. The builder called ``dlg._cfg.load_setting(..., warn=False)``.
     ``ConfigManager.load_setting`` takes ``warn_missing``; only the
     ``core_api`` wrapper takes ``warn``. TypeError, swallowed, no tab.

None of these could fail a test that only checked the component in isolation,
because each is a disagreement *between* two files. So this module reads the
real signatures out of the front-end sources with ``ast`` — no Qt, no Textual,
no display needed — and binds the component's calls against them. A signature
that drifts on either side fails here rather than in a debug log nobody reads.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _signature_of(path: Path, qualname: str) -> inspect.Signature:
    """Signature of ``Class.method`` or ``function``, without importing."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parts = qualname.split(".")
    node = tree
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        found = None
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef)) and child.name == part:
                found = child
                break
        assert found is not None, f"{qualname} not found in {path.name}"
        node = found
    assert isinstance(node, ast.FunctionDef)

    params = []
    args = node.args
    defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)
    for arg, default in zip(args.args, defaults):
        if arg.arg == "self":
            continue
        params.append(inspect.Parameter(
            arg.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=inspect.Parameter.empty if default is None else None))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params.append(inspect.Parameter(
            arg.arg, inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty if default is None else None))
    return inspect.Signature(params)


# ── the signatures the component depends on ───────────────────────────────────

def test_config_manager_and_core_wrapper_disagree_about_the_warn_argument():
    """Documents the trap, so nobody 'simplifies' one call into the other.

    These two are not interchangeable and never have been. Anything reaching
    settings from inside a preferences builder must use the core wrapper.
    """
    cm = _signature_of(ROOT / "core" / "config.py", "ConfigManager.load_setting")
    api = _signature_of(ROOT / "core" / "core_api.py", "CoreAPI.load_setting")
    assert "warn_missing" in cm.parameters
    assert "warn" not in cm.parameters
    assert "warn" in api.parameters


def test_the_component_never_calls_config_manager_directly():
    """The failure this catches is silent: TypeError inside a builder is
    caught by the tab loop and logged, so the page just does not appear."""
    tree = ast.parse((ROOT / "components" / "surface_mining.py")
                     .read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "load_setting" \
                and isinstance(fn.value, ast.Attribute) and fn.value.attr == "_cfg":
            offenders.append(node.lineno)
    assert not offenders, (
        f"ConfigManager.load_setting called directly at line(s) {offenders}; "
        "use core.load_setting() from a preferences builder — the two take "
        "different keyword names and the TypeError is swallowed by the tab loop")


def test_builder_calls_bind_against_the_real_gui_helpers():
    """Every dlg._bool_combo / dlg._text_edit call in the component must be a
    call the real PreferencesDialog would accept."""
    gui = ROOT / "gui" / "preferences.py"
    sigs = {
        "_bool_combo": _signature_of(gui, "PreferencesDialog._bool_combo"),
        "_text_edit":  _signature_of(gui, "PreferencesDialog._text_edit"),
    }

    tree = ast.parse((ROOT / "components" / "surface_mining.py")
                     .read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in sigs):
            continue
        if not (isinstance(fn.value, ast.Name) and fn.value.id == "dlg"):
            continue
        args = [None] * len(node.args)
        kwargs = {kw.arg: None for kw in node.keywords if kw.arg}
        try:
            sigs[fn.attr].bind(*args, **kwargs)
        except TypeError as exc:
            pytest.fail(f"dlg.{fn.attr}(...) at line {node.lineno} would raise: {exc}")
        checked += 1
    assert checked >= 6, f"expected several helper calls to check, saw {checked}"


def test_the_dialog_attributes_the_builder_reaches_for_exist():
    gui_src = (ROOT / "gui" / "preferences.py").read_text(encoding="utf-8")
    comp_src = (ROOT / "components" / "surface_mining.py").read_text(encoding="utf-8")

    reached = set()
    for node in ast.walk(ast.parse(comp_src)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "dlg":
            reached.add(node.attr)
    assert reached, "the builder should be using the dialog it is handed"
    for attr in sorted(reached):
        assert f"self.{attr}" in gui_src, \
            f"builder uses dlg.{attr}, which PreferencesDialog does not define"


def test_both_front_ends_discover_the_tab_the_way_they_actually_call_it():
    """Mirrors the two _extra_tabs() loops exactly: no arguments, use result."""
    comp = (ROOT / "components" / "surface_mining.py").read_text(encoding="utf-8")
    for name in ("gui_preferences_tab", "tui_preferences_tab"):
        tree = ast.parse(comp)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == name), None)
        assert fn is not None, f"{name} is missing"
        required = [a.arg for a in fn.args.args if a.arg != "self"]
        required = required[:len(required) - len(fn.args.defaults)]
        assert not required, \
            f"{name} must be callable with no arguments — _extra_tabs() calls it that way"


def test_closed_vocabularies_use_pickers_not_text_fields():
    """Zone, mode and hide-mode have fixed valid values.

    A typed setting can be wrong, which means validating it, reporting it and
    ignoring it — and the commander finds out by noticing nothing happened.
    The dialog has had a combo helper all along; there was no reason to hand-
    roll text entry for a three-item list.
    """
    src = (ROOT / "components" / "overlay.py").read_text(encoding="utf-8")
    for key in ("HideMode", '.Zone"', '.Mode"'):
        assert f'_text_edit' not in _calls_for(src, key), \
            f"{key} should be a picker, not a text field"


def _calls_for(src: str, needle: str) -> str:
    """The source lines mentioning ``needle``, for a targeted assertion."""
    return "\n".join(l for l in src.splitlines() if needle in l)


def test_the_gui_choice_helper_exists_and_records():
    gui = (ROOT / "gui" / "preferences.py").read_text(encoding="utf-8")
    assert "def _choice_combo" in gui
    sig = _signature_of(ROOT / "gui" / "preferences.py",
                        "PreferencesDialog._choice_combo")
    for expected in ("current", "section", "key", "choices"):
        assert expected in sig.parameters


def test_every_overlay_picker_call_binds_against_the_real_helper():
    gui = ROOT / "gui" / "preferences.py"
    sig = _signature_of(gui, "PreferencesDialog._choice_combo")
    tree = ast.parse((ROOT / "components" / "overlay.py").read_text(encoding="utf-8"))
    seen = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "_choice_combo":
            sig.bind(*[None] * len(node.args),
                     **{kw.arg: None for kw in node.keywords if kw.arg})
            seen += 1
    assert seen >= 3, f"expected the zone/mode/hide pickers, saw {seen}"

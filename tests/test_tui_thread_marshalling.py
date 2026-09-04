"""
tests/test_tui_thread_marshalling.py — guard cross-thread UI marshalling in the TUI.

Background
----------
Blocks that do network work run it on a background thread and marshal the
result back onto the Textual event loop before touching widgets.  The call
that does that is ``call_from_thread``, and it is defined on ``App`` — not on
``Widget``, and not on ``MessagePump`` which ``Widget`` inherits from.

``tui/blocks/navigation.py`` called it as ``self.call_from_thread(...)`` from
inside a ``TuiBlock``.  That is an ``AttributeError``, and it fired on the
worker's *last* line, after the Spansh/EDSM round trip had already succeeded.
The daemon thread died there, no repaint was ever scheduled, and the status
label sat on "Plotting…" indefinitely.  Both the FSD and the Neutron tab were
affected; the GUI was fine because Qt marshals through a signal instead.  From
a --trace log of the failure:

    [Spansh] neutron POST accepted by https://spansh.co.uk/api/route (HTTP 202)
    Unhandled exception in thread 'nav-plot-neutron': AttributeError:
        'NavigationBlock' object has no attribute 'call_from_thread'

The correct form is ``self.app.call_from_thread(...)``, which is what
``tui/search_modal.py`` already used.

These tests derive the rule mechanically rather than asserting against a
hand-written expected line, so they cover blocks that do not exist yet and
relax automatically if Textual ever promotes the method onto ``Widget``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TUI_DIR = ROOT / "tui"

#: Methods that exist on App but not on Widget.  Reaching for any of these on
#: ``self`` from inside a block is the bug this module guards.
APP_ONLY_METHODS = ("call_from_thread",)


def _tui_sources() -> list[Path]:
    return sorted(p for p in TUI_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def test_tui_package_has_sources():
    """A silent glob miss would make every scan below vacuously pass."""
    assert _tui_sources(), f"no Python sources found under {TUI_DIR}"


def test_app_only_methods_are_actually_app_only():
    """Pin the premise: these live on App and not on Widget.

    If Textual ever adds one to Widget this fails loudly, telling us the
    scan below has become unnecessary rather than letting it quietly enforce
    a rule that no longer applies.
    """
    textual_app = pytest.importorskip("textual.app")
    textual_widget = pytest.importorskip("textual.widget")

    for name in APP_ONLY_METHODS:
        assert hasattr(textual_app.App, name), f"App lost {name}()"
        assert not hasattr(textual_widget.Widget, name), (
            f"Widget gained {name}() — APP_ONLY_METHODS is now wrong"
        )


def _self_attribute_calls(tree: ast.AST) -> list[tuple[str, int]]:
    """Every ``self.<name>(...)`` call site in a module, as (name, lineno)."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
        ):
            found.append((func.attr, node.lineno))
    return found


@pytest.mark.parametrize("path", _tui_sources(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_app_only_method_called_on_self(path: Path):
    """No TUI module may call an App-only method directly on ``self``.

    ``self.app.call_from_thread(...)`` is an Attribute whose value is another
    Attribute, not a Name, so the correct form is not matched here and only
    the broken form trips the assertion.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = [
        (name, lineno)
        for name, lineno in _self_attribute_calls(tree)
        if name in APP_ONLY_METHODS
    ]
    assert not offenders, (
        f"{path.relative_to(ROOT)} calls an App-only method on self: "
        + ", ".join(f"self.{n}() at line {ln}" for n, ln in offenders)
        + " — use self.app.<method>() instead"
    )


def test_navigation_worker_marshals_through_app():
    """The navigation plot worker specifically must marshal via self.app.

    The AST scan above proves the broken form is absent; this proves the
    correct form is present, so deleting the marshalling entirely (which
    would also pass the scan) still fails.
    """
    path = TUI_DIR / "blocks" / "navigation.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    marshalled = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "call_from_thread"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "app"
    ]
    assert marshalled, (
        "tui/blocks/navigation.py no longer marshals its plot result back onto "
        "the event loop via self.app.call_from_thread()"
    )

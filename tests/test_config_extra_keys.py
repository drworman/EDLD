"""
tests/test_config_extra_keys.py — Sections whose keys are not known in advance.

``load_setting`` resolves by iterating ``defaults``. Anything not declared
there is invisible however plainly it is written in config.toml: read back as
absent, reported as missing, and discarded on the next write of that section.

That is right for a fixed schema and wrong for the overlay, which names one key
per panel and gets its panels from whichever components are loaded. This is the
fault that made overlay placement appear to save and then do nothing — the
values reached the file every time and were never read back.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import load_setting

DEFAULTS = {"HideMode": "reserve"}


def _cfg(section: dict, profile: str | None = None) -> dict:
    return {profile: {"OverlayPanels": section}} if profile \
        else {"OverlayPanels": section}


def test_undeclared_keys_are_dropped_by_default():
    got = load_setting(_cfg({"HideMode": "collapse", "PanelZone_cargo": "left"}),
                       None, "OverlayPanels", DEFAULTS, False)
    assert got["HideMode"] == "collapse"
    assert "PanelZone_cargo" not in got, \
        "the fixed-schema behaviour must not change"


def test_include_extra_returns_them():
    got = load_setting(_cfg({"HideMode": "collapse", "PanelZone_cargo": "left"}),
                       None, "OverlayPanels", DEFAULTS, False,
                       include_extra=True)
    assert got["PanelZone_cargo"] == "left"
    assert got["HideMode"] == "collapse"


def test_include_extra_works_inside_a_profile():
    """Which is where they actually live — the profile is how EDLD is run."""
    got = load_setting(_cfg({"PanelMode_ship": "on"}, profile="EDP1"),
                       "EDP1", "OverlayPanels", DEFAULTS, False,
                       include_extra=True)
    assert got["PanelMode_ship"] == "on"


def test_a_profile_key_wins_over_the_global_one():
    cfg = {"OverlayPanels": {"PanelMode_ship": "off"},
           "EDP1": {"OverlayPanels": {"PanelMode_ship": "on"}}}
    got = load_setting(cfg, "EDP1", "OverlayPanels", DEFAULTS, False,
                       include_extra=True)
    assert got["PanelMode_ship"] == "on"


def test_declared_keys_still_get_their_declared_default():
    got = load_setting(_cfg({"PanelZone_cargo": "left"}), None,
                       "OverlayPanels", DEFAULTS, False, include_extra=True)
    assert got["HideMode"] == "reserve"


def test_extra_keys_are_not_type_checked():
    """There is no declared type to check them against, so they come back as
    found rather than being coerced or rejected."""
    got = load_setting(_cfg({"PanelOrder_cargo": 3}), None, "OverlayPanels",
                       DEFAULTS, False, include_extra=True)
    assert got["PanelOrder_cargo"] == 3


def test_a_missing_section_is_still_just_defaults():
    got = load_setting({}, None, "OverlayPanels", DEFAULTS, False,
                       include_extra=True)
    assert got == DEFAULTS


def test_the_overlay_component_asks_for_extra_keys():
    """Without this the placement round trip is broken end to end, and it looks
    exactly like a UI that is not saving."""
    import ast

    src = (ROOT / "components" / "overlay.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "load_setting":
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if "OverlayPanels" in args:
                assert any(kw.arg == "include_extra" for kw in node.keywords), \
                    "OverlayPanels must be read with include_extra=True"
                found = True
    assert found, "the overlay component should read OverlayPanels"

"""
tests/test_carrier_display.py — Assets Carrier tab data.

The tab used to read three keys no parser produced — ``reserve_balance``,
``coreCost`` and a ``capacity`` sub-dict — so Reserve, Upkeep and both Cargo
rows were permanently blank while roughly twenty parsed fields had nowhere to
appear.  Three separate parsers populate ``state.assets_carrier`` and they did
not agree on key names, so a CAPI-sourced carrier and a journal-sourced one
rendered differently.

These tests fix the contract between the parsers and the display.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ui_helpers import (  # noqa: E402
    CARRIER_HULL_VALUE,
    carrier_active_services,
    carrier_display_sections,
    normalise_carrier,
)

# A carrier as the journal's CarrierStats parser produces it.
JOURNAL = {
    "callsign": "KVX-31Z", "name": "Nomad's Rest", "theme": "—",
    "system": "Ogmar", "fuel": 857, "carrier_state": "—",
    "docking": "All", "notorious": False,
    "balance": 4_120_000_000, "reserve": 300_000_000, "available": 3_820_000_000,
    "reserve_pct": 7.3,
    "tax_refuel": 10, "tax_repair": 5, "tax_rearm": 0, "tax_pioneer": 2,
    "cargo_total": 25_000, "cargo_used": 15_655, "cargo_free": 9_345,
    "ship_packs": 800, "module_packs": 400,
    "micro_total": 100_000, "micro_free": 88_000, "micro_used": 12_000,
    "services": {"Refuel": "ok", "Repair": "ok", "Shipyard": "unavailable"},
    "carrier_type": "FleetCarrier",
}

# The same carrier as the CAPI parsers produce it: no cargo_total, no
# reserve_pct, but crew space and maintenance instead.
CAPI = {
    "callsign": "KVX-31Z", "name": "Nomad's Rest", "theme": "Vibrant Blue",
    "system": "Ogmar", "fuel": 857, "carrier_state": "normalOperation",
    "docking": "All", "notorious": False,
    "balance": 4_120_000_000, "reserve": 300_000_000,
    "maintenance": 11_500_000, "maintenance_wtd": 4_200_000,
    "cargo_used": 15_655, "cargo_free": 9_345, "cargo_crew": 1_200,
    "ship_packs": 800, "module_packs": 400,
    "micro_total": 100_000, "micro_used": 12_000,
    "services": {"refuel": "ok", "repair": "ok", "carrierfuel": "ok"},
    "carrier_type": "FleetCarrier",
}


def _all_labels(sections) -> list[str]:
    return [label for _title, rows in sections for label, _v in rows]


def _value(sections, label) -> str:
    for _title, rows in sections:
        for lbl, val in rows:
            if lbl == label:
                return val
    raise KeyError(label)


def _strip_comments_and_docstrings(path: Path) -> str:
    """Return a module's source with comments and docstrings removed.

    Used so a scan for dead key names inspects executable code rather than
    prose that explains why those names are gone.
    """
    import ast
    import io
    import tokenize

    src = path.read_text(encoding="utf-8")
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        out.append(tok.string)
    code = " ".join(out)

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                code = code.replace(doc, "")
    return code


# ── The regression that started this ──────────────────────────────────────────

@pytest.mark.parametrize("carrier", [JOURNAL, CAPI], ids=["journal", "capi"])
def test_finance_and_cargo_rows_are_populated(carrier):
    """Reserve, Available and Cargo were the permanently blank rows."""
    sections = carrier_display_sections(carrier)
    assert _value(sections, "Reserved") != "—"
    assert _value(sections, "Available") != "—"
    cargo = _value(sections, "Cargo")
    assert "15,655" in cargo and "25,000" in cargo


def test_no_row_renders_as_a_bare_dash():
    """Absent data drops its row rather than rendering an empty column."""
    sections = carrier_display_sections(CAPI)
    for _title, rows in sections:
        for label, value in rows:
            assert value != "—", f"{label} rendered as a bare dash"


# ── Both sources render equivalently ──────────────────────────────────────────

@pytest.mark.parametrize(
    "label", ["Name", "Callsign", "System", "Tritium", "Cargo",
              "Balance", "Reserved", "Available", "Hull (decom.)"]
)
def test_core_rows_present_from_either_source(label):
    assert label in _all_labels(carrier_display_sections(JOURNAL))
    assert label in _all_labels(carrier_display_sections(CAPI))


def test_journal_and_capi_agree_on_shared_values():
    j = carrier_display_sections(JOURNAL)
    c = carrier_display_sections(CAPI)
    for label in ("Name", "Callsign", "System", "Tritium", "Cargo", "Balance"):
        assert _value(j, label) == _value(c, label), f"{label} differs by source"


# ── Normalisation ─────────────────────────────────────────────────────────────

def test_cargo_total_derived_when_absent():
    """CAPI never reports TotalCapacity; it has to come from used + free."""
    assert normalise_carrier(CAPI)["cargo_total"] == 25_000


def test_cargo_free_derived_when_absent():
    c = normalise_carrier({"cargo_total": 25_000, "cargo_used": 10_000})
    assert c["cargo_free"] == 15_000


def test_available_derived_from_balance_minus_reserve():
    c = normalise_carrier({"balance": 1_000_000, "reserve": 250_000})
    assert c["available"] == 750_000


def test_state_key_aliases_to_carrier_state():
    """The CAPI parser used to emit 'state' where the others emit 'carrier_state'."""
    assert normalise_carrier({"state": "normalOperation"})["carrier_state"] == "normalOperation"


def test_normalise_handles_no_carrier():
    assert normalise_carrier(None) == {}
    assert normalise_carrier({}) == {}


def test_garbage_numeric_values_do_not_raise():
    c = normalise_carrier({"cargo_used": "n/a", "balance": None, "fuel": ""})
    assert c["cargo_total"] == 25_000


# ── Carrier type ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "ctype,expected_label",
    [("FleetCarrier", "Fleet carrier"), ("SquadronCarrier", "Squadron carrier")],
)
def test_carrier_type_label_and_hull_value(ctype, expected_label):
    sections = carrier_display_sections({**JOURNAL, "carrier_type": ctype})
    assert _value(sections, "Type") == expected_label
    c = normalise_carrier({"carrier_type": ctype})
    assert c["hull_value"] == CARRIER_HULL_VALUE[ctype]


def test_squadron_hull_is_worth_more():
    assert (CARRIER_HULL_VALUE["SquadronCarrier"]
            > CARRIER_HULL_VALUE["FleetCarrier"])


# ── Services ──────────────────────────────────────────────────────────────────

def test_only_active_services_are_listed():
    assert carrier_active_services(JOURNAL) == ["Refuel", "Repair"]


def test_capi_service_spellings_map_to_display_names():
    """CAPI lowercases the keys and uses different names for some services."""
    assert carrier_active_services(CAPI) == ["Refuel", "Repair", "Tritium depot"]


def test_nested_service_status_shape_is_handled():
    got = carrier_active_services({"services": {"refuel": {"state": "ok"}}})
    assert got == ["Refuel"]


def test_missing_services_is_not_an_error():
    assert carrier_active_services({}) == []
    assert carrier_active_services({"services": None}) == []


# ── Squadron section ──────────────────────────────────────────────────────────

def test_squadron_section_states_the_limitation():
    sections = carrier_display_sections(JOURNAL, squadron_name="Deep Space Cartographers")
    assert "Squadron" in [t for t, _ in sections]
    text = " ".join(v for _t, rows in sections for _l, v in rows)
    assert "Deep Space Cartographers" in text
    assert "anonymous API" in text


def test_no_squadron_section_without_a_squadron():
    assert "Squadron" not in [t for t, _ in carrier_display_sections(JOURNAL)]


# ── No carrier ────────────────────────────────────────────────────────────────

def test_no_carrier_says_so():
    sections = carrier_display_sections(None)
    assert _value(sections, "Fleet carrier") == "None on file"


def test_no_carrier_still_shows_squadron():
    sections = carrier_display_sections(None, squadron_name="DSC")
    assert _value(sections, "Squadron") == "DSC"


# ── Guard against the dead keys coming back ───────────────────────────────────

@pytest.mark.parametrize("dead_key", ["reserve_balance", "coreCost"])
def test_display_layer_does_not_read_keys_no_parser_writes(dead_key):
    """These were read by the blocks and produced by nothing.

    Comments are stripped before scanning — the module docstring in
    ui_helpers.py names both keys while explaining why they were removed.
    """
    for path in (ROOT / "tui" / "blocks" / "assets.py",
                 ROOT / "gui" / "blocks" / "assets.py",
                 ROOT / "core" / "ui_helpers.py"):
        code = _strip_comments_and_docstrings(path)
        assert dead_key not in code, (
            f"{path.name} still reads {dead_key}, which no parser produces"
        )


def test_parsers_and_display_share_a_key_vocabulary():
    """Every key the display reads must be produced by at least one parser."""
    helpers = (ROOT / "core" / "ui_helpers.py").read_text(encoding="utf-8")
    section = helpers[helpers.index("def carrier_display_sections"):]
    read = set(re.findall(r'c\.get\("(\w+)"', section))
    read |= set(re.findall(r'_i\("(\w+)"\)', section))

    produced: set[str] = set()
    for path, marker in (
        (ROOT / "components" / "assets.py", 'def _parse_carrier_stats(self'),
        (ROOT / "components" / "assets.py", 'def _parse_carrier_stats_from_capi'),
        (ROOT / "core" / "data.py", 'state.assets_carrier = {'),
    ):
        text = path.read_text(encoding="utf-8")
        produced |= set(re.findall(r'"(\w+)":\s', text[text.index(marker):][:3400]))

    # Keys normalise_carrier synthesises rather than reading from a parser.
    derived = {"hull_value", "is_squadron", "carrier_state", "cargo_total",
               "cargo_free", "available", "carrier_type"}
    missing = read - produced - derived
    assert not missing, f"display reads keys no parser produces: {sorted(missing)}"

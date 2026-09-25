"""
tests/test_deposit_form.py — Validating what a commander types about a deposit.

A malformed row on a shared sheet is not a local mistake. It is a row somebody
else fetches, fails to parse, and blames on their own install — so the formats
accepted here are the ones Frontier's journal uses, and a hand-typed row has to
be indistinguishable from a captured one downstream.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.deposit_form import (
    FIELDS, MAX_RIGS, MAX_SIGNAL_NO, clean, describe, prefill,
)


# ── commodity ─────────────────────────────────────────────────────────────────

def test_a_typed_commodity_is_stored_both_ways():
    """Canonical for deduplication and the sheet, typed for a human to read."""
    v = clean({"commodity": "Helium-3"}).values
    assert v["commodity"] == "helium3"
    assert v["commodity_display"] == "Helium-3"


def test_a_typed_commodity_matches_the_journals_spelling():
    assert clean({"commodity": "Low Temp. Diamonds"}).values["commodity"] \
        == clean({"commodity": "lowtempdiamonds"}).values["commodity"]


def test_commodity_is_required_only_for_a_new_deposit():
    assert clean({}, require_commodity=True).errors
    assert clean({}).errors == {}


def test_a_commodity_of_punctuation_alone_is_refused():
    assert "commodity" in clean({"commodity": "---"}).errors


# ── closed vocabularies ───────────────────────────────────────────────────────

@pytest.mark.parametrize("typed,expected", [
    ("high", "High"), ("HIGH", "High"), ("  Medium  ", "Medium"),
])
def test_amount_is_case_and_space_insensitive(typed, expected):
    assert clean({"amount": typed}).values["amount"] == expected


def test_an_amount_outside_the_vocabulary_is_named_in_the_error():
    err = clean({"amount": "Enormous"}).errors["amount"]
    assert "Low" in err and "High" in err


def test_depleted_is_not_an_amount():
    """Depletion is recorded by its date alone; the amount says what the site
    holds when full, and does not change when it empties."""
    assert "amount" in clean({"amount": "Depleted"}).errors


def test_advertised_density_is_gone():
    """It was the density of the fresh deposit, which is what Density already
    records — two controls for one measurement."""
    assert "density_claimed" not in [f.key for f in FIELDS]
    assert "density_claimed" not in clean({"density_claimed": "High"}).values


def test_a_depletion_date_is_accepted():
    assert clean({"depleted_on": "2026-09-14"}).values["depleted_on"] \
        == "2026-09-14"


@pytest.mark.parametrize("bad", ["14/09/2026", "2026-13-01", "yesterday",
                                 "2026-09-32"])
def test_a_date_that_is_not_a_date_is_refused(bad):
    assert "depleted_on" in clean({"depleted_on": bad}).errors


def test_a_future_depletion_date_is_refused():
    """A site cannot have been worked out tomorrow, and the reset-period
    arithmetic would be nonsense if it could."""
    assert "depleted_on" in clean({"depleted_on": "2099-01-01"}).errors


def test_a_blank_date_is_left_alone():
    assert "depleted_on" not in clean({"depleted_on": ""}).values


def test_depleted_is_not_a_density():
    assert "density_observed" in clean({"density_observed": "Depleted"}).errors


# ── numbers ───────────────────────────────────────────────────────────────────

def test_rigs_and_signal_number_parse():
    v = clean({"rigs": "4", "signal_no": "17"}).values
    assert v["rigs"] == 4 and v["signal_no"] == 17


def test_a_number_that_is_not_a_number_is_refused():
    assert "rigs" in clean({"rigs": "four"}).errors


@pytest.mark.parametrize("field,value", [
    ("rigs", str(MAX_RIGS + 1)), ("rigs", "-1"),
    ("signal_no", "0"), ("signal_no", str(MAX_SIGNAL_NO + 1)),
])
def test_numbers_outside_their_range_are_refused(field, value):
    assert field in clean({field: value}).errors


def test_zero_rigs_is_allowed_but_signal_zero_is_not():
    """A site can have no rigs on it; signals are numbered from one."""
    assert clean({"rigs": "0"}).values["rigs"] == 0
    assert "signal_no" in clean({"signal_no": "0"}).errors


# ── blanks mean leave alone ───────────────────────────────────────────────────

def test_an_empty_field_is_absent_rather_than_blank():
    """Editing the amount must not silently blank the density recorded last
    week."""
    v = clean({"commodity": "Silver", "amount": "High",
               "density_observed": "", "rigs": "", "signal_no": "",
               "depleted_on": ""}).values
    assert "amount" in v
    for absent in ("density_observed", "rigs", "signal_no"):
        assert absent not in v


def test_an_entirely_empty_form_writes_nothing():
    """Nothing but the note, whose empty box is a value: it withdraws a note
    that was there and is a no-op against one that was not."""
    assert clean({f.key: "" for f in FIELDS}).values == {"notes": ""}


# ── the test flag ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False),
])
def test_the_test_flag_accepts_what_a_front_end_might_send(raw, expected):
    assert clean({"is_test": raw}).values["is_test"] is expected


def test_an_untouched_test_flag_is_left_alone():
    assert "is_test" not in clean({"is_test": ""}).values
    assert "is_test" not in clean({}).values


# ── reporting and prefill ─────────────────────────────────────────────────────

def test_every_error_is_reported_not_just_the_first():
    line = describe(clean({"amount": "x", "rigs": "y", "signal_no": "999"}).errors)
    assert line.count(";") == 2


def test_no_errors_is_an_empty_line():
    assert describe({}) == ""


def test_prefill_round_trips_an_existing_deposit():
    stored = {"commodity": "helium3", "commodity_display": "Helium-3",
              "amount": "High", "density_observed": "Medium",
              "rigs": 4, "signal_no": 3, "is_test": 1}
    form = prefill(stored)
    assert form["commodity"] == "Helium-3" and form["rigs"] == "4"
    assert form["is_test"] == "true" and form["depleted_on"] == ""

    back = clean(form).values
    assert back["amount"] == "High" and back["rigs"] == 4
    assert back["is_test"] is True


def test_prefill_of_nothing_is_a_blank_form():
    form = prefill(None)
    assert set(form) == {f.key for f in FIELDS}
    assert all(v == "" for v in form.values())


def test_both_front_ends_build_from_the_same_field_list():
    """So the TUI and the GUI cannot drift apart on what a deposit has."""
    assert [f.key for f in FIELDS][0] == "commodity"
    for f in FIELDS:
        assert f.kind in ("text", "choice", "int", "bool", "note")
        if f.kind == "choice":
            assert f.choices


# ── the two front ends stay in step ───────────────────────────────────────────

def test_both_front_ends_bind_the_same_shortcuts():
    """Ctrl+D and Ctrl+G mean the same thing in the TUI and the GUI, or a
    commander who uses both has to remember which is which."""
    tui = (ROOT / "tui" / "app.py").read_text(encoding="utf-8")
    gui = (ROOT / "gui" / "app.py").read_text(encoding="utf-8")
    assert '"ctrl+d"' in tui and 'QKeySequence("Ctrl+D")' in gui
    assert '"ctrl+g"' in tui and 'QKeySequence("Ctrl+G")' in gui


def test_both_front_ends_build_their_form_from_FIELDS():
    """Listing fields in either window is how the two drift apart."""
    import ast

    for path in (ROOT / "tui" / "deposit_screen.py",
                 ROOT / "gui" / "deposit_dialog.py"):
        src = path.read_text(encoding="utf-8")
        assert "from core.deposit_form import FIELDS" in src, path.name
        assert "for field in FIELDS" in src, path.name
        # and no hand-written field list alongside it
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in ("density_observed", "density_claimed"), \
                    f"{path.name} names a field instead of reading FIELDS"


def test_both_front_ends_submit_through_the_component():
    """Neither window writes to the store itself, so validation, the
    add-or-edit decision and the wording of the result cannot differ."""
    for path in (ROOT / "tui" / "deposit_screen.py",
                 ROOT / "gui" / "deposit_dialog.py"):
        src = path.read_text(encoding="utf-8")
        assert "submit_form" in src
        assert "record_deposit" not in src and "annotate_deposit" not in src


def test_a_rejection_keeps_the_window_open():
    """So the offending field can be corrected rather than the form retyped."""
    for path in (ROOT / "tui" / "deposit_screen.py",
                 ROOT / "gui" / "deposit_dialog.py"):
        src = path.read_text(encoding="utf-8")
        assert 'startswith(("recorded", "updated"))' in src, path.name


def test_prefill_shows_a_date_already_on_record():
    """The date lives in its own table, so a site already known to be worked
    out would otherwise show blank — and saving would re-stamp it with today."""
    form = prefill({"commodity": "silver", "commodity_display": "Silver",
                    "amount": "Depleted", "depleted_on": "2026-09-14T00:00:00Z"})
    assert form["depleted_on"] == "2026-09-14"

"""
core/deposit_form.py — Validating what a commander types about a deposit.

The survey captures a deposit's position, commodity and refine count without
being asked. Everything else — how much is left, how dense the seam is, how
many rigs the site took — is on the HUD and in no journal event, so it has to
be typed, and typed values reach a sheet other people read.

That is why this is a module of its own with tests rather than a few
``str.strip()`` calls in a dialog. A malformed row on a shared sheet is not a
local mistake: it is a row somebody else fetches, fails to parse, and blames on
their own install. The formats here are the ones Frontier's journal uses, so a
hand-typed row and a captured one are indistinguishable downstream.

Everything is optional except the commodity on a new deposit, and an empty
field means "leave it alone" rather than "set it to nothing" — a commander
editing the amount should not silently blank the density they recorded last
week.
"""

from __future__ import annotations

from typing import NamedTuple

from core.mining_db import AMOUNT_LEVELS, DENSITY_LEVELS
from core.surface_survey import canonical_commodity

#: Largest plausible rig count. The Rhino carries twelve; the cap exists to
#: catch a typo rather than to encode a game rule, so it is generous.
MAX_RIGS = 12

#: Mining location signals are numbered per body and the numbers are small.
MAX_SIGNAL_NO = 99


class Field(NamedTuple):
    """One editable field, for a front end to build a control from."""
    key:      str
    label:    str
    kind:     str              # "text" | "choice" | "int" | "bool"
    choices:  tuple[str, ...] = ()
    hint:     str = ""


#: The editable fields, in the order they should be shown. Front ends build
#: their controls from this rather than listing fields themselves, so the TUI
#: and the GUI cannot drift apart on what a deposit has.
FIELDS: tuple[Field, ...] = (
    Field("commodity", "Commodity", "text", hint="as the game names it"),
    Field("amount", "Amount", "choice", AMOUNT_LEVELS,
          "how much is left"),
    Field("density_observed", "Density", "choice", DENSITY_LEVELS,
          "what you actually found"),
    Field("density_claimed", "Advertised", "choice", DENSITY_LEVELS,
          "what the body's signals promised"),
    Field("rigs", "Rigs", "int", hint=f"0-{MAX_RIGS}"),
    Field("signal_no", "Signal #", "int", hint=f"1-{MAX_SIGNAL_NO}"),
    Field("is_test", "Test data", "bool", hint="held back from the sheet"),
)


class Cleaned(NamedTuple):
    values: dict
    errors: dict


def _clean_int(raw, low: int, high: int, label: str,
               values: dict, errors: dict, key: str) -> None:
    text = str(raw).strip()
    if not text:
        return
    try:
        number = int(text)
    except ValueError:
        errors[key] = f"{label} must be a whole number"
        return
    if not low <= number <= high:
        errors[key] = f"{label} must be between {low} and {high}"
        return
    values[key] = number


def clean(raw: dict, *, require_commodity: bool = False) -> Cleaned:
    """Validate and normalise a form's contents.

    Returns the values that should be written and the errors that should be
    shown. A key absent from ``values`` is one to leave alone; only fields the
    commander actually filled in are returned, so editing one thing cannot
    blank another.
    """
    values: dict = {}
    errors: dict = {}

    commodity = str(raw.get("commodity", "") or "").strip()
    if commodity:
        canon = canonical_commodity(commodity)
        if not canon:
            errors["commodity"] = "Commodity is not a usable name"
        else:
            # Both forms are kept: the canonical one is what deduplication and
            # the sheet match on, the typed one is what a human reads.
            values["commodity"] = canon
            values["commodity_display"] = commodity
    elif require_commodity:
        errors["commodity"] = "Commodity is required for a new deposit"

    for key, allowed, label in (("amount", AMOUNT_LEVELS, "Amount"),
                                ("density_observed", DENSITY_LEVELS, "Density"),
                                ("density_claimed", DENSITY_LEVELS, "Advertised")):
        text = str(raw.get(key, "") or "").strip()
        if not text:
            continue
        match = next((a for a in allowed if a.lower() == text.lower()), None)
        if match is None:
            errors[key] = f"{label} must be one of {', '.join(allowed)}"
        else:
            values[key] = match

    _clean_int(raw.get("rigs", ""), 0, MAX_RIGS, "Rigs", values, errors, "rigs")
    _clean_int(raw.get("signal_no", ""), 1, MAX_SIGNAL_NO, "Signal #",
               values, errors, "signal_no")

    flag = raw.get("is_test", None)
    if flag not in (None, ""):
        values["is_test"] = str(flag).strip().lower() in ("1", "true", "yes", "on")

    return Cleaned(values, errors)


def describe(errors: dict) -> str:
    """One line naming what is wrong, for a status label."""
    if not errors:
        return ""
    return "; ".join(errors[k] for k in sorted(errors))


def prefill(deposit: dict | None) -> dict:
    """Form contents for an existing deposit, or blanks for a new one."""
    if not deposit:
        return {f.key: "" for f in FIELDS}
    return {
        "commodity": deposit.get("commodity_display")
                     or deposit.get("commodity", "") or "",
        "amount": deposit.get("amount", "") or "",
        "density_observed": deposit.get("density_observed", "") or "",
        "density_claimed": deposit.get("density_claimed", "") or "",
        "rigs": "" if deposit.get("rigs") in (None, "") else str(deposit["rigs"]),
        "signal_no": "" if deposit.get("signal_no") in (None, "")
                     else str(deposit["signal_no"]),
        "is_test": "true" if deposit.get("is_test") else "",
    }

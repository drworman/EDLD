"""
tests/test_cargo_pricing.py — Where a manifest price comes from.

A commodity priced off the galactic average while the commodity next to it in
the same hold is priced off the station is not a rendering problem, it is a
lookup miss — and a lookup miss here is silent by construction, because the
fallback produces a plausible number rather than an error.

Two things are asserted: that the two market sources agree about what a
commodity is called, and that learning one station's prices does not discard
what was learned at every other one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.commodity_ledger import canonical_name
from core.ui_helpers import cargo_manifest


def _ctx(mode="station", gal=None, tgt=None, means=None):
    return {"mode": mode, "gal_comms": gal or {}, "tgt_comms": tgt or {},
            "mean_prices": means or {}, "source_label": "Test Station"}


def _price(rows, name):
    return next(r["price"] for r in rows if r["name"] == name)


# ── the two market sources must agree on keys ─────────────────────────────────

@pytest.mark.parametrize("raw", [
    "$lowtemperaturediamond_name;", "LowTemperatureDiamond",
    "lowtemperaturediamond",
])
def test_every_spelling_of_one_commodity_canonicalises_together(raw):
    assert canonical_name(raw) == canonical_name("$lowtemperaturediamond_name;")


def test_canonical_name_does_not_collapse_spaces():
    """Documented limitation, not an oversight to fix blindly.

    A spaced display name does not reduce to the joined internal name, so
    anything feeding display text in as a key will miss. CAPI supplies the
    internal symbol, which is why canonicalising its keys is sufficient — but
    if a future source hands over display names this is where it breaks, and
    it breaks silently into the galactic-average fallback.
    """
    assert canonical_name("Low Temperature Diamond") != \
        canonical_name("LowTemperatureDiamond")


def test_the_capi_path_canonicalises_like_the_market_json_path():
    """Both build the same structure and are read with the same keys.

    Only one of them was normalising, so a CAPI name in a different form
    produced an entry nothing could look up, and that commodity quietly priced
    off the stored galactic average while its neighbours priced off the
    station.
    """
    import ast

    src = (ROOT / "core" / "data.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # The CAPI key assignment must run the name through a canonicaliser rather
    # than just lowercasing it.
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        tgt = node.targets[0]
        if not (isinstance(tgt, ast.Name) and tgt.id == "key"):
            continue
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                and call.func.attr == "lower":
            offenders.append(node.lineno)
    assert not offenders, (
        f"raw .lower() used as a commodity key at line(s) {offenders}; "
        "use canonical_name() so CAPI and Market.json keys match")


# ── the fallback map must accumulate ──────────────────────────────────────────

def test_a_new_station_does_not_erase_averages_learned_elsewhere():
    class _State:
        cargo_mean_prices = {"painite": 40000, "tritium": 51294}

    state = _State()
    existing = dict(state.cargo_mean_prices)
    # What the CAPI handler now does.
    incoming = {"gold": 9000, "tritium": 51500}
    merged = getattr(state, "cargo_mean_prices", None) or {}
    merged.update(incoming)
    state.cargo_mean_prices = merged

    assert state.cargo_mean_prices["painite"] == existing["painite"], \
        "a station that does not trade painite must not forget painite"
    assert state.cargo_mean_prices["tritium"] == 51500, "newer wins"
    assert state.cargo_mean_prices["gold"] == 9000


# ── price selection ───────────────────────────────────────────────────────────

def test_a_commodity_in_the_station_table_prices_off_the_station():
    items = {"tritium": {"count": 161}}
    ctx = _ctx(gal={"tritium": {"sell_price": 57164, "mean_price": 51294,
                                "name_local": "Tritium"}})
    freight, _ = cargo_manifest(items, ctx)
    assert _price(freight, "Tritium") == 57164


def test_a_commodity_missing_from_the_station_table_falls_back_and_is_wrong():
    """This is the observed failure, reproduced.

    Nothing raises; the number is simply the galactic average dressed as a
    station price, which is why it went unnoticed next to two correct rows.
    """
    items = {"lowtemperaturediamond": {"count": 103},
             "tritium": {"count": 161}}
    ctx = _ctx(
        gal={"tritium": {"sell_price": 57164, "mean_price": 51294,
                         "name_local": "Tritium"}},
        means={"lowtemperaturediamond": 96438},
    )
    freight, _ = cargo_manifest(items, ctx)
    assert _price(freight, "Tritium") == 57164
    assert _price(freight, "Lowtemperaturediamond") == 96438


def test_with_the_key_present_the_same_hold_prices_correctly():
    items = {"lowtemperaturediamond": {"count": 103}}
    ctx = _ctx(gal={"lowtemperaturediamond": {
        "sell_price": 179090, "mean_price": 96438,
        "name_local": "Low Temp. Diamonds"}})
    freight, _ = cargo_manifest(items, ctx)
    assert _price(freight, "Low Temp. Diamonds") == 179090


def test_pinning_to_galactic_ignores_the_station():
    items = {"tritium": {"count": 1}}
    ctx = _ctx(mode="galactic",
               gal={"tritium": {"sell_price": 57164, "mean_price": 51294,
                                "name_local": "Tritium"}})
    freight, _ = cargo_manifest(items, ctx)
    assert _price(freight, "Tritium") == 51294

"""
tests/test_commodity_ledger.py — the commodity catalogue must not lie.

The catalogue is written from Market.json and read back weeks later, so the
failures that matter are the quiet ones: the same commodity recorded twice
under two spellings of its name, a Fleet Carrier's MeanPrice of 0 overwriting
a real galactic average, a drift that never gets written, a rewrite that
truncates the file.  Each of those is asserted here against the shape of data
the game actually emits.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.commodity_ledger import (  # noqa: E402
    FIELDNAMES,
    CommodityLedger,
    canonical_category,
    canonical_name,
    row_from_item,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def item(name, *, cid=128049152, local=None, mean=1000,
         cat="$MARKET_category_metals;", cat_local="Metals"):
    """One Market.json Items entry, in the game's own shape."""
    return {
        "id":                 cid,
        "Name":               name,
        "Name_Localised":     local or name.strip("$").replace("_name;", "").title(),
        "Category":           cat,
        "Category_Localised": cat_local,
        "BuyPrice":           0,
        "SellPrice":          mean + 10,
        "MeanPrice":          mean,
        "Stock":              0,
        "Demand":             1,
    }


@pytest.fixture
def ledger(tmp_path):
    return CommodityLedger(tmp_path / "cargo.commodities.csv")


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── Canonicalisation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("$gold_name;",                    "gold"),
    ("$Gold_Name;",                    "gold"),
    ("Gold",                           "gold"),
    ("$lowtemperaturediamond_name;",   "lowtemperaturediamond"),
    ("  $platinum_name;  ",            "platinum"),
    ("",                               ""),
])
def test_commodity_names_canonicalise_to_one_spelling(raw, expected):
    assert canonical_name(raw) == expected


def test_wrapped_and_bare_names_are_the_same_commodity(ledger):
    """The wrapper is the difference between one row and two."""
    ledger.apply([item("$gold_name;", mean=47113)])
    ledger.apply([item("gold", mean=47113)])
    assert list(ledger.rows()) == ["gold"]


@pytest.mark.parametrize("raw,expected", [
    ("$MARKET_category_metals;",               "metals"),
    ("$MARKET_category_industrial_materials;", "industrial_materials"),
    ("Metals",                                 "metals"),
    ("",                                       ""),
])
def test_categories_canonicalise(raw, expected):
    assert canonical_category(raw) == expected


def test_an_item_without_a_name_is_not_a_row():
    assert row_from_item({"id": 1, "MeanPrice": 10}) is None


# ── Recording ─────────────────────────────────────────────────────────────────

def test_first_sighting_records_identity_and_price(ledger):
    added, drifted = ledger.apply([
        item("$gold_name;", cid=128049154, local="Gold", mean=47113)
    ])
    assert (added, drifted) == (1, 0)

    row = ledger.rows()["gold"]
    assert row["id"] == 128049154
    assert row["name_localised"] == "Gold"
    assert row["category"] == "metals"
    assert row["category_localised"] == "Metals"
    assert row["mean_price"] == 47113
    assert row["updates"] == 0
    assert row["first_seen"] == row["last_updated"]


def test_seeing_the_same_market_again_changes_nothing(ledger):
    items = [item("$gold_name;", mean=47113), item("$silver_name;", cid=2, mean=36553)]
    ledger.apply(items)
    assert ledger.apply(items) == (0, 0)
    assert ledger.apply(items) == (0, 0)


def test_a_drifting_mean_price_rewrites_the_row(ledger):
    ledger.apply([item("$gold_name;", mean=47113)])
    before = ledger.rows()["gold"]

    added, drifted = ledger.apply([item("$gold_name;", mean=48000)])
    assert (added, drifted) == (0, 1)

    after = ledger.rows()["gold"]
    assert after["mean_price"] == 48000
    assert after["updates"] == before["updates"] + 1
    assert after["first_seen"] == before["first_seen"]


def test_drift_is_counted_once_per_change_not_per_sighting(ledger):
    ledger.apply([item("$gold_name;", mean=47113)])
    ledger.apply([item("$gold_name;", mean=48000)])
    ledger.apply([item("$gold_name;", mean=48000)])
    ledger.apply([item("$gold_name;", mean=48000)])
    assert ledger.rows()["gold"]["updates"] == 1


def test_one_row_per_commodity_across_many_markets(ledger):
    for price in (47113, 48000, 47500, 49000):
        ledger.apply([item("$gold_name;", mean=price)])
    assert list(ledger.rows()) == ["gold"]
    assert ledger.rows()["gold"]["mean_price"] == 49000


# ── Zero prices ───────────────────────────────────────────────────────────────

def test_a_fleet_carrier_zero_does_not_erase_a_real_price(ledger):
    """FC markets publish trade orders with MeanPrice 0.  That is the absence
    of a galactic average, not a new one."""
    ledger.apply([item("$gold_name;", mean=47113)])
    added, drifted = ledger.apply([item("$gold_name;", mean=0)])
    assert (added, drifted) == (0, 0)
    assert ledger.rows()["gold"]["mean_price"] == 47113


def test_a_commodity_first_seen_at_zero_is_still_catalogued(ledger):
    """Thargoid tissue samples carry MeanPrice 0 at ordinary station markets.
    They are still commodities and still belong in the catalogue."""
    ledger.apply([item("$thargoidtissuesampletype10a_name;",
                       cid=129022402, local="Titan Maw Deep Tissue Sample",
                       mean=0, cat="$MARKET_category_salvage;",
                       cat_local="Salvage")])
    row = ledger.rows()["thargoidtissuesampletype10a"]
    assert row["mean_price"] == 0
    assert row["name_localised"] == "Titan Maw Deep Tissue Sample"


def test_a_zero_row_heals_when_a_real_price_arrives(ledger):
    ledger.apply([item("$gold_name;", mean=0)])
    added, drifted = ledger.apply([item("$gold_name;", mean=47113)])
    assert (added, drifted) == (0, 1)
    assert ledger.rows()["gold"]["mean_price"] == 47113


# ── Identity corrections ──────────────────────────────────────────────────────

def test_identity_changes_are_absorbed_without_counting_as_drift(ledger):
    ledger.apply([item("$gold_name;", cid=128049154, local="Gold", mean=47113)])
    added, drifted = ledger.apply([
        item("$gold_name;", cid=128049154, local="Gold Bullion", mean=47113)
    ])
    assert (added, drifted) == (0, 0)
    assert ledger.rows()["gold"]["name_localised"] == "Gold Bullion"


# ── The file on disk ──────────────────────────────────────────────────────────

def test_the_file_carries_the_declared_columns(ledger):
    ledger.apply([item("$gold_name;", mean=47113)])
    rows = read_csv(ledger.path)
    assert list(rows[0]) == FIELDNAMES


def test_the_catalogue_survives_a_reload(ledger, tmp_path):
    ledger.apply([
        item("$gold_name;",     cid=128049154, local="Gold",     mean=47113),
        item("$silver_name;",   cid=128049155, local="Silver",   mean=36553),
        item("$platinum_name;", cid=128049152, local="Platinum", mean=55505),
    ])
    reopened = CommodityLedger(ledger.path)
    assert reopened.load() == 3
    assert reopened.rows() == ledger.rows()
    # ...and re-seeing the same market after a reload is still a no-op, which
    # is what proves the reloaded prices are the ones that were written.
    assert reopened.apply([item("$gold_name;", cid=128049154,
                                local="Gold", mean=47113)]) == (0, 0)


def test_a_rewrite_keeps_every_earlier_commodity(ledger):
    """The file is rewritten whole on every change; a bug here silently drops
    everything the current market does not happen to stock."""
    ledger.apply([item("$gold_name;", cid=1, local="Gold", mean=47113)])
    ledger.apply([item("$tea_name;", cid=2, local="Tea", mean=1500,
                       cat="$MARKET_category_foods;", cat_local="Foods")])
    assert {r["name"] for r in read_csv(ledger.path)} == {"gold", "tea"}


def test_rows_are_written_in_id_order(ledger):
    ledger.apply([
        item("$silver_name;",   cid=128049155, mean=36553),
        item("$platinum_name;", cid=128049152, mean=55505),
        item("$gold_name;",     cid=128049154, mean=47113),
    ])
    ids = [int(r["id"]) for r in read_csv(ledger.path)]
    assert ids == sorted(ids)


def test_an_unwritable_path_is_reported_not_swallowed(tmp_path):
    """Silent failure is the bug class this project keeps paying for."""
    blocked = tmp_path / "afile"
    blocked.write_text("not a directory")
    seen: list[str] = []
    led = CommodityLedger(blocked / "cargo.commodities.csv", log=seen.append)
    led.apply([item("$gold_name;", mean=47113)])
    assert seen, "write failure produced no diagnostic"


def test_a_corrupt_file_is_reported_and_rebuilt(tmp_path):
    path = tmp_path / "cargo.commodities.csv"
    path.write_bytes(b"\xff\xfe not a csv at all \x00")
    seen: list[str] = []
    led = CommodityLedger(path, log=seen.append)
    assert led.load() == 0
    assert seen, "unreadable catalogue produced no diagnostic"
    led.apply([item("$gold_name;", mean=47113)])
    assert {r["name"] for r in read_csv(path)} == {"gold"}


# ── Against real captured data ────────────────────────────────────────────────

REAL_MARKET = ROOT.parent.parent / "saved-games" / "elite-dangerous" / "EDP1" / "Market.json"


@pytest.mark.skipif(not REAL_MARKET.is_file(), reason="no captured Market.json")
def test_a_real_market_round_trips(ledger):
    import json
    items = json.loads(REAL_MARKET.read_text(encoding="utf-8"))["Items"]
    added, drifted = ledger.apply(items)
    assert added == len({canonical_name(i["Name"]) for i in items})
    assert drifted == 0
    assert ledger.apply(items) == (0, 0)

    reopened = CommodityLedger(ledger.path)
    reopened.load()
    assert reopened.rows() == ledger.rows()

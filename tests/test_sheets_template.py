"""
tests/test_sheets_template.py — a sheet built in place matches the template.

Pasting Loader.gs into a blank spreadsheet and running Install used to leave
the spreadsheet as it found it plus a bare Deposits tab: the upgrade steps only
ever adjusted tabs that already existed, on the assumption that everybody
started from Mining_Dashboard.xlsx. Template.gs now builds whatever dashboard
tabs are missing, from TEMPLATE — the constants the xlsx is built from, copied
into the bundle by build_bundle.py.

The comparison below is the point: the same tab built two ways, by openpyxl
into the xlsx and by Template.gs into a sheet, must say the same thing cell for
cell. Formatting is not compared; applyTheme() owns it in both, and the fake
does not model it.

Needs Node for the sheet side and openpyxl for the xlsx; skips without either.
"""
from __future__ import annotations

import copy
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

from test_sheets_loader import (COLUMNS, LAYOUT, LEGACY_DEPOSITS, TOKEN,  # noqa: E402
                                _run)

openpyxl = pytest.importorskip("openpyxl")
sys.path.insert(0, str(ROOT / "sheets"))
from build_dashboard import unwrap  # noqa: E402

XLSX = openpyxl.load_workbook(ROOT / "sheets" / "Mining_Dashboard.xlsx")
INSTALL_UI = ["YES", {"button": "OK", "text": TOKEN}]


def _install_into(sheets: dict, ui=INSTALL_UI, **kw) -> dict:
    return _run([{"call": "edldUpgrade"}], sheets=sheets, ui=ui, **kw)


@pytest.fixture(scope="module")
def blank():
    """A new spreadsheet, as Google makes one, with EDLD installed into it."""
    return _install_into({"Sheet1": []})


def _cells_xlsx(tab: str) -> dict:
    out = {}
    for row in XLSX[tab].iter_rows():
        for c in row:
            v = c.value
            if v is None or v == "":
                continue
            if isinstance(v, str) and v.startswith("=IFERROR(__xludf.DUMMYFUNCTION("):
                v = unwrap(v)
            out[c.coordinate] = v
    return out


def _cells_sheet(res: dict, tab: str) -> dict:
    from openpyxl.utils import get_column_letter
    out = {}
    for r, row in enumerate(res["sheets"][tab]["rows"], 1):
        for c, v in enumerate(row, 1):
            if v is None or v == "":
                continue
            out[f"{get_column_letter(c)}{r}"] = v
    return out


# ── a blank spreadsheet ───────────────────────────────────────────────────────

def test_a_blank_spreadsheet_gets_every_tab_in_order(blank):
    assert blank["order"] == ["Dashboard", "Settings", "Deposits", "Themes", "Queries"]
    assert blank["sheets"]["Themes"]["hidden"] and blank["sheets"]["Queries"]["hidden"]
    assert not blank["sheets"]["Dashboard"]["hidden"]
    assert blank["docProps"]["EDLD_SHEET_VERSION"] == str(LAYOUT)


def test_googles_empty_first_tab_is_removed(blank):
    assert "Sheet1" not in blank["order"]


def test_the_dashboard_freezes_above_the_table(blank):
    assert blank["sheets"]["Dashboard"]["frozen"] == 7


@pytest.mark.parametrize("tab", ["Settings", "Themes"])
def test_a_built_tab_says_exactly_what_the_xlsx_says(blank, tab):
    assert _cells_sheet(blank, tab) == _cells_xlsx(tab)


def test_queries_says_what_the_xlsx_says(blank):
    """Written by rebuildDashboard_ in the sheet and by openpyxl in the xlsx."""
    assert _cells_sheet(blank, "Queries") == _cells_xlsx("Queries")


def test_the_dashboard_says_what_the_xlsx_says(blank):
    assert _cells_sheet(blank, "Dashboard") == _cells_xlsx("Dashboard")


def test_the_deposits_header_is_the_xlsx_header(blank):
    assert blank["sheets"]["Deposits"]["rows"][0] == COLUMNS
    assert [c.value for c in XLSX["Deposits"][1]] == COLUMNS


# ── what is left alone ────────────────────────────────────────────────────────

OWNED_SETTINGS = [["Squadron", "Mining and Logistics, Ltd. [MALL]", "",
                   "My own note in D1"],
                  ["Maintainer", "Merrick Calbruin"], [], ["DASHBOARD THEME"],
                  ["Theme", "Alliance"]]


def test_an_existing_tab_is_not_rewritten():
    res = _install_into({"Settings": copy.deepcopy(OWNED_SETTINGS),
                         "Deposits": copy.deepcopy(LEGACY_DEPOSITS)})
    rows = res["sheets"]["Settings"]["rows"]
    assert rows[0][:2] == ["Squadron", "Mining and Logistics, Ltd. [MALL]"]
    assert rows[4][:2] == ["Theme", "Alliance"]
    assert rows[0][3] == "My own note in D1", "an owner's own D1 text is theirs"
    assert {"Dashboard", "Themes", "Queries"} <= set(res["order"])


def test_the_version_line_follows_the_release_while_it_is_ours():
    old = copy.deepcopy(OWNED_SETTINGS)
    old[0][3] = "Mining Dashboard v20260923 powered by EDLD"
    res = _install_into({"Settings": old})
    version = (ROOT / "version").read_text(encoding="utf-8").strip()
    assert res["sheets"]["Settings"]["rows"][0][3] == \
        f"Mining Dashboard v{version} powered by EDLD"


@pytest.mark.parametrize("name,rows", [
    ("Sheet1", [["something typed here"]]),   # not empty
    ("Notes", []),                            # empty, but somebody named it
])
def test_only_googles_empty_default_tab_is_removed(name, rows):
    res = _install_into({name: rows})
    assert name in res["order"]


def test_nothing_is_removed_when_nothing_was_built():
    """A complete sheet with a stray empty Sheet1 keeps it: an upgrade that
    builds no tabs has no business tidying the owner's."""
    first = _install_into({"Sheet1": []})
    sheets = {n: v["rows"] for n, v in first["sheets"].items()}
    sheets["Sheet2"] = []
    again = _run([{"call": "edldMenu2"}], sheets=sheets,       # Repair
                 script_props=first["scriptProps"], doc_props=first["docProps"])
    assert "Sheet2" in again["order"]


# ── Repair ────────────────────────────────────────────────────────────────────

def test_repair_rebuilds_a_tab_somebody_deleted(blank):
    sheets = {n: v["rows"] for n, v in blank["sheets"].items() if n != "Themes"}
    res = _run([{"call": "edldMenu2"}], sheets=sheets,
               script_props=blank["scriptProps"], doc_props=blank["docProps"])
    assert "Themes" in res["order"]
    assert any("rebuilt Themes" in t for t in res["toasts"])
    assert _cells_sheet(res, "Themes") == _cells_xlsx("Themes")

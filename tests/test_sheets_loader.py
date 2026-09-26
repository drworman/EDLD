"""
tests/test_sheets_loader.py — Installing and upgrading a sheet from its own menu.

Loader.gs is the one file a sheet owner pastes; everything else arrives through
ED Dashboard > Upgrade. These run the real Loader.gs and the real generated
bundle under Node, against tests/gas_fake.js, and check what an owner would
notice: that an old sheet comes through with every deposit intact, that
nothing is installed that does not match the release, that the token the
squadron holds survives, and that a second Upgrade is a no-op.

Skipped where Node is not installed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHEETS = ROOT / "sheets"
FAKE = ROOT / "tests" / "gas_fake.js"
LOADER = SHEETS / "Loader.gs"
BUNDLE = (SHEETS / "edld_sheet.js").read_text(encoding="utf-8")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")

RELEASE_URL = re.search(r"var EDLD_RELEASE_URL =\s*'([^']+)'",
                        LOADER.read_text(encoding="utf-8")).group(1)
BUNDLE_URL = "https://raw.githubusercontent.com/drworman/EDLD/T1/sheets/edld_sheet.js"
TOKEN = "squadron-token-0123456789"

COLUMNS = re.findall(r"'([a-z_]+)'", re.search(
    r"var COLUMNS = \[(.*?)\];", (SHEETS / "Code.gs").read_text(encoding="utf-8"),
    re.S).group(1))
HEADERS = re.findall(r"'([^']+)'", re.search(
    r"HEADERS: \[(.*?)\]", (SHEETS / "Dashboard.gs").read_text(encoding="utf-8"),
    re.S).group(1))


def _release(version="T1", bundle=BUNDLE, **over) -> dict:
    rel = {"version": version, "sheet_version": 1, "min_loader": 1,
           "bundle": {"url": BUNDLE_URL,
                      "sha256": hashlib.sha256(bundle.encode()).hexdigest()}}
    rel.update(over)
    return rel


def _run(steps, *, sheets=None, script_props=None, doc_props=None, ui=None,
         release=None, bundle=BUNDLE) -> dict:
    rel = release if release is not None else _release(bundle=bundle)
    spec = {
        "files": [str(LOADER)],
        "steps": steps,
        "sheets": sheets or {},
        "scriptProps": script_props or {},
        "docProps": doc_props or {},
        "ui": ui or [],
        "urls": {RELEASE_URL: json.dumps(rel), rel["bundle"]["url"]: bundle},
    }
    out = subprocess.run([NODE, str(FAKE)], input=json.dumps(spec),
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _install(**kw) -> dict:
    """A fresh install: confirm, then a token."""
    return _run([{"call": "edldUpgrade"}],
                ui=["YES", {"button": "OK", "text": TOKEN}], **kw)


def _ping(token=TOKEN):
    return {"post": {"token": token, "ping": True}}


# ── before anything is installed ──────────────────────────────────────────────

def test_a_web_request_before_install_says_what_to_do():
    res = _run([_ping()])
    assert res["results"][0]["ok"] is False
    assert "Upgrade" in res["results"][0]["error"]


def test_the_menu_before_install_offers_to_install():
    res = _run([{"call": "onOpen"}])
    labels = [label for label, _ in res["menus"][0]["items"]]
    assert labels[0] == "Install / Upgrade…"
    assert "Set sheet token…" in labels


# ── a fresh install ───────────────────────────────────────────────────────────

def test_a_fresh_install_answers_with_its_versions():
    res = _install()
    props = res["scriptProps"]
    assert props["EDLD_CODE_VERSION"] == "T1" and props["EDLD_TOKEN"] == TOKEN

    after = _run([_ping()], script_props=props, doc_props=res["docProps"])
    pong = after["results"][0]
    assert pong["ok"] and pong["columns"] == len(COLUMNS)
    assert pong["sheet_version"] == 1


def test_the_first_install_says_to_deploy_once():
    """The web app still serves the old pasted Code.gs until it is redeployed
    onto the loader — the one manual step, and it has to be said."""
    assert "New version" in _install()["alerts"][-1]


def test_the_menu_after_install_comes_from_the_bundle():
    res = _install()
    labels = [label for label, _ in res["menus"][-1]["items"]]
    assert labels[:3] == ["Apply theme", "Copy active theme to Custom",
                          "Repair dashboard formulas"]
    assert "Upgrade…" in labels


def test_code_too_big_for_one_property_is_split_and_reassembled():
    props = _install()["scriptProps"]
    parts = int(props["EDLD_CODE_PARTS"])
    assert parts > 1
    assert all(len(props[f"EDLD_CODE_{i}"]) <= 4000 for i in range(parts))
    assert "".join(props[f"EDLD_CODE_{i}"] for i in range(parts)) == BUNDLE


def test_a_blank_token_generates_one_and_shows_it():
    res = _run([{"call": "edldUpgrade"}], ui=["YES", {"button": "OK", "text": ""}])
    token = res["scriptProps"]["EDLD_TOKEN"]
    assert len(token) >= 32 and any(token in a for a in res["alerts"])


def test_cancelling_the_token_installs_nothing():
    res = _run([{"call": "edldUpgrade"}], ui=["YES", {"button": "CANCEL", "text": ""}])
    assert "EDLD_CODE_VERSION" not in res["scriptProps"]


# ── an old sheet, upgraded in place ───────────────────────────────────────────

LEGACY_DEPOSITS = [
    COLUMNS[:24],
    ["abc123def456", "Igbonii", 1, "Igbonii A 2 c", 7, "", 0.069, "", "", "",
     11, "Monazite", 1.5, 2.5, "", "Medium", "Depleted", 1, 3,
     "2026-09-01T00:00:00Z", "2026-09-12T00:00:00Z", "CMDR A", 0,
     {"__date": "2026-09-10T00:00:00.000Z"}],
    ["fed000000001", "Igbonii", 1, "Igbonii A 3", 9, "", 0.1, "", "", "",
     4, "Platinum", 3.0, 4.0, "", "High", "High", 2, 5,
     "2026-09-02T00:00:00Z", "2026-09-13T00:00:00Z", "CMDR B", 0, ""],
]
LEGACY_SHEETS = {
    "Deposits": LEGACY_DEPOSITS,
    "Dashboard": [["title"], [], [], ["System", "Commodity"], ["Igbonii", ""],
                  [], ["=IFERROR(__xludf.DUMMYFUNCTION(\"old\"),\"\")"]],
    "Queries": [["", "", "", "System", "Body", "Gravity", "Mining Site",
                 "Commodity", "Amount", "Density", "Rigs", "Depleted"]],
    "Settings": [["Squadron", "Mining and Logistics [MALL]"],
                 ["Maintainer", "Merrick Calbruin"]],
}


def _legacy():
    return _run([{"call": "edldUpgrade"}, _ping(),
                 {"post": {"token": TOKEN, "fetch": {"system_address": 1, "body_id": 7}}}],
                sheets=copy.deepcopy(LEGACY_SHEETS),
                ui=["YES", {"button": "OK", "text": TOKEN}])


def test_an_old_sheet_keeps_every_deposit():
    rows = _legacy()["sheets"]["Deposits"]["rows"]
    assert rows[0] == COLUMNS
    assert [r[0] for r in rows[1:]] == ["abc123def456", "fed000000001"]
    assert rows[1][COLUMNS.index("reported_by")] == "CMDR A"
    assert rows[2][COLUMNS.index("amount")] == "High"


def test_an_old_sheets_depletion_moves_out_of_the_amount():
    res = _legacy()
    row = res["sheets"]["Deposits"]["rows"][1]
    assert row[COLUMNS.index("amount")] == ""
    assert row[COLUMNS.index("depleted_on")] == "2026-09-10"
    fetched = res["results"][2]["deposits"][0]
    assert fetched["depleted_on"] == "2026-09-10" and fetched["amount"] == ""


def test_deposits_are_backed_up_first_as_they_were():
    res = _legacy()
    backups = {k: v for k, v in res["sheets"].items() if k.startswith("Deposits backup")}
    assert len(backups) == 1
    (backup,) = backups.values()
    assert backup["hidden"] is True
    assert backup["rows"][1][COLUMNS.index("amount")] == "Depleted"
    assert len(backup["rows"][0]) == 24


def test_an_old_dashboard_gains_the_notes_column():
    res = _legacy()
    assert res["sheets"]["Queries"]["rows"][0][3:3 + len(HEADERS)] == HEADERS
    assert res["sheets"]["Dashboard"]["rows"][6][0].startswith("=IF(")
    assert res["docProps"]["EDLD_SHEET_VERSION"] == "1"


def test_the_owners_settings_are_untouched():
    rows = _legacy()["sheets"]["Settings"]["rows"]
    assert rows[0][:2] == ["Squadron", "Mining and Logistics [MALL]"]
    assert rows[1][:2] == ["Maintainer", "Merrick Calbruin"]


def test_the_old_token_keeps_working():
    res = _legacy()
    assert res["results"][1]["ok"] is True


def test_a_receiver_only_sheet_upgrades_just_its_deposits():
    res = _run([{"call": "edldUpgrade"}],
               sheets={"Deposits": copy.deepcopy(LEGACY_DEPOSITS)},
               ui=["YES", {"button": "OK", "text": TOKEN}])
    assert set(res["sheets"]) == {"Deposits"} | {k for k in res["sheets"]
                                                  if k.startswith("Deposits backup")}
    assert res["sheets"]["Deposits"]["rows"][0] == COLUMNS


# ── the second time ───────────────────────────────────────────────────────────

def test_upgrading_an_up_to_date_sheet_changes_nothing():
    first = _legacy()
    again = _run([{"call": "edldUpgrade"}], sheets=None,
                 script_props=first["scriptProps"], doc_props=first["docProps"])
    assert "up to date" in again["alerts"][-1]
    assert again["scriptProps"] == first["scriptProps"]


def test_a_later_release_keeps_the_token_and_asks_nothing_else():
    first = _install()
    later = _run([{"call": "edldUpgrade"}], release=_release(version="T2"),
                 script_props=first["scriptProps"], doc_props=first["docProps"],
                 ui=["YES"])
    assert later["scriptProps"]["EDLD_CODE_VERSION"] == "T2"
    assert later["scriptProps"]["EDLD_TOKEN"] == TOKEN
    assert later["prompts"] == []
    assert "New version" not in later["alerts"][-1], "only the first install redeploys"


def test_declining_the_confirmation_changes_nothing():
    res = _run([{"call": "edldUpgrade"}], ui=["NO"])
    assert res["scriptProps"] == {} and res["fetched"] == [RELEASE_URL]


# ── what is refused ───────────────────────────────────────────────────────────

def test_code_that_does_not_match_the_manifest_is_not_installed():
    rel = _release()
    rel["bundle"]["sha256"] = "0" * 64
    res = _run([{"call": "edldUpgrade"}], release=rel, ui=["YES"])
    assert "does not match" in res["alerts"][-1]
    assert res["scriptProps"] == {}


def test_code_from_anywhere_but_github_raw_is_not_fetched():
    rel = _release()
    rel["bundle"]["url"] = "https://example.com/edld_sheet.js"
    res = _run([{"call": "edldUpgrade"}], release=rel, ui=["YES"])
    assert "refusing" in res["alerts"][-1]
    assert "https://example.com/edld_sheet.js" not in res["fetched"]


def test_a_release_needing_a_newer_loader_says_so_and_stops():
    res = _run([{"call": "edldUpgrade"}], release=_release(min_loader=99))
    assert "newer loader" in res["alerts"][-1]
    assert res["scriptProps"] == {} and len(res["fetched"]) == 1


def test_something_that_is_not_a_bundle_is_not_installed():
    res = _run([{"call": "edldUpgrade"}], bundle="return {};", ui=["YES"])
    assert "does not look like" in res["alerts"][-1]
    assert res["scriptProps"] == {}


def test_stored_code_that_was_altered_is_refused_on_use():
    props = dict(_install()["scriptProps"])
    props["EDLD_CODE_0"] = props["EDLD_CODE_0"].replace("deposit", "dep0sit", 1)
    res = _run([_ping()], script_props=props)
    assert res["results"][0]["ok"] is False
    assert "altered" in res["results"][0]["error"]


# ── the bundle and its manifest ───────────────────────────────────────────────

def test_the_committed_manifest_describes_the_committed_bundle():
    rel = json.loads((SHEETS / "release.json").read_text(encoding="utf-8"))
    assert rel["bundle"]["sha256"] == hashlib.sha256(BUNDLE.encode()).hexdigest()
    assert rel["version"] == (ROOT / "version").read_text(encoding="utf-8").strip()
    assert rel["bundle"]["url"].endswith(f"/{rel['version']}/sheets/edld_sheet.js")
    loader_version = int(re.search(r"var LOADER_VERSION = (\d+);",
                                   LOADER.read_text(encoding="utf-8")).group(1))
    assert rel["min_loader"] <= loader_version == rel["loader"]["version"]

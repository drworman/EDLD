"""
tests/test_sheets_loader.py — Installing and upgrading a sheet from its own menu.

Loader.gs is the one file a sheet owner pastes; everything else arrives through
ED Dashboard > Upgrade, from a branch of the repository — main unless the
owner picks another — with no tag or GitHub Release involved. These run the real Loader.gs and the real generated
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
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHEETS = ROOT / "sheets"
FAKE = ROOT / "tests" / "gas_fake.js"
LOADER = SHEETS / "Loader.gs"
BUNDLE = (SHEETS / "edld_sheet.js").read_text(encoding="utf-8")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")

REPO_RAW = re.search(r"var EDLD_REPO_RAW = '([^']+)'",
                     LOADER.read_text(encoding="utf-8")).group(1)


def _on(branch: str, name: str) -> str:
    return f"{REPO_RAW}/{branch}/sheets/{name}"


RELEASE_URL = _on("main", "release.json")
BUNDLE_URL = _on("main", "edld_sheet.js")
TOKEN = "squadron-token-0123456789"
#: The layout version the committed bundle brings a sheet to.
LAYOUT = json.loads((SHEETS / "release.json").read_text(encoding="utf-8"))["sheet_version"]

COLUMNS = re.findall(r"'([a-z_]+)'", re.search(
    r"var COLUMNS = \[(.*?)\];", (SHEETS / "Code.gs").read_text(encoding="utf-8"),
    re.S).group(1))
HEADERS = re.findall(r"'([^']+)'", re.search(
    r"HEADERS: \[(.*?)\]", (SHEETS / "Dashboard.gs").read_text(encoding="utf-8"),
    re.S).group(1))


def _release(version="T1", bundle=BUNDLE, **over) -> dict:
    rel = {"version": version, "sheet_version": LAYOUT, "min_loader": 1,
           "bundle": {"file": "edld_sheet.js",
                      "sha256": hashlib.sha256(bundle.encode()).hexdigest()}}
    rel.update(over)
    return rel


def _run(steps, *, sheets=None, script_props=None, doc_props=None, ui=None,
         release=None, bundle=BUNDLE, branch="main", urls=None) -> dict:
    """Run the loader with ``release`` and ``bundle`` published on ``branch``."""
    rel = release if release is not None else _release(bundle=bundle)
    published = {_on(branch, "release.json"): json.dumps(rel),
                 _on(branch, "edld_sheet.js"): bundle}
    spec = {
        "files": [str(LOADER)],
        "steps": steps,
        "sheets": sheets or {},
        "scriptProps": script_props or {},
        "docProps": doc_props or {},
        "ui": ui or [],
        "urls": urls if urls is not None else published,
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
    assert pong["sheet_version"] == LAYOUT


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
    assert res["docProps"]["EDLD_SHEET_VERSION"] == str(LAYOUT)


def test_an_old_sheet_missing_a_tab_gets_just_that_tab():
    """LEGACY_SHEETS has Dashboard, Queries and Settings but no Themes."""
    res = _legacy()
    assert "Themes" in res["sheets"] and res["sheets"]["Themes"]["hidden"]
    assert "added Themes" in res["alerts"][-1]
    assert "Settings, " not in res["alerts"][-1].split("added ")[1]


def test_the_owners_settings_are_untouched():
    rows = _legacy()["sheets"]["Settings"]["rows"]
    assert rows[0][:2] == ["Squadron", "Mining and Logistics [MALL]"]
    assert rows[1][:2] == ["Maintainer", "Merrick Calbruin"]


def test_the_old_token_keeps_working():
    res = _legacy()
    assert res["results"][1]["ok"] is True


def test_a_receiver_only_sheet_gains_the_dashboard_and_keeps_its_deposits():
    """Sheets set up by pasting Code.gs alone had nothing but Deposits."""
    res = _run([{"call": "edldUpgrade"}],
               sheets={"Deposits": copy.deepcopy(LEGACY_DEPOSITS)},
               ui=["YES", {"button": "OK", "text": TOKEN}])
    assert res["order"][:3] == ["Dashboard", "Settings", "Deposits"]
    rows = res["sheets"]["Deposits"]["rows"]
    assert rows[0] == COLUMNS
    assert [r[0] for r in rows[1:]] == ["abc123def456", "fed000000001"]


# ── the second time ───────────────────────────────────────────────────────────

def test_upgrading_an_up_to_date_sheet_changes_nothing():
    first = _legacy()
    again = _run([{"call": "edldUpgrade"}], sheets=None,
                 script_props=first["scriptProps"], doc_props=first["docProps"])
    assert "up to date" in again["alerts"][-1]
    assert again["scriptProps"] == first["scriptProps"]


def test_a_later_release_keeps_the_token_and_asks_nothing_else():
    first = _install()
    newer = BUNDLE + "\n// T2\n"
    later = _run([{"call": "edldUpgrade"}], bundle=newer,
                 release=_release(version="T2", bundle=newer),
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


@pytest.mark.parametrize("named", ["https://example.com/edld_sheet.js",
                                   "../main/sheets/edld_sheet.js", "a/b.js", ""])
def test_a_manifest_cannot_send_the_loader_anywhere_else(named):
    """The bundle comes from beside the manifest or not at all."""
    rel = _release()
    rel["bundle"]["file"] = named
    res = _run([{"call": "edldUpgrade"}], release=rel, ui=["YES"])
    assert res["scriptProps"] == {}
    assert res["fetched"] == [RELEASE_URL]


def test_a_release_url_elsewhere_is_not_fetched():
    elsewhere = "https://example.com/release.json"
    res = _run([{"call": "edldUpgrade"}], script_props={"EDLD_RELEASE_URL": elsewhere},
               urls={elsewhere: json.dumps(_release())})
    assert "refusing" in res["alerts"][-1] and res["fetched"] == []


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
    assert rel["version"] == (ROOT / "version").read_text(encoding="utf-8").strip(), (
        "release.json is stale — the version file changed and the bundle was not "
        "rebuilt. Run python3 sheets/build_bundle.py and commit the result.")
    assert rel["bundle"]["file"] == "edld_sheet.js"
    assert rel["loader"]["file"] == "Loader.gs"
    loader_version = int(re.search(r"var LOADER_VERSION = (\d+);",
                                   LOADER.read_text(encoding="utf-8")).group(1))
    assert rel["min_loader"] <= loader_version == rel["loader"]["version"]


# ── following a branch ────────────────────────────────────────────────────────

def _pick_branch(answer: str, props=None) -> dict:
    return _run([{"call": "edldSetBranch"}], script_props=props,
                ui=[{"button": "OK", "text": answer}])


def test_a_sheet_follows_main_until_told_otherwise():
    res = _install()
    assert res["fetched"] == [RELEASE_URL, BUNDLE_URL]
    assert res["scriptProps"]["EDLD_CODE_FROM"] == RELEASE_URL


def test_following_dev_takes_manifest_and_bundle_from_dev_with_no_tag():
    """What testing sheet code before a release needs: a pushed branch."""
    props = _pick_branch("dev")["scriptProps"]
    assert props["EDLD_BRANCH"] == "dev"
    res = _run([{"call": "edldUpgrade"}], branch="dev", script_props=props,
               ui=["YES", {"button": "OK", "text": TOKEN}])
    assert res["fetched"] == [_on("dev", "release.json"), _on("dev", "edld_sheet.js")]
    assert res["scriptProps"]["EDLD_CODE_VERSION"] == "T1"
    assert "branch dev" in res["alerts"][0]


def test_a_branch_with_a_slash_works():
    props = _pick_branch("exp/server-mode")["scriptProps"]
    res = _run([{"call": "edldUpgrade"}], branch="exp/server-mode", script_props=props,
               ui=["YES", {"button": "OK", "text": TOKEN}])
    assert res["scriptProps"]["EDLD_CODE_VERSION"] == "T1"


def test_a_blank_branch_goes_back_to_main():
    props = _pick_branch("dev")["scriptProps"]
    assert "EDLD_BRANCH" not in _pick_branch("", props)["scriptProps"]


@pytest.mark.parametrize("bad", ["-rf", "a..b", "has space", "x" * 101])
def test_a_branch_that_is_not_a_branch_name_is_refused(bad):
    res = _pick_branch(bad)
    assert "EDLD_BRANCH" not in res["scriptProps"]
    assert "not a branch name" in res["alerts"][-1]


def test_a_branch_with_no_release_says_so():
    """main has no sheets/release.json until the loader is merged."""
    res = _run([{"call": "edldUpgrade"}], urls={})
    msg = res["alerts"][-1]
    assert "no sheet release on branch main" in msg and "Update from branch" in msg
    assert res["scriptProps"] == {}


def test_a_new_build_with_the_same_version_is_installed():
    """On dev the version file stays put across commits; the hash does not."""
    first = _install(branch="dev", script_props={"EDLD_BRANCH": "dev"})
    rebuilt = BUNDLE + "\n// another dev commit\n"
    again = _run([{"call": "edldUpgrade"}], branch="dev", bundle=rebuilt,
                 release=_release(bundle=rebuilt),
                 script_props=first["scriptProps"], doc_props=first["docProps"],
                 ui=["YES"])
    new_sha = hashlib.sha256(rebuilt.encode()).hexdigest()
    assert again["scriptProps"]["EDLD_CODE_SHA256"] == new_sha
    assert new_sha[:8] in again["alerts"][0], "the hashes tell two T1s apart"


def test_a_stale_raw_copy_is_explained():
    """raw.githubusercontent.com caches for minutes after a push, so the
    manifest and the bundle can briefly disagree."""
    rel = _release(bundle=BUNDLE + "// newer, not yet served")
    res = _run([{"call": "edldUpgrade"}], release=rel, ui=["YES"])
    assert "wait five minutes" in res["alerts"][-1]
    assert res["scriptProps"] == {}


def test_stepping_back_to_an_older_layout_says_so_and_undoes_nothing():
    first = _install()
    older = BUNDLE + "\n// main, older\n"
    back = _run([{"call": "edldUpgrade"}], bundle=older,
                release=_release(version="T0", bundle=older, sheet_version=0),
                script_props=first["scriptProps"], doc_props=first["docProps"],
                ui=["YES"])
    assert "newer than this code expects" in back["alerts"][0]
    assert back["docProps"]["EDLD_SHEET_VERSION"] == str(LAYOUT)


def test_about_names_where_updates_come_from():
    res = _run([{"call": "edldAbout"}], script_props={"EDLD_BRANCH": "dev"})
    assert "branch dev (development builds)" in res["alerts"][0]


# ── the manifest is rebuilt when it must be ───────────────────────────────────

def test_the_bundle_check_passes_on_this_commit():
    out = subprocess.run([sys.executable, str(SHEETS / "build_bundle.py"), "--check"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_bundle_check_fails_after_a_version_bump(tmp_path):
    """The mistake that shipped a manifest naming the wrong version."""
    for name in ("edld_sheet.js", "release.json"):
        (tmp_path / name).write_bytes((SHEETS / name).read_bytes())
    out = subprocess.run([sys.executable, str(SHEETS / "build_bundle.py"), "--check",
                          "--out-dir", str(tmp_path), "--version", "29991231"],
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "stale" in out.stdout and "build_bundle.py" in out.stdout

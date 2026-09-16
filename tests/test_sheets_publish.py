"""
tests/test_sheets_publish.py — Publishing the survey to a sheet.

The failure this file mostly exists to prevent is the silent one: a send that
did not land being treated as one that did, so the deposits are marked
published locally and never sent again. Every path that is not an explicit
success from the script has to leave the rows pending.

The column order is also asserted against Code.gs, because the two sides place
values positionally and a field added to one and not the other lands in the
wrong column rather than raising anything.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.sheets_publish import (
    COLUMNS, SheetsPublisher, publisher_from_config, row_from_deposit,
    safe_endpoint,
)

URL = "https://script.google.com/macros/s/AKfyDEADBEEF/exec"


def _dep(dep_id="abc123def456", **over):
    base = {
        "deposit_id": dep_id, "system_name": "Eme", "system_address": 3657332462290,
        "body_name": "Eme A 1", "body_id": 14, "planet_class": "Rocky body",
        "gravity": 0.21, "radius_m": 1.5e6, "atmosphere": "", "volcanism": "",
        "signal_no": None, "commodity": "thortveitite",
        "commodity_display": "Thortveitite", "latitude": 77.09024,
        "longitude": -25.76536, "density_claimed": "", "density_observed": "High",
        "amount": "", "rigs": None, "refine_count": 12,
        "first_seen": "2026-09-13T19:49:48Z", "last_confirmed": "2026-09-13T20:10:00Z",
        "reported_by": "", "is_test": 0,
    }
    base.update(over)
    return base


def _responder(payload):
    """Build an opener returning a canned body, capturing what was sent."""
    sent = {}

    def opener(url, data, timeout):
        sent["url"] = url
        sent["body"] = json.loads(data.decode("utf-8"))
        return payload if isinstance(payload, str) else json.dumps(payload)

    return opener, sent


# ── the column contract ───────────────────────────────────────────────────────

def test_python_and_apps_script_agree_on_column_order():
    gs = (ROOT / "sheets" / "Code.gs").read_text(encoding="utf-8")
    block = re.search(r"var COLUMNS = \[(.*?)\];", gs, re.S)
    assert block, "COLUMNS not found in Code.gs"
    js_cols = tuple(re.findall(r"'([a-z_]+)'", block.group(1)))
    assert js_cols == COLUMNS, (
        "sheet columns are positional — Code.gs and sheets_publish.py must "
        "list the same fields in the same order")


def test_row_has_exactly_the_declared_columns():
    row = row_from_deposit(_dep())
    assert tuple(row.keys()) == COLUMNS


def test_reporter_fills_in_only_when_the_deposit_has_none():
    assert row_from_deposit(_dep(), "CMDR A")["reported_by"] == "CMDR A"
    assert row_from_deposit(_dep(reported_by="CMDR B"), "CMDR A")["reported_by"] \
        == "CMDR B"


def test_commodity_prefers_the_display_name():
    assert row_from_deposit(_dep())["commodity"] == "Thortveitite"
    assert row_from_deposit(_dep(commodity_display=""))["commodity"] \
        == "thortveitite"


# ── success ───────────────────────────────────────────────────────────────────

def test_a_good_send_reports_ids_for_marking():
    opener, sent = _responder({"ok": True, "added": 1, "updated": 0, "unchanged": 0})
    pub = SheetsPublisher(URL, "tok", opener=opener)
    res = pub.publish([_dep()])
    assert res.ok and res.added == 1
    assert res.sent_ids == ["abc123def456"]
    assert sent["body"]["token"] == "tok"
    assert len(sent["body"]["deposits"]) == 1


def test_an_empty_batch_is_a_no_op_not_a_send():
    calls = []

    def opener(url, data, timeout):
        calls.append(1)
        return json.dumps({"ok": True})

    res = SheetsPublisher(URL, "tok", opener=opener).publish([])
    assert res.ok and res.sent_ids == [] and not calls


def test_deposits_without_an_id_are_dropped_before_sending():
    opener, sent = _responder({"ok": True, "added": 1, "updated": 0, "unchanged": 0})
    pub = SheetsPublisher(URL, "tok", opener=opener)
    res = pub.publish([_dep(), _dep(dep_id="")])
    assert res.ok and len(sent["body"]["deposits"]) == 1


# ── every failure leaves the rows pending ─────────────────────────────────────

def test_a_rejected_token_is_not_a_success():
    opener, _ = _responder({"ok": False, "error": "bad token"})
    res = SheetsPublisher(URL, "tok", opener=opener).publish([_dep()])
    assert res.ok is False and res.sent_ids == [] and "bad token" in res.error


def test_an_html_error_page_is_reported_as_itself():
    opener, _ = _responder("<!DOCTYPE html>\n<html><title>Error</title>")
    res = SheetsPublisher(URL, "tok", opener=opener).publish([_dep()])
    assert res.ok is False and res.sent_ids == []
    assert "unreadable response" in res.error


def test_an_unreachable_host_is_reported_without_the_path():
    def opener(url, data, timeout):
        raise urllib.error.URLError("Name or service not known")

    res = SheetsPublisher(URL, "tok", opener=opener).publish([_dep()])
    assert res.ok is False and res.sent_ids == []
    assert "script.google.com" in res.error
    assert "AKfyDEADBEEF" not in res.error, "the deployment id must not be logged"


def test_an_http_error_is_reported():
    def opener(url, data, timeout):
        raise urllib.error.HTTPError(URL, 500, "boom", {}, None)

    res = SheetsPublisher(URL, "tok", opener=opener).publish([_dep()])
    assert res.ok is False and "HTTP 500" in res.error


def test_a_partial_write_is_a_failure():
    # Two rows sent, one accounted for. Marking both published would lose the
    # second permanently.
    opener, _ = _responder({"ok": True, "added": 1, "updated": 0, "unchanged": 0})
    pub = SheetsPublisher(URL, "tok", opener=opener)
    res = pub.publish([_dep("aaa"), _dep("bbb")])
    assert res.ok is False and res.sent_ids == []
    assert "1 of 2" in res.error


def test_an_unconfigured_publisher_refuses_rather_than_sends():
    res = SheetsPublisher("", "", opener=lambda *a: "").publish([_dep()])
    assert res.ok is False and "no web app URL or token" in res.error


# ── configuration and logging hygiene ─────────────────────────────────────────

def test_publisher_is_none_unless_enabled_and_complete():
    assert publisher_from_config({}) is None
    assert publisher_from_config({"Enabled": False, "WebAppURL": URL,
                                  "Token": "t"}) is None
    assert publisher_from_config({"Enabled": True, "WebAppURL": "",
                                  "Token": "t"}) is None
    assert publisher_from_config({"Enabled": True, "WebAppURL": URL,
                                  "Token": ""}) is None
    assert publisher_from_config({"Enabled": True, "WebAppURL": URL,
                                  "Token": "t"}) is not None


def test_safe_endpoint_keeps_only_the_host():
    assert safe_endpoint(URL) == "script.google.com"
    assert "AKfyDEADBEEF" not in safe_endpoint(URL)
    assert safe_endpoint("") == "<no host>"


def test_test_connection_sends_a_ping_and_reports_the_answer():
    opener, sent = _responder({"ok": True, "pong": True, "columns": len(COLUMNS)})
    res = SheetsPublisher(URL, "tok", opener=opener).test_connection()
    assert res.ok and sent["body"]["ping"] is True
    assert "deposits" not in sent["body"]


def test_a_failed_test_says_what_went_wrong():
    opener, _ = _responder({"ok": False, "error": "server token not configured"})
    res = SheetsPublisher(URL, "tok", opener=opener).test_connection()
    assert res.ok is False
    assert "server token not configured" in res.summary()


# ── store round trip ──────────────────────────────────────────────────────────

def test_store_to_sheet_round_trip_marks_only_on_success(tmp_path):
    """The whole path: record, read pending, publish, mark, re-read."""
    from core.mining_db import MiningDB

    db = MiningDB(tmp_path / "mining.db")
    db.upsert_body(3657332462290, 14, system_name="Eme", body_name="Eme A 1",
                   planet_class="Rocky body", radius_m=1.5e6)
    db.record_deposit(3657332462290, 14, "thortveitite", 77.09024, -25.76536,
                      commodity_display="Thortveitite", refined=True)

    pending = db.unpublished()
    assert len(pending) == 1
    assert pending[0]["system_name"] == "Eme", "the join must carry body facts"

    # A failed send leaves it pending.
    opener, _ = _responder({"ok": False, "error": "sheet busy, try again"})
    res = SheetsPublisher(URL, "tok", opener=opener).publish(pending)
    assert res.ok is False
    db.mark_published(res.sent_ids)
    assert len(db.unpublished()) == 1, "a failed send must not mark anything"

    # A good one does not.
    opener, sent = _responder({"ok": True, "added": 1, "updated": 0,
                               "unchanged": 0})
    res = SheetsPublisher(URL, "tok", opener=opener).publish(pending, "CMDR A")
    assert res.ok
    assert db.mark_published(res.sent_ids) == 1
    assert db.unpublished() == []

    row = sent["body"]["deposits"][0]
    assert row["reported_by"] == "CMDR A"
    assert row["body"] == "Eme A 1" and row["planet_class"] == "Rocky body"


# ── Apps Script transport quirks ──────────────────────────────────────────────

def test_a_302_becomes_a_get_as_apps_script_requires():
    """Apps Script answers a POST to /exec with a 302 to a temporary
    script.googleusercontent.com URL, and that URL is *not* another POST
    endpoint — re-posting the body there returns 405.

    An earlier version of this module re-issued the POST on the theory that a
    redirected POST becoming a GET was the bug. It was the opposite: the
    standard library's behaviour was already correct for 301/302/303, and
    forcing a POST broke the one thing that worked. 307/308 keep the method,
    as HTTP requires.
    """
    import urllib.request

    from core import sheets_publish as sp

    handler = next((getattr(sp, n)() for n in dir(sp)
                    if n.endswith("Redirects") or "Redirect" in n
                    if isinstance(getattr(sp, n), type)), None)
    if handler is None:
        pytest.skip("no custom redirect handler in this build")

    original = urllib.request.Request(
        URL, data=b'{"token":"t"}', method="POST",
        headers={"Content-Type": "application/json"})
    redirected = handler.redirect_request(
        original, None, 302, "Found", {},
        "https://script.googleusercontent.com/macros/echo?x=1")
    if redirected is not None:
        assert redirected.get_method() == "GET", \
            "a 302 from Apps Script must be followed as a GET"


def test_the_client_does_not_announce_itself_to_google():
    from core.sheets_publish import _USER_AGENT
    assert "EDLD" not in _USER_AGENT, \
        "script.google.com 403s unfamiliar clients"


# ── reading back ──────────────────────────────────────────────────────────────

def test_fetch_asks_for_one_body():
    """Scoped to a body because that is the question being asked — a commander
    arriving somewhere wants to know what is on this rock, and a squadron sheet
    will eventually have more rows than anyone wants to pull down to answer it."""
    opener, sent = _responder({"ok": True, "deposits": [_dep("aaa")]})
    rows, err = SheetsPublisher(URL, "tok", opener=opener).fetch_body(1234, 7)
    assert err == "" and len(rows) == 1
    assert sent["body"]["fetch"] == {"system_address": 1234, "body_id": 7}
    assert "deposits" not in sent["body"], "a fetch must not send rows"


def test_a_failed_fetch_returns_the_reason_not_an_exception():
    """A sheet that cannot be reached is a reason to have fewer deposits on the
    compass, not a reason to stop surveying."""
    opener, _ = _responder({"ok": False, "error": "bad token"})
    rows, err = SheetsPublisher(URL, "tok", opener=opener).fetch_body(1234, 7)
    assert rows == [] and "bad token" in err


def test_an_unreachable_sheet_fetch_is_reported():
    import urllib.error

    def opener(url, data, timeout):
        raise urllib.error.URLError("Name or service not known")

    rows, err = SheetsPublisher(URL, "tok", opener=opener).fetch_body(1, 2)
    assert rows == [] and "script.google.com" in err


def test_an_empty_body_fetches_cleanly():
    opener, _ = _responder({"ok": True, "deposits": []})
    rows, err = SheetsPublisher(URL, "tok", opener=opener).fetch_body(1, 2)
    assert rows == [] and err == ""

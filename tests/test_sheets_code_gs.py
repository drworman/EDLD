"""
tests/test_sheets_code_gs.py — The sheet's own half of the merge rules, run.

Code.gs decides what a write does to a row that is already there, and nothing
on the Python side can see that happen. These tests run the real file under
Node against a small in-memory stand-in for SpreadsheetApp, so the rules are
checked where they are enforced:

- a note is replaced by a newer-stamped note, a blank one included, and never
  by an older copy coming back round;
- amount and density fill blanks and change only on a newer correction, so a
  later sighting cannot put back a value somebody fixed;
- depletion is a date, the latest wins, and an old sheet's "Depleted" amount is
  cleared rather than kept;
- text that Sheets would run as a formula is stored as text;
- a sheet from before these columns gains them on its next write.

The stand-in stores a value with a leading apostrophe as the text after it,
which is what Sheets does. Skipped where Node is not installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CODE_GS = ROOT / "sheets" / "Code.gs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")

_HARNESS = r"""
const fs = require('fs');
const spec = JSON.parse(fs.readFileSync(0, 'utf8'));
let src = fs.readFileSync(spec.code, 'utf8');
const props = (init) => { const d = Object.assign({}, init);
  return { getProperty: (k) => (k in d ? d[k] : null), setProperty: (k, v) => { d[k] = String(v); } }; };
globalThis.PropertiesService = {
  getScriptProperties: ((p) => () => p)(props({ EDLD_TOKEN: 'tok' })),
  getDocumentProperties: ((p) => () => p)(props({})),
};

const raw = [];                        // every value as written, before storing
function store(v) {
  raw.push(v);
  return (typeof v === 'string' && v.startsWith("'")) ? v.slice(1) : v;
}
function makeSheet(rows) {
  rows = rows || [];
  const at = (r, c) => (rows[r - 1] && rows[r - 1][c - 1] !== undefined) ? rows[r - 1][c - 1] : '';
  const put = (r, c, v) => {
    while (rows.length < r) rows.push([]);
    while (rows[r - 1].length < c) rows[r - 1].push('');
    rows[r - 1][c - 1] = store(v);
  };
  const used = () => rows.filter(r => r.some(v => v !== '' && v !== null));
  return {
    rows,
    getLastRow: () => { let n = rows.length; while (n && !rows[n - 1].some(v => v !== '')) n--; return n; },
    getLastColumn: () => used().reduce((m, r) => { let n = r.length; while (n && r[n - 1] === '') n--; return Math.max(m, n); }, 0),
    getMaxRows: () => 1000,
    setFrozenRows: () => {},
    deleteRow: (r) => rows.splice(r - 1, 1),
    getRange: (r, c, nr = 1, nc = 1) => {
      const range = {
        getValues: () => Array.from({length: nr}, (_, i) => Array.from({length: nc}, (_, j) => at(r + i, c + j))),
        setValues: (vs) => { vs.forEach((row, i) => row.forEach((v, j) => put(r + i, c + j, v))); return range; },
        setValue: (v) => { put(r, c, v); return range; },
        setFontWeight: () => range,
        setNumberFormat: () => range,
      };
      return range;
    },
  };
}
const sheets = {};
if (spec.initial) sheets.Deposits = makeSheet(spec.initial);
globalThis.SpreadsheetApp = { getActiveSpreadsheet: () => ({
  getSheetByName: (n) => sheets[n] || null,
  insertSheet: (n) => (sheets[n] = makeSheet()),
}) };
globalThis.LockService = { getDocumentLock: () => ({ tryLock: () => true, releaseLock: () => {} }) };
globalThis.ContentService = { createTextOutput: (t) => ({ setMimeType: () => JSON.parse(t) }) };
globalThis.ContentService.MimeType = { JSON: 'json' };
globalThis.Utilities = { formatDate: (d) => d.toISOString().slice(0, 10) };
globalThis.Session = { getScriptTimeZone: () => 'UTC' };
(0, eval)(src);

const replies = spec.posts.map(body =>
  doPost({ postData: { contents: JSON.stringify(Object.assign({ token: 'tok' }, body)) } }));
process.stdout.write(JSON.stringify({ replies, rows: sheets.Deposits ? sheets.Deposits.rows : [], raw, columns: COLUMNS }));
"""


def _run(posts, initial=None) -> dict:
    spec = {"code": str(CODE_GS), "posts": posts, "initial": initial}
    out = subprocess.run([NODE, "-e", _HARNESS], input=json.dumps(spec),
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _dep(**kw) -> dict:
    d = {"deposit_id": "abc123def456", "system": "Igbonii", "system_address": 1,
         "body": "Igbonii A 2 c", "body_id": 7, "commodity": "Monazite",
         "latitude": 1.0, "longitude": 2.0, "last_confirmed": "2026-09-01T00:00:00Z"}
    d.update(kw)
    return d


def _cell(res: dict, field: str, row: int = 2):
    return res["rows"][row - 1][res["columns"].index(field)]


def _write(*deps):
    return [{"deposits": [d]} for d in deps]


# ── notes ─────────────────────────────────────────────────────────────────────

def test_a_newer_note_replaces_and_an_older_one_does_not():
    res = _run(_write(
        _dep(notes="first", notes_updated="2026-09-01T00:00:00Z"),
        _dep(notes="second", notes_updated="2026-09-02T00:00:00Z"),
        _dep(notes="first", notes_updated="2026-09-01T00:00:00Z",
             last_confirmed="2026-09-30T00:00:00Z"),
    ))
    assert _cell(res, "notes") == "second"


def test_a_newer_blank_note_withdraws_the_old_one():
    res = _run(_write(
        _dep(notes="going", notes_updated="2026-09-01T00:00:00Z"),
        _dep(notes="", notes_updated="2026-09-02T00:00:00Z"),
    ))
    assert _cell(res, "notes") == ""


def test_a_client_that_sends_no_note_leaves_it_alone():
    res = _run(_write(_dep(notes="keep", notes_updated="2026-09-01T00:00:00Z"),
                      _dep(last_confirmed="2026-09-05T00:00:00Z")))
    assert _cell(res, "notes") == "keep"


@pytest.mark.parametrize("text", ["=IMPORTXML(\"x\",\"//a\")", "+1", "-dangerous",
                                  "@me", "'tis a fine site"])
def test_text_sheets_would_run_is_stored_as_written(text):
    res = _run(_write(_dep(notes=text, notes_updated="2026-09-01T00:00:00Z")))
    assert _cell(res, "notes") == text
    assert "'" + text in res["raw"], "written with the text marker"


def test_a_fetch_returns_the_note_as_it_was_sent():
    res = _run(_write(_dep(notes="=SUM(1)", notes_updated="2026-09-01T00:00:00Z"))
               + [{"fetch": {"system_address": 1, "body_id": 7}}])
    assert res["replies"][-1]["deposits"][0]["notes"] == "=SUM(1)"


# ── amount and density ────────────────────────────────────────────────────────

def test_a_later_sighting_does_not_overwrite_an_amount():
    res = _run(_write(_dep(amount="High"),
                      _dep(amount="Low", last_confirmed="2026-09-30T00:00:00Z")))
    assert _cell(res, "amount") == "High"


def test_a_later_sighting_fills_a_blank_amount():
    res = _run(_write(_dep(), _dep(density_observed="Medium",
                                   last_confirmed="2026-09-30T00:00:00Z")))
    assert _cell(res, "density_observed") == "Medium"


def test_a_newer_correction_replaces_and_an_older_one_does_not():
    res = _run(_write(
        _dep(amount="High", assessment_updated="2026-09-01T00:00:00Z"),
        _dep(amount="Low", assessment_updated="2026-09-02T00:00:00Z"),
        _dep(amount="High", assessment_updated="2026-09-01T00:00:00Z",
             last_confirmed="2026-09-30T00:00:00Z"),
    ))
    assert _cell(res, "amount") == "Low"
    assert _cell(res, "assessment_updated") == "2026-09-02T00:00:00Z"


# ── depletion ─────────────────────────────────────────────────────────────────

def test_the_latest_depletion_date_wins_whoever_sent_it_last():
    res = _run(_write(_dep(depleted_on="2026-09-10"),
                      _dep(depleted_on="2026-09-05", last_confirmed="2026-09-30T00:00:00Z"),
                      _dep(depleted_on="2026-09-20")))
    assert _cell(res, "depleted_on") == "2026-09-20"


def test_a_depletion_date_is_written_as_text():
    """Otherwise Sheets parses it into its own timezone and reads back a Date."""
    res = _run(_write(_dep(depleted_on="2026-09-10")))
    assert "'2026-09-10" in res["raw"]


def test_an_old_sheets_depleted_amount_is_cleared_and_not_served():
    header = _run([])["columns"]
    old = [header[:24],
           ["abc123def456", "Igbonii", 1, "Igbonii A 2 c", 7, "", "", "", "", "",
            "", "Monazite", 1.0, 2.0, "", "", "Depleted", "", "", "",
            "2026-09-01T00:00:00Z", "", 0, "2026-09-01"]]
    fetched = _run([{"fetch": {"system_address": 1, "body_id": 7}}], initial=old)
    assert fetched["replies"][0]["deposits"][0]["amount"] == ""

    touched = _run(_write(_dep(last_confirmed="2026-09-30T00:00:00Z")), initial=old)
    assert _cell(touched, "amount") == ""
    assert _cell(touched, "depleted_on") == "2026-09-01"


# ── an older sheet ────────────────────────────────────────────────────────────

def test_a_sheet_from_before_the_new_columns_gains_them():
    cols = _run([])["columns"]
    old = [cols[:24],
           ["abc123def456", "Igbonii", 1, "Igbonii A 2 c", 7, "", "", "", "", "",
            "", "Monazite", 1.0, 2.0, "", "", "High", "", "", "",
            "2026-09-01T00:00:00Z", "", 0, ""]]
    res = _run(_write(_dep(notes="now stored", notes_updated="2026-09-02T00:00:00Z")),
               initial=old)
    assert res["rows"][0] == cols
    assert _cell(res, "notes") == "now stored"
    assert _cell(res, "amount") == "High"


def test_the_ping_reports_every_column():
    res = _run([{"ping": True}])
    assert res["replies"][0]["columns"] == len(res["columns"])

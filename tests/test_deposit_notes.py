"""
tests/test_deposit_notes.py — A commander's note on a deposit, end to end.

A note is the one deposit field that is writing rather than observation, and
the rest of the survey's merge rules are built for observation: fill blanks,
follow the freshest sighting, never let a blank overwrite. Applied to a note
those rules would make it impossible to withdraw, and would let anyone who
drove onto a site re-send a copy they imported weeks ago over its author's
correction. These tests pin the rule that replaces them — the most recently
written note wins, a blank one included — at every place a note passes
through: the form, the store, the publisher and the import from the sheet.
The sheet's own half is in test_sheets_code_gs.py.
"""
from __future__ import annotations

import inspect
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import mining_db
from core.deposit_form import FIELDS, clean, prefill
from core.mining_db import MAX_NOTES_CHARS, MiningDB, clean_notes
from core.sheets_publish import COLUMNS, SheetsPublisher, row_from_deposit

SA, BODY = 1234, 7


@pytest.fixture()
def db(tmp_path) -> MiningDB:
    d = MiningDB(tmp_path / "mining.db")
    d.upsert_body(SA, BODY, system_name="Test", body_name="Test A 1",
                  radius_m=1.5e6)
    return d


def _deposit(db: MiningDB) -> str:
    did, created = db.record_deposit(SA, BODY, "monazite", 10.0, 20.0,
                                     amount="High")
    assert created
    return did


def _row(db: MiningDB, did: str) -> dict:
    return next(d for d in db.deposits_on(SA, BODY) if d["deposit_id"] == did)


def _sheet_row(did: str, **kw) -> dict:
    row = {"deposit_id": did, "system_address": SA, "body_id": BODY,
           "commodity": "monazite", "latitude": 10.0, "longitude": 20.0}
    row.update(kw)
    return row


# ── the store ─────────────────────────────────────────────────────────────────

def test_a_new_store_has_notes(db):
    assert db.current_version() == mining_db.SCHEMA_VERSION >= 2
    did = _deposit(db)
    assert _row(db, did)["notes"] == "" and _row(db, did)["notes_updated"] == ""


def test_a_version_one_store_gains_notes_and_keeps_its_deposits(tmp_path):
    """Built exactly as 20260923 left it: the v1 schema, version 1 in meta."""
    path = tmp_path / "mining.db"
    conn = sqlite3.connect(path)
    conn.executescript(mining_db._SCHEMA)
    conn.execute("INSERT INTO meta VALUES('schema_version','1')")
    conn.execute("INSERT INTO bodies(system_address, body_id, updated_at) "
                 "VALUES(?,?,'2026-09-01T00:00:00Z')", (SA, BODY))
    conn.execute(
        "INSERT INTO deposits(deposit_id, system_address, body_id, commodity,"
        " latitude, longitude, amount, first_seen, last_confirmed, published_at)"
        " VALUES('abc123def456',?,?,'monazite',1,2,'High',"
        " '2026-09-01T00:00:00Z','2026-09-01T00:00:00Z','2026-09-01T00:00:00Z')",
        (SA, BODY))
    conn.commit()
    conn.close()

    db = MiningDB(path)
    assert db.current_version() == mining_db.SCHEMA_VERSION
    row = _row(db, "abc123def456")
    assert row["amount"] == "High" and row["notes"] == ""
    # Migrating is not a change to the deposit: it is not queued to publish.
    assert row["published_at"] == "2026-09-01T00:00:00Z"


def test_migration_tolerates_columns_already_present(tmp_path):
    """A store copied back from a newer build: columns there, version behind."""
    db = MiningDB(tmp_path / "mining.db")
    db.current_version()
    db.close()
    conn = sqlite3.connect(tmp_path / "mining.db")
    conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    assert MiningDB(tmp_path / "mining.db").current_version() == \
        mining_db.SCHEMA_VERSION


def test_writing_a_note_stamps_it_and_queues_a_publish(db):
    did = _deposit(db)
    db.mark_published([did])
    assert db.annotate_deposit(did, notes="Approach from the north ridge")
    row = _row(db, did)
    assert row["notes"] == "Approach from the north ridge"
    assert row["notes_updated"] and row["published_at"] == ""


def test_saving_the_same_note_again_changes_nothing(db):
    did = _deposit(db)
    db.annotate_deposit(did, notes="Canyon floor")
    stamp = _row(db, did)["notes_updated"]
    db.mark_published([did])
    assert db.annotate_deposit(did, notes="Canyon floor") is False
    row = _row(db, did)
    assert row["notes_updated"] == stamp and row["published_at"] != ""


def test_an_empty_note_withdraws_the_old_one(db):
    did = _deposit(db)
    db.annotate_deposit(did, notes="Pirates in orbit")
    assert db.annotate_deposit(did, notes="")
    assert _row(db, did)["notes"] == ""
    assert _row(db, did)["notes_updated"]


def test_leaving_notes_out_leaves_the_note_alone(db):
    """Every other caller — the proximity confirm, the Survey tab's flag —
    annotates without mentioning notes, and must not blank one."""
    did = _deposit(db)
    db.annotate_deposit(did, notes="Keep this")
    stamp = _row(db, did)["notes_updated"]
    assert db.annotate_deposit(did, amount="Low")
    assert _row(db, did)["notes"] == "Keep this"
    assert _row(db, did)["notes_updated"] == stamp


def test_a_note_alone_is_enough_to_save(db):
    did = _deposit(db)
    assert db.annotate_deposit(did, notes="Only a note")
    assert _row(db, did)["amount"] == "High"


def test_a_depletion_date_still_works_beside_an_unchanged_note(db):
    did = _deposit(db)
    db.annotate_deposit(did, notes="n")
    assert db.annotate_deposit(did, notes="n", depleted_on="2026-09-01")
    assert _row(db, did)["amount"] == "High"
    assert db.depletion_history(did)[-1]["noted_at"].startswith("2026-09-01")


def test_the_note_reaches_the_publisher(db):
    did = _deposit(db)
    db.annotate_deposit(did, notes="line one\nline two")
    pending = [d for d in db.unpublished() if d["deposit_id"] == did][0]
    row = row_from_deposit(pending)
    assert row["notes"] == "line one\nline two"
    assert row["notes_updated"] == pending["notes_updated"] != ""
    assert set(row) == set(COLUMNS)


# ── importing from the sheet ──────────────────────────────────────────────────

def test_an_imported_deposit_brings_its_note(db):
    added, _ = db.import_deposits([_sheet_row(
        "fed000000001", notes="Found by a wingmate",
        notes_updated="2026-09-20T10:00:00Z")])
    assert added == 1
    row = _row(db, "fed000000001")
    assert row["notes"] == "Found by a wingmate"
    assert row["notes_updated"] == "2026-09-20T10:00:00Z"
    assert row["published_at"], "imported rows are never sent back up"


def test_a_newer_note_from_the_sheet_replaces_mine(db):
    did = _deposit(db)
    db.annotate_deposit(did, notes="mine")
    db.import_deposits([_sheet_row(did, notes="theirs",
                                   notes_updated="2999-01-01T00:00:00Z")])
    assert _row(db, did)["notes"] == "theirs"


def test_a_newer_blank_from_the_sheet_withdraws_mine(db):
    did = _deposit(db)
    db.annotate_deposit(did, notes="about to be withdrawn")
    db.import_deposits([_sheet_row(did, notes="",
                                   notes_updated="2999-01-01T00:00:00Z")])
    assert _row(db, did)["notes"] == ""


def test_an_older_note_from_the_sheet_does_not_undo_mine(db):
    """The stale echo: somebody's imported copy, sent back with an old stamp."""
    did = _deposit(db)
    db.annotate_deposit(did, notes="corrected")
    db.import_deposits([_sheet_row(did, notes="original",
                                   notes_updated="2000-01-01T00:00:00Z")])
    assert _row(db, did)["notes"] == "corrected"


def test_a_note_typed_into_the_sheet_fills_only_a_blank(db):
    """Unstamped because nobody's EDLD wrote it — a person did, in the sheet."""
    blank = _deposit(db)
    db.import_deposits([_sheet_row(blank, notes="typed in the sheet")])
    assert _row(db, blank)["notes"] == "typed in the sheet"

    db.annotate_deposit(blank, notes="mine")
    db.import_deposits([_sheet_row(blank, notes="typed again")])
    assert _row(db, blank)["notes"] == "mine"


def test_an_imported_note_is_normalised_and_capped(db):
    db.import_deposits([_sheet_row(
        "fed000000002", notes="  a\r\nb\tc\x07  " + "x" * (MAX_NOTES_CHARS * 2),
        notes_updated="2026-09-20T10:00:00Z")])
    note = _row(db, "fed000000002")["notes"]
    assert note.startswith("a\nb c") and "\x07" not in note
    assert len(note) == MAX_NOTES_CHARS


# ── the form ──────────────────────────────────────────────────────────────────

def test_notes_is_the_last_field_and_multi_line():
    assert FIELDS[-1].key == "notes" and FIELDS[-1].kind == "note"


@pytest.mark.parametrize("typed,stored", [
    ("  plain  ", "plain"),
    ("a\r\nb", "a\nb"),
    ("a\rb", "a\nb"),
    ("tab\there", "tab here"),
    ("trailing   \nspace", "trailing\nspace"),
    ("bell\x07gone", "bellgone"),
    ("", ""),
])
def test_a_note_is_normalised(typed, stored):
    assert clean({"notes": typed}).values["notes"] == stored


def test_an_emptied_note_is_a_value_not_an_absence():
    """The one field where blank means nothing rather than leave-it-alone."""
    assert clean({"notes": ""}).values == {"notes": ""}
    assert "notes" not in clean({}).values


def test_an_over_long_note_is_refused_with_its_length():
    res = clean({"notes": "x" * (MAX_NOTES_CHARS + 5)})
    assert "notes" not in res.values
    assert str(MAX_NOTES_CHARS + 5) in res.errors["notes"]


def test_the_limit_itself_is_accepted():
    assert len(clean({"notes": "x" * MAX_NOTES_CHARS}).values["notes"]) == \
        MAX_NOTES_CHARS


def test_prefill_shows_the_stored_note():
    assert prefill({"commodity": "monazite", "notes": "hello"})["notes"] == "hello"
    assert prefill({"commodity": "monazite", "notes": None})["notes"] == ""


def test_everything_the_form_returns_the_store_can_take():
    """submit_form passes the cleaned values straight to annotate_deposit, so a
    field the form knows and the store does not is a TypeError on Save."""
    full = {f.key: "" for f in FIELDS}
    full.update(commodity="Monazite", amount="High", density_observed="Low",
                depleted_on="2026-09-01", rigs="2", signal_no="3",
                is_test="true", notes="n")
    values = clean(full).values
    for handled_by_record in ("commodity", "commodity_display"):
        values.pop(handled_by_record)
    params = inspect.signature(MiningDB.annotate_deposit).parameters
    assert set(values) <= set(params)


def test_clean_notes_is_what_the_store_uses_for_imports():
    assert clean_notes("x" * (MAX_NOTES_CHARS + 1)) == "x" * MAX_NOTES_CHARS


# ── the sheet's script is new enough ──────────────────────────────────────────

def _ping(columns: int):
    def opener(url, data, timeout):
        return json.dumps({"ok": True, "pong": True, "columns": columns})
    return SheetsPublisher("https://script.google.com/macros/s/X/exec", "t",
                           opener=opener).test_connection()


def test_a_script_without_the_notes_columns_fails_the_test():
    """It would accept every write and drop the note without a word."""
    res = _ping(24)
    assert res.ok is False
    assert "notes" in res.error and "Code.gs" in res.error


def test_a_current_script_passes_the_test():
    assert _ping(len(COLUMNS)).ok


def test_a_script_that_does_not_say_is_not_failed_for_it():
    assert _ping(0).ok

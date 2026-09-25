"""
tests/test_deposit_assessment.py — Amount, density and depletion, as recorded.

Amount and density are what the HUD says a site holds when it is full. They
are filled in once and changed only when somebody corrects them; a later
sighting does not overturn them. Depletion is not an amount at all — it is the
date a site was last worked out, and nothing else about the deposit moves when
it is set. These pin both rules in the store, the form's path into it, the
import from the sheet and the upgrade of a store written before either rule.
The sheet's side is in test_sheets_code_gs.py.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import mining_db
from core.mining_db import AMOUNT_LEVELS, MiningDB, replenishes_on
from core.sheets_publish import row_from_deposit

SA, BODY = 1234, 7


@pytest.fixture()
def db(tmp_path) -> MiningDB:
    d = MiningDB(tmp_path / "mining.db")
    d.upsert_body(SA, BODY, system_name="Test", body_name="Test A 1", radius_m=1.5e6)
    return d


def _row(db, did):
    return next(d for d in db.deposits_on(SA, BODY) if d["deposit_id"] == did)


def _new(db, **kw):
    did, _ = db.record_deposit(SA, BODY, "monazite", 10.0, 20.0, **kw)
    return did


def test_depleted_is_not_an_amount():
    assert "Depleted" not in AMOUNT_LEVELS
    assert AMOUNT_LEVELS == ("Low", "Medium", "High")


# ── assessments ───────────────────────────────────────────────────────────────

def test_a_later_sighting_does_not_overturn_an_amount(db):
    did = _new(db, amount="High", density_observed="Medium")
    db.record_deposit(SA, BODY, "monazite", 10.0, 20.0, amount="Low",
                      density_observed="High", refined=True)
    row = _row(db, did)
    assert (row["amount"], row["density_observed"]) == ("High", "Medium")


def test_a_correction_is_stamped_and_published(db):
    did = _new(db, amount="High")
    db.mark_published([did])
    assert db.annotate_deposit(did, amount="Low")
    row = _row(db, did)
    assert row["amount"] == "Low" and row["assessment_updated"]
    sent = row_from_deposit(db.unpublished()[0])
    assert sent["assessment_updated"] == row["assessment_updated"]


def test_restating_an_amount_is_not_a_correction(db):
    did = _new(db, amount="High")
    assert db.annotate_deposit(did, amount="High") is False
    assert _row(db, did)["assessment_updated"] == ""


def test_changing_something_else_does_not_stamp_the_assessment(db):
    did = _new(db, amount="High")
    db.annotate_deposit(did, rigs=3, notes="n")
    assert _row(db, did)["assessment_updated"] == ""


def _sheet(did, **kw):
    row = {"deposit_id": did, "system_address": SA, "body_id": BODY,
           "commodity": "monazite", "latitude": 10.0, "longitude": 20.0}
    row.update(kw)
    return row


def test_a_newer_correction_from_the_sheet_replaces_mine(db):
    did = _new(db, amount="High")
    db.import_deposits([_sheet(did, amount="Low", density_observed="High",
                               assessment_updated="2999-01-01T00:00:00Z")])
    row = _row(db, did)
    assert (row["amount"], row["density_observed"]) == ("Low", "High")


def test_an_older_correction_does_not(db):
    did = _new(db)
    db.annotate_deposit(did, amount="Medium")
    db.import_deposits([_sheet(did, amount="High",
                               assessment_updated="2000-01-01T00:00:00Z")])
    assert _row(db, did)["amount"] == "Medium"


def test_an_uncorrected_sheet_value_only_fills_a_blank(db):
    mine = _new(db, amount="High")
    db.import_deposits([_sheet(mine, amount="Low")])
    assert _row(db, mine)["amount"] == "High"
    did, _ = db.record_deposit(SA, BODY, "silver", 11.0, 21.0)
    db.import_deposits([_sheet(did, commodity="silver", latitude=11.0,
                               longitude=21.0, amount="Low")])
    assert _row(db, did)["amount"] == "Low"


def test_an_old_sheets_depleted_amount_is_not_imported(db):
    db.import_deposits([_sheet("fed000000009", amount="Depleted",
                               depleted_on="2026-09-10")])
    row = _row(db, "fed000000009")
    assert row["amount"] == "" and row["depleted_on"].startswith("2026-09-10")


# ── depletion ─────────────────────────────────────────────────────────────────

def test_a_depletion_date_touches_nothing_but_the_log(db):
    did = _new(db, amount="High", density_observed="Low")
    assert db.annotate_deposit(did, depleted_on="2026-09-14")
    row = _row(db, did)
    assert (row["amount"], row["density_observed"]) == ("High", "Low")
    assert row["assessment_updated"] == ""
    assert row["depleted_on"].startswith("2026-09-14")


def test_refill_is_unknown_until_it_is_measured():
    assert mining_db.REPLENISH_DAYS is None
    assert replenishes_on("2026-09-14") == ""


def test_a_known_refill_period_turns_every_date_into_a_refresh(monkeypatch):
    monkeypatch.setattr(mining_db, "REPLENISH_DAYS", 30)
    assert replenishes_on("2026-09-14T00:00:00Z") == "2026-10-14"
    assert replenishes_on("") == "" and replenishes_on("garbage") == ""


# ── a store written before these rules ────────────────────────────────────────

def _v1_store(path: Path, amount: str, logged: bool) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(mining_db._SCHEMA)
    conn.execute("INSERT INTO meta VALUES('schema_version','1')")
    conn.execute("INSERT INTO bodies(system_address, body_id, updated_at) "
                 "VALUES(?,?,'2026-09-01T00:00:00Z')", (SA, BODY))
    conn.execute(
        "INSERT INTO deposits(deposit_id, system_address, body_id, commodity,"
        " latitude, longitude, amount, first_seen, last_confirmed, published_at)"
        " VALUES('abc123def456',?,?,'monazite',1,2,?,'2026-09-01T00:00:00Z',"
        " '2026-09-12T08:00:00Z','2026-09-12T09:00:00Z')", (SA, BODY, amount))
    if logged:
        conn.execute("INSERT INTO depletion_log VALUES('abc123def456',"
                     "'2026-09-10T00:00:00Z','Worked out 2026-09-10')")
    conn.commit()
    conn.close()


def test_an_old_depleted_amount_becomes_a_date(tmp_path):
    _v1_store(tmp_path / "m.db", "Depleted", logged=False)
    row = _row(MiningDB(tmp_path / "m.db"), "abc123def456")
    assert row["amount"] == ""
    assert row["depleted_on"] == "2026-09-12T08:00:00Z", "dated by its last sighting"
    assert row["published_at"] == "2026-09-12T09:00:00Z", "not news for the sheet"


def test_an_old_depleted_amount_keeps_the_date_it_already_had(tmp_path):
    _v1_store(tmp_path / "m.db", "Depleted", logged=True)
    db = MiningDB(tmp_path / "m.db")
    assert _row(db, "abc123def456")["depleted_on"].startswith("2026-09-10")
    assert len(db.depletion_history("abc123def456")) == 1


def test_a_real_amount_survives_the_upgrade(tmp_path):
    _v1_store(tmp_path / "m.db", "High", logged=False)
    row = _row(MiningDB(tmp_path / "m.db"), "abc123def456")
    assert row["amount"] == "High" and row["depleted_on"] is None


# ── the desktop form ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_the_desktop_form_offers_no_depleted_amount_and_a_note_box(qapp):
    from PySide6.QtWidgets import QComboBox, QPlainTextEdit

    from core.deposit_form import prefill
    from gui.deposit_dialog import DepositDialog

    class _Plugin:
        submitted = None

        def form_for_here(self):
            return prefill({"commodity": "monazite", "amount": "High",
                            "notes": "north ridge\nno SRV"}), "Editing"

        def submit_form(self, values):
            self.submitted = values
            return "updated abc"

    plugin = _Plugin()
    dlg = DepositDialog(plugin)
    amount = dlg._widgets["amount"]
    assert isinstance(amount, QComboBox)
    assert [amount.itemData(i) for i in range(amount.count())] == ["", *AMOUNT_LEVELS]

    notes = dlg._widgets["notes"]
    assert isinstance(notes, QPlainTextEdit)
    assert notes.toPlainText() == "north ridge\nno SRV"
    notes.setPlainText("changed")
    dlg._save()
    assert plugin.submitted["notes"] == "changed"
    assert plugin.submitted["amount"] == "High"

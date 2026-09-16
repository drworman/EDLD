"""
tests/test_surface_survey.py — Surface mining survey: join, identity, dedupe.

The three things that can silently corrupt the survey are tested here:

  * a refine matched to the wrong position, or to none when one exists;
  * a deposit given a new identity every time it is seen, filling the store
    and then the shared sheet with duplicates of one rock;
  * the commodity ledger merge dropping an observation count.

Each of those produces data that looks entirely reasonable, which is why they
get tests rather than a careful read.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import surface_survey as survey
from core.surface_survey import Position, PositionRing, parse_journal_ts
from core.mining_db import MiningDB, deposit_id, DEDUPE_RADIUS_M
from core.data_migrate import migrate_to_shared


# ── position ring and the time join ───────────────────────────────────────────

def _pos(ts: float, lat=10.0, lon=20.0, in_srv=True) -> Position:
    return Position(ts=ts, latitude=lat, longitude=lon, heading=0.0,
                    body_name="Test A 1", radius_m=1.5e6, in_srv=in_srv)


def test_ring_matches_nearest_sample_within_window():
    ring = PositionRing()
    for t in (100.0, 100.5, 101.0, 101.5):
        ring.add(_pos(t, lat=t))
    got = ring.at(101.2)
    assert got is not None
    assert got.latitude == pytest.approx(101.0)


def test_ring_returns_none_outside_window():
    ring = PositionRing()
    ring.add(_pos(100.0))
    assert ring.at(105.0) is None


def test_ring_is_bounded():
    ring = PositionRing(size=4)
    for t in range(10):
        ring.add(_pos(float(t)))
    assert len(ring) == 4
    assert ring.latest().ts == 9.0


def test_journal_timestamp_parses_and_survives_rubbish():
    # Verified independently with calendar.timegm, not with the parser.
    assert parse_journal_ts("2026-09-13T19:49:48Z") == pytest.approx(1789328988.0)
    assert parse_journal_ts("") is None
    assert parse_journal_ts("not a timestamp") is None
    assert parse_journal_ts(None) is None


def test_surface_refine_requires_an_srv():
    assert survey.is_surface_refine(_pos(1.0, in_srv=True)) is True
    assert survey.is_surface_refine(_pos(1.0, in_srv=False)) is False
    assert survey.is_surface_refine(None) is False


def test_position_from_status_requires_the_latlong_flag():
    payload = {"Flags": 0, "Latitude": 1.0, "Longitude": 2.0}
    assert survey.position_from_status(payload, 0.0) is None

    payload = {"Flags": survey.FLAG_HAS_LATLONG | survey.FLAG_IN_SRV,
               "Latitude": 1.0, "Longitude": 2.0, "PlanetRadius": 1.0e6,
               "BodyName": "Eme A 3"}
    pos = survey.position_from_status(payload, 42.0)
    assert pos is not None and pos.in_srv and pos.body_name == "Eme A 3"


def test_canonical_commodity_strips_the_wrapper():
    assert survey.canonical_commodity("$thortveitite_name;") == "thortveitite"
    assert survey.canonical_commodity("Monazite") == "monazite"
    assert survey.canonical_commodity("") == ""


# ── deposit identity and dedupe ───────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path) -> MiningDB:
    d = MiningDB(tmp_path / "mining.db")
    d.upsert_body(1234, 7, system_name="Test", body_name="Test A 1",
                  radius_m=1.5e6)
    return d


def test_deposit_id_is_stable_and_position_sensitive():
    a = deposit_id(1234, 7, "monazite", 10.0, 20.0)
    b = deposit_id(1234, 7, "monazite", 10.0, 20.0)
    c = deposit_id(1234, 7, "monazite", 10.5, 20.0)
    assert a == b and a != c and len(a) == 12


def test_second_sighting_nearby_confirms_rather_than_duplicates(db):
    first, created = db.record_deposit(1234, 7, "monazite", 10.0, 20.0,
                                       refined=True)
    assert created is True

    # ~35 m away on a 1500 km body: the same rock, seen from the other side
    # of the rig.
    again, created = db.record_deposit(1234, 7, "monazite", 10.0002, 20.0,
                                       refined=True)
    assert created is False
    assert again == first
    assert db.counts()["deposits"] == 1

    row = db.deposits_on(1234, 7)[0]
    assert row["refine_count"] == 2


def test_a_sighting_beyond_the_radius_is_a_new_deposit(db):
    first, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    far,  created = db.record_deposit(1234, 7, "monazite", 10.02, 20.0,
                                      refined=True)
    assert created is True and far != first
    assert db.counts()["deposits"] == 2


def test_dedupe_does_not_cross_commodities(db):
    a, _ = db.record_deposit(1234, 7, "monazite",  10.0, 20.0, refined=True)
    b, created = db.record_deposit(1234, 7, "haematite", 10.0, 20.0,
                                   refined=True)
    assert created is True and a != b


def test_dedupe_does_not_cross_bodies(db):
    db.upsert_body(1234, 8, radius_m=1.5e6)
    a, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    b, created = db.record_deposit(1234, 8, "monazite", 10.0, 20.0,
                                   refined=True)
    assert created is True and a != b


def test_confirming_does_not_blank_stored_fields(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0,
                               density_observed="High", rigs=4, refined=True)
    db.record_deposit(1234, 7, "monazite", 10.0001, 20.0, refined=True)
    row = db.deposits_on(1234, 7)[0]
    assert row["density_observed"] == "High"
    assert row["rigs"] == 4


def test_depletion_is_history_not_deletion(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    assert db.mark_depleted(dep, "worked out") is True
    rows = db.deposits_on(1234, 7)
    assert len(rows) == 1 and rows[0]["amount"] == "Depleted"
    assert len(db.depletion_history(dep)) == 1

    # Working it again lifts it back out of Depleted without losing the note.
    db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    assert db.deposits_on(1234, 7)[0]["amount"] == "Low"
    assert len(db.depletion_history(dep)) == 1


def test_publishing_marks_and_changes_unmark(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    assert len(db.unpublished()) == 1
    assert db.mark_published([dep]) == 1
    assert db.unpublished() == []

    db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    assert len(db.unpublished()) == 1, "a confirmed deposit is stale on the sheet"


def test_test_rows_are_held_back_from_publishing(db):
    db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True,
                      is_test=True)
    assert db.unpublished() == []
    assert len(db.unpublished(include_test=True)) == 1


def test_body_survey_records_the_dss_count(db):
    db.record_survey(1234, 7, 13, "Monazite:1")
    assert db.survey(1234, 7)["signal_count"] == 13
    db.record_survey(1234, 7, 13, "Monazite:1")
    assert db.counts()["surveyed"] == 1


# ── commodity ledger consolidation ────────────────────────────────────────────

_COLS = ("name", "id", "name_localised", "category", "category_localised",
         "mean_price", "first_seen", "last_updated", "updates")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(_COLS))
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in _COLS})


def _read_csv(path: Path) -> dict[str, dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return {r["name"]: r for r in csv.DictReader(f)}


def test_ledger_merge_sums_observation_counts(tmp_path):
    root = tmp_path / "EDLD"
    _write_csv(root / "commanders" / "111" / "data" / "cargo.commodities.csv", [
        {"name": "gold", "mean_price": "9000", "first_seen": "2026-01-01T00:00:00Z",
         "last_updated": "2026-05-01T00:00:00Z", "updates": "7"},
    ])
    _write_csv(root / "commanders" / "222" / "data" / "cargo.commodities.csv", [
        {"name": "gold", "mean_price": "9500", "first_seen": "2026-02-01T00:00:00Z",
         "last_updated": "2026-06-01T00:00:00Z", "updates": "4"},
        {"name": "painite", "mean_price": "40000", "first_seen": "2026-03-01T00:00:00Z",
         "last_updated": "2026-03-01T00:00:00Z", "updates": "2"},
    ])

    shared = root / "data"
    summary = migrate_to_shared(root, shared)
    assert summary["ran"] is True and summary["sources"] == 2

    rows = _read_csv(shared / "cargo.commodities.csv")
    gold = rows["gold"]
    assert gold["updates"] == "11", "observation counts must be summed, not picked"
    assert gold["first_seen"] == "2026-01-01T00:00:00Z", "earliest sighting wins"
    assert gold["last_updated"] == "2026-06-01T00:00:00Z"
    assert gold["mean_price"] == "9500", "price follows the later last_updated"
    assert "painite" in rows


def test_ledger_migration_runs_once(tmp_path):
    root = tmp_path / "EDLD"
    _write_csv(root / "commanders" / "111" / "data" / "cargo.commodities.csv", [
        {"name": "gold", "mean_price": "9000", "first_seen": "2026-01-01T00:00:00Z",
         "last_updated": "2026-05-01T00:00:00Z", "updates": "7"},
    ])
    shared = root / "data"
    assert migrate_to_shared(root, shared)["ran"] is True
    assert migrate_to_shared(root, shared)["ran"] is False

    # The second pass must not have doubled the counter.
    assert _read_csv(shared / "cargo.commodities.csv")["gold"]["updates"] == "7"


def test_migration_leaves_sources_in_place(tmp_path):
    root = tmp_path / "EDLD"
    src = root / "commanders" / "111" / "data" / "cargo.commodities.csv"
    _write_csv(src, [{"name": "gold", "updates": "1"}])
    migrate_to_shared(root, root / "data")
    assert src.is_file()


# ── recording an assessment ───────────────────────────────────────────────────

def test_nearest_deposit_ignores_the_commodity(db):
    """Standing on a deposit should not require naming it first."""
    a, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    got = db.nearest_deposit(1234, 7, 10.0001, 20.0)
    assert got and got["deposit_id"] == a


def test_nearest_deposit_returns_none_when_standing_nowhere_near_one(db):
    db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    assert db.nearest_deposit(1234, 7, 11.0, 20.0) is None


def test_nearest_deposit_picks_the_closer_of_two(db):
    near, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    far, _ = db.record_deposit(1234, 7, "haematite", 10.0004, 20.0, refined=True)
    assert near != far
    assert db.nearest_deposit(1234, 7, 10.00005, 20.0)["deposit_id"] == near


def test_annotating_sets_only_what_was_given(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    assert db.annotate_deposit(dep, density_observed="High") is True
    assert db.annotate_deposit(dep, amount="Low") is True

    row = db.deposits_on(1234, 7)[0]
    assert row["density_observed"] == "High", "a later edit must not blank it"
    assert row["amount"] == "Low"


def test_annotating_with_nothing_changes_nothing(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    assert db.annotate_deposit(dep) is False
    assert db.annotate_deposit(dep, amount="") is False


def test_re_annotating_the_same_value_is_not_a_change(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    assert db.annotate_deposit(dep, amount="Medium") is True
    assert db.annotate_deposit(dep, amount="Medium") is False, \
        "an unchanged value must not make the row stale on the sheet"


def test_annotating_an_unknown_deposit_is_false_not_an_exception(db):
    assert db.annotate_deposit("nosuchdeposit", amount="High") is False


def test_an_annotation_makes_the_row_stale_on_the_sheet(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    db.mark_published([dep])
    assert db.unpublished() == []
    db.annotate_deposit(dep, amount="Low")
    assert len(db.unpublished()) == 1, \
        "a correction the squadron never sees is worse than no correction"


def test_annotating_to_depleted_stamps_the_history(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    db.annotate_deposit(dep, amount="Depleted")
    assert len(db.depletion_history(dep)) == 1
    assert db.deposits_on(1234, 7)[0]["amount"] == "Depleted"


def test_the_test_flag_can_be_set_and_held_back_from_publishing(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0, refined=True)
    assert len(db.unpublished()) == 1
    db.annotate_deposit(dep, is_test=True)
    assert db.unpublished() == []
    assert len(db.unpublished(include_test=True)) == 1


def test_touch_moves_the_timestamp_and_nothing_else(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 10.0, 20.0,
                               density_observed="High", refined=True)
    before = db.deposits_on(1234, 7)[0]
    db.mark_published([dep])

    assert db.touch_deposit(dep) is True
    after = db.deposits_on(1234, 7)[0]
    assert after["density_observed"] == "High", "a visit is not a judgement"
    assert after["refine_count"] == before["refine_count"]
    assert after["published_at"] == "", "the sheet should learn it was seen"


def test_touching_an_unknown_deposit_is_false(db):
    assert db.touch_deposit("nosuchthing") is False


# ── recording a deposit you are parked on ─────────────────────────────────────

def _plugin_at(tmp_path, monkeypatch, lat=10.0, lon=20.0, in_srv=True,
               age=0.0):
    import time as _t
    import importlib.util
    import core.state as state_mod
    import core.mining_db as mdb
    from core.surface_survey import POSITIONS, Position

    monkeypatch.setattr(state_mod, "EDLD_DATA_DIR", tmp_path)
    monkeypatch.setattr(state_mod, "shared_data_dir", lambda: tmp_path)
    monkeypatch.setattr(mdb, "_instance", None)

    spec = importlib.util.spec_from_file_location(
        "sm_rec", ROOT / "components" / "surface_mining.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Core:
        _plugins: dict = {}

        def register_session_provider(self, p):
            pass

        def load_setting(self, section, defaults, warn=False):
            d = dict(defaults)
            d["AutoConfirm"] = False
            return d

    p = mod.SurfaceMiningPlugin()
    p.on_load(_Core())
    p._system_address, p._body_id = 1234, 7
    p._db.upsert_body(1234, 7, radius_m=1.5e6)
    POSITIONS.clear()
    POSITIONS.add(Position(ts=_t.time() - age, latitude=lat, longitude=lon,
                           heading=0.0, body_name="B", radius_m=1.5e6,
                           in_srv=in_srv))
    return p


def test_recording_creates_a_deposit_from_the_live_position(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    msg = p.record_here("Helium-3", amount="High", density="High")
    assert "recorded" in msg
    rows = p._db.deposits_on(1234, 7)
    assert len(rows) == 1
    assert rows[0]["commodity"] == "helium3"
    assert rows[0]["amount"] == "High" and rows[0]["density_observed"] == "High"
    assert rows[0]["latitude"] == pytest.approx(10.0)


def test_recording_twice_annotates_rather_than_duplicating(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    p.record_here("Helium-3", amount="High")
    msg = p.record_here("Helium-3", amount="Low")
    assert "updated" in msg
    rows = p._db.deposits_on(1234, 7)
    assert len(rows) == 1 and rows[0]["amount"] == "Low"


def test_recording_without_a_commodity_on_empty_ground_says_so(tmp_path,
                                                               monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    assert "name the commodity" in p.record_here("", amount="High")
    assert p._db.deposits_on(1234, 7) == []


def test_a_stale_position_is_refused_rather_than_used(tmp_path, monkeypatch):
    """Recording a deposit at a position from five minutes ago would put a
    fictional coordinate in a store whose only value is that they are real."""
    p = _plugin_at(tmp_path, monkeypatch, age=300)
    assert "no live position" in p.record_here("Helium-3")
    assert p._db.deposits_on(1234, 7) == []


def test_a_bad_amount_is_refused(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    assert "amount must be" in p.record_here("Helium-3", amount="Enormous")
    assert p._db.deposits_on(1234, 7) == []


def test_the_dedupe_radius_matches_observed_deposit_spacing():
    """Real spacing is 400-500 m at the closest, so 100 m cannot merge two
    neighbours while still being close enough to walk from."""
    from core.mining_db import DEDUPE_RADIUS_M
    assert DEDUPE_RADIUS_M == 100.0


# ── the journal is buffered ───────────────────────────────────────────────────

def _refine_plugin(tmp_path, monkeypatch, *, pos_age=0.0, event_age=0.0,
                   in_srv=True, have_pos=True):
    import time as _t
    import importlib.util
    import core.state as state_mod
    import core.mining_db as mdb
    from core.surface_survey import POSITIONS, Position
    from datetime import datetime, timezone

    monkeypatch.setattr(state_mod, "EDLD_DATA_DIR", tmp_path)
    monkeypatch.setattr(state_mod, "shared_data_dir", lambda: tmp_path)
    monkeypatch.setattr(mdb, "_instance", None)

    spec = importlib.util.spec_from_file_location(
        "sm_lag", ROOT / "components" / "surface_mining.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Core:
        _plugins: dict = {}

        def register_session_provider(self, p):
            pass

        def load_setting(self, section, defaults, warn=False,
                         include_extra=False):
            d = dict(defaults)
            d["AutoConfirm"] = False
            return d

    p = mod.SurfaceMiningPlugin()
    p.on_load(_Core())
    p._system_address, p._body_id = 1234, 7
    p._db.upsert_body(1234, 7, radius_m=1.5e6)

    POSITIONS.clear()
    if have_pos:
        POSITIONS.add(Position(ts=_t.time() - pos_age, latitude=10.0,
                               longitude=20.0, heading=0.0, body_name="B",
                               radius_m=1.5e6, in_srv=in_srv))

    stamp = datetime.fromtimestamp(_t.time() - event_age, timezone.utc)
    event = {"event": "MiningRefined", "Type": "$helium3_name;",
             "Type_Localised": "Helium-3",
             "timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return p, mod, event


def test_a_refine_read_late_still_lands(tmp_path, monkeypatch):
    """The game writes the journal in batches.

    The gap between a refine happening and EDLD reading the line routinely
    exceeds the two-second match window, and every live refine was falling
    through that hole — 190 in one real session, silently, because only the
    replay branch logged anything.
    """
    p, _, event = _refine_plugin(tmp_path, monkeypatch, event_age=30.0)
    p.on_event(event, None)
    p._flush_pending(force=True)
    rows = p._db.deposits_on(1234, 7)
    # canonical_commodity strips the $..._name; wrapper: helium3, no hyphen.
    assert len(rows) == 1 and rows[0]["commodity"] == "helium3"
    assert rows[0]["commodity_display"] == "Helium-3"


def test_a_refine_inside_the_window_still_uses_the_window(tmp_path, monkeypatch):
    p, _, event = _refine_plugin(tmp_path, monkeypatch, event_age=0.5)
    p.on_event(event, None)
    p._flush_pending(force=True)
    assert len(p._db.deposits_on(1234, 7)) == 1


def test_a_stale_position_is_not_used_for_a_late_refine(tmp_path, monkeypatch):
    """Once the commander has driven off, the current position is no longer
    where the refine happened."""
    p, _, event = _refine_plugin(tmp_path, monkeypatch, event_age=30.0,
                                 pos_age=60.0)
    p.on_event(event, None)
    p._flush_pending(force=True)
    assert p._db.deposits_on(1234, 7) == []


def test_replayed_history_is_still_refused(tmp_path, monkeypatch):
    p, _, event = _refine_plugin(tmp_path, monkeypatch, event_age=6000.0)
    p.on_event(event, None)
    p._flush_pending(force=True)
    assert p._db.deposits_on(1234, 7) == []
    assert p._replayed_unpositioned == 1


def test_a_ring_refine_records_nothing(tmp_path, monkeypatch):
    """No latitude at all in space, so the fallback must not invent one."""
    p, _, event = _refine_plugin(tmp_path, monkeypatch, have_pos=False)
    p.on_event(event, None)
    p._flush_pending(force=True)
    assert p._db.deposits_on(1234, 7) == []


def test_a_refine_outside_an_srv_records_nothing(tmp_path, monkeypatch):
    p, _, event = _refine_plugin(tmp_path, monkeypatch, in_srv=False)
    p.on_event(event, None)
    p._flush_pending(force=True)
    assert p._db.deposits_on(1234, 7) == []


def test_an_unplaceable_live_refine_says_so_once(tmp_path, monkeypatch):
    """Silence is what let 190 dropped refines look like nothing happening."""
    p, _, event = _refine_plugin(tmp_path, monkeypatch, in_srv=False)
    said: list[str] = []
    p._log = said.append
    p.on_event(event, None)
    p.on_event(event, None)
    assert sum("could not be placed" in m for m in said) == 1


# ── the record action is reachable ────────────────────────────────────────────

def test_the_record_action_takes_values_from_the_widgets(tmp_path, monkeypatch):
    """A field the commander has typed into but not saved is exactly the one
    "record what I am standing on" needs — nothing has been applied yet, so the
    pending-change map is the wrong source."""
    p = _plugin_at(tmp_path, monkeypatch)
    msg = p.preferences_action("btn-srv-record", {
        "srv-rec-commodity": "Helium-3",
        "srv-rec-amount": "High",
        "srv-rec-density": "High",
    })
    assert "recorded" in msg
    row = p._db.deposits_on(1234, 7)[0]
    assert row["commodity"] == "helium3", "must match the journal's spelling"
    assert row["amount"] == "High" and row["density_observed"] == "High"


def test_the_depleted_action_is_reachable(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    p.record_here("Helium-3", amount="High")
    assert "Depleted" in p.preferences_action("btn-srv-depleted", {}) or \
        p._db.deposits_on(1234, 7)[0]["amount"] == "Depleted"


def test_an_action_id_that_is_not_ours_is_declined(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    assert p.preferences_action("btn-something-else", {}) is None


def test_the_old_single_argument_call_still_works(tmp_path, monkeypatch):
    """The TUI falls back to it, so it must not raise."""
    p = _plugin_at(tmp_path, monkeypatch)
    assert p.preferences_action("btn-something-else") is None


def test_both_front_ends_offer_the_recording_controls():
    src = (ROOT / "components" / "surface_mining.py").read_text(encoding="utf-8")
    for token in ("btn-srv-record", "btn-srv-depleted"):
        assert src.count(token) >= 2, f"{token} must be in both front ends"
    assert "srv-rec-commodity" in src


def test_a_hand_typed_commodity_matches_the_journal_spelling():
    """The journal writes $helium3_name; and a commander types "Helium-3".
    Canonicalising those differently makes one rock into two deposits — one
    recorded by hand, one by the first refine."""
    from core.surface_survey import canonical_commodity

    assert canonical_commodity("$helium3_name;") == canonical_commodity("Helium-3")
    assert canonical_commodity("Helium 3") == canonical_commodity("helium-3")
    assert canonical_commodity("$thortveitite_name;") == "thortveitite"


def test_a_finished_run_of_refines_is_written_without_another_event(
        tmp_path, monkeypatch):
    """The flush used to run only at the end of _on_refined, and a run of
    refines collapses into one pending entry that is not ready to write until
    the confirm interval has passed. Mine four tonnes and stop, and the deposit
    sat in memory with nothing left to trigger the write — no log line, no row,
    because the code had succeeded right up to the last step and then had no
    reason to run again."""
    import time as _t

    p, _mod, event = _refine_plugin(tmp_path, monkeypatch, event_age=1.0)
    for _ in range(4):
        p.on_event(event, None)
    assert p._db.deposits_on(1234, 7) == [], "not yet — the run may continue"

    # What the tick does, once the confirm interval has passed.
    for key in p._pending:
        p._pending[key]["first"] -= 60
    p._tick()
    rows = p._db.deposits_on(1234, 7)
    assert len(rows) == 1 and rows[0]["refine_count"] == 4


def test_the_survey_tick_runs_even_with_proximity_confirmation_off(
        tmp_path, monkeypatch):
    """The flush is on that tick and is not optional."""
    import ast

    src = (ROOT / "components" / "surface_mining.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    tick = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_tick")
    body = ast.get_source_segment(src, tick) or ""
    assert "_flush_pending" in body
    assert "self._prox_enabled" in body, "proximity is the optional half"
    assert "if self._prox_enabled:\n                threading.Thread" not in src


# ── pulling other commanders' deposits down ───────────────────────────────────

def _remote(dep_id="aaa111bbb222", **over):
    row = {"deposit_id": dep_id, "system_address": 1234, "body_id": 7,
           "commodity": "monazite", "commodity_display": "Monazite",
           "latitude": 11.0, "longitude": 21.0, "signal_no": 3,
           "density_claimed": "", "density_observed": "High",
           "amount": "Medium", "rigs": 4, "first_seen": "2026-08-01T00:00:00Z",
           "last_confirmed": "2026-09-01T00:00:00Z",
           "reported_by": "CMDR Someone Else", "is_test": 0}
    row.update(over)
    return row


def test_imported_deposits_land_in_the_store(db):
    added, updated = db.import_deposits([_remote()])
    assert (added, updated) == (1, 0)
    row = db.deposits_on(1234, 7)[0]
    assert row["commodity_display"] == "Monazite"
    assert row["reported_by"] == "CMDR Someone Else"


def test_an_imported_deposit_is_never_sent_back_up(db):
    """Without this every commander re-publishes every other commander's finds
    on their next flush, and the sheet spends its write quota echoing itself."""
    db.import_deposits([_remote()])
    assert db.unpublished() == []


def test_importing_twice_changes_nothing(db):
    db.import_deposits([_remote()])
    assert db.import_deposits([_remote()]) == (0, 0)
    assert len(db.deposits_on(1234, 7)) == 1


def test_local_observation_beats_the_sheet(db):
    """What the commander saw with their own eyes is better evidence than what
    a stranger wrote down last month."""
    dep, _ = db.record_deposit(1234, 7, "monazite", 11.0, 21.0,
                               amount="Depleted", density_observed="Low",
                               refined=True)
    db.import_deposits([_remote(dep_id=dep, amount="High",
                                density_observed="High")])
    row = db.deposits_on(1234, 7)[0]
    assert row["amount"] == "Depleted" and row["density_observed"] == "Low"


def test_the_sheet_fills_blanks_the_local_row_does_not_have(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 11.0, 21.0, refined=True)
    db.import_deposits([_remote(dep_id=dep, amount="High")])
    assert db.deposits_on(1234, 7)[0]["amount"] == "High"


def test_a_newer_sighting_advances_last_confirmed(db):
    dep, _ = db.record_deposit(1234, 7, "monazite", 11.0, 21.0, refined=True)
    before = db.deposits_on(1234, 7)[0]["last_confirmed"]
    db.import_deposits([_remote(dep_id=dep, last_confirmed="2099-01-01T00:00:00Z")])
    assert db.deposits_on(1234, 7)[0]["last_confirmed"] == "2099-01-01T00:00:00Z"

    db.import_deposits([_remote(dep_id=dep, last_confirmed="1999-01-01T00:00:00Z")])
    assert db.deposits_on(1234, 7)[0]["last_confirmed"] == "2099-01-01T00:00:00Z"
    assert before < "2099-01-01T00:00:00Z"


def test_malformed_rows_are_skipped_not_fatal(db):
    said: list[str] = []
    added, _ = db.import_deposits(
        [{"deposit_id": "bad", "system_address": None},
         {"latitude": 1.0},
         _remote()], log=said.append)
    assert added == 1
    assert said and "malformed" in said[0]


def test_the_imported_deposit_is_findable_by_the_compass(db):
    """The whole point: a deposit the commander has never seen, on a body they
    have just arrived at, in range of the thing that points at deposits."""
    from core.overlay_content import nearest_deposits

    db.upsert_body(1234, 7, radius_m=1.5e6)
    db.import_deposits([_remote()])
    near = nearest_deposits(11.0, 21.0, 1.5e6, db.deposits_on(1234, 7))
    assert near and near[0]["commodity_display"] == "Monazite"


def test_a_published_deposit_names_its_system(tmp_path, monkeypatch):
    """A body scanned in an earlier session has no Scan in this one, so the
    system name has to come from wherever we last learned where we were. A
    shared row that names the rock but not the system is one nobody else can
    use."""
    p = _plugin_at(tmp_path, monkeypatch)
    p._system_name = "Ega"
    p._body_name = "Ega 3 a"
    p.record_here("Silver", amount="High")

    pending = p._db.unpublished()
    assert len(pending) == 1
    assert pending[0]["system_name"] == "Ega"
    assert pending[0]["body_name"] == "Ega 3 a"


def test_a_refined_deposit_names_its_system_too(tmp_path, monkeypatch):
    p, _mod, event = _refine_plugin(tmp_path, monkeypatch, event_age=1.0)
    p._system_name = "Ega"
    p._body_name = "Ega 3 a"
    p.on_event(event, None)
    p._flush_pending(force=True)
    assert p._db.unpublished()[0]["system_name"] == "Ega"


def test_the_system_name_survives_an_fsd_jump(tmp_path, monkeypatch):
    """FSDJump is often the only event in a session that carries it."""
    p = _plugin_at(tmp_path, monkeypatch)
    p.on_event({"event": "FSDJump", "StarSystem": "Ega",
                "SystemAddress": 4923936737651}, None)
    assert p._system_name == "Ega"
    assert p._system_address == 4923936737651


def test_a_single_deposit_can_be_flagged_as_test(tmp_path, monkeypatch):
    """The config switch flags everything recorded from now on and cannot
    reach the one row that was a mistake."""
    p = _plugin_at(tmp_path, monkeypatch)
    p.record_here("Silver", amount="High")
    assert len(p._db.unpublished()) == 1

    assert "test data" in p.flag_here(True)
    assert p._db.unpublished() == [], "flagged rows are held back from the sheet"
    assert len(p._db.unpublished(include_test=True)) == 1

    assert "live data" in p.flag_here(False)
    assert len(p._db.unpublished()) == 1


def test_flagging_with_nothing_underfoot_says_so(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    assert "no recorded deposit" in p.flag_here(True)


def test_flagging_is_reachable_from_both_front_ends(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    p.record_here("Silver")
    assert "test data" in p.preferences_action("btn-srv-test-on", {})
    assert "live data" in p.preferences_action("btn-srv-test-off", {})


# ── the add / edit form ───────────────────────────────────────────────────────

def test_the_form_offers_a_new_deposit_when_there_is_nothing_here(
        tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    form, heading = p.form_for_here()
    assert all(v == "" for v in form.values())
    assert "New deposit" in heading


def test_the_form_offers_the_deposit_underfoot_when_there_is_one(
        tmp_path, monkeypatch):
    """One call answers add-or-edit, so a front end needs one keybind and one
    window rather than two of each."""
    p = _plugin_at(tmp_path, monkeypatch)
    p.record_here("Silver", amount="High")
    form, heading = p.form_for_here()
    assert form["commodity"] == "Silver" and form["amount"] == "High"
    assert heading.startswith("Editing")


def test_submitting_a_new_deposit_records_it(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    msg = p.submit_form({"commodity": "Silver", "amount": "High",
                         "density_observed": "Medium", "rigs": "4"})
    assert "recorded" in msg
    row = p._db.deposits_on(1234, 7)[0]
    assert row["commodity"] == "silver" and row["rigs"] == 4


def test_submitting_an_edit_updates_without_duplicating(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    p.submit_form({"commodity": "Silver", "amount": "High"})
    msg = p.submit_form({"amount": "Low", "rigs": "2"})
    assert "updated" in msg
    rows = p._db.deposits_on(1234, 7)
    assert len(rows) == 1 and rows[0]["amount"] == "Low" and rows[0]["rigs"] == 2


def test_an_edit_cannot_change_the_commodity(tmp_path, monkeypatch):
    """It is part of the deposit's identity — changing it would leave the id
    pointing at something else on every sheet that already has it."""
    p = _plugin_at(tmp_path, monkeypatch)
    p.submit_form({"commodity": "Silver"})
    p.submit_form({"commodity": "Gold", "amount": "High"})
    rows = p._db.deposits_on(1234, 7)
    assert len(rows) == 1 and rows[0]["commodity"] == "silver"


def test_a_new_deposit_needs_a_commodity(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    assert "required" in p.submit_form({"amount": "High"})
    assert p._db.deposits_on(1234, 7) == []


def test_validation_errors_come_back_instead_of_a_write(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch)
    msg = p.submit_form({"commodity": "Silver", "amount": "Enormous",
                         "rigs": "many"})
    assert "Amount must be" in msg and "Rigs must be" in msg
    assert p._db.deposits_on(1234, 7) == []


def test_the_form_refuses_a_stale_position(tmp_path, monkeypatch):
    p = _plugin_at(tmp_path, monkeypatch, age=300)
    assert "no live position" in p.submit_form({"commodity": "Silver"})

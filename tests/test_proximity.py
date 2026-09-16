"""
tests/test_proximity.py — Arriving at a deposit, once.

The failure this guards is quiet and expensive: without hysteresis a parked SRV
re-confirms the same deposit twice a second, `last_confirmed` becomes a record
of how long somebody idled, and — because every confirmation clears
`published_at` — that one deposit is pushed to the shared sheet on every flush
forever.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.proximity import DEFAULT_ENTER_M, ProximityTracker, distances_to


def test_arriving_fires_once():
    t = ProximityTracker(enter_m=25)
    assert t.update({"a": 10.0}) == ["a"]
    assert t.update({"a": 10.0}) == []
    assert t.update({"a": 5.0}) == []


def test_a_parked_srv_does_not_re_confirm():
    t = ProximityTracker(enter_m=25)
    t.update({"a": 12.0})
    for _ in range(200):          # a hundred seconds at two samples a second
        assert t.update({"a": 12.0}) == []


def test_leaving_and_returning_fires_again():
    t = ProximityTracker(enter_m=25, exit_factor=2.0)
    assert t.update({"a": 10.0}) == ["a"]
    assert t.update({"a": 60.0}) == []     # past the exit radius
    assert t.update({"a": 10.0}) == ["a"]


def test_sitting_on_the_boundary_does_not_oscillate():
    """A single threshold makes a commander parked at exactly the radius
    generate an arrival on every other sample. Two radii is the whole point."""
    t = ProximityTracker(enter_m=25, exit_factor=2.0)
    assert t.update({"a": 25.0}) == ["a"]
    for d in (25.0, 25.5, 26.0, 30.0, 40.0, 49.0, 25.0):
        assert t.update({"a": d}) == [], f"re-fired at {d} m"


def test_exit_radius_always_exceeds_entry():
    assert ProximityTracker(enter_m=25, exit_factor=1.0).exit_m > 25


def test_out_of_range_never_fires():
    t = ProximityTracker(enter_m=25)
    assert t.update({"a": 26.0}) == []
    assert t.inside == frozenset()


def test_several_deposits_are_tracked_independently():
    t = ProximityTracker(enter_m=25)
    assert sorted(t.update({"a": 10.0, "b": 200.0})) == ["a"]
    assert sorted(t.update({"a": 10.0, "b": 5.0})) == ["b"]
    assert t.inside == frozenset({"a", "b"})


def test_a_deposit_that_vanishes_from_the_sample_counts_as_left():
    """Which is what happens on changing body — no special case needed."""
    t = ProximityTracker(enter_m=25)
    t.update({"a": 10.0})
    assert t.update({}) == []
    assert t.inside == frozenset()
    assert t.update({"a": 10.0}) == ["a"]


def test_reset_forgets_everything():
    t = ProximityTracker(enter_m=25)
    t.update({"a": 10.0})
    t.reset()
    assert t.inside == frozenset()
    assert t.update({"a": 10.0}) == ["a"]


# ── distances ─────────────────────────────────────────────────────────────────

def test_distances_are_keyed_by_deposit_id():
    deps = [{"deposit_id": "aaa", "latitude": 10.0, "longitude": 20.0},
            {"deposit_id": "bbb", "latitude": 10.001, "longitude": 20.0}]
    got = distances_to(10.0, 20.0, 1.5e6, deps)
    assert set(got) == {"aaa", "bbb"}
    assert got["aaa"] == pytest.approx(0.0, abs=0.5)
    assert 20 < got["bbb"] < 30


def test_deposits_without_coordinates_or_id_are_skipped():
    deps = [{"deposit_id": "x", "latitude": None, "longitude": None},
            {"latitude": 10.0, "longitude": 20.0}]
    assert distances_to(10.0, 20.0, 1.5e6, deps) == {}


def test_the_default_radius_is_well_inside_the_dedupe_radius():
    """An arrival must never be ambiguous between two deposits, and 75 m is
    what decides whether two sightings are the same one."""
    from core.mining_db import DEDUPE_RADIUS_M
    assert DEFAULT_ENTER_M * 2 <= DEDUPE_RADIUS_M

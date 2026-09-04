"""
tests/test_spansh_carrier_params.py — pin the Spansh fleet-carrier wire format.

Background
----------
Carrier routing submitted successfully (HTTP 202, job id returned) and then
never produced a usable result.  The endpoint and the parameter *names* were
right all along; the encoding of the two list-shaped parameters was not.

spansh.co.uk's own front-end bundle submits the job through

    plotFleetCarrierRoute(e){return this.performRequest("/api/fleetcarrier/route", e)}
    performRequest(e,t){return $.ajax({... method:"POST", data:t, traditional:!0 ...})}

``traditional: true`` is jQuery's flag for serialising a list as repeated bare
keys — ``destination_systems=A&destination_systems=B`` — with no ``[]`` suffix
and no JSON.  EDLD was sending ``json.dumps([...])``, so the destination list
arrived as the literal string ``["6681123623626"]``, parsed to nothing, and the
queued job had no destination to route to.

The expectations here are derived from a real completed job saved from the
site (``tests/data/spansh_fleetcarrier_job.json``).  Its ``parameters`` block
is the server's own echo of what it parsed, so it is authoritative about the
shape EDLD has to produce rather than a guess restated by hand.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.spansh import (  # noqa: E402
    _SPANSH_LIST_PARAMS,
    _SPANSH_ROUTE_URLS,
    _normalise_list_params,
)

FIXTURE = Path(__file__).parent / "data" / "spansh_fleetcarrier_job.json"


@pytest.fixture(scope="module")
def job() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def echoed_params(job) -> dict:
    """The parameters Spansh reported having parsed for a real carrier job."""
    return job["parameters"]


# ── Endpoint ──────────────────────────────────────────────────────────────────

def test_carrier_endpoint_is_the_one_the_site_posts_to():
    assert _SPANSH_ROUTE_URLS["carrier"] == [
        "https://spansh.co.uk/api/fleetcarrier/route"
    ]


# ── Which params are list-shaped is derived from the captured job ─────────────

def test_list_params_match_the_captured_job(echoed_params):
    """Every list in the real job must be declared in _SPANSH_LIST_PARAMS.

    Derived from the fixture rather than hand-listed, so a future Spansh
    parameter that is also list-shaped fails here instead of silently being
    JSON-encoded onto the wire.
    """
    actual_lists = {k for k, v in echoed_params.items() if isinstance(v, list)}
    assert actual_lists <= _SPANSH_LIST_PARAMS, (
        f"list-shaped params not declared: {actual_lists - _SPANSH_LIST_PARAMS}"
    )


# ── Normalisation ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "supplied",
    [
        pytest.param(["6681123623626"], id="already-a-list"),
        pytest.param('["6681123623626"]', id="json-string-the-old-bug"),
        pytest.param("6681123623626", id="bare-scalar"),
    ],
)
def test_destination_normalises_to_a_real_list(supplied):
    out = _normalise_list_params({"destination_systems": supplied})
    assert out["destination_systems"] == ["6681123623626"]


@pytest.mark.parametrize(
    "supplied", [[], "[]", "", ()], ids=["empty-list", "json-empty", "empty-str", "tuple"]
)
def test_empty_list_params_are_dropped_not_sent_empty(supplied):
    """traditional serialisation omits empty arrays; sending '' is not the same."""
    out = _normalise_list_params({"refuel_destinations": supplied})
    assert "refuel_destinations" not in out


def test_non_list_params_pass_through_untouched():
    src = {"source_system": "84180519395914", "capacity": 25000, "mass": 25000}
    assert _normalise_list_params(src) == src


# ── The encoded body ──────────────────────────────────────────────────────────

def _encode(params: dict) -> str:
    return urllib.parse.urlencode(_normalise_list_params(params), doseq=True)


def test_encoded_body_round_trips_to_the_captured_parameters(echoed_params):
    """Encode the real job's parameters, parse them back, and compare.

    This is the end-to-end statement: what EDLD puts on the wire must parse
    server-side into exactly what Spansh recorded for this job.
    """
    body = _encode(dict(echoed_params))
    parsed = urllib.parse.parse_qs(body, keep_blank_values=True)

    for key, expected in echoed_params.items():
        if isinstance(expected, list):
            if not expected:
                assert key not in parsed, f"empty {key} should be absent"
            else:
                assert parsed[key] == [str(v) for v in expected]
        else:
            assert parsed[key] == [str(expected)]


def test_old_json_encoding_would_not_round_trip(echoed_params):
    """Guard the premise: the previous encoding genuinely loses the list.

    If this ever stops failing, the bug this module exists for was not what
    we thought it was.
    """
    broken = dict(echoed_params)
    broken["destination_systems"] = json.dumps(echoed_params["destination_systems"])
    parsed = urllib.parse.parse_qs(urllib.parse.urlencode(broken))
    assert parsed["destination_systems"] != [
        str(v) for v in echoed_params["destination_systems"]
    ], "old JSON encoding unexpectedly round-tripped"


# ── Result shape the UI has to render ─────────────────────────────────────────

def test_carrier_result_uses_jumps_not_system_jumps(job):
    result = job["result"]
    assert "jumps" in result
    assert "system_jumps" not in result
    # No top-level totals — the UI must derive them.
    assert "total_jumps" not in result
    assert "distance" not in result


def test_every_jump_carries_the_fuel_fields_the_ui_shows(job):
    required = {
        "name", "distance", "distance_to_destination", "fuel_used",
        "fuel_in_tank", "must_restock", "restock_amount",
        "tritium_in_market", "has_icy_ring", "is_system_pristine",
    }
    for i, jump in enumerate(job["result"]["jumps"]):
        missing = required - set(jump)
        assert not missing, f"jumps[{i}] missing {missing}"


def test_no_leg_exceeds_the_carrier_max_jump(job):
    """500 ly is the fleet carrier maximum; a longer leg means we misread the units."""
    for jump in job["result"]["jumps"]:
        assert jump["distance"] <= 500.0 + 1e-6

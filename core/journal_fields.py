"""
core/journal_fields.py — Pure helpers for reading fields out of journal events.

Extracted so the exploration and exobiology ingest modules can share them
without either importing the other, and without importing the dispatcher that
imports them both.  Nothing here touches the database or holds state.
"""

from __future__ import annotations

import json
from typing import Any

# Standard gravity used to convert journal surface gravity (m/s²) to g.
G = 9.80665

# ``ScanType`` → ``scan_state``: 0 = unscanned, 1 = auto/basic, 2 = detailed,
# 3 = nav-beacon detail.
SCAN_STATE = {
    "Basic": 1,
    "AutoScan": 1,
    "Detailed": 2,
    "NavBeaconDetail": 3,
}


def ts(event: dict) -> str:
    """ISO timestamp for status rows, from ``_logtime`` or the raw field."""
    lt = event.get("_logtime")
    if lt is not None:
        try:
            return lt.isoformat()
        except Exception:
            pass
    return str(event.get("timestamp", ""))


def name(event: dict, key: str) -> str:
    """Prefer a localised field when the game provides one."""
    return str(event.get(f"{key}_Localised") or event.get(key) or "")


def signal_kind(type_str: str) -> str:
    """Classify a signal ``Type`` string into the kinds the store records."""
    s = (type_str or "").lower()
    if "biolog" in s:
        return "bio"
    if "geolog" in s:
        return "geo"
    if "human" in s:
        return "human"
    return "other"


def materials_json(event: dict) -> str:
    """Serialise a Scan's ``Materials`` to the JSON blob the planets table holds."""
    m = event.get("Materials")
    out: dict[str, Any] = {}
    if isinstance(m, list):
        for it in m:
            if isinstance(it, dict) and "Name" in it:
                out[str(it["Name"]).lower()] = it.get("Percent", 0.0)
    elif isinstance(m, dict):
        for k, v in m.items():
            out[str(k).lower()] = v
    return json.dumps(out) if out else ""

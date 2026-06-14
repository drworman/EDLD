"""
core/explo_view.py — Exploration window view builder.

Turns the stored facts for one system (from :mod:`core.explo_db`) plus a
commander's scan/map status into a structured view the TUI Exploration
blocks render.  All cartographic values come from :mod:`core.explo_value`.

The view is deliberately presentation-agnostic: a dict of plain values and
flags, no widget or formatting concerns — the dashboard renders this data.
"""

from __future__ import annotations

from typing import Optional

from core.explo_db import ExploDB, get_db
from core import explo_value as V

# Default threshold (Cr) above which an unmapped body is flagged worth mapping.
HIGH_VALUE_THRESHOLD = 300_000


def _short_name(body_name: str, system_name: str) -> str:
    """Body name with the system prefix stripped (e.g. 'Foo A 1' -> 'A 1')."""
    if system_name and body_name.startswith(system_name):
        rest = body_name[len(system_name):].strip()
        return rest or body_name
    return body_name


def _planet_values(p: dict) -> tuple[int, int]:
    """Return (value_now, value_max) for a planet row joined with status."""
    pclass = p.get("type", "") or ""
    mass   = p.get("mass", 0.0) or 0.0
    terra  = p.get("terraform_state", "") or ""
    was_d  = bool(p.get("was_discovered"))
    was_m  = bool(p.get("was_mapped"))
    mapped = bool(p.get("mapped"))
    eff    = bool(p.get("efficient"))
    value_now = V.scan_value(pclass, mass, terra, was_d, was_m, dss_mapped=mapped, efficient=eff)
    value_max = V.scan_value(pclass, mass, terra, was_d, was_m, dss_mapped=True, efficient=True)
    return value_now, value_max


def build_system_view(
    system_address: Optional[int],
    commander_id: Optional[int],
    db: Optional[ExploDB] = None,
    high_value_threshold: int = HIGH_VALUE_THRESHOLD,
) -> Optional[dict]:
    """Build the exploration view for a system, or None if unknown/unset."""
    if system_address is None or commander_id is None:
        return None
    db = db or get_db()
    sysrow = db.get_system(int(system_address))
    if not sysrow:
        return None
    system_id = sysrow["id"]
    sys_name  = sysrow.get("name", "") or ""

    grouped = db.system_bodies(system_id, commander_id)
    bodies: list[dict] = []

    total_now = total_max = 0
    scanned = mapped_n = bio_bodies = 0
    fd_count = ff_count = 0

    # Stars first (lowest body_id), then planets — both already ordered by body_id.
    for s in grouped["stars"]:
        val = V.star_value(s.get("type", "") or "", s.get("mass", 0.0) or 0.0)
        was_d = bool(s.get("was_discovered"))
        if not was_d:
            val = round(val * V.FIRST_DISC_MULT)
        discovered = bool(s.get("discovered"))
        if discovered:
            scanned += 1
        first_disc = not was_d
        if first_disc:
            fd_count += 1
        total_now += val
        total_max += val
        bodies.append({
            "name": s.get("name", ""), "short": _short_name(s.get("name", ""), sys_name),
            "kind": "star", "is_star": True, "type": s.get("type", ""),
            "value_now": val, "value_max": val, "mapping_gain": 0,
            "discovered": discovered, "was_discovered": was_d,
            "mapped": False, "was_mapped": False, "efficient": False, "footfall": False,
            "terraformable": False, "bio_signals": 0, "geo_signals": 0,
            "high_value": False, "landable": False,
            "first_discovery": first_disc, "first_mapped": False, "first_footfall": False,
        })

    for p in grouped["planets"]:
        value_now, value_max = _planet_values(p)
        discovered = bool(p.get("discovered"))
        mapped     = bool(p.get("mapped"))
        bio        = int(p.get("bio_signals", 0) or 0)
        if discovered:
            scanned += 1
        if mapped:
            mapped_n += 1
        if bio:
            bio_bodies += 1
        terraformable = V.is_terraformable(p.get("terraform_state", "") or "")
        high_value = (not mapped) and (value_max >= high_value_threshold or terraformable)
        was_d    = bool(p.get("was_discovered"))
        was_m    = bool(p.get("was_mapped"))
        landable = bool(p.get("landable"))
        first_disc = not was_d
        first_map  = not was_m
        first_ff   = (not was_d) and landable
        if first_disc:
            fd_count += 1
        if first_ff:
            ff_count += 1
        total_now += value_now
        total_max += value_max
        bodies.append({
            "name": p.get("name", ""), "short": _short_name(p.get("name", ""), sys_name),
            "kind": "planet", "is_star": False, "type": p.get("type", ""),
            "value_now": value_now, "value_max": value_max,
            "mapping_gain": max(0, value_max - value_now),
            "discovered": discovered, "was_discovered": was_d,
            "mapped": mapped, "was_mapped": was_m,
            "efficient": bool(p.get("efficient")), "footfall": bool(p.get("footfall")),
            "terraformable": terraformable,
            "bio_signals": bio, "geo_signals": int(p.get("geo_signals", 0) or 0),
            "high_value": high_value, "landable": landable,
            "first_discovery": first_disc, "first_mapped": first_map, "first_footfall": first_ff,
        })

    return {
        "system": {
            "name": sys_name,
            "address": int(system_address),
            "honked": _system_flag(db, system_id, commander_id, "honked"),
            "fully_scanned": _system_flag(db, system_id, commander_id, "fully_scanned"),
            "fully_mapped": _system_flag(db, system_id, commander_id, "fully_mapped"),
            "body_count": int(sysrow.get("body_count", 0) or 0),
        },
        "bodies": bodies,
        "totals": {
            "value_now": total_now,
            "value_max": total_max,
            "bodies": len(bodies),
            "scanned": scanned,
            "mapped": mapped_n,
            "bio_bodies": bio_bodies,
            "high_value": sum(1 for b in bodies if b["high_value"]),
            "first_discovery": fd_count,
            "first_footfall": ff_count,
        },
    }


def _system_flag(db: ExploDB, system_id: int, commander_id: int, flag: str) -> bool:
    try:
        row = db._c.execute(
            f"SELECT {flag} FROM system_status WHERE system_id=? AND commander_id=?",
            (system_id, commander_id),
        ).fetchone()
        return bool(row[flag]) if row else False
    except Exception:
        return False

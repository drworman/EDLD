"""
core/ui_helpers.py — Pure-Python display helpers for the dashboard.

No UI-framework imports — safe to import anywhere.
"""

from __future__ import annotations


# ── Powerplay rank helpers ─────────────────────────────────────────────────────

PP_RANK_NAMES = [
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]


def pp_merits_for_rank(rank: int) -> int:
    """Return total cumulative merits required to reach the given rank."""
    if rank <= 1:   return 0
    if rank == 2:   return 2_000
    if rank == 3:   return 5_000
    if rank == 4:   return 9_000
    if rank == 5:   return 15_000
    if rank <= 100: return 15_000 + (rank - 5) * 8_000
    return 775_000 + (rank - 100) * 8_000


def pp_rank_progress(rank: int, total_merits: int) -> tuple:
    """Return (fraction 0.0-1.0, merits_in_rank, merits_needed, next_rank)."""
    floor    = pp_merits_for_rank(rank)
    ceil     = pp_merits_for_rank(rank + 1)
    span     = ceil - floor
    earned   = max(0, total_merits - floor)
    fraction = min(1.0, earned / span) if span > 0 else 1.0
    return fraction, earned, span, rank + 1


# ── Health / shield display helpers ───────────────────────────────────────────

def hull_css(pct: int) -> str:
    """Return CSS class name for a hull/shield percentage."""
    if pct > 75:  return "health-good"
    if pct >= 25: return "health-warn"
    return "health-crit"


def fmt_shield(shields_up, recharging: bool) -> str:
    """Return human-readable shield status string."""
    if shields_up is None: return "\u2014"
    if shields_up:         return "Up"
    if recharging:         return "Recharging"
    return "Down"


def fmt_crew_active(delta) -> str:
    """Format a timedelta as human-readable crew active duration."""
    total_days = int(delta.total_seconds() // 86400)
    if total_days < 1:
        return "<1d"
    years,  rem_days = divmod(total_days, 365)
    months, days     = divmod(rem_days, 30)
    parts = []
    if years:  parts.append(f"{years}y")
    if months: parts.append(f"{months}mo")
    if days and len(parts) < 2: parts.append(f"{days}d")
    return " ".join(parts) or "<1d"


# ── Body-data fault reporting ─────────────────────────────────────────────────

def explo_fault(core, exc: BaseException | None = None) -> str:
    """Return why the Exploration / Exobiology data is unusable, or "".

    The four body-data windows all reduce a missing view to the same empty-state
    sentence ("honk to populate", "surface-scan a body with signals").  That is
    correct when the commander simply has not scanned anything, and badly wrong
    when the component never loaded or the database is failing every write —
    the two cases look identical on screen and nothing else reports the
    difference, because both the ingest path and the view builders swallow their
    exceptions.  This returns a short fault line for the genuine fault cases so
    the windows can print that instead.

    Pass the exception caught around the view builder, if any.
    """
    sync = None
    try:
        sync = core._plugins.get("explo_sync")
    except Exception:
        pass

    if sync is None:
        return "Exploration component not loaded — see the error log."

    reason = None
    try:
        reason = sync.health()
    except Exception:
        reason = None
    if reason:
        return f"Body data unavailable: {reason}"

    if exc is not None:
        return f"Body data unavailable: {type(exc).__name__}: {exc}"

    return ""


# ── Fleet carrier route rendering ─────────────────────────────────────────────
#
# Both front ends render the Spansh fleet-carrier result identically, and the
# fuel arithmetic is the part worth getting right exactly once.  These helpers
# return plain data so tui/blocks/navigation.py and gui/blocks/navigation.py
# each only have to turn tuples into their own row widgets.
#
# The carrier result differs from the ship-route results in three ways that
# matter here: waypoints live under "jumps" rather than "system_jumps", there
# is no top-level total_jumps or distance, and every leg carries fuel planning.

#: Fleet carriers jump at most 500 ly at a time.
CARRIER_MAX_JUMP_LY = 500.0


def carrier_route_summary(result: dict) -> dict:
    """Derive the headline figures for a Spansh fleet-carrier route.

    Returns {jumps, distance_ly, fuel_total, restocks, tritium_sources,
    destination}.  Totals are derived from the legs because the carrier
    result carries no top-level totals.
    """
    jumps = result.get("jumps") or []
    if not jumps:
        return {"jumps": 0, "distance_ly": 0.0, "fuel_total": 0,
                "restocks": 0, "tritium_sources": 0, "destination": ""}

    # jumps[0] is the origin (distance 0), so legs flown is len - 1.
    legs = max(len(jumps) - 1, 0)
    distance = float(jumps[0].get("distance_to_destination") or 0.0)
    fuel_total = sum(int(j.get("fuel_used") or 0) for j in jumps)
    restocks = sum(1 for j in jumps if j.get("must_restock"))
    sources = sum(
        1 for j in jumps
        if j.get("has_icy_ring") or int(j.get("tritium_in_market") or 0) > 0
    )
    return {
        "jumps":           legs,
        "distance_ly":     distance,
        "fuel_total":      fuel_total,
        "restocks":        restocks,
        "tritium_sources": sources,
        "destination":     str(jumps[-1].get("name") or ""),
    }


def carrier_route_rows(result: dict) -> list[tuple[str, str]]:
    """Return (label, value) pairs, one per waypoint, for the carrier route.

    Value column carries the leg distance then the fuel picture, because on a
    long haul the question at every stop is "can I make the next jump and
    where do I top up".  Markers:

        ⛽ n   restock here, n tonnes
        ✦      pristine icy ring — tritium is mineable
        ·      icy ring present
        n t    tritium purchasable in the market
    """
    rows: list[tuple[str, str]] = []
    for i, jump in enumerate(result.get("jumps") or []):
        name = str(jump.get("name") or "—")
        dist = float(jump.get("distance") or 0.0)
        used = int(jump.get("fuel_used") or 0)
        tank = int(jump.get("fuel_in_tank") or 0)

        parts = [f"{dist:,.0f} ly" if i else "start"]
        if used:
            parts.append(f"-{used}t")
        parts.append(f"[{tank}t]")

        if jump.get("must_restock"):
            parts.append(f"⛽{int(jump.get('restock_amount') or 0)}t")
        elif jump.get("is_system_pristine") and jump.get("has_icy_ring"):
            parts.append("✦")
        elif jump.get("has_icy_ring"):
            parts.append("·")

        market = int(jump.get("tritium_in_market") or 0)
        if market:
            parts.append(f"mkt {market}t")

        rows.append((f"{i}. {name}", "  ".join(parts)))
    return rows

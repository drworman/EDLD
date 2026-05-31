"""
core/ui_helpers.py — Pure-Python display helpers shared between TUI and GUI.

No GTK4, no gi, no textual — safe to import anywhere.
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

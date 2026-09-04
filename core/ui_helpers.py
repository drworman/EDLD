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


# ── Fleet carrier display ─────────────────────────────────────────────────────
#
# Three separate parsers populate state.assets_carrier and they do not agree
# on key names:
#
#   components/assets.py  _parse_carrier_stats            journal CarrierStats
#   components/assets.py  _parse_carrier_stats_from_capi  capi_fleetcarrier.json
#   core/data.py          (CAPI fleetcarrier ingest)      capi_fleetcarrier.json
#
# The Assets block was reading three keys that none of them produce —
# "reserve_balance", "coreCost" and a "capacity" sub-dict — so Reserve,
# Upkeep and both Cargo rows were permanently blank, while roughly twenty
# fields that *were* being parsed had nowhere to appear.
#
# normalise_carrier() reconciles the shapes and fills what can be derived;
# carrier_display_sections() is the single description of what the tab shows,
# so the TUI and the GUI cannot drift.

#: Hull value recovered on decommission, by carrier type.
CARRIER_HULL_VALUE = {
    "FleetCarrier":    4_850_000_000,
    "SquadronCarrier": 24_850_000_000,
}

#: Journal service keys → display names.  The journal and CAPI use different
#: spellings for the same services; both are mapped here.
_CARRIER_SERVICES = {
    "Refuel": "Refuel", "refuel": "Refuel",
    "Repair": "Repair", "repair": "Repair",
    "Rearm": "Restock", "rearm": "Restock",
    "Shipyard": "Shipyard", "shipyard": "Shipyard",
    "Outfitting": "Outfitting", "outfitting": "Outfitting",
    "BlackMarket": "Black market", "blackmarket": "Black market",
    "Commodities": "Commodities", "commodities": "Commodities",
    "VoucherRedemption": "Redemption", "voucherredemption": "Redemption",
    "Exploration": "Universal cartographics", "exploration": "Universal cartographics",
    "CarrierFuel": "Tritium depot", "carrierfuel": "Tritium depot",
    "Bartender": "Bartender", "bartender": "Bartender",
    "VistaGenomics": "Vista Genomics", "vistagenomics": "Vista Genomics",
    "PioneerSupplies": "Pioneer supplies", "pioneersupplies": "Pioneer supplies",
    "Concourse": "Concourse", "concourse": "Concourse",
    "Refinery": "Refinery", "refinery": "Refinery",
}


def fmt_credits(n) -> str:
    """Compact credit formatting, shared by both front ends."""
    if not n:
        return "—"
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "—"
    if abs(v) >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B cr"
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M cr"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f}K cr"
    return f"{v} cr"


def normalise_carrier(carrier: dict | None) -> dict:
    """Reconcile the three carrier dict shapes into one.

    Aliases the divergent keys and fills anything derivable, so a carrier
    sourced from the journal renders the same as one sourced from CAPI.
    Returns {} for no carrier.
    """
    if not carrier:
        return {}
    c = dict(carrier)

    # CAPI (components/assets.py) says "state"; everything else says
    # "carrier_state".
    if not c.get("carrier_state") and c.get("state"):
        c["carrier_state"] = c["state"]

    def _i(key) -> int:
        try:
            return int(c.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    used, free = _i("cargo_used"), _i("cargo_free")

    # Only the journal reports TotalCapacity; CAPI has to be derived.  A
    # standard fleet carrier holds 25,000 t.
    if not _i("cargo_total"):
        c["cargo_total"] = (used + free) or 25_000
    if not _i("cargo_free") and _i("cargo_total"):
        c["cargo_free"] = max(_i("cargo_total") - used, 0)

    # Journal CarrierStats gives all three balances; CAPI gives two.
    if not _i("available"):
        c["available"] = max(_i("balance") - _i("reserve"), 0)

    ctype = str(c.get("carrier_type") or "FleetCarrier")
    c["carrier_type"] = ctype
    c["hull_value"] = CARRIER_HULL_VALUE.get(
        ctype, CARRIER_HULL_VALUE["FleetCarrier"])
    c["is_squadron"] = "Squadron" in ctype
    return c


def carrier_active_services(carrier: dict) -> list[str]:
    """Display names of the carrier's active services, sorted.

    Handles both encodings: the journal's {"Refuel": "ok"} and CAPI's
    {"refuel": "ok"} / {"refuel": {"state": "ok"}}.
    """
    raw = carrier.get("services") or {}
    if not isinstance(raw, dict):
        return []
    out = []
    for key, status in raw.items():
        if isinstance(status, dict):
            status = status.get("state") or status.get("status") or ""
        if str(status).lower() not in ("ok", "active", "true", "1"):
            continue
        out.append(_CARRIER_SERVICES.get(key, str(key)))
    return sorted(set(out))


def carrier_display_sections(carrier: dict | None,
                             fc_materials: list | None = None,
                             cargo_hold: dict | None = None,
                             squadron_name: str = "") -> list[tuple[str, list]]:
    """Describe the Assets Carrier tab as [(section title, [(label, value)])].

    The single source of truth for that tab in both front ends.  Rows whose
    underlying data is genuinely absent are omitted rather than rendered as
    a column of dashes.
    """
    c = normalise_carrier(carrier)
    sections: list[tuple[str, list]] = []

    if not c:
        rows = [("Fleet carrier", "None on file")]
        if squadron_name:
            rows.append(("Squadron", squadron_name))
        return [("Carrier", rows)]

    def _i(key) -> int:
        try:
            return int(c.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    # ── Identity ──────────────────────────────────────────────────────────
    ident = [
        ("Name", str(c.get("name") or "—")),
        ("Callsign", str(c.get("callsign") or "—")),
        ("Type", "Squadron carrier" if c["is_squadron"] else "Fleet carrier"),
    ]
    if c.get("theme") and c["theme"] != "—":
        ident.append(("Theme", str(c["theme"])))
    sections.append(("Identity", ident))

    # ── Location & access ─────────────────────────────────────────────────
    loc = [("System", str(c.get("system") or "—"))]
    if c.get("carrier_state") and c["carrier_state"] != "—":
        loc.append(("Status", str(c["carrier_state"])))
    if c.get("docking") and c["docking"] != "—":
        loc.append(("Docking", str(c["docking"])))
    loc.append(("Notorious", "Allowed" if c.get("notorious") else "Denied"))
    sections.append(("Location & access", loc))

    # ── Fuel & capacity ───────────────────────────────────────────────────
    fuel = _i("fuel")
    total, used, free = _i("cargo_total"), _i("cargo_used"), _i("cargo_free")
    cap = [
        ("Tritium", f"{fuel}/1000 t  ({fuel // 10}%)"),
        ("Cargo", f"{used:,} / {total:,} t  ({free:,} free)"),
    ]
    if _i("cargo_crew"):
        cap.append(("Crew space", f"{_i('cargo_crew'):,} t"))
    if _i("ship_packs") or _i("module_packs"):
        cap.append(("Packs", f"{_i('ship_packs'):,} t ship · "
                             f"{_i('module_packs'):,} t module"))
    if _i("micro_total"):
        cap.append(("Microresources",
                    f"{_i('micro_used'):,} / {_i('micro_total'):,}"))
    sections.append(("Fuel & capacity", cap))

    # ── Finance ───────────────────────────────────────────────────────────
    fin = [
        ("Balance", fmt_credits(c.get("balance"))),
        ("Reserved", fmt_credits(c.get("reserve"))),
        ("Available", fmt_credits(c.get("available"))),
    ]
    if _i("maintenance"):
        fin.append(("Upkeep/wk", fmt_credits(c.get("maintenance"))))
    if _i("maintenance_wtd"):
        fin.append(("Upkeep to date", fmt_credits(c.get("maintenance_wtd"))))

    taxes = [(lbl, c.get(key)) for lbl, key in (
        ("Refuel", "tax_refuel"), ("Repair", "tax_repair"),
        ("Restock", "tax_rearm"), ("Pioneer", "tax_pioneer"))]
    if any(v for _lbl, v in taxes):
        fin.append(("Tax rates", " · ".join(
            f"{lbl} {float(v or 0):g}%" for lbl, v in taxes)))
    fin.append(("Hull (decom.)", fmt_credits(c.get("hull_value"))))
    sections.append(("Finance", fin))

    # ── Inventory ─────────────────────────────────────────────────────────
    inv = []
    listings = sum((m.get("price", 0) or 0) * (m.get("stock", 0) or 0)
                   for m in (fc_materials or []))
    if listings:
        inv.append(("Market listings", fmt_credits(listings)))
    if cargo_hold:
        tonnes = sum(int(v or 0) for v in cargo_hold.values())
        inv.append(("Hold", f"{tonnes:,} t across {len(cargo_hold)} commodities"))
    if inv:
        sections.append(("Inventory", inv))

    # ── Services ──────────────────────────────────────────────────────────
    active = carrier_active_services(c)
    if active:
        sections.append(("Services", [("Active", ", ".join(active))]))

    # ── Squadron ──────────────────────────────────────────────────────────
    # No anonymous API exposes squadron carrier jump data, so this stays a
    # name plus an explicit statement of the limitation rather than a row of
    # blanks that looks like a bug.
    if squadron_name:
        sections.append(("Squadron", [
            ("Squadron", squadron_name),
            ("Carrier data", "Not exposed by the journal or any anonymous API"),
        ]))
    return sections

"""
core/reports.py — Statistical reports built from all available journal files.

Reports are computed by scanning every journal in the configured journal folder.
All report functions return a ReportResult containing a title, subtitle, and
a list of ReportSection objects for display.

Available reports
─────────────────
1. Career Overview       — lifetime kills, credits, time played
2. Bounty Breakdown      — kills and credits by ship type
3. Session History       — per-session summary table
4. Top Hunting Grounds   — most-visited systems and stations
5. NPC Rogues' Gallery   — unique attacker names + frequency
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.state import normalise_ship_name


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ReportRow:
    cells: list[str]

@dataclass
class ReportSection:
    heading:  str
    columns:  list[str]          = field(default_factory=list)  # column headers; empty = prose
    rows:     list[ReportRow]    = field(default_factory=list)
    prose:    str                = ""                            # used when columns is empty
    note:     str                = ""                           # small footnote

@dataclass
class ReportResult:
    title:    str
    subtitle: str
    sections: list[ReportSection] = field(default_factory=list)
    error:    str                 = ""


# ── Journal scanner ───────────────────────────────────────────────────────────

def _iter_journal_events(journal_dir: Path):
    """Yield (event_dict, journal_path) for every parseable event in all journals."""
    paths = sorted(journal_dir.glob("Journal.*.log"))
    for path in paths:
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if isinstance(ev, dict) and "event" in ev:
                        yield ev, path
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass


def _fmt_credits(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


# ── Report 1: Career Overview ─────────────────────────────────────────────────

def report_career_overview(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Career Overview",
        subtitle="Lifetime statistics across all journal files"
    )

    kills         = 0
    bounty_total  = 0
    bond_total    = 0
    missions_done = 0
    mission_pay   = 0
    deaths        = 0
    rebuys        = 0
    jumps         = 0
    first_ts      = None
    last_ts       = None
    journals_read = 0
    prev_journal  = None

    for ev, jp in _iter_journal_events(journal_dir):
        if jp != prev_journal:
            journals_read += 1
            prev_journal   = jp

        ts = ev.get("timestamp", "")
        if ts:
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts

        etype = ev.get("event", "")

        if etype == "Bounty":
            kills         += 1
            bounty_total  += ev.get("TotalReward", ev.get("Reward", 0))
        elif etype == "FactionKillBond":
            kills         += 1
            bond_total    += ev.get("Reward", 0)
        elif etype == "MissionCompleted":
            missions_done += 1
            mission_pay   += ev.get("Reward", 0)
        elif etype == "Died":
            deaths += 1
        elif etype == "Resurrect":
            rebuys += ev.get("Cost", 0)
        elif etype == "FSDJump":
            jumps += 1

    # Derive date range
    date_range = "Unknown"
    if first_ts and last_ts:
        d1 = first_ts[:10]
        d2 = last_ts[:10]
        date_range = d1 if d1 == d2 else f"{d1} → {d2}"

    overview_sec = ReportSection(
        heading="Lifetime Totals",
        columns=["Metric", "Value"],
        rows=[
            ReportRow(["Journals scanned",    str(journals_read)]),
            ReportRow(["Date range",          date_range]),
            ReportRow(["Kills",               f"{kills:,}"]),
            ReportRow(["Bounty rewards",      _fmt_credits(bounty_total)]),
            ReportRow(["Kill bond rewards",   _fmt_credits(bond_total)]),
            ReportRow(["Missions completed",  f"{missions_done:,}"]),
            ReportRow(["Mission pay",         _fmt_credits(mission_pay)]),
            ReportRow(["Total combat pay",    _fmt_credits(bounty_total + bond_total)]),
            ReportRow(["Deaths",              str(deaths)]),
            ReportRow(["Rebuy costs",         _fmt_credits(rebuys)]),
            ReportRow(["Hyperspace jumps",    f"{jumps:,}"]),
        ]
    )
    result.sections.append(overview_sec)
    return result


# ── Report 2: Bounty Breakdown by Ship Type ───────────────────────────────────

def report_bounty_breakdown(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Bounty Breakdown",
        subtitle="Kills and rewards by target ship type"
    )

    by_ship: dict[str, dict] = defaultdict(lambda: {"kills": 0, "credits": 0})

    for ev, _ in _iter_journal_events(journal_dir):
        if ev.get("event") == "Bounty":
            ship   = normalise_ship_name(ev.get("Target_Localised") or ev.get("Target")) or "Unknown"
            reward = ev.get("TotalReward", ev.get("Reward", 0))
            by_ship[ship]["kills"]   += 1
            by_ship[ship]["credits"] += reward

    if not by_ship:
        result.sections.append(ReportSection(
            heading="No Data",
            prose="No Bounty events found in the journal directory."
        ))
        return result

    sorted_ships = sorted(by_ship.items(), key=lambda kv: kv[1]["credits"], reverse=True)

    sec = ReportSection(
        heading="By Ship Type  (sorted by total reward)",
        columns=["Ship", "Kills", "Total Reward", "Avg / Kill"],
    )
    for ship, data in sorted_ships[:40]:  # cap at 40 rows
        k = data["kills"]
        c = data["credits"]
        avg = c // k if k else 0
        sec.rows.append(ReportRow([ship, f"{k:,}", _fmt_credits(c), _fmt_credits(avg)]))

    result.sections.append(sec)
    return result


# ── Report 3: Session History ─────────────────────────────────────────────────

def report_session_history(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Session History",
        subtitle="Per-session summary across all journals"
    )

    # A session is delimited by LoadGame events (each journal start = new session)
    sessions = []
    cur: dict[str, Any] = {}

    def _flush():
        if cur and cur.get("kills", 0) + cur.get("missions", 0) > 0:
            sessions.append(dict(cur))

    for ev, jp in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")

        if etype == "LoadGame":
            _flush()
            cur = {
                "date":    ev.get("timestamp", "")[:10],
                "cmdr":    ev.get("Commander", ""),
                "ship":    normalise_ship_name(ev.get("Ship_Localised") or ev.get("Ship")) or "",
                "kills":   0,
                "bounty":  0,
                "missions":0,
                "mission_pay": 0,
                "deaths":  0,
            }
        elif etype == "Bounty":
            cur["kills"]  = cur.get("kills", 0) + 1
            cur["bounty"] = cur.get("bounty", 0) + ev.get("TotalReward", ev.get("Reward", 0))
        elif etype == "FactionKillBond":
            cur["kills"]  = cur.get("kills", 0) + 1
            cur["bounty"] = cur.get("bounty", 0) + ev.get("Reward", 0)
        elif etype == "MissionCompleted":
            cur["missions"]    = cur.get("missions", 0) + 1
            cur["mission_pay"] = cur.get("mission_pay", 0) + ev.get("Reward", 0)
        elif etype == "Died":
            cur["deaths"] = cur.get("deaths", 0) + 1

    _flush()

    if not sessions:
        result.sections.append(ReportSection(
            heading="No Data",
            prose="No sessions with activity found in the journal directory."
        ))
        return result

    # Most recent first
    sessions.reverse()

    sec = ReportSection(
        heading=f"{len(sessions)} sessions found",
        columns=["Date", "Commander", "Ship", "Kills", "Bounty", "Missions", "Mission Pay", "Deaths"],
    )
    for s in sessions[:60]:  # cap display at 60 rows
        sec.rows.append(ReportRow([
            s.get("date", ""),
            s.get("cmdr", ""),
            s.get("ship", ""),
            str(s.get("kills", 0)),
            _fmt_credits(s.get("bounty", 0)),
            str(s.get("missions", 0)),
            _fmt_credits(s.get("mission_pay", 0)),
            str(s.get("deaths", 0)),
        ]))
    if len(sessions) > 60:
        sec.note = f"Showing most recent 60 of {len(sessions)} sessions."
    result.sections.append(sec)
    return result


# ── Report 4: Top Hunting Grounds ─────────────────────────────────────────────

# ── Station type classification ───────────────────────────────────────────────
#
# StationType values seen in Docked / Location events.  These are the raw
# strings the game logs — names that only appear in FSSSignalDiscovered or
# CarrierLocation are NOT present here and handled separately.
#
# Fleet carrier (Drake-class personal AND Javelin-class squadron) both dock
# with StationType = "FleetCarrier".  Distinction requires cross-referencing
# CarrierLocation.CarrierType / CarrierStats.CarrierType (see report code).
#
# Stronghold Carrier: faction-controlled large vessel.  Appears in the FSS
# scanner as SignalType = "StationMegaShip" with SignalName = "Stronghold Carrier".
# If dockable it uses StationType = "StationMegaShip".  It is NOT a megaship
# in gameplay terms but is physically a large orbital vessel — categorised here
# as its own group so it never falls through to "Surface installation".

_MEGASHIP_TYPES = {
    "MegaShip",
    "MegaShipSrv",      # megaship with services bay
}

_STRONGHOLD_TYPES = {
    "StationMegaShip",  # Stronghold Carrier (faction-owned capital vessel)
}

_SURFACE_TYPES = {
    "SurfaceStation",
    "CraterOutpost",
    "CraterPort",
    "OnFootSettlement",
}

_ASTEROID_TYPES = {"AsteroidBase"}


def _station_kind(
    station_type: str,
    market_id:    int | None,
    own_fc_ids:   set[int],   # MarketIDs from CarrierStats(CarrierType=FleetCarrier)
    sqn_fc_ids:   set[int],   # MarketIDs from CarrierStats(CarrierType=SquadronCarrier)
    seen_sqn_ids: set[int],   # MarketIDs seen in CarrierLocation(CarrierType=SquadronCarrier)
) -> str:
    """Return a human-readable venue category string for the Type column.

    Carrier ID sets are built by the report during its journal scan pass:

      own_fc_ids   — CarrierStats where CarrierType = "FleetCarrier"
                     → your personal Drake-class carrier(s)

      sqn_fc_ids   — CarrierStats where CarrierType = "SquadronCarrier"
                     → squadron carriers you own or manage (DOCO etc.)
                     CarrierStats fires when YOU open the carrier management
                     panel, so this only covers carriers you have access to.

      seen_sqn_ids — CarrierLocation where CarrierType = "SquadronCarrier"
                     → any Javelin in the same system at login, regardless of
                     ownership.  Covers carriers you dock on but don't manage.
    """
    if station_type == "FleetCarrier":
        mid = market_id
        if mid and mid in own_fc_ids:
            return "Your fleet carrier"
        if mid and mid in sqn_fc_ids:
            return "Your squadron carrier"
        if mid and mid in seen_sqn_ids:
            return "Squadron carrier"
        return "Fleet carrier"
    if station_type in _STRONGHOLD_TYPES:
        return "Stronghold Carrier"
    if station_type in _MEGASHIP_TYPES:
        return "Megaship"
    if station_type in _SURFACE_TYPES:
        return "Surface installation"
    if station_type in _ASTEROID_TYPES:
        return "Asteroid base"
    return "Station / Outpost"


def report_hunting_grounds(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Top Hunting Grounds",
        subtitle="Most visited systems and stations by kill count"
    )

    # ── First pass: build carrier identity lookup tables ──────────────────────
    #
    # We need three ID sets to fully classify any FleetCarrier dock entry:
    #
    #   own_fc_ids   — personal Drake-class carriers you own
    #                  source: CarrierStats(CarrierType="FleetCarrier")
    #
    #   sqn_fc_ids   — Javelin-class squadron carriers you own/manage
    #                  source: CarrierStats(CarrierType="SquadronCarrier")
    #                  fires when you open carrier management on YOUR squadron carrier
    #
    #   seen_sqn_ids — any Javelin in your system at login (whether you own it or not)
    #                  source: CarrierLocation(CarrierType="SquadronCarrier")
    #                  fires once per session for each carrier tracked by the client
    #
    #   carrier_names — CarrierID → (callsign, display_name)
    #                   built from CarrierStats which carries both Callsign (permanent)
    #                   and Name (user-changeable).  Later events overwrite earlier ones
    #                   so the most-recently-seen name is always current.
    #                   Only populated for carriers whose management panel you open.
    #
    # MarketID in Docked/Location matches CarrierID in all carrier events.
    #
    own_fc_ids:    set[int] = set()
    sqn_fc_ids:    set[int] = set()
    seen_sqn_ids:  set[int] = set()
    carrier_names: dict[int, tuple[str, str]] = {}   # id → (callsign, name)

    for ev, _ in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")
        if etype == "CarrierStats":
            cid      = ev.get("CarrierID")
            ctype    = ev.get("CarrierType", "")
            callsign = ev.get("Callsign", "")
            name     = ev.get("Name", "").strip().title()   # game stores in ALL CAPS
            if cid:
                if ctype == "SquadronCarrier":
                    sqn_fc_ids.add(cid)
                else:
                    own_fc_ids.add(cid)
                if callsign:
                    carrier_names[cid] = (callsign, name)
        elif etype == "CarrierLocation":
            cid   = ev.get("CarrierID")
            ctype = ev.get("CarrierType", "")
            if cid and ctype == "SquadronCarrier":
                seen_sqn_ids.add(cid)

    # ── Second pass: tally kills by system and venue ──────────────────────────
    system_kills: dict[str, int] = defaultdict(int)
    # venue_kills: name → [kills, station_type, market_id]
    venue_kills:  dict[str, list] = {}

    current_system       = "Unknown"
    current_station:     str | None = None
    current_station_type = ""
    current_market_id:   int | None = None

    for ev, _ in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")
        if etype == "FSDJump":
            current_system       = ev.get("StarSystem", current_system)
            current_station      = None
            current_station_type = ""
            current_market_id    = None
        elif etype in ("Docked", "Location"):
            current_station      = ev.get("StationName")
            current_station_type = ev.get("StationType", "")
            current_market_id    = ev.get("MarketID")
        elif etype in ("Bounty", "FactionKillBond"):
            system_kills[current_system] += 1
            if current_station:
                if current_station not in venue_kills:
                    venue_kills[current_station] = [0, current_station_type, current_market_id]
                venue_kills[current_station][0] += 1

    top_systems = sorted(system_kills.items(), key=lambda x: x[1], reverse=True)[:20]

    # ── Systems section ───────────────────────────────────────────────────────
    if top_systems:
        sec = ReportSection(
            heading="Top Systems  (by kill count)",
            columns=["System", "Kills"]
        )
        for name, n in top_systems:
            sec.rows.append(ReportRow([name, f"{n:,}"]))
        result.sections.append(sec)

    # ── Venues section ────────────────────────────────────────────────────────
    if venue_kills:
        top_venues = sorted(venue_kills.items(), key=lambda x: x[1][0], reverse=True)[:20]
        sec2 = ReportSection(
            heading="Top Venues  (when docked or based nearby)",
            columns=["Venue", "Type", "Kills"],
        )
        for station_name, (kills, stype, mid) in top_venues:
            kind = _station_kind(stype, mid, own_fc_ids, sqn_fc_ids, seen_sqn_ids)
            # For fleet/squadron carriers we know the name from CarrierStats —
            # display as "CALLSIGN (Name)" so the permanent ID is always visible
            # alongside the current (potentially changed) display name.
            display_name = station_name
            if stype == "FleetCarrier" and mid and mid in carrier_names:
                callsign, cname = carrier_names[mid]
                if cname and cname.upper() != callsign.upper():
                    display_name = f"{callsign} ({cname})"
            sec2.rows.append(ReportRow([display_name, kind, f"{kills:,}"]))
        result.sections.append(sec2)

    if not top_systems and not venue_kills:
        result.sections.append(ReportSection(
            heading="No Data",
            prose="No kill events with system or location data found."
        ))
    return result


# ── Report 5: NPC Rogues' Gallery ────────────────────────────────────────────

def report_rogues_gallery(journal_dir: Path) -> ReportResult:
    # ── Find the commander name from the most recent journal ─────────────────
    # Iterate all journals in chronological order; the last LoadGame seen
    # is the most recent session, giving us the current commander name.
    _latest_cmdr: str = ""
    for ev, _ in _iter_journal_events(journal_dir):
        if ev.get("event") == "LoadGame":
            name = ev.get("Commander", "").strip()
            if name:
                _latest_cmdr = name.upper()

    _subtitle_cmdr = f"CMDR {_latest_cmdr}" if _latest_cmdr else "CMDR <unknown>"
    result = ReportResult(
        title="NPC Rogues' Gallery",
        subtitle=f"Every named pilot killed by or who has killed {_subtitle_cmdr}"
    )

    # ── Collect own commander names for self-filter ───────────────────────────
    own_names: set[str] = set()
    for ev, _ in _iter_journal_events(journal_dir):
        if ev.get("event") == "LoadGame":
            cmdr = ev.get("Commander", "")
            if cmdr:
                n = cmdr.strip().upper()
                own_names.add(n)
                own_names.add(f"CREW CMDR {n}")

    def _clean(raw: str):
        name = raw.strip()
        if not name or name.startswith("$") or len(name) < 2:
            return None
        if name.upper() in ("SYSTEM AUTHORITY VESSEL", "CLEAN", "WANTED"):
            return None
        nu = name.upper()
        if nu in own_names:
            return None
        for own in own_names:
            if nu == f"CREW CMDR {own}" or nu.endswith(own):
                return None
        return name

    # ── Journal scan ──────────────────────────────────────────────────────────
    #
    # Sources (from actual journal inspection):
    #
    #   Bounty.PilotName_Localised   — NPC you killed; on every Bounty event.
    #                                   Primary and most reliable name source.
    #   Bounty.PilotName "$ShipName_Police*" — authority vessel you destroyed.
    #
    #   Died.Killers[].Name          — pilots who killed you.
    #
    #   Interdicted (Submitted=false, IsPlayer=false)
    #                                — NPC interdiction you fought off.
    #
    #   PVPKill.Victim               — player you killed.
    #
    #   Scanned (ScanType=Cargo)     — cop scanned your cargo. No individual
    #                                   name available; counted as interactions.
    #
    # NOT used:
    #   ShipTargeted  — fires on every target lock; no engagement implied
    #   UnderAttack   — no pilot name field
    #   Interdicted (Submitted=true) — you fled; no fight
    #
    _POLICE_PREFIX = "$shipname_police"

    pirate_counts: dict[str, int] = defaultdict(int)
    killed_us:     dict[str, int] = defaultdict(int)
    pvp_counts:    dict[str, int] = defaultdict(int)
    cop_kills  = 0
    cop_deaths = 0
    cop_scans  = 0

    for ev, _ in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")

        if etype == "Bounty":
            raw_key = ev.get("PilotName", "")
            if raw_key.lower().startswith(_POLICE_PREFIX):
                cop_kills += 1
            else:
                name = _clean(ev.get("PilotName_Localised", raw_key))
                if name:
                    pirate_counts[name] += 1

        elif etype == "Died":
            killers = ev.get("Killers", [])
            if not killers:
                killers = [{"Name": ev.get("KillerName", "")}]
            for k in killers:
                raw_key = k.get("Name", "")
                if raw_key.lower().startswith(_POLICE_PREFIX):
                    cop_deaths += 1
                elif raw_key.upper().startswith("CMDR "):
                    name = _clean(raw_key)
                    if name:
                        pvp_counts[name] = pvp_counts.get(name, 0) + 1
                else:
                    name = _clean(k.get("Name_Localised", raw_key))
                    if name:
                        killed_us[name] = killed_us.get(name, 0) + 1

        elif etype == "Interdicted" and not ev.get("Submitted", True) and not ev.get("IsPlayer", False):
            name = _clean(ev.get("Interdictor_Localised", ev.get("Interdictor", "")))
            if name:
                pirate_counts[name] += 1

        elif etype == "PVPKill":
            name = _clean(ev.get("Victim", ""))
            if name:
                pvp_counts[name] = pvp_counts.get(name, 0) + 1

        elif etype == "Scanned" and ev.get("ScanType") == "Cargo":
            cop_scans += 1

    # ── Build sections ────────────────────────────────────────────────────────

    if not pirate_counts and not killed_us and not pvp_counts and not cop_scans:
        result.sections.append(ReportSection(
            heading="No Records",
            prose=(
                "No combat engagements found. "
                "This report sources pilot names from Bounty events (kills you made), "
                "Died events (who killed you), and fought-off NPC interdictions. "
                "Data will appear after sessions with active combat."
            )
        ))
        return result

    # Kills made
    if pirate_counts:
        total_unique = len(pirate_counts)
        total_kills  = sum(pirate_counts.values())
        by_freq      = sorted(pirate_counts.items(), key=lambda x: (-x[1], x[0].lower()))
        by_alpha     = sorted(pirate_counts.items(), key=lambda x: x[0].lower())

        repeat_offenders = [(n, c) for n, c in by_freq if c > 1]
        if repeat_offenders:
            sec_repeat = ReportSection(
                heading=f"Repeat Offenders  ({len(repeat_offenders)} pilots encountered more than once)",
                columns=["Name", "Times killed"],
                note="Either very unlucky, or the same name reused by the RNG."
            )
            for name, count in repeat_offenders[:50]:
                sec_repeat.rows.append(ReportRow([name, str(count)]))
            result.sections.append(sec_repeat)

        sec_kills = ReportSection(
            heading=f"Pilots Destroyed — Alphabetical  ({total_unique} unique · {total_kills} total kills)",
            columns=["Name", "Times killed"],
        )
        for name, count in by_alpha:
            sec_kills.rows.append(ReportRow([name, str(count)]))
        result.sections.append(sec_kills)

    # Pilots who killed us
    if killed_us:
        sec_killers = ReportSection(
            heading=f"Pilots Who Have Killed You  ({len(killed_us)} unique)",
            columns=["Name", "Times"],
        )
        for name, count in sorted(killed_us.items(), key=lambda x: (-x[1], x[0].lower())):
            sec_killers.rows.append(ReportRow([name, str(count)]))
        result.sections.append(sec_killers)

    # Space cops
    if cop_scans or cop_deaths or cop_kills:
        sec_cops = ReportSection(
            heading="Law Enforcement Interactions",
            columns=["Metric", "Count"],
            rows=[
                ReportRow(["Times police scanned your cargo",    str(cop_scans)]),
                ReportRow(["Times killed by law enforcement",    str(cop_deaths)]),
                ReportRow(["Authority vessels destroyed by you", str(cop_kills)]),
            ],
            note="Police have no individual names in the journal — only 'System Authority Vessel'."
        )
        result.sections.append(sec_cops)

    # PvP
    if pvp_counts:
        sec_pvp = ReportSection(
            heading=f"Player vs Player  ({len(pvp_counts)} unique commanders)",
            columns=["Commander", "Engagements"],
        )
        for name, count in sorted(pvp_counts.items(), key=lambda x: (-x[1], x[0].lower())):
            sec_pvp.rows.append(ReportRow([name, str(count)]))
        result.sections.append(sec_pvp)

    return result


# ── Report 6: Exploration ─────────────────────────────────────────────────────

def _get_latest_statistics(journal_dir: Path) -> dict:
    """Return the most recent Statistics event dict, or {} if none found."""
    result = {}
    result_ts = ""
    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("event") == "Statistics":
                        ts = ev.get("timestamp", "")
                        if ts > result_ts:
                            result_ts = ts
                            result = ev
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass
    return result


# ── Report 6: Exploration ─────────────────────────────────────────────────────

def report_exploration(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Exploration",
        subtitle="Career exploration statistics"
    )

    # ── Section 1: Career totals from Statistics event (authoritative) ────────
    # Statistics fires on every login and contains Frontier's server-side career
    # totals. These cover the full account history regardless of journal coverage.
    stats = _get_latest_statistics(journal_dir)
    expl  = stats.get("Exploration", {})

    if expl:
        career_sec = ReportSection(
            heading="Career Totals  (from game statistics)",
            columns=["Metric", "Value"],
            rows=[
                ReportRow(["Systems visited",         f"{expl.get('Systems_Visited', 0):,}"]),
                ReportRow(["Hyperspace jumps",        f"{expl.get('Total_Hyperspace_Jumps', 0):,}"]),
                ReportRow(["Distance travelled",      f"{expl.get('Total_Hyperspace_Distance', 0):,.0f} ly"]),
                ReportRow(["Exploration profits",     _fmt_credits(expl.get("Exploration_Profits", 0))]),
                ReportRow(["Planets FSS scanned",     f"{expl.get('Planets_Scanned_To_Level_2', 0):,}"]),
                ReportRow(["Planets DSS mapped",      f"{expl.get('Planets_Scanned_To_Level_3', 0):,}"]),
                ReportRow(["Efficient scans",         f"{expl.get('Efficient_Scans', 0):,}"]),
                ReportRow(["Highest payout",          _fmt_credits(expl.get("Highest_Payout", 0))]),
                ReportRow(["First footfalls",         f"{expl.get('First_Footfalls', 0):,}"]),
                ReportRow(["Planet footfalls",        f"{expl.get('Planet_Footfalls', 0):,}"]),
                ReportRow(["Settlements visited",     f"{expl.get('Settlements_Visited', 0):,}"]),
            ]
        )
        result.sections.append(career_sec)

    # ── Section 2: Journal breakdown by planet class ──────────────────────────
    # Journal data covers only the journals present in the folder. This may not
    # represent the full career if older journals have been deleted or archived.
    by_class: dict[str, dict] = defaultdict(
        lambda: {"scanned": 0, "first_disc": 0, "mapped": 0, "first_mapped": 0}
    )
    by_star: dict[str, int] = defaultdict(int)
    seen_bodies: set[tuple] = set()
    pending: dict = {}

    carto_sold_total  = 0
    carto_base_total  = 0
    carto_bonus_total = 0
    carto_sell_events = 0

    for ev, _ in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")

        if etype == "Scan":
            scan_type = ev.get("ScanType", "")
            if scan_type not in ("AutoScan", "Detailed", ""):
                continue
            sys_addr = ev.get("SystemAddress")
            body_id  = ev.get("BodyID")
            bk       = (sys_addr, body_id)
            if sys_addr and body_id is not None:
                if bk in seen_bodies:
                    continue
                seen_bodies.add(bk)

            planet_class = ev.get("PlanetClass", "")
            star_type    = ev.get("StarType", "")
            was_disc     = ev.get("WasDiscovered", True)
            was_mapped   = ev.get("WasMapped", True)

            if planet_class:
                pc = planet_class.strip()
                by_class[pc]["scanned"] += 1
                if not was_disc:
                    by_class[pc]["first_disc"] += 1
                if body_id is not None:
                    pending[body_id] = {"class": pc, "was_mapped": was_mapped}
            elif star_type:
                by_star[star_type.strip()] += 1

        elif etype == "SAAScanComplete":
            body_id = ev.get("BodyID")
            p = pending.get(body_id)
            if p:
                pc = p["class"]
                by_class[pc]["mapped"] += 1
                if not p["was_mapped"]:
                    by_class[pc]["first_mapped"] += 1

        elif etype in ("SellExplorationData", "MultiSellExplorationData"):
            base  = ev.get("BaseValue", 0)
            bonus = ev.get("Bonus", 0)
            total = ev.get("TotalEarnings", 0) or (base + bonus)
            carto_sold_total  += total
            carto_base_total  += base
            carto_bonus_total += bonus
            carto_sell_events += 1

    if by_class or by_star:
        journal_note = (
            "Journal coverage only — may not reflect full career if older journals "
            "are not present in the journal folder."
        )

        # Journal sell summary
        if carto_sold_total:
            sell_sec = ReportSection(
                heading="Cartography Sales  (journals only)",
                columns=["Metric", "Value"],
                note=journal_note,
                rows=[
                    ReportRow(["Total sold",       _fmt_credits(carto_sold_total)]),
                    ReportRow(["Discovery bonus",  _fmt_credits(carto_bonus_total)]),
                    ReportRow(["Sell events",      f"{carto_sell_events:,}"]),
                ]
            )
            result.sections.append(sell_sec)

        # By planet class
        planet_sec = ReportSection(
            heading="By Planet Class  (journals only)",
            columns=["Class", "Scanned", "1st Disc", "DSS", "1st Map"],
            note=journal_note,
        )
        for cls in sorted(by_class, key=lambda c: -by_class[c]["scanned"]):
            d = by_class[cls]
            planet_sec.rows.append(ReportRow([
                cls,
                f"{d['scanned']:,}",
                f"{d['first_disc']:,}" if d["first_disc"]  else "—",
                f"{d['mapped']:,}"     if d["mapped"]       else "—",
                f"{d['first_mapped']:,}" if d["first_mapped"] else "—",
            ]))
        result.sections.append(planet_sec)

        # By star type
        if by_star:
            star_sec = ReportSection(
                heading="By Star Type  (journals only)",
                columns=["Star Type", "Count"],
                note=journal_note,
            )
            for st in sorted(by_star, key=lambda s: -by_star[s]):
                star_sec.rows.append(ReportRow([st, f"{by_star[st]:,}"]))
            result.sections.append(star_sec)

    if not expl and not by_class and not by_star:
        result.sections.append(ReportSection(
            heading="No Data",
            prose="No exploration data found."
        ))

    return result


# ── Report 7: Exobiology ──────────────────────────────────────────────────────

def report_exobiology(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="Exobiology",
        subtitle="Career exobiology statistics"
    )

    # ── Section 1: Career totals from Statistics event (authoritative) ────────
    stats = _get_latest_statistics(journal_dir)
    exo   = stats.get("Exobiology", {})

    if exo:
        career_sec = ReportSection(
            heading="Career Totals  (from game statistics)",
            columns=["Metric", "Value"],
            rows=[
                ReportRow(["Samples analysed",     f"{exo.get('Organic_Data', 0):,}"]),
                ReportRow(["Total sold value",      _fmt_credits(exo.get("Organic_Data_Profits", 0))]),
                ReportRow(["First logged",          f"{exo.get('First_Logged', 0):,}"]),
                ReportRow(["First logged profits",  _fmt_credits(exo.get("First_Logged_Profits", 0))]),
                ReportRow(["Genus encountered",     f"{exo.get('Organic_Genus_Encountered', 0):,}"]),
                ReportRow(["Species encountered",   f"{exo.get('Organic_Species_Encountered', 0):,}"]),
                ReportRow(["Variants encountered",  f"{exo.get('Organic_Variant_Encountered', 0):,}"]),
                ReportRow(["Systems with biology",  f"{exo.get('Organic_Systems', 0):,}"]),
                ReportRow(["Planets with biology",  f"{exo.get('Organic_Planets', 0):,}"]),
                ReportRow(["Genus analysed",        f"{exo.get('Organic_Genus', 0):,}"]),
                ReportRow(["Species analysed",      f"{exo.get('Organic_Species', 0):,}"]),
            ]
        )
        result.sections.append(career_sec)

    # ── Section 2: Journal breakdown by species ───────────────────────────────
    by_species: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "sold": 0, "first_disc": 0, "footfall": 0, "value_sold": 0}
    )
    by_genus: dict[str, int] = defaultdict(int)
    total_analysed   = 0
    total_sold_value = 0
    total_sold_count = 0
    total_first_disc = 0
    total_footfall   = 0
    pending_species: list[dict] = []

    def _genus_label(key: str) -> str:
        k = key.lower()
        for g in ("aleoida", "bacterium", "bacterial", "cactoida", "clypeus",
                  "concha", "electricae", "fonticulua", "fonticulus", "frutexa",
                  "fumerola", "fungoida", "osseus", "recepta", "stratum",
                  "tubus", "tussock", "shrubs"):
            if g in k:
                return g.title()
        return "Other"

    for ev, _ in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")

        if etype == "ScanOrganic" and ev.get("ScanType") == "Analyse":
            total_analysed += 1
            sp_key   = ev.get("Species", "")
            sp_local = ev.get("Species_Localised", sp_key) or sp_key
            genus    = _genus_label(sp_key)
            was_logged = bool(ev.get("WasLogged", True))
            footfall   = (ev.get("WasFootfalled") is False)
            by_species[sp_local]["count"] += 1
            by_genus[genus] += 1
            if not was_logged:
                by_species[sp_local]["first_disc"] += 1
                total_first_disc += 1
            if footfall:
                by_species[sp_local]["footfall"] += 1
                total_footfall += 1
            pending_species.append({"key": sp_key, "local": sp_local})

        elif etype == "SellOrganicData":
            for item in ev.get("BioData", []):
                sp  = item.get("Species", "")
                val = int(item.get("Value", 0))
                sp_local = item.get("Species_Localised", sp) or sp
                total_sold_value += val
                total_sold_count += 1
                by_species[sp_local]["sold"]       += 1
                by_species[sp_local]["value_sold"] += val
                for i, p in enumerate(pending_species):
                    if p["key"] == sp:
                        pending_species.pop(i)
                        break

    if total_analysed > 0:
        journal_note = (
            "Journal coverage only — may not reflect full career if older journals "
            "are not present in the journal folder."
        )

        if by_genus:
            genus_sec = ReportSection(
                heading="By Genus  (journals only)",
                columns=["Genus", "Samples"],
                note=journal_note,
            )
            for genus in sorted(by_genus, key=lambda g: -by_genus[g]):
                genus_sec.rows.append(ReportRow([genus, f"{by_genus[genus]:,}"]))
            result.sections.append(genus_sec)

        if by_species:
            species_sec = ReportSection(
                heading="By Species  (journals only)",
                columns=["Species", "Analysed", "Sold", "1st Disc", "Footfall", "Value Sold"],
                note=journal_note,
            )
            for sp in sorted(by_species, key=lambda s: -by_species[s]["count"]):
                d = by_species[sp]
                species_sec.rows.append(ReportRow([
                    sp,
                    f"{d['count']:,}",
                    f"{d['sold']:,}"       if d["sold"]       else "—",
                    f"{d['first_disc']:,}" if d["first_disc"] else "—",
                    f"{d['footfall']:,}"   if d["footfall"]   else "—",
                    _fmt_credits(d["value_sold"]) if d["value_sold"] else "—",
                ]))
            result.sections.append(species_sec)

    if not exo and total_analysed == 0:
        result.sections.append(ReportSection(
            heading="No Data",
            prose="No exobiology data found."
        ))

    return result


# ── Report 8: PowerPlay ───────────────────────────────────────────────────────

def report_powerplay(journal_dir: Path) -> ReportResult:
    result = ReportResult(
        title="PowerPlay",
        subtitle="Merit history by system since current pledge"
    )

    # TotalMerits in each PowerplayMerits event is the server's authoritative
    # running total. MeritsGained is the client's estimate and may differ from
    # the server total due to wing kill award adjustments. We always use the
    # last TotalMerits seen as the definitive figure.
    pp_active      = False
    pp_power       = ""
    pp_rank        = 0
    pp_total       = 0    # last TotalMerits seen from any PP event
    system_merits: dict[str, int] = defaultdict(int)
    current_system = ""
    pledge_date    = ""
    merit_events   = 0

    for ev, _ in _iter_journal_events(journal_dir):
        etype = ev.get("event", "")
        ts    = ev.get("timestamp", "")

        if etype in ("FSDJump", "Location", "CarrierJump"):
            current_system = ev.get("StarSystem", current_system)

        elif etype == "Powerplay":
            pp_active = True
            pp_power  = ev.get("Power", pp_power)
            snap      = ev.get("Merits", 0)
            if snap and snap > pp_total:
                pp_total = snap
            pp_rank = ev.get("Rank", pp_rank)
            if not pledge_date:
                pledge_date = ts[:10]

        elif etype == "PowerplayJoin":
            pp_active = True
            pp_power  = ev.get("Power", "")
            pp_total  = 0
            system_merits.clear()
            merit_events  = 0
            pledge_date   = ts[:10]

        elif etype == "PowerplayLeave":
            pp_active = False
            pp_power  = ""
            pp_total  = 0
            system_merits.clear()
            merit_events  = 0
            pledge_date   = ""

        elif etype == "PowerplayRank":
            pp_rank = ev.get("Rank", pp_rank)

        elif etype == "PowerplayMerits" and pp_active:
            gained = ev.get("MeritsGained", 0)
            total  = ev.get("TotalMerits")
            if total is not None:
                pp_total = total   # always trust the server's running total
            if gained > 0:
                merit_events += 1
                sys = current_system or "Unknown"
                system_merits[sys] += gained

    if not pp_active and not pp_power:
        result.sections.append(ReportSection(
            heading="Not Pledged",
            prose="No PowerPlay pledge found in the journal directory."
        ))
        return result

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = ReportSection(
        heading=f"PowerPlay — {pp_power}",
        columns=["Metric", "Value"],
        rows=[
            ReportRow(["Power",              pp_power]),
            ReportRow(["Rank",               str(pp_rank)]),
            ReportRow(["Merits (current)",   f"{pp_total:,}"]),
            ReportRow(["Merit events",       f"{merit_events:,}"]),
        ]
    )
    if pledge_date:
        summary.rows.insert(0, ReportRow(["Pledged since (journals)", pledge_date]))
    result.sections.append(summary)

    # ── Per-system breakdown ──────────────────────────────────────────────────
    if system_merits:
        total_sys = sum(system_merits.values())
        sec = ReportSection(
            heading="Merits Earned by System",
            columns=["System", "Merits Earned", "% of Total"],
        )
        for sys, merits in sorted(system_merits.items(), key=lambda x: -x[1]):
            pct = f"{merits / total_sys * 100:.1f}%"
            sec.rows.append(ReportRow([sys, f"{merits:,}", pct]))
        result.sections.append(sec)

    return result


# ── Registry ──────────────────────────────────────────────────────────────────

REPORT_REGISTRY = [
    ("career",      "Career Overview",       report_career_overview),
    ("bounty",      "Bounty Breakdown",      report_bounty_breakdown),
    ("sessions",    "Session History",       report_session_history),
    ("grounds",     "Hunting Grounds",       report_hunting_grounds),
    ("rogues",      "NPC Rogues' Gallery",   report_rogues_gallery),
    ("exploration", "Exploration",           report_exploration),
    ("exobiology",  "Exobiology",            report_exobiology),
    ("powerplay",   "PowerPlay",             report_powerplay),
]

"""
components/crew_slf.py — NPC Crew and SLF (Support Landing Fighter) state.

Owns: crew_*, slf_*, has_fighter_bay, cmdr_in_slf, fighter_integrity.
GUI block: col=16, row=0, width=8, height=5 (default).
"""

import re
from core.plugin_loader import BasePlugin
from core.emit import Terminal
from core.state import FIGHTER_LOADOUT_NAMES, FIGHTER_TYPE_NAMES, resolve_fighter_name


class CrewSlfPlugin(BasePlugin):
    PLUGIN_NAME    = "crew_slf"
    PLUGIN_DISPLAY = "NPC Crew & SLF"
    PLUGIN_DESCRIPTION = "NPC crew details and fighter bay status including hull integrity."
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "CrewAssign", "CrewHire", "CrewFire",
        "NpcCrewPaidWage", "NpcCrewRank",
        "LaunchFighter", "DockFighter", "FighterDestroyed",
        "FighterRebuilt", "FighterOrders", "RestockVehicle",
        "HullDamage", "Loadout", "ShipyardSwap",
    ]

    DEFAULT_COL    = 16
    DEFAULT_ROW    = 0
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 5

    _FIGHTERBAY_CAPACITY = {"3": 1, "5": 4, "6": 6, "7": 9, "8": 12}

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=15)
        s = core.state
        if not hasattr(s, "slf_ship_id"): s.slf_ship_id = None
        # Per-crew-name combat-rank cache.  Populated by CrewHire and
        # NpcCrewRank events so we can restore the right rank when the
        # active crew changes (CrewAssign for someone we already know).
        # Ephemeral — not persisted across restarts.  Bootstrap recovers
        # the active crew's rank from journals on startup; for inactive
        # crew we'll see an NpcCrewRank within minutes of activation.
        if not hasattr(s, "crew_known_ranks"): s.crew_known_ranks = {}


    def _bootstrap_type_from_journals(self) -> None:
        """Scan journals for the most recent RestockVehicle for the CURRENT ship.

        Scans newest-first, tracking which ShipID was active at each point via
        Loadout events. Only accepts a RestockVehicle that occurred while the
        current ship was active — avoids picking up fighter types from other
        ships the player owns.
        """
        try:
            import json as _j, pathlib as _pl
            from core.state import resolve_fighter_name as _rfn
            # Identify current ship from the ShipID stored by the last Loadout event.
            # This is set directly from the journal and doesn't depend on assets plugin.
            current_sid = getattr(self.core.state, "slf_ship_id", None)
            if current_sid is None:
                # No ShipID known yet — don't guess, leave slf_type=None
                return

            jdir     = _pl.Path(self.core.journal_dir)
            journals = sorted(jdir.glob("Journal*.log"), reverse=True)

            # Track which ShipID was active as we walk backwards through events
            active_sid: int | None = current_sid

            for jp in journals:
                try:
                    lines = jp.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in reversed(lines):
                    try:
                        ev = _j.loads(line)
                    except ValueError:
                        continue
                    evt = ev.get("event")

                    # Walking backwards: a Loadout event tells us which ship
                    # was active at this point in time
                    if evt == "Loadout":
                        try:
                            active_sid = int(ev.get("ShipID", 0)) or None
                        except (TypeError, ValueError):
                            pass

                    if evt == "RestockVehicle":
                        ft = ev.get("Type", "")
                        lo = ev.get("Loadout", "")
                        if not ft:
                            continue
                        # Skip restocks with no Loadout — Frontier omits it when
                        # only one variant is stocked, making the resolved name
                        # ambiguous. Keep scanning for one with a Loadout field.
                        if not lo:
                            continue
                        # Only use if this restock happened on the current ship
                        if current_sid is None or active_sid == current_sid:
                            self.core.state.slf_known_ft = ft
                            self.core.state.slf_type = _rfn(ft, lo)
                            gq = self.core.gui_queue
                            if gq:
                                gq.put(("slf_update", None))
                            return
        except Exception:
            pass


    def _bootstrap_crew_from_journals(self) -> None:
        """Scan recent journals for the last CrewAssign {Role: Active} event.

        Called when Loadout fires and SLF type is unknown (state reset path).
        Finds the most recent CrewAssign to restore crew_name authorit-
        atively — regardless of NpcCrewPaidWage event ordering.
        """
        try:
            import json as _j, pathlib as _pl
            jdir     = _pl.Path(self.core.journal_dir)
            journals = sorted(jdir.glob("Journal*.log"), reverse=True)

            for jp in journals:
                try:
                    lines = jp.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in reversed(lines):
                    try:
                        ev = _j.loads(line)
                    except ValueError:
                        continue
                    if ev.get("event") == "CrewAssign" and ev.get("Role") == "Active":
                        name = ev.get("Name")
                        if name:
                            self.core.state.crew_name   = name
                            self.core.state.crew_active = True
                            gq = self.core.gui_queue
                            if gq:
                                gq.put(("crew_update", None))
                            return
        except Exception:
            pass

    def on_event(self, event: dict, state) -> None:
        core    = self.core
        gq      = core.gui_queue
        notify  = core.notify_levels
        cfg     = core.cfg
        ev      = event.get("event")
        logtime = event.get("_logtime")

        match ev:

            case "ShipyardSwap":
                # Switching ships: clear fighter type so stale data from
                # another ship's bay doesn't persist.
                state.slf_type     = None
                state.slf_deployed = False
                state.slf_docked   = False
                if gq: gq.put(("plugin_refresh", "crew_slf"))

            case "Loadout":
                # Track which ship we're on — used by bootstrap to avoid
                # picking up RestockVehicle events from other ships.
                state.slf_ship_id = event.get("ShipID")
                # Fighter bay detection — drives crew and SLF visibility
                slf_found = False
                slf_cap   = 0
                for mod in event.get("Modules", []):
                    item = mod.get("Item", "").lower()
                    if "fighterbay" in item:
                        slf_found = True
                        m = re.search(r"fighterbay_size(\d+)", item)
                        if m:
                            slf_cap = max(slf_cap, self._FIGHTERBAY_CAPACITY.get(m.group(1), 1))
                state.has_fighter_bay = slf_found
                if slf_found:
                    state.slf_stock_total     = slf_cap or 1
                    state.slf_destroyed_count = 0
                if not slf_found:
                    state.slf_type     = None
                    state.slf_deployed = False
                    state.slf_docked   = False
                elif state.slf_type is None or "(" not in (state.slf_type or ""):
                    # Fighter bay present but type unknown — schedule a
                    # bootstrap scan to recover from RestockVehicle history.
                    import threading as _thr
                    _thr.Thread(
                        target=self._bootstrap_type_from_journals,
                        daemon=True,
                    ).start()
                    state.slf_hull     = 100
                    state.slf_loadout  = None
                    state.crew_active  = False
                    state.crew_name    = None
                    # Bootstrap crew_name from the last CrewAssign in journals
                    # so we don't rely on NpcCrewPaidWage ordering to identify
                    # who the active crew member is.
                    import threading as _ct
                    _ct.Thread(
                        target=self._bootstrap_crew_from_journals,
                        daemon=True,
                    ).start()
                if slf_found and state.crew_name and not state.crew_active:
                    state.crew_active = True
                if gq:
                    gq.put(("slf_update",  None))
                    gq.put(("crew_update", None))

            case "FighterDestroyed" if state.prev_event != "StartJump":
                state.slf_deployed        = False
                state.slf_docked          = False
                state.slf_hull            = 0
                state.slf_orders          = None
                state.slf_destroyed_count += 1
                if gq: gq.put(("slf_update", None))
                core.emitter.emit(
                    msg_term=f"{Terminal.BAD}Fighter destroyed!{Terminal.END}",
                    msg_discord="**Fighter destroyed!**",
                    emoji="💀", sigil="!! SLF ",
                    timestamp=logtime, loglevel=notify["FighterLost"],
                )

            case "LaunchFighter" if not event.get("PlayerControlled"):
                state.slf_deployed = True
                state.slf_docked   = False
                state.slf_hull     = 100
                state.slf_orders   = "Defend"
                state.slf_loadout  = event.get("Loadout")
                # Frontier omits Type when only one type is stocked.
                # Use slf_known_ft (from RestockVehicle) + the loadout key
                # to resolve the exact variant even without a Type field.
                _ft = event.get("Type", "") or getattr(state, "slf_known_ft", "") or ""
                _lo = event.get("Loadout", "")
                if _ft:
                    state.slf_type = resolve_fighter_name(_ft, _lo)
                elif state.slf_type is None or "(" not in (state.slf_type or ""):
                    import threading as _thr
                    _thr.Thread(
                        target=self._bootstrap_type_from_journals,
                        daemon=True,
                    ).start()
                if gq: gq.put(("slf_update", None))
                core.emitter.emit(
                    msg_term="Fighter launched",
                    emoji="🛩️", sigil="-  SLF ",
                    timestamp=logtime, loglevel=2,
                )

            case "RestockVehicle":
                ft   = event.get("Type", "")
                lo   = event.get("Loadout", "")
                if ft:
                    state.slf_known_ft = ft
                state.slf_type = resolve_fighter_name(ft, lo)
                state.slf_destroyed_count = 0
                state.slf_docked          = True
                state.slf_deployed        = False
                if gq: gq.put(("slf_update", None))

            case "DockFighter":
                state.slf_deployed      = False
                state.slf_docked        = True
                state.slf_hull          = 100
                state.fighter_integrity = 1.0   # reset so next launch reads fresh
                state.slf_orders        = None
                if gq: gq.put(("slf_update", None))

            case "FighterRebuilt":
                state.slf_destroyed_count = max(0, state.slf_destroyed_count - 1)
                if gq: gq.put(("slf_update", None))

            case "FighterOrders":
                state.slf_orders = event.get("Orders")
                if gq: gq.put(("slf_update", None))

            case "HullDamage":
                hullhealth = round(event["Health"] * 100)
                if event.get("Fighter") and not event.get("PlayerPilot"):
                    if state.fighter_integrity != event["Health"]:
                        state.fighter_integrity = event["Health"]
                        state.slf_hull          = hullhealth
                        if gq: gq.put(("slf_update", None))
                        core.emitter.emit(
                            msg_term=(
                                f"{Terminal.WARN}Fighter hull damaged!{Terminal.END} "
                                f"(Integrity: {hullhealth}%)"
                            ),
                            msg_discord=f"**Fighter hull damaged!** (Integrity: {hullhealth}%)",
                            emoji="🛩️", sigil="^  SLF ",
                            timestamp=logtime, loglevel=notify["FighterDamage"],
                        )
                elif event.get("PlayerPilot") and not event.get("Fighter"):
                    state.ship_hull = hullhealth
                    if gq: gq.put(("vessel_update", None))
                    core.emitter.emit(
                        msg_term=(
                            f"{Terminal.BAD}Ship hull damaged!{Terminal.END} "
                            f"(Integrity: {hullhealth}%)"
                        ),
                        msg_discord=f"**Ship hull damaged!** (Integrity: {hullhealth}%)",
                        emoji="⚠️", sigil="^  HULL",
                        timestamp=logtime, loglevel=notify["HullEvent"],
                    )

            case "CrewHire":
                # Hiring a new NPC crew member.  Frontier supplies their
                # CombatRank in this event; cache it so a later CrewAssign
                # can pick the right rank up immediately, instead of leaving
                # the previous crew member's rank visible.
                name = event.get("Name")
                rank = event.get("CombatRank")
                if name and isinstance(rank, int):
                    if not hasattr(state, "crew_known_ranks"):
                        state.crew_known_ranks = {}
                    state.crew_known_ranks[name] = rank
                    # Edge case: re-hiring while already active.  Refresh
                    # the live rank too so the display doesn't go stale.
                    if state.crew_name == name:
                        state.crew_rank = rank
                        if gq: gq.put(("crew_update", None))

            case "CrewFire":
                # Firing an NPC.  Drop them from the rank cache, and if
                # they were the active crew, clear active state so the
                # display doesn't keep showing a fired pilot's name and
                # rank between the fire and the next CrewAssign.
                name = event.get("Name")
                if name:
                    if hasattr(state, "crew_known_ranks"):
                        state.crew_known_ranks.pop(name, None)
                    if state.crew_name == name:
                        state.crew_name       = None
                        state.crew_rank       = None
                        state.crew_active     = False
                        state.crew_total_paid = 0
                        if gq: gq.put(("crew_update", None))

            case "CrewAssign":
                name = event.get("Name")
                if name:
                    if state.crew_name != name:
                        state.crew_total_paid = 0
                        # Crew member changed.  Refresh rank from the
                        # known-ranks cache (populated by CrewHire and
                        # NpcCrewRank); fall back to None when we have no
                        # cached value so the display doesn't carry the
                        # outgoing crew member's rank forward.  The next
                        # NpcCrewRank event for this crew will refine.
                        cached = (getattr(state, "crew_known_ranks", {}) or {}).get(name)
                        state.crew_rank = cached  # None when unknown
                    state.crew_name   = name
                    state.crew_active = True
                if gq: gq.put(("crew_update", None))

            case "NpcCrewPaidWage":
                wage_name = event.get("NpcCrewName")
                # crew_name is set exclusively by CrewAssign (and its bootstrap).
                # Never infer active crew from wage events — with multiple crew
                # hired, both receive NpcCrewPaidWage and the ordering is not
                # guaranteed to put the active member first.
                if wage_name and wage_name == state.crew_name:
                    state.crew_active = True
                    if state.crew_total_paid is None:
                        state.crew_total_paid = 0
                    state.crew_total_paid += event.get("Amount", 0)
                if gq: gq.put(("crew_update", None))

            case "NpcCrewRank":
                rank_name = event.get("NpcCrewName")
                new_rank  = event.get("RankCombat")
                # Always cache by name — even when the rank-up is for an
                # inactive crew member, we want the value ready for the
                # moment they're activated.
                if rank_name and isinstance(new_rank, int):
                    if not hasattr(state, "crew_known_ranks"):
                        state.crew_known_ranks = {}
                    state.crew_known_ranks[rank_name] = new_rank
                if not state.crew_name and rank_name:
                    state.crew_name = rank_name
                if rank_name and rank_name == state.crew_name:
                    if isinstance(new_rank, int):
                        state.crew_rank = new_rank
                if gq: gq.put(("crew_update", None))

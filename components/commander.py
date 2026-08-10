"""
components/commander.py — Commander, ship, location, and powerplay state.

Owns: pilot_*, pp_*, ship_*, in_game, pilot_mode, location tracking.
Dashboard block: commander.
"""

from core.plugin_loader import BasePlugin
from core.state import RANK_NAMES
from core.emit import Terminal



def _read_nav_route_json(journal_dir) -> list | None:
    """Read NavRoute.json from the journal directory.

    Returns the Route list on success, or None if the file is absent,
    unreadable, or contains an empty/cleared route.
    """
    import json as _json
    from pathlib import Path as _Path
    try:
        p = _Path(journal_dir) / "NavRoute.json"
        if not p.exists():
            return None
        data = _json.loads(p.read_text(encoding="utf-8"))
        route = data.get("Route") or []
        return route if route else None
    except Exception:
        return None


class CommanderPlugin(BasePlugin):
    PLUGIN_NAME    = "commander"
    PLUGIN_DISPLAY = "Commander"
    PLUGIN_DESCRIPTION = "Commander identity, ship vitals, location, ranks, and PowerPlay status."
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "Commander", "LoadGame", "Rank", "Progress", "Reputation",
        "Location", "Docked", "Undocked",
        "FSDJump", "SupercruiseEntry", "SupercruiseExit",
        "ShipyardSwap", "Loadout",
        "Powerplay", "PowerplayJoin", "PowerplayLeave",
        "PowerplayDefect", "PowerplayRank", "PowerplayMerits",
        "VehicleSwitch", "Shutdown", "Music",
        "NavRoute",
        "EngineerProgress",
        "ReservoirReplenished",   # fuel level updates
        "HullDamage",             # player ship/SRV hull integrity updates
        "RepairAll",              # ship repaired — hull to 100%
        "RepairPartial",          # station repair — hull to 100%
        "ShieldState",            # shield up/down — ship or suit
        "LaunchSRV",              # player entered SRV
        "DockSRV",                # player returned to ship from SRV
        "Disembark",              # player went on foot
        "Embark",                 # player entered SRV or ship from on foot
        "SuitLoadout",            # suit and loadout name when on foot
    ]

    # Default grid placement (legacy)
    DEFAULT_COL    = 0
    DEFAULT_ROW    = 0
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 6

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=10)
        # Read current fuel level from Status.json so the block shows a value
        # immediately on startup rather than waiting for the first refuel event.
        self._read_status_json(core)
        # Load persisted home location
        self._load_home_location()
        # True once a live (post-preload) Location or FSDJump event has updated
        # pilot_star_pos.  Prevents displaying a stale preload position as the
        # "current" position for the home distance calculation.
        self._star_pos_live: bool = False

    # ── Home location ──────────────────────────────────────────────────────────

    def _load_home_location(self) -> None:
        """Load persisted home location from plugin storage."""
        data = self.storage.read_json("data.json")
        self._home_name:     str        = data.get("name", "")
        self._home_system:   str        = data.get("system", "")
        self._home_star_pos: list | None = data.get("star_pos")  # [x, y, z] or None

    def get_home_location(self) -> dict | None:
        """Return the stored home location dict or None if not set."""
        if not self._home_name:
            return None
        return {
            "name":     self._home_name,
            "system":   self._home_system,
            "star_pos": self._home_star_pos,
        }

    def set_home_location(self, name: str, system: str, star_pos: list | None) -> None:
        """Persist and activate a new home location."""
        self._home_name     = name
        self._home_system   = system
        self._home_star_pos = star_pos
        self.storage.write_json({
            "name":     name,
            "system":   system,
            "star_pos": star_pos,
        }, "data.json")
        gq = self.core.gui_queue if self.core else None
        if gq:
            try: gq.put_nowait(("cmdr_update", None))
            except Exception: pass

    def clear_home_location(self) -> None:
        """Clear the home location."""
        self._home_name     = ""
        self._home_system   = ""
        self._home_star_pos = None
        self.storage.write_json({}, "data.json")

    def home_distance_ly(self, current_star_pos: list | None) -> float | None:
        """
        Return distance in ly from current position to home, or None if
        either position is unknown or the current position has not yet been
        confirmed by a live (post-preload) Location or FSDJump event.

        Returning None when position is stale prevents the block/bridge from
        showing a wildly wrong distance calculated from the last historical
        journal position rather than the player's actual current location.
        """
        import math
        if not self._star_pos_live:
            return None
        if not self._home_star_pos or not current_star_pos:
            return None
        dx = current_star_pos[0] - self._home_star_pos[0]
        dy = current_star_pos[1] - self._home_star_pos[1]
        dz = current_star_pos[2] - self._home_star_pos[2]
        return math.sqrt(dx*dx + dy*dy + dz*dz)

    def _read_status_json(self, core) -> None:
        """Read FuelMain from Status.json for immediate display on startup."""
        import json
        from pathlib import Path
        try:
            path = Path(core.journal_dir) / "Status.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                fuel = data.get("Fuel", {})
                main = fuel.get("FuelMain")
                if main is not None:
                    core.state.fuel_current = float(main)
        except Exception:
            pass

    def on_event(self, event: dict, state) -> None:
        core    = self.core
        gq      = core.gui_queue
        ev      = event.get("event")
        logtime = event.get("_logtime")

        match ev:
            case "Commander":
                if not state.pilot_name:
                    state.pilot_name = event.get("Name")
                fid = event.get("FID", "")
                if fid and not state.pilot_fid:
                    state.pilot_fid = fid
                    from core.state import set_active_fid
                    set_active_fid(fid)

            case "Rank":
                state.pilot_rank = RANK_NAMES[event["Combat"]]

            case "Progress":
                state.pilot_rank_progress = event["Combat"]

            case "Reputation":
                # Major faction standing 0-100 floats from Journal.
                # Stored as-is; display layer formats as percentages.
                rep = {}
                for faction in ("Federation", "Empire", "Alliance", "Independent"):
                    val = event.get(faction)
                    if val is not None:
                        rep[faction] = float(val)
                if rep:
                    if not state.pilot_reputation:
                        state.pilot_reputation = {}
                    state.pilot_reputation.update(rep)
                    if gq: gq.put(("cmdr_update", None))

            case "LoadGame":
                state.crew_active    = False
                state.in_game        = True
                state.in_supercruise = False
                state.offline_since_mono = None
                state.last_offline_alert = None
                state.pilot_ship = event.get("Ship_Localised") or event.get("Ship")
                fid = event.get("FID", "")
                if fid and not state.pilot_fid:
                    state.pilot_fid = fid
                    from core.state import set_active_fid
                    set_active_fid(fid)
                # Reset timing anchors on every game launch — prevents a stale
                # anchor from a previous session (e.g. crash, no Shutdown event)
                # producing a wildly wrong burn rate estimate. The rate itself is
                # kept as a warm-start estimate (same ship, same consumption)
                # and will be refined after two ReservoirReplenished events.
                core.active_session.fuel_check_time  = 0
                core.active_session.fuel_check_level = 0
                # Session boundary: new session if gap since last Shutdown
                # exceeds SESSION_GAP_MINUTES (default 15).
                from core.state import SESSION_GAP_MINUTES
                from datetime import timedelta
                shutdown_ts = getattr(state, "last_shutdown_time", None)
                if shutdown_ts and logtime:
                    gap = (logtime - shutdown_ts).total_seconds() / 60
                    if gap >= SESSION_GAP_MINUTES:
                        # Gap exceeds threshold — notify all session providers
                        for provider in getattr(core, "session_providers", []):
                            try:
                                provider.on_session_reset()
                            except Exception:
                                pass
                        # Emit to session_stats plugin directly if registered
                        try:
                            core.plugin_call("session_stats", "on_new_session", gap)
                        except Exception:
                            pass
                state.last_shutdown_time = None
                if event.get("ShipName"):  state.ship_name  = event["ShipName"]
                state.vessel_mode  = "ship"
                state.srv_type     = ""
                state.srv_hull     = 100
                state.suit_name    = ""
                state.suit_loadout = ""
                state.suit_shields = True
                if event.get("ShipIdent"): state.ship_ident = event["ShipIdent"]
                # LoadGame carries FuelLevel (current) and FuelCapacity (tank max).
                # Set both immediately so the fuel display is correct on login
                # without waiting for the first ReservoirReplenished or Loadout.
                # FuelCapacity in LoadGame is a plain float (not the {Main,Reserve}
                # dict from the Loadout event), so handle both forms.
                lg_fuel = event.get("FuelLevel")
                if lg_fuel is not None:
                    state.fuel_current = float(lg_fuel)
                lg_cap = event.get("FuelCapacity")
                if lg_cap is not None:
                    cap_main = (lg_cap["Main"] if isinstance(lg_cap, dict)
                                else float(lg_cap))
                    if cap_main >= 2:
                        state.fuel_tank_size = cap_main
                if "GameMode" in event:
                    state.pilot_mode = (
                        "Private Group" if event["GameMode"] == "Group"
                        else event["GameMode"]
                    )
                if gq: gq.put(("vessel_update", None))
                cmdrinfo = (
                    f"{state.pilot_ship} / {state.pilot_mode} / "
                    f"{state.pilot_rank} +{state.pilot_rank_progress}%"
                )
                core.emitter.emit(
                    msg_term=f"CMDR {state.pilot_name} ({cmdrinfo})",
                    msg_discord=f"**CMDR {state.pilot_name}** ({cmdrinfo})",
                    emoji="👤", sigil="-  INFO",
                    timestamp=event.get("_logtime"),
                    loglevel=2,
                )

            case "ReservoirReplenished":
                # Commander owns fuel state: level, tank size, and burn rate.
                fuel_main = event.get("FuelMain")
                state.fuel_current = fuel_main
                # Burn rate: rolling estimate from consecutive events.
                # No session_start_time guard — just needs two events.
                ses = core.active_session
                if (
                    fuel_main is not None
                    and ses.fuel_check_time
                    and logtime > ses.fuel_check_time
                ):
                    fuel_time = (logtime - ses.fuel_check_time).total_seconds()
                    if fuel_time > 0:
                        consumed = ses.fuel_check_level - fuel_main
                        fuel_hour = 3600 / fuel_time * consumed
                        if fuel_hour > 0:
                            state.fuel_burn_rate = fuel_hour
                if fuel_main is not None:
                    ses.fuel_check_time  = logtime
                    ses.fuel_check_level = fuel_main
                if gq: gq.put(("cmdr_update", None))

            case "Loadout":
                state.fuel_tank_size = (
                    event["FuelCapacity"]["Main"]
                    if event["FuelCapacity"]["Main"] >= 2 else 64
                )
                state.ship_name  = event.get("ShipName") or None
                state.ship_ident = event.get("ShipIdent") or None
                hh = event.get("HullHealth")
                if hh is not None:
                    state.ship_hull = round(hh * 100)
                if gq: gq.put(("vessel_update", None))

            case "ShieldState":
                shields_up = bool(event.get("ShieldsUp"))
                if state.vessel_mode == "on_foot":
                    state.suit_shields = shields_up
                else:
                    state.ship_shields            = shields_up
                    state.ship_shields_recharging = not shields_up
                if gq: gq.put(("vessel_update", None))

            case "HullDamage" if event.get("PlayerPilot") and not event.get("Fighter"):
                if state.vessel_mode == "srv":
                    state.srv_hull = round(event["Health"] * 100)
                else:
                    state.ship_hull = round(event["Health"] * 100)
                if gq: gq.put(("vessel_update", None))

            case "RepairAll" | "RepairPartial":
                state.ship_hull = 100
                if gq: gq.put(("vessel_update", None))

            case "LaunchSRV":
                state.vessel_mode = "srv"
                state.srv_type    = event.get("SRVType_Localised") or event.get("SRVType", "SRV")
                state.srv_hull    = 100
                if gq: gq.put(("vessel_update", None))

            case "DockSRV":
                state.vessel_mode = "ship"
                state.srv_type    = ""
                state.srv_hull    = 100
                if gq: gq.put(("vessel_update", None))

            case "Disembark":
                if not event.get("Taxi"):
                    state.vessel_mode  = "on_foot"
                    state.suit_shields = True
                    if gq: gq.put(("vessel_update", None))

            case "Embark":
                if event.get("SRV"):
                    state.vessel_mode = "srv"
                elif not event.get("Taxi"):
                    state.vessel_mode  = "ship"
                    state.suit_name    = ""
                    state.suit_loadout = ""
                if gq: gq.put(("vessel_update", None))

            case "SuitLoadout":
                state.suit_name    = event.get("SuitName_Localised") or event.get("SuitName", "")
                state.suit_loadout = event.get("LoadoutName", "")
                if gq: gq.put(("vessel_update", None))

            case "VehicleSwitch":
                to = event.get("To", "")
                if to == "Fighter":      state.cmdr_in_slf = True
                elif to == "Mothership": state.cmdr_in_slf = False
                if gq:
                    gq.put(("vessel_update", None))
                    gq.put(("slf_update",    None))

            case "Music" if event.get("MusicTrack") == "MainMenu":
                state.in_game = False
                import time
                if state.offline_since_mono is None:
                    state.offline_since_mono = time.monotonic()
                core.emitter.emit(
                    msg_term="Exited to main menu",
                    emoji="🚪", sigil="-  INFO",
                    timestamp=event.get("_logtime"), loglevel=2,
                )


            case "EngineerProgress":
                # Full engineer list fires at every login — authoritative source
                engineers = event.get("Engineers", [])
                if engineers:
                    parsed = []
                    for e in engineers:
                        name  = e.get("Engineer", "")
                        rank  = e.get("Rank")           # int or None
                        prog  = e.get("Progress", "")   # "Unlocked"/"Invited"/"Known"/etc.
                        rprog = e.get("RankProgress")   # 0-100 or None
                        if not name:
                            continue
                        parsed.append({
                            "name":           name,
                            "rank":           rank,
                            "progress":       rprog,
                            "progress_stage": prog,
                            "unlocked":       rank is not None,
                        })
                    if parsed:
                        state.pilot_engineer_ranks = parsed
                if gq: gq.put(("cmdr_update", None))

            case "NavRoute":
                # Full route plotted — read NavRoute.json for waypoints
                route = _read_nav_route_json(self.core.journal_dir)
                if route is not None:
                    state.nav_route = route
                elif event.get("Route"):
                    state.nav_route = event["Route"]
                if gq: gq.put(("vessel_update", None))

            case "Shutdown":
                state.in_game = False
                state.last_shutdown_time = logtime
                import time
                if state.offline_since_mono is None:
                    state.offline_since_mono = time.monotonic()
                core.emitter.emit(
                    msg_term="Quit to desktop",
                    emoji="🛑", sigil="-  INFO",
                    timestamp=event.get("_logtime"), loglevel=2,
                )

            case "ShipyardSwap":
                state.pilot_ship = (
                    event.get("ShipType_Localised") or event["ShipType"].title()
                )
                # Clear fuel burn rate — old ship's consumption is irrelevant
                state.fuel_burn_rate = None
                core.active_session.fuel_check_time  = 0
                core.active_session.fuel_check_level = 0
                core.emitter.emit(
                    msg_term=f"Swapped ship to {state.pilot_ship}",
                    emoji="🚢", sigil="-  SHIP",
                    timestamp=event.get("_logtime"), loglevel=2,
                )

            case "Powerplay":
                if event.get("Power"):             state.pp_power        = event["Power"]
                if event.get("Rank") is not None:  state.pp_rank         = event["Rank"]
                if event.get("Merits") is not None: state.pp_merits_total = event["Merits"]
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayJoin":
                state.pp_power = event.get("Power"); state.pp_rank = 1
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayLeave":
                state.pp_power = state.pp_rank = state.pp_merits_total = None
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayDefect":
                state.pp_power = event.get("ToPower"); state.pp_rank = 1
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayRank":
                state.pp_rank = event.get("Rank")
                if gq: gq.put(("cmdr_update", None))

            case "PowerplayMerits":
                if event.get("TotalMerits") is not None:
                    state.pp_merits_total = event["TotalMerits"]
                    if gq: gq.put(("cmdr_update", None))
                if event.get("Power") and not state.pp_power:
                    state.pp_power = event["Power"]

            case "Location":
                if event.get("StarSystem"): state.pilot_system = event["StarSystem"]
                if event.get("StarPos"):
                    state.pilot_star_pos = list(event["StarPos"])
                    # Location always reflects the player's actual current position
                    # (it fires at login/zone transition, not during historical replay).
                    self._star_pos_live = True
                if event.get("Body"):
                    state.pilot_body = event["Body"] if event.get("Docked") is False else None
                if event.get("Docked") and event.get("StationName"):
                    state.pilot_body = event["StationName"]
                elif event.get("Docked") and not event.get("StationName"):
                    state.pilot_body = None
                # Harvest local faction standings
                factions = event.get("Factions", [])
                if factions:
                    minor_rep = {}
                    for f in factions:
                        name = f.get("Name") or f.get("FactionName")
                        val  = f.get("MyReputation")
                        if name and val is not None:
                            minor_rep[name] = float(val)
                    if minor_rep:
                        state.pilot_minor_reputation = minor_rep
                if gq: gq.put(("cmdr_update", None))

            case "Docked":
                if event.get("StationName"): state.pilot_body   = event["StationName"]
                if event.get("StarSystem"):  state.pilot_system = event["StarSystem"]
                if gq: gq.put(("cmdr_update", None))

            case "Undocked":
                state.pilot_body = None
                if gq: gq.put(("cmdr_update", None))

            case "FSDJump":
                state.pilot_system   = event.get("StarSystem", state.pilot_system)
                state.pilot_body     = None
                if event.get("StarPos"):
                    state.pilot_star_pos = list(event["StarPos"])
                    if not state.in_preload:
                        self._star_pos_live = True
                # Update fuel display — FuelLevel is accurate post-jump
                fuel_level = event.get("FuelLevel")
                if fuel_level is not None:
                    state.fuel_current = float(fuel_level)
                if gq: gq.put(("vessel_update", None))
                # Harvest local faction standings for the Rep tab
                factions = event.get("Factions", [])
                if factions:
                    minor_rep = {}
                    for f in factions:
                        name = f.get("Name") or f.get("FactionName")
                        val  = f.get("MyReputation")
                        if name and val is not None:
                            minor_rep[name] = float(val)
                    if minor_rep:
                        state.pilot_minor_reputation = minor_rep
                if gq: gq.put(("cmdr_update", None))
                core.emitter.emit(
                    msg_term=f"FSD jump to {event['StarSystem']}",
                    emoji="🌌", sigil=">  JUMP",
                    timestamp=event.get("_logtime"), loglevel=2,
                )
                state.sessionend()

            case "SupercruiseEntry":
                state.pilot_system   = event.get("StarSystem", state.pilot_system)
                state.pilot_body     = None
                state.in_supercruise = True
                if gq: gq.put(("cmdr_update", None))
                core.emitter.emit(
                    msg_term=f"Supercruise entry in {event['StarSystem']}",
                    emoji="🚀", sigil=">  JUMP",
                    timestamp=event.get("_logtime"), loglevel=2,
                )
                state.sessionend()

            case "SupercruiseExit":
                import time as _time
                state.in_supercruise    = False
                state.last_sc_exit_mono = _time.monotonic()
                state.pilot_body        = event.get("Body")
                if gq: gq.put(("cmdr_update", None))

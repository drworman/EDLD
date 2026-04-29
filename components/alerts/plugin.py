"""
components/alerts/plugin.py — Combat and hazard alert tracking.

Maintains a deque of the last 5 alert events with monotonic timestamps.
Feeds both the Alerts dashboard block and the existing emit() pipeline
(terminal + Discord alerts are handled here for these event types).

GUI block: col=0, row=9, width=24, height=3 (default — full width).
"""

import time
from collections import deque
from core.plugin_loader import BasePlugin
from core.emit import Terminal
from core.state import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD


class AlertsPlugin(BasePlugin):
    PLUGIN_NAME    = "alerts"
    PLUGIN_DESCRIPTION = "Combat and ship alerts — shields, hull, fuel, fighter, and inactivity warnings."
    PLUGIN_DISPLAY = "Alerts"
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        "ShieldState",
        "HullDamage",
        "Loadout",
        "FighterDestroyed",
        "DockFighter",          # reset SLF hull to 100 on bay return
        "ReservoirReplenished", # fuel burn rate + fuel_current
        "RefuelAll",            # update fuel_current on manual refuel
        "RefuelPartial",        # update fuel_current on partial refuel
        "EjectCargo",
        "Died",
        "RepairAll",            # hull to 100 on station repair
        "RepairPartial",        # hull to 100 on partial repair
        "Repair",               # individual hull/component repair at station
        "ShipyardSwap",         # ship swap — clear stale alerts
        "ReceiveText",          # cargo scans, pirate messages, police attacks
        "ShipTargeted",         # outbound scans
        # Auto-clear stale alerts whenever context resets
        "LoadGame",
        "Docked",
        "FSDJump",              # also reads FuelLevel for fuel_current
        "SupercruiseEntry",
        # Hull/shield reset after rebuy
        "Resurrect",
    ]

    DEFAULT_COL    = 0
    DEFAULT_ROW    = 10
    DEFAULT_WIDTH  = 24
    DEFAULT_HEIGHT = 3

    # Fade timing (seconds)
    FADE_START  = 60
    FADE_END    = 90
    DIM_OPACITY = 0.4

    def on_load(self, core) -> None:
        super().on_load(core)
        # alert_queue: deque of dicts {emoji, text, mono_time}
        self.alert_queue: deque = deque(maxlen=5)
        core.register_block(self, priority=90)
        core.register_alert(self)


    def _push(self, emoji: str, text: str) -> None:
        # Never populate the queue during journal replay — those events are
        # historical and the player's current situation is already different.
        if self.core.state.in_preload:
            return
        self.alert_queue.appendleft({
            "emoji":     emoji,
            "text":      text,
            "mono_time": time.monotonic(),
        })
        gq = self.core.gui_queue
        if gq: gq.put(("alerts_update", None))

    def on_event(self, event: dict, state) -> None:
        core     = self.core
        notify   = core.notify_levels
        cfg      = core.cfg
        settings = core.app_settings
        logtime  = event.get("_logtime")
        ev       = event.get("event")

        match ev:

            case "ShieldState":
                if event["ShieldsUp"]:
                    col     = Terminal.GOOD
                    shields = "back up"
                    state.ship_shields            = True
                    state.ship_shields_recharging = False
                    self._push("🛡️", "Ship shields back up")
                else:
                    col     = Terminal.BAD
                    shields = "down!"
                    state.ship_shields            = False
                    state.ship_shields_recharging = True
                    self._push("🛡️", "Ship shields down!")
                gq = core.gui_queue
                if gq: gq.put(("vessel_update", None))
                core.emitter.emit(
                    msg_term=f"{col}Ship shields {shields}{Terminal.END}",
                    msg_discord=f"**Ship shields {shields}**",
                    emoji="🛡️", sigil="^  SHLD",
                    timestamp=logtime, loglevel=notify["ShieldEvent"],
                )

            case "HullDamage" if event.get("PlayerPilot") and not event.get("Fighter"):
                hullhealth = round(event["Health"] * 100)
                state.ship_hull = hullhealth
                gq = core.gui_queue
                if gq: gq.put(("vessel_update", None))
                self._push("⚠️", f"Ship hull: {hullhealth}%")
                core.emitter.emit(
                    msg_term=(
                        f"{Terminal.BAD}Ship hull damaged!{Terminal.END} "
                        f"(Integrity: {hullhealth}%)"
                    ),
                    msg_discord=f"**Ship hull damaged!** (Integrity: {hullhealth}%)",
                    emoji="⚠️", sigil="^  HULL",
                    timestamp=logtime, loglevel=notify["HullEvent"],
                )

            case "HullDamage" if event.get("Fighter") and not event.get("PlayerPilot"):
                # Only push when health actually changes — mirrors the dedup guard in
                # crew_slf/plugin.py which compares against state.fighter_integrity.
                hullhealth = round(event["Health"] * 100)
                if state.fighter_integrity != event["Health"]:
                    self._push("🛩️", f"Fighter hull: {hullhealth}%")
            case "RefuelAll" | "RefuelPartial":
                # Player manually refuelled — update fuel_current immediately.
                # RefuelAll/Partial do not carry absolute FuelLevel, only Amount
                # (tons added). Add to current known level and cap at tank size.
                amount = event.get("Amount", 0.0)
                if amount and state.fuel_current is not None:
                    state.fuel_current = min(
                        state.fuel_current + amount,
                        state.fuel_tank_size,
                    )
                elif state.fuel_current is None:
                    # No prior reading — cap logic unavailable, set to tank size
                    # as a safe overestimate for fuel duration calculations
                    state.fuel_current = float(state.fuel_tank_size)
                gq = core.gui_queue
                if gq: gq.put(("vessel_update", None))

            case "FSDJump":
                # FuelLevel in FSDJump is always the accurate post-jump value.
                fuel_level = event.get("FuelLevel")
                if fuel_level is not None:
                    state.fuel_current = float(fuel_level)
                    gq = core.gui_queue
                    if gq: gq.put(("vessel_update", None))

            case "RepairAll" | "RepairPartial":
                # Ship has been repaired at a station — hull is back to 100%.
                # Neither event carries an absolute hull value, but station
                # repairs are always full regardless of RepairAll vs Partial.
                state.ship_hull = 100
                gq = core.gui_queue
                if gq: gq.put(("vessel_update", None))

            case "DockFighter":
                # Fighter returned to the bay — it is automatically repaired
                # to full integrity on dock. Reset the display immediately
                # so we do not show a damaged fighter that is actually repaired.
                state.slf_hull = 100
                gq = core.gui_queue
                if gq: gq.put(("vessel_update", None))


            case "ReceiveText" if event.get("Channel") == "npc":
                from core.state import PIRATE_NOATTACK_MSGS, LABEL_UNKNOWN
                msg = event.get("Message", "")
                if "$Pirate_OnStartScanCargo" in msg:
                    piratename = event.get("From_Localised", LABEL_UNKNOWN)
                    ses = core.active_session
                    if piratename not in ses.recent_inbound_scans:
                        ses.inbound_scan_count += 1
                        count_str  = f" (x{ses.inbound_scan_count})" if settings.get("ExtendedStats") else ""
                        pirate_str = f" [{piratename}]" if settings.get("PirateNames") else ""
                        if len(ses.recent_inbound_scans) == 5:
                            ses.recent_inbound_scans.pop(0)
                        ses.recent_inbound_scans.append(piratename)
                        core.emitter.emit(
                            msg_term=f"Cargo scan{count_str}{pirate_str}",
                            msg_discord=f"**Cargo scan{count_str}**{pirate_str}",
                            emoji="📦", sigil="-  SCAN",
                            timestamp=logtime, loglevel=notify["InboundScan"],
                        )
                elif any(x in msg for x in PIRATE_NOATTACK_MSGS):
                    ses = core.active_session
                    ses.low_cargo_count += 1
                    count_str = f" (x{ses.low_cargo_count})" if settings.get("ExtendedStats") else ""
                    core.emitter.emit(
                        msg_term=(
                            f"{Terminal.WARN}"
                            f'Pirate didn"t engage due to insufficient cargo value'
                            f"{count_str}{Terminal.END}"
                        ),
                        msg_discord=(
                            f'**Pirate didn"t engage due to insufficient cargo value**'
                            f"{count_str}"
                        ),
                        emoji="📦", sigil="-  SCAN",
                        timestamp=logtime, loglevel=notify["LowCargoValue"],
                        event="LowCargoValue",
                    )
                elif "Police_Attack" in msg:
                    core.emitter.emit(
                        msg_term=f"{Terminal.BAD}Under attack by security services!{Terminal.END}",
                        msg_discord="**Under attack by security services!**",
                        emoji="🚨", sigil="!! ATCK",
                        timestamp=logtime, loglevel=notify["PoliceAttack"],
                    )

            case "ShipTargeted" if "Ship" in event:
                from core.state import LABEL_UNKNOWN
                from core.state import normalise_ship_name as _nsn
                ship = _nsn(event.get("Ship_Localised") or event.get("Ship"))
                rank = "" if "PilotRank" not in event else f" ({event['PilotRank']})"
                ses = core.active_session
                if (
                    ship != ses.last_security_ship
                    and "PilotName" in event
                    and "$ShipName_Police" in event["PilotName"]
                ):
                    ses.last_security_ship = ship
                    core.emitter.emit(
                        msg_term=f"{Terminal.WARN}Scanned security{Terminal.END} ({ship})",
                        msg_discord=f"**Scanned security** ({ship})",
                        emoji="🔍", sigil="-  SCAN",
                        timestamp=logtime, loglevel=notify["PoliceScan"],
                    )
                else:
                    piratename = event.get("PilotName_Localised", LABEL_UNKNOWN)
                    check      = piratename if settings.get("MinScanLevel") != 0 else ship
                    scanstage  = event.get("ScanStage", 0)
                    if (
                        scanstage >= settings.get("MinScanLevel", 1)
                        and check not in ses.recent_outbound_scans
                    ):
                        if len(ses.recent_outbound_scans) == 10:
                            ses.recent_outbound_scans.pop(0)
                        ses.recent_outbound_scans.append(check)
                        pirate_str = (
                            f" [{piratename}]"
                            if settings.get("PirateNames") and piratename != LABEL_UNKNOWN
                            else ""
                        )
                        core.emitter.emit(
                            msg_term=f"{Terminal.WHITE}Scan{Terminal.END}: {ship}{rank}{pirate_str}",
                            msg_discord=f"**{ship}**{rank}{pirate_str}",
                            emoji="🔍", sigil="-  SCAN",
                            timestamp=logtime, loglevel=notify["InboundScan"],
                        )

            case "ShipyardSwap":
                # Commander plugin handles fuel burn rate reset on ship swap.
                pass

            case "Loadout":
                # Fires on dock, undock, ship swap, and every SLF dock-back.
                # HullHealth is always accurate — server-confirmed on each event.
                hh = event.get("HullHealth")
                if hh is not None:
                    state.ship_hull = round(hh * 100)
                    gq = core.gui_queue
                    if gq: gq.put(("vessel_update", None))


            case "FighterDestroyed" if state.prev_event != "StartJump":
                self._push("💀", "Fighter destroyed!")

            case "ReservoirReplenished":
                # Commander plugin owns burn rate calculation and fuel_current.
                # Alerts reads state.fuel_burn_rate for the duration string.
                fuel_pct = round((event["FuelMain"] / state.fuel_tank_size) * 100)
                state.fuel_current = event["FuelMain"]
                burn = getattr(state, "fuel_burn_rate", None)
                if burn and burn > 0:
                    secs_r = (event["FuelMain"] / burn) * 3600
                    h_r = int(secs_r // 3600); m_r = int((secs_r % 3600) // 60)
                    fuel_time_remain = f"  (~{h_r}h {m_r}m)" if h_r > 0 else f"  (~{m_r}m)"
                else:
                    fuel_time_remain = ""

                col = ""; level = ":"; fuel_loglevel = 0
                if event["FuelMain"] < state.fuel_tank_size * FUEL_CRIT_THRESHOLD:
                    col = Terminal.BAD;  fuel_loglevel = notify["FuelCritical"]; level = " critical!"
                    self._push("⛽", f"Fuel critical: {fuel_pct}%")
                elif event["FuelMain"] < state.fuel_tank_size * FUEL_WARN_THRESHOLD:
                    col = Terminal.WARN; fuel_loglevel = notify["FuelWarning"];  level = " low:"
                    self._push("⛽", f"Fuel low: {fuel_pct}%")
                elif state.session_start_time:
                    fuel_loglevel = notify["FuelStatus"]

                core.emitter.emit(
                    msg_term=f"{col}Fuel: {fuel_pct}% remaining{Terminal.END}{fuel_time_remain}",
                    msg_discord=f"**Fuel{level} {fuel_pct}% remaining**{fuel_time_remain}",
                    emoji="⛽", sigil="+  FUEL",
                    timestamp=logtime, loglevel=fuel_loglevel,
                )

            case "EjectCargo" if not event.get("Abandoned") and event.get("Count") == 1:
                name = event.get("Type_Localised") or event["Type"].title()
                self._push("📦", f"Cargo stolen! ({name})")
                core.emitter.emit(
                    msg_term=f"{Terminal.BAD}Cargo stolen!{Terminal.END} ({name})",
                    msg_discord=f"**Cargo stolen!** ({name})",
                    emoji="📦", sigil="^  SHLD",
                    timestamp=logtime, loglevel=notify["CargoLost"],
                    event="CargoLost",
                )

            case "Died":
                self._push("💀", "Ship destroyed!")
                core.emitter.emit(
                    msg_term=f"{Terminal.BAD}Ship destroyed!{Terminal.END}",
                    msg_discord="**Ship destroyed!**",
                    emoji="💀", sigil="!! DEAD",
                    timestamp=logtime, loglevel=notify["Died"],
                )

            case "LoadGame" | "Docked" | "FSDJump" | "SupercruiseEntry":
                # Any context change makes existing alerts irrelevant.
                # No in_preload guard: _push already blocks replay events, so
                # the queue is either empty during preload (nothing to clear)
                # or has live events that genuinely need clearing.
                if self.alert_queue:
                    self.alert_queue.clear()
                    if core.gui_queue:
                        core.gui_queue.put(("alerts_update", None))
                # Reset shields to up on LoadGame — new ship instance always spawns
                # with shields online. Do NOT reset hull here; Status.json poll
                # reads the real hull value within 500ms and will override it.
                if ev == "LoadGame":
                    state.ship_shields            = True
                    state.ship_shields_recharging = False
                    if core.gui_queue:
                        core.gui_queue.put(("vessel_update", None))

            case "Resurrect":
                # Player rebuyed after destruction — ship is restored to full
                state.ship_hull               = 100
                state.ship_shields            = True
                state.ship_shields_recharging = False
                if self.alert_queue:
                    self.alert_queue.clear()
                if core.gui_queue:
                    core.gui_queue.put(("vessel_update", None))
                    core.gui_queue.put(("alerts_update", None))

            case "RepairAll":
                # Full station repair — hull is definitively back to 100%
                state.ship_hull = 100
                if core.gui_queue:
                    core.gui_queue.put(("vessel_update", None))

            case "Repair":
                # Individual repair — hull reinforcement or structural repair
                # implies player is at a repair facility; reset to 100%.
                item = event.get("Item", "").lower()
                if "hull" in item or "repair" in item or item == "":
                    state.ship_hull = 100
                    if core.gui_queue:
                        core.gui_queue.put(("vessel_update", None))

    def get_alerts(self) -> list[dict]:
        """Return current alerts list for the GUI block renderer."""
        return list(self.alert_queue)

    def clear_alerts(self) -> None:
        """Clear all alerts (called by the GUI Clear button)."""
        self.alert_queue.clear()
        if self.core.gui_queue:
            self.core.gui_queue.put(("alerts_update", None))

    def opacity_for(self, alert: dict) -> float:
        """Return current display opacity for an alert based on its age."""
        age = time.monotonic() - alert["mono_time"]
        if age < self.FADE_START:
            return 1.0
        if age < self.FADE_END:
            frac = (age - self.FADE_START) / (self.FADE_END - self.FADE_START)
            return 1.0 - frac * (1.0 - self.DIM_OPACITY)
        return self.DIM_OPACITY

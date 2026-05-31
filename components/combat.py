"""components/combat.py — Combat session aggregator.

Maintains session-scoped counters: kills, bounties, bonds, deaths, fighter
losses, faction tallies, and ship tallies.

Emits kill, death, and fighter-loss notifications directly — the journal.py
legacy dispatch path is inactive when plugin_dispatch is in use.

Idle and rate alerts are fired from tick() using state.last_kill_mono — the
single authoritative kill timestamp written by journal.py on every live kill
and reset on every LoadGame. Cooldowns are plugin-local so they survive
session resets without drifting.
"""
from __future__ import annotations
import time
from core.state      import normalise_ship_name
from core.emit       import fmt_credits, fmt_duration, Terminal
from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin

try:
    from core.utils import clip_name
except ImportError:
    def clip_name(s, n): return s[:n] if len(s) > n else s

RECENT_KILL_WINDOW = 5


class CombatPlugin(BasePlugin, ActivityProviderMixin):

    PLUGIN_NAME        = "combat"
    PLUGIN_DISPLAY     = "Combat Activity"
    PLUGIN_VERSION     = "2.0.0"
    PLUGIN_DESCRIPTION = "Session combat: kills, bounties, bonds, deaths, idle and rate alerts."
    SUBSCRIBED_EVENTS  = ["Bounty", "FactionKillBond", "Died", "FighterDestroyed"]
    ACTIVITY_TAB_TITLE = "Combat"
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 5

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=20)
        core.register_session_provider(self)
        self._reset_counters()
        # Alert cooldown timestamps (plugin-local; survive session resets)
        self._last_inactive_alert_mono: float | None = None
        self._last_rate_alert_mono:     float | None = None

    def _reset_counters(self) -> None:
        self.kills:               int   = 0
        self.bounty_total:        int   = 0
        self.bond_total:          int   = 0
        self.deaths:              int   = 0
        self.rebuy_paid:          int   = 0
        self.fighter_losses:      int   = 0
        self.faction_tally:       dict  = {}
        self.ship_tally:          dict  = {}
        self.kill_interval_total: float = 0.0
        self.recent_kill_times:   list  = []
        self.last_kill_time             = None
        self.session_start_time         = None

    def on_session_reset(self) -> None:
        self._reset_counters()

    def on_event(self, event: dict, state) -> None:
        core     = self.core
        gq       = core.gui_queue
        notify   = core.notify_levels
        settings = core.app_settings
        ev       = event.get("event")
        logtime  = event.get("_logtime")
        max_trunc = settings.get("TruncateNames", 30)

        match ev:

            case "Bounty" | "FactionKillBond":
                self.kills += 1
                if self.session_start_time is None:
                    self.session_start_time = logtime

                if self.last_kill_time:
                    secs = (logtime - self.last_kill_time).total_seconds()
                    self.kill_interval_total += secs
                    if len(self.recent_kill_times) >= RECENT_KILL_WINDOW:
                        self.recent_kill_times.pop(0)
                    self.recent_kill_times.append(secs)
                self.last_kill_time = logtime

                if not state.in_preload:
                    self._last_inactive_alert_mono = None

                if ev == "Bounty":
                    value  = event.get("TotalReward") or event["Rewards"][0]["Reward"]
                    ship   = normalise_ship_name(
                        event.get("Target_Localised") or event.get("Target", "Unknown")
                    )
                    victim = event.get("VictimFaction_Localised") or event.get("VictimFaction", "")
                    self.bounty_total += value
                else:
                    value  = event["Reward"]
                    ship   = "Bond target"
                    victim = event.get("Faction", "")
                    self.bond_total += value

                self.faction_tally[victim] = self.faction_tally.get(victim, 0) + 1
                self.ship_tally[ship]      = self.ship_tally.get(ship, 0) + 1

                killtime_str = ""
                if self.recent_kill_times:
                    killtime_str = f" (+{fmt_duration(self.recent_kill_times[-1])})"

                kills_t = f" x{self.kills}" if settings.get("ExtendedStats") else ""
                kills_d = f"x{self.kills} " if settings.get("ExtendedStats") else ""
                bv_str  = f" [{fmt_credits(value)} cr]" if settings.get("BountyValue") else ""
                pirate_str = (
                    f" [{clip_name(event['PilotName_Localised'], max_trunc)}]"
                    if "PilotName_Localised" in event and settings.get("PirateNames")
                    else ""
                )
                bf_str = ""
                if settings.get("BountyFaction") and victim:
                    fc = f" x{self.faction_tally[victim]}" if settings.get("ExtendedStats") else ""
                    bf_str = f" [{clip_name(victim, max_trunc)}{fc}]"

                core.emitter.emit(
                    msg_term=(
                        f"{Terminal.WHITE}Kill{Terminal.END}{kills_t}: "
                        f"{ship}{killtime_str}{pirate_str}{bv_str}{bf_str}"
                    ),
                    msg_discord=(
                        f"{kills_d}**{ship}{killtime_str}**"
                        f"{pirate_str}{bv_str}{bf_str}"
                    ),
                    emoji="💥", sigil="*  KILL",
                    timestamp=logtime, loglevel=notify["RewardEvent"],
                )
                if gq: gq.put(("stats_update", None))

            case "Died":
                self.deaths    += 1
                rebuy = event.get("Cost", 0)
                self.rebuy_paid += rebuy
                core.emitter.emit(
                    msg_term=f"{Terminal.BAD}Ship destroyed!{Terminal.END}"
                             + (f" (Rebuy: {fmt_credits(rebuy)} cr)" if rebuy else ""),
                    msg_discord="**Ship destroyed!**"
                                + (f" (Rebuy: {fmt_credits(rebuy)} cr)" if rebuy else ""),
                    emoji="💀", sigil="!! DEAD",
                    timestamp=logtime, loglevel=notify["Died"],
                )
                if gq: gq.put(("stats_update", None))

            case "FighterDestroyed":
                self.fighter_losses += 1
                if gq: gq.put(("stats_update", None))

    def tick(self, state) -> None:
        """Called every second.

        Checks inactivity and kill-rate thresholds against state.last_kill_mono
        — the single authoritative kill timestamp written by journal.py.
        """
        if not state.in_game or state.in_preload:
            return
        if getattr(state, "in_supercruise", False):
            return

        now      = time.monotonic()
        core     = self.core
        settings = core.app_settings
        notify   = core.notify_levels

        last_kill = getattr(state, "last_kill_mono", 0.0)

        # ── Inactivity alert (WarnNoKills) ────────────────────────────────
        # Only check once the plugin has seen a session start and there has
        # been at least one kill (or LoadGame reset the timer to now).
        warn_no_kills = settings.get("WarnNoKills",   60)
        warn_cooldown = settings.get("WarnCooldown",  15)
        if (
            notify.get("InactiveAlert", 3) > 0
            and self.session_start_time is not None
            and warn_no_kills > 0
            and last_kill > 0.0
        ):
            cooldown_ok = (
                self._last_inactive_alert_mono is None
                or now - self._last_inactive_alert_mono >= warn_cooldown * 60
            )
            if cooldown_ok and now - last_kill >= warn_no_kills * 60:
                idle_dur = fmt_duration(int(now - last_kill))
                core.emitter.emit(
                    msg_term=f"No kills in {idle_dur} — session may be inactive",
                    msg_discord=f"⚠️ **No kills in {idle_dur}** — session may be inactive",
                    emoji="⚠️", sigil="!  WARN",
                    timestamp=state.event_time,
                    loglevel=notify.get("InactiveAlert", 3),
                )
                self._last_inactive_alert_mono = now

        # ── Kill rate alert (WarnKillRate) ────────────────────────────────
        warn_rate = settings.get("WarnKillRate", 20)
        if (
            notify.get("RateAlert", 3) > 0
            and warn_rate > 0
            and self.kills >= 3
            and len(self.recent_kill_times) >= 3
        ):
            recent_avg_secs = sum(self.recent_kill_times) / len(self.recent_kill_times)
            recent_rate = 3600 / recent_avg_secs if recent_avg_secs > 0 else 0
            rate_cooldown_ok = (
                self._last_rate_alert_mono is None
                or now - self._last_rate_alert_mono >= warn_cooldown * 60
            )
            if rate_cooldown_ok and recent_rate < warn_rate:
                core.emitter.emit(
                    msg_term=f"Kill rate low: {recent_rate:.1f}/hr (threshold: {warn_rate}/hr)",
                    msg_discord=f"📉 **Kill rate low: {recent_rate:.1f}/hr** (threshold: {warn_rate}/hr)",
                    emoji="📉", sigil="!  WARN",
                    timestamp=state.event_time,
                    loglevel=notify.get("RateAlert", 3),
                )
                self._last_rate_alert_mono = now

        # ── No-kill timeout (session flush) ──────────────────────────────
        limit_minutes = core.cfg.pcfg("QuitOnNoKillsMinutes", 0)
        if limit_minutes and last_kill > 0.0:
            elapsed = (now - last_kill) / 60
            if elapsed >= limit_minutes:
                try:
                    core.plugin_call(
                        "session_manager", "flush_session",
                        f"No kills for {elapsed:.0f} min (threshold {limit_minutes} min)"
                    )
                except Exception:
                    pass

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return self.kills > 0 or self.deaths > 0 or self.fighter_losses > 0

    def get_summary_rows(self) -> list[dict]:
        if not self.has_activity():
            return []
        dur = self._duration_seconds()
        rows: list[dict] = []
        kph = (self.kills / dur * 3600) if dur > 0 else 0
        rows.append({"label": "Kills",    "value": str(self.kills),
                     "rate": f"{kph:.1f} /hr"})
        if self.bounty_total:
            bph = self.bounty_total / dur * 3600 if dur > 0 else 0
            rows.append({"label": "Bounties", "value": fmt_credits(self.bounty_total),
                         "rate": f"{fmt_credits(bph)} /hr"})
        return rows

    def get_tab_rows(self) -> list[dict]:
        rows: list[dict] = []
        dur = self._duration_seconds()
        kph = (self.kills / dur * 3600) if dur > 0 else 0
        rows.append({"label": "Kills",        "value": str(self.kills),
                     "rate": f"{kph:.1f} /hr"})
        if self.bounty_total:
            bph = self.bounty_total / dur * 3600 if dur > 0 else 0
            rows.append({"label": "Bounties",      "value": fmt_credits(self.bounty_total),
                         "rate": f"{fmt_credits(bph)} /hr"})
        if self.bond_total:
            rows.append({"label": "Combat bonds",  "value": fmt_credits(self.bond_total)})
        if self.deaths:
            rows.append({"label": "Deaths",        "value": str(self.deaths)})
        if self.rebuy_paid:
            rows.append({"label": "Rebuy paid",    "value": fmt_credits(self.rebuy_paid)})
        if self.fighter_losses:
            rows.append({"label": "Fighter losses","value": str(self.fighter_losses)})
        return rows

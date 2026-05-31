"""
components/powerplay.py — PowerPlay session tracking.

Tracks merits earned across all PowerPlay activities with per-system
attribution. Merit count and rate at the session level; per-system
breakdown shows which systems drove the most merit income this session.

PowerplayMerits does not carry a system field. We attribute merits to
state.pilot_system at the moment the event fires, which is the system
the player was in when the merit was earned (kill, delivery, etc.).

Tab title: PowerPlay
"""

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.emit import Terminal, rate_per_hour


class ActivityPowerplayPlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME         = "powerplay"
    PLUGIN_DISPLAY      = "PowerPlay Activity"
    PLUGIN_VERSION      = "2.0.0"
    PLUGIN_DESCRIPTION  = "Tracks PowerPlay merits, rank progress, and per-system merit breakdown."
    ACTIVITY_TAB_TITLE  = "PowerPlay"

    SUBSCRIBED_EVENTS = [
        "Powerplay",
        "PowerplayMerits",
        "PowerplayRank",
        "PowerplayJoin",
        "PowerplayLeave",
        "PowerplayDefect",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.merits_earned:    int  = 0
        self.rank_start:       int | None = None
        self.rank_current:     int | None = None
        self.power:            str | None = None
        self.session_start_time           = None
        # Per-system merit attribution: system_name → merits
        self.system_merits:    dict[str, int] = {}

    def on_session_reset(self) -> None:
        self.merits_earned    = 0
        self.rank_start       = self.rank_current
        self.session_start_time = None
        self.system_merits    = {}

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")
        gq      = self.core.gui_queue

        match ev:

            case "Powerplay":
                self.power        = event.get("Power")
                self.rank_current = event.get("Rank")
                if self.rank_start is None:
                    self.rank_start = self.rank_current
                state.pp_power        = self.power
                state.pp_rank         = self.rank_current
                state.pp_merits_total = event.get("Merits")

            case "PowerplayMerits":
                gained = event.get("MeritsGained", 0)
                if gained > 0:
                    if self.session_start_time is None:
                        self.session_start_time = logtime
                    self.merits_earned += gained
                    total = event.get("TotalMerits")
                    if total is not None:
                        state.pp_merits_total = total
                    # Attribute to current system
                    system = getattr(state, "pilot_system", None) or "Unknown"
                    self.system_merits[system] = self.system_merits.get(system, 0) + gained
                    self.core.emitter.emit(
                        msg_term=(
                            f"Merits: +{gained:,}"
                            + (f" ({self.power})" if self.power else "")
                        ),
                        emoji="⭐", sigil="+  MERC",
                        timestamp=logtime,
                        loglevel=self.core.notify_levels.get("MeritEvent", 0),
                    )
                    if gq: gq.put(("stats_update", None))

            case "PowerplayRank":
                self.rank_current = event.get("Rank")
                state.pp_rank     = self.rank_current
                if gq: gq.put(("stats_update", None))

            case "PowerplayJoin":
                self.power        = event.get("Power")
                self.rank_current = 1
                self.rank_start   = 1
                state.pp_power    = self.power
                state.pp_rank     = 1

            case "PowerplayLeave" | "PowerplayDefect":
                self.power    = event.get("Power") if ev == "PowerplayDefect" else None
                state.pp_power = self.power
                state.pp_rank  = None

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return self.merits_earned > 0

    def get_summary_rows(self) -> list[dict]:
        dur  = self._duration_seconds()
        rows = []
        if self.merits_earned > 0:
            rate = (f"{rate_per_hour(dur / self.merits_earned, 1):,.0f} /hr"
                    if dur else "—")
            rows.append({
                "label": "Merits",
                "value": f"{self.merits_earned:,}",
                "rate":  rate,
            })
        return rows

    def get_tab_rows(self) -> list[dict]:
        rows = self.get_summary_rows()
        if self.power:
            rows.append({"label": "Power", "value": self.power, "rate": None})
        if self.rank_current is not None:
            rank_str = str(self.rank_current)
            if self.rank_start is not None and self.rank_current != self.rank_start:
                rank_str += f" (was {self.rank_start})"
            rows.append({"label": "Rank", "value": rank_str, "rate": None})
        # Per-system breakdown — top systems by merit count
        if self.system_merits:
            rows.append({"label": "─── By system ───", "value": "", "rate": None})
            for system, merits in sorted(
                self.system_merits.items(), key=lambda x: -x[1]
            )[:10]:   # cap at 10 rows
                rows.append({
                    "label": f"  {system}",
                    "value": f"{merits:,}",
                    "rate":  None,
                })
        return rows

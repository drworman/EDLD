"""
components/missions_session.py — Mission session tracking.

Tracks missions accepted, completed, failed, and credits earned.
Includes massacre stack analysis: per-source-faction kill requirements,
rewards (wing vs non-wing), stack height, delta-to-max, and warnings for
mixed stacks (multiple target factions, types, or systems).

Tab title: Missions
"""

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.emit import fmt_credits


def _strip_target_type(raw: str) -> str:
    """Return a clean target type label from a raw journal value."""
    s = raw or ""
    # Strip localisation wrappers e.g. $MissionUtil_FactionTag_Pirate;
    if s.startswith("$") and s.endswith(";"):
        inner = s[1:-1]
        if "_" in inner:
            s = inner.rsplit("_", 1)[-1]
    return s.strip()


class ActivityMissionsPlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME         = "missions_session"
    PLUGIN_DISPLAY      = "Missions Session"
    PLUGIN_VERSION      = "1.1.0"
    PLUGIN_DESCRIPTION  = "Tracks mission completions, credits, and massacre stack analysis."
    ACTIVITY_TAB_TITLE  = "Missions"

    SUBSCRIBED_EVENTS = [
        "MissionAccepted",
        "MissionCompleted",
        "MissionFailed",
        "MissionAbandoned",
        "Missions",            # bulk load on login — triggers stack recompute
        "MissionRedirected",   # massacre redirect = one more complete
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.accepted:       int  = 0
        self.completed:      int  = 0
        self.failed:         int  = 0
        self.abandoned:      int  = 0
        self.credits_earned: int  = 0
        self.type_tally:     dict = {}   # mission type → count
        self.session_start_time   = None

    def on_session_reset(self) -> None:
        self._reset_counters()

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")
        gq      = self.core.gui_queue

        match ev:

            case "MissionAccepted":
                if self.session_start_time is None:
                    self.session_start_time = logtime
                self.accepted += 1
                if gq: gq.put(("stats_update", None))

            case "MissionCompleted":
                if self.session_start_time is None:
                    self.session_start_time = logtime
                self.completed += 1
                reward = event.get("Reward", 0)
                self.credits_earned += reward
                mtype = (
                    event.get("LocalisedName") or
                    event.get("Name", "Unknown")
                ).strip()
                import re as _re
                mtype = _re.sub(r'_\w+$', '', mtype).strip().title()
                self.type_tally[mtype] = self.type_tally.get(mtype, 0) + 1
                if gq: gq.put(("stats_update", None))

            case "MissionRedirected":
                if gq: gq.put(("stats_update", None))

            case "Missions":
                if gq: gq.put(("stats_update", None))

            case "MissionFailed":
                self.failed += 1
                if gq: gq.put(("stats_update", None))

            case "MissionAbandoned":
                self.abandoned += 1
                if gq: gq.put(("stats_update", None))

    # ── Massacre stack analysis ───────────────────────────────────────────────

    def _build_massacre_analysis(self, state) -> dict | None:
        """
        Group active massacre missions by source faction and compute stack
        metrics. Returns None if there are no active massacre missions.

        Returns a dict:
          factions: {faction_name: {kill_count, reward, wing_reward}}
          stack_height: int            highest kill_count across all factions
          second_height: int           second-highest (for delta display)
          total_reward: int
          total_wing_reward: int
          mission_count: int
          warnings: list[str]          mixed-stack warnings
        """
        detail = getattr(state, "mission_detail_map", {})
        if not detail:
            return None

        factions:       dict[str, dict] = {}
        target_factions: set[str]       = set()
        target_types:    set[str]       = set()
        target_systems:  set[str]       = set()
        total_reward     = 0
        total_wing       = 0

        for mid, info in detail.items():
            src       = info.get("faction", "Unknown")
            kc        = int(info.get("kill_count", 0))
            reward    = int(info.get("reward", 0))
            is_wing   = bool(info.get("wing", False))
            tgt_f     = info.get("target_faction", "")
            tgt_s     = info.get("target_system", "")
            tgt_t     = _strip_target_type(info.get("target_type", ""))

            if src not in factions:
                factions[src] = {"kill_count": 0, "reward": 0, "wing_reward": 0}
            factions[src]["kill_count"] += kc
            factions[src]["reward"]     += reward
            if is_wing:
                factions[src]["wing_reward"] += reward

            total_reward += reward
            if is_wing:
                total_wing += reward

            if tgt_f: target_factions.add(tgt_f)
            if tgt_s: target_systems.add(tgt_s)
            if tgt_t: target_types.add(tgt_t)

        if not factions:
            return None

        heights = sorted(
            (v["kill_count"] for v in factions.values()), reverse=True
        )
        stack_height  = heights[0] if heights else 0
        second_height = heights[1] if len(heights) > 1 else stack_height

        warnings = []
        if len(target_factions) > 1:
            warnings.append(f"Multiple target factions: {', '.join(sorted(target_factions))}")
        if len(target_types) > 1:
            warnings.append(f"Multiple target types: {', '.join(sorted(target_types))}")
        if len(target_systems) > 1:
            warnings.append(f"Multiple target systems: {', '.join(sorted(target_systems))}")

        return {
            "factions":          factions,
            "stack_height":      stack_height,
            "second_height":     second_height,
            "total_reward":      total_reward,
            "total_wing_reward": total_wing,
            "mission_count":     len(getattr(state, "active_missions", [])),
            "warnings":          warnings,
        }

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return self.completed > 0 or self.failed > 0 or self.accepted > 0

    def get_summary_rows(self) -> list[dict]:
        rows = []
        if self.accepted > 0:
            rows.append({"label": "Accepted", "value": str(self.accepted), "rate": None})
        if self.completed > 0:
            cr_rate = (f"{fmt_credits(self.credits_earned)} credits"
                       if self.credits_earned > 0 else None)
            rows.append({"label": "Completed", "value": str(self.completed),
                         "rate": cr_rate})
        if self.failed > 0:
            rows.append({"label": "Failed", "value": str(self.failed), "rate": None})
        return rows

    def get_tab_rows(self) -> list[dict]:
        rows = []

        if self.accepted > 0:
            rows.append({"label": "Accepted",  "value": str(self.accepted),  "rate": None})
        if self.completed > 0:
            cr_rate = (f"{fmt_credits(self.credits_earned)} credits"
                       if self.credits_earned > 0 else None)
            rows.append({"label": "Completed", "value": str(self.completed),
                         "rate": cr_rate})
        if self.failed > 0:
            rows.append({"label": "Failed",    "value": str(self.failed),    "rate": None})
        if self.abandoned > 0:
            rows.append({"label": "Abandoned", "value": str(self.abandoned), "rate": None})

        if self.type_tally:
            rows.append({"label": "─── Mission types ───", "value": "", "rate": None})
            for mtype, count in sorted(self.type_tally.items(), key=lambda x: -x[1]):
                rows.append({"label": f"  {mtype}", "value": str(count), "rate": None})

        return rows

"""
components/missions.py — Massacre mission stack tracking.

Owns: active_missions, missions_complete, stack_value,
      mission_value_map, mission_target_faction_map, mission_detail_map.

Persistence
───────────
mission_detail_map is persisted to plugin storage on every change and
restored on load. This is the only source of kill_count, faction, target,
and reward data after a restart, since the Missions bulk event carries only
MissionID, Name, PassengerMission, and Expires.

On the Missions bulk event:
  - The reconciliation ALWAYS runs (no short-circuit guard) so that an empty
    Active list correctly clears any stale stored missions.
  - Any active mission already in mission_detail_map keeps its stored detail.
  - Any active mission NOT in detail_map gets an empty skeleton entry, then
    backfill scans backwards through journals to populate it.
  - Any stored detail for a MissionID no longer in Active is discarded.

Kill counting per mission is tracked via MissionRedirected (which carries
MissionID), so per-mission redirect status is also persisted.
"""

from core.plugin_loader import BasePlugin
from core.emit import Terminal, fmt_credits


class MissionsPlugin(BasePlugin):
    PLUGIN_NAME    = "missions"
    PLUGIN_DISPLAY = "Massacre Mission Stack"
    PLUGIN_DESCRIPTION = "Active massacre mission stack — progress, value, and completion tracking."
    PLUGIN_VERSION = "1.2.0"

    SUBSCRIBED_EVENTS = [
        "Missions",
        "MissionAccepted",
        "MissionRedirected",
        "MissionAbandoned",
        "MissionCompleted",
        "MissionFailed",
        "Bounty",
    ]

    DEFAULT_COL    = 0
    DEFAULT_ROW    = 6
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 4

    def on_load(self, core) -> None:
        super().on_load(core)
        self._restore()
        core.register_block(self, priority=30)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _restore(self) -> None:
        """Restore mission state from storage on load."""
        data  = self.storage.read_json() or {}
        state = self.core.state

        detail = data.get("mission_detail_map", {})
        # Keys are stored as strings (JSON); convert back to int
        state.mission_detail_map = {int(k): v for k, v in detail.items()}

        active = data.get("active_missions", [])
        state.active_missions = [int(m) for m in active]

        redirected = data.get("redirected_missions", [])
        self._redirected: set[int] = {int(m) for m in redirected}

        # Safety net: prune any redirected IDs that are not in the persisted
        # active_missions list.
        self._redirected &= set(state.active_missions)
        state.missions_complete = len(self._redirected)
        state.stack_value       = sum(
            v.get("reward", 0)
            for v in state.mission_detail_map.values()
        )
        state.mission_value_map = {
            mid: v.get("reward", 0)
            for mid, v in state.mission_detail_map.items()
        }
        state.mission_target_faction_map = {
            mid: v.get("target_faction", "")
            for mid, v in state.mission_detail_map.items()
        }

    def _persist(self) -> None:
        """Write mission state to storage."""
        state = self.core.state
        self.storage.write_json({
            "active_missions":    state.active_missions,
            "mission_detail_map": {
                str(k): v for k, v in state.mission_detail_map.items()
            },
            "redirected_missions": list(self._redirected),
        })

    # ── Kill counting ─────────────────────────────────────────────────────────

    def _session_kills_against(self, victim_faction: str) -> None:
        """Attribute a kill to all active missions targeting victim_faction.

        Increments a per-mission kill counter so the GUI can show live
        progress within a session.  Not persisted — resets on restart;
        MissionRedirected is the authoritative completion signal.
        """
        state = self.core.state
        for mid, info in state.mission_detail_map.items():
            if info.get("target_faction", "") == victim_faction:
                info["kills_this_session"] = info.get("kills_this_session", 0) + 1

    # ── Events ────────────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        core     = self.core
        gq       = core.gui_queue
        notify   = core.notify_levels
        settings = core.app_settings
        ev       = event.get("event")

        match ev:

            case "Missions" if "Active" in event:
                # Bulk reconciliation on login.  This branch ALWAYS runs —
                # no short-circuit guard — so that an empty Active list (zero
                # active missions) correctly clears any stale stored detail
                # that survived from a previous session whose MissionCompleted
                # events were processed during the prior preload.
                live_ids = {
                    int(m["MissionID"])
                    for m in event["Active"]
                    if "Mission_Massacre" in m.get("Name", "")
                    and (m.get("Expires", 0) == 0 or m.get("Expires", 0) > 0)
                }

                # Discard stored detail for missions no longer active
                for mid in list(state.mission_detail_map.keys()):
                    if mid not in live_ids:
                        state.mission_detail_map.pop(mid, None)
                        state.mission_value_map.pop(mid, None)
                        state.mission_target_faction_map.pop(mid, None)
                self._redirected &= live_ids

                # Ensure every live mission has a detail entry (skeleton if new)
                for m in event["Active"]:
                    if "Mission_Massacre" not in m.get("Name", ""):
                        continue
                    mid = int(m["MissionID"])
                    if mid not in state.mission_detail_map:
                        state.mission_detail_map[mid] = {
                            "faction":        m.get("Faction", ""),
                            "kill_count":     m.get("KillCount", 0),
                            "target_faction": m.get("TargetFaction", ""),
                            "target_system":  m.get("DestinationSystem", ""),
                            "target_type":    (m.get("TargetType_Localised")
                                               or m.get("TargetType", "")),
                            "wing":           m.get("Wing", False),
                            "reward":         m.get("Reward", 0),
                        }

                # Backfill skeleton entries that have kill_count == 0.
                # The Missions bulk event carries only MissionID/Name/Expires —
                # no kill counts, factions, or rewards.  Missions accepted in a
                # prior journal session are not replayed during preload, so their
                # MissionAccepted detail must be recovered by scanning backwards.
                needs_backfill = {
                    mid for mid, info in state.mission_detail_map.items()
                    if not info.get("kill_count")
                }
                if needs_backfill:
                    try:
                        import json as _j, pathlib as _pl
                        _jdir = getattr(core, "journal_dir", None)
                        if _jdir:
                            for _jp in reversed(sorted(_pl.Path(_jdir).glob("Journal*.log"))):
                                if not needs_backfill:
                                    break
                                try:
                                    _lines = _jp.read_text(encoding="utf-8").splitlines()
                                except OSError:
                                    continue
                                for _line in reversed(_lines):
                                    if not needs_backfill:
                                        break
                                    try:
                                        _ev = _j.loads(_line)
                                    except ValueError:
                                        continue
                                    if _ev.get("event") == "MissionAccepted":
                                        _mid = int(_ev.get("MissionID", 0))
                                        if _mid in needs_backfill:
                                            state.mission_detail_map[_mid] = {
                                                "faction":        _ev.get("Faction", ""),
                                                "kill_count":     _ev.get("KillCount", 0),
                                                "target_faction": _ev.get("TargetFaction", ""),
                                                "target_system":  _ev.get("DestinationSystem", ""),
                                                "target_type":    (_ev.get("TargetType_Localised")
                                                                   or _ev.get("TargetType", "")),
                                                "wing":           _ev.get("Wing", False),
                                                "reward":         _ev.get("Reward", 0),
                                            }
                                            needs_backfill.discard(_mid)
                    except Exception:
                        pass

                state.active_missions   = list(live_ids)
                state.missions_complete = len(self._redirected)
                state.stack_value       = sum(
                    v.get("reward", 0) for v in state.mission_detail_map.values()
                )
                state.mission_value_map = {
                    mid: v.get("reward", 0)
                    for mid, v in state.mission_detail_map.items()
                }
                state.mission_target_faction_map = {
                    mid: v.get("target_faction", "")
                    for mid, v in state.mission_detail_map.items()
                }
                state.missions = True
                self._persist()

                core.emitter.emit(
                    msg_term=(
                        f"Missions loaded (active massacres: {len(state.active_missions)}"
                        + (f", {len(self._redirected)} redirected)" if self._redirected else ")")
                    ),
                    emoji="📋", sigil="*  MISS",
                    timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                )
                if gq: gq.put(("mission_update", None))

            case "MissionAccepted" if "Mission_Massacre" in event.get("Name", ""):
                mid = int(event["MissionID"])
                # During preload, only skip if this mission is already fully tracked
                # (either restored from storage or enriched by backfill).  Missions
                # accepted after the Missions bulk snapshot, or skeletons that backfill
                # didn't reach, still need to be processed.
                if state.in_preload and mid in state.mission_detail_map:
                    return
                already_active = mid in state.active_missions
                if not already_active:
                    state.active_missions.append(mid)
                reward = event.get("Reward", 0)
                if reward and mid not in state.mission_value_map:
                    state.stack_value += reward
                    state.mission_value_map[mid] = reward
                target_f = event.get("TargetFaction", "")
                if target_f:
                    state.mission_target_faction_map[mid] = target_f
                state.mission_detail_map[mid] = {
                    "faction":        event.get("Faction", ""),
                    "kill_count":     event.get("KillCount", 0),
                    "target_faction": target_f,
                    "target_system":  event.get("DestinationSystem", ""),
                    "target_type":    (event.get("TargetType_Localised")
                                       or event.get("TargetType", "")),
                    "wing":           event.get("Wing", False),
                    "reward":         reward,
                }
                self._persist()
                if not state.in_preload:
                    total_now = len(state.active_missions)
                    core.emitter.emit(
                        msg_term=f"Accepted massacre mission (active: {total_now})",
                        emoji="📋", sigil="*  MISS",
                        timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                    )
                    full_stack = settings.get("FullStackSize", 20)
                    if total_now == full_stack and state.stack_value > 0:
                        _sl = f"Stack full ({total_now} missions) — {fmt_credits(state.stack_value)}"
                        core.emitter.emit(
                            msg_term=_sl, msg_discord=f"**{_sl}**",
                            emoji="🏆", sigil="*  MISS",
                            timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                        )
                if gq: gq.put(("mission_update", None))

            case "MissionRedirected" if "Mission_Massacre" in event.get("Name", ""):
                mid = int(event["MissionID"])
                if mid in state.mission_detail_map:
                    self._redirected.add(mid)
                    state.missions_complete = len(self._redirected)
                    self._persist()
                    if not state.in_preload:
                        total = len(state.active_missions)
                        done  = state.missions_complete
                        if done < total:
                            log      = notify["MissionUpdate"]
                            msg_term = (f"Mission {done} of {total} complete "
                                        f"({total - done} remaining)")
                        else:
                            log      = notify["AllMissionsReady"]
                            msg_term = f"All {total} missions complete — ready to turn in!"
                        core.emitter.emit(
                            msg_term=msg_term, emoji="✅", sigil="*  MISS",
                            timestamp=event.get("_logtime"), loglevel=log,
                        )
                    if gq: gq.put(("mission_update", None))

            case "Bounty" if state.active_missions:
                # Attribute kill to matching target-faction missions for
                # live in-session kill counting.
                victim = event.get("VictimFaction", "")
                if victim:
                    self._session_kills_against(victim)
                    if gq: gq.put(("mission_update", None))

            case "MissionAbandoned" | "MissionCompleted" | "MissionFailed" if (
                state.missions
            ):
                # Preload guard removed intentionally: completions, abandonments, and
                # failures must be processed during preload so that _redirected is
                # drained of turned-in missions.  Notifications are suppressed during
                # preload via the inner guard below.
                mid = int(event.get("MissionID", 0))
                if mid not in state.active_missions:
                    return
                reward = state.mission_value_map.pop(mid, 0)
                if reward:
                    state.stack_value -= reward
                state.mission_target_faction_map.pop(mid, None)
                state.mission_detail_map.pop(mid, None)
                self._redirected.discard(mid)
                state.active_missions = [m for m in state.active_missions if m != mid]
                state.missions_complete = len(self._redirected)
                self._persist()
                if not state.in_preload:
                    event_label = ev[7:].lower()
                    core.emitter.emit(
                        msg_term=(f"Massacre mission {event_label} "
                                  f"(active: {len(state.active_missions)})"),
                        emoji="📋", sigil="*  MISS",
                        timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                    )
                    if gq: gq.put(("mission_update", None))

    def get_summary_line(self) -> str | None:
        state = self.core.state
        if state.stack_value <= 0:
            return None
        done      = state.missions_complete
        total     = len(state.active_missions)
        remaining = total - done
        status = (
            "all complete — turn in!"
            if remaining == 0
            else f"{done}/{total} complete, {remaining} remaining"
        )
        return f"- Missions: {fmt_credits(state.stack_value)} stack ({status})"

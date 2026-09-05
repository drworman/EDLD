"""
gui/blocks/session.py — Session window (Qt).

Current-session activity, rendered from ``core.summary_model.session_sections()``
— the same model the Career block's Summary tab renders at lifetime scope, and
the same one the Textual Session window uses.  Three renderers, one model: a
section added to the model appears in all of them without any of them changing.

A second tab carries the mission board: the massacre stack exactly as the
former Massacre Mission Stack window rendered it, followed by every other
mission the commander is holding, grouped by type.  That window is gone —
missions are session-scoped work, so they belong beside the session summary
rather than occupying a panel of their own.

Reset with Ctrl+R, which routes to ``session_stats.on_new_session(0)``.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from gui.block_base import GuiBlock, RowScroll
from core.summary_model import session_sections


def _fmt_rew(v: int) -> str:
    """Compact reward: 103.3M / 1.2B — no 'cr' suffix, consistent width."""
    if not v:                          return "—"
    if v >= 1_000_000_000:             return f"{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:                 return f"{v/1_000_000:.1f}M"
    if v >= 1_000:                     return f"{v/1_000:.0f}k"
    return str(v)


def _strip_target_type(raw: str) -> str:
    s = raw or ""
    if s.startswith("$") and s.endswith(";"):
        inner = s[1:-1]
        if "_" in inner:
            s = inner.rsplit("_", 1)[-1]
    return s.strip()



class SessionBlock(GuiBlock):
    BLOCK_TITLE = "SESSION"

    def _build_body(self, layout) -> None:
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._scroll = RowScroll()
        self._tabs.addTab(self._scroll, "Session")

        self._missions = RowScroll()
        self._tabs.addTab(self._missions, "Missions")

        layout.addWidget(self._tabs, 1)

    def refresh_data(self) -> None:
        self._refresh_summary()
        self._refresh_massacre()

    def _refresh_summary(self) -> None:
        try:
            sections = session_sections(self.core)
        except Exception:
            sections = []

        rows: list = []
        for section in sections:
            rows.append(self.hdr(section["title"]))
            for row in section["rows"]:
                if row["kind"] == "sub":
                    rows.append(self.text(row["label"], "dim"))
                    continue
                value = row["value"]
                if row.get("rate"):
                    value = f"{value}  {row['rate']}"
                rows.append(self.kv(row["label"], value))

        if not rows:
            rows = [self.text("No session activity yet", "dim")]
        self._scroll.set_rows(rows)

    def _refresh_massacre(self) -> None:
        s = self.state
        detail = getattr(s, "mission_detail_map", {}) or {}

        if not detail:
            # No massacres does not mean no missions — fall through to the
            # general board rather than reporting an empty stack and stopping.
            rows = self._refresh_all_missions([])
            if not rows:
                rows = [self.text("No active missions", "dim")]
            self._missions.set_rows(rows)
            return

        factions:        dict[str, dict] = {}
        target_factions: set[str]        = set()
        target_types:    set[str]        = set()
        total_reward                     = 0

        for mid, info in detail.items():
            src     = info.get("faction", "Unknown")
            kc      = int(info.get("kill_count", 0))
            reward  = int(info.get("reward", 0))
            tgt_f   = info.get("target_faction", "")
            tgt_t   = _strip_target_type(info.get("target_type", ""))
            sess_k  = int(info.get("kills_this_session", 0))

            if src not in factions:
                factions[src] = {"kill_count": 0, "reward": 0, "session_kills": 0}
            factions[src]["kill_count"]    += kc
            factions[src]["reward"]        += reward
            factions[src]["session_kills"] += sess_k
            total_reward += reward
            if tgt_f: target_factions.add(tgt_f)
            if tgt_t: target_types.add(tgt_t)

        heights      = sorted((v["kill_count"] for v in factions.values()), reverse=True)
        stack_height = heights[0] if heights else 0
        n_missions   = len(getattr(s, "active_missions", []))
        done         = getattr(s, "missions_complete", 0)
        full_stack   = self.core.app_settings.get("FullStackSize", 20)

        # Column widths (monospace): count = 5, credit = 8
        # Result:  "  118  |   103.3M"  — | always at same position.
        # The value labels use a monospace family for exactly this reason.
        def _val(count_str: str, reward: int | None = None) -> str:
            c = f"{count_str:>5}"
            if reward is not None:
                return f"{c}  |  {_fmt_rew(reward):>8}"
            # Pad to same visible width (18) so count column aligns with credit rows
            return f"{c}             "

        rows: list = []
        active_str = f"{n_missions}/{full_stack}"
        rows.append(self.kv("Active", _val(active_str)))
        if done > 0:
            rows.append(self.kv("Redirected", _val(f"{done}/{n_missions}")))
        rows.append(self.hdr("By Source Faction"))

        for faction in sorted(factions, key=lambda f: -factions[f]["kill_count"]):
            info  = factions[faction]
            kc    = info["kill_count"]
            rew_f = info["reward"]
            rows.append(self.kv(faction, _val(str(kc), rew_f)))

        rows.append(self.rule())
        # Stack height: kills | total credit value — matches the dashboard layout.
        rows.append(self.kv("Stack height", _val(str(stack_height), total_reward)))

        if len(target_factions) > 1:
            rows.append(self.text(
                f"[yellow]⚠ Mixed targets: {', '.join(sorted(target_factions))}[/yellow]"
            ))
        if len(target_types) > 1:
            rows.append(self.text(
                f"[yellow]⚠ Mixed types: {', '.join(sorted(target_types))}[/yellow]"
            ))

        rows = self._refresh_all_missions(rows)
        self._missions.set_rows(rows)

    def _refresh_all_missions(self, rows: list) -> list:
        """Append every non-massacre mission, grouped by category.

        Massacres are already summarised above by source faction, so listing
        them again here would just repeat the stack.
        """
        board = getattr(self.state, "all_missions", {}) or {}
        others = {mid: m for mid, m in board.items()
                  if m.get("category") != "Massacre"}
        if not others:
            return rows

        by_category: dict = {}
        for mission in others.values():
            by_category.setdefault(mission.get("category", "Other"), []).append(mission)

        rows.append(self.hdr(f"Other Missions ({len(others)})"))
        for category in sorted(by_category):
            rows.append(self.text(category, "dim"))
            for mission in sorted(by_category[category],
                                  key=lambda m: -int(m.get("reward", 0) or 0)):
                label = f"  {mission.get('name') or 'Mission'}"
                if mission.get("wing"):
                    label += "  [W]"
                rows.append(self.kv(label, _fmt_rew(int(mission.get("reward", 0) or 0))))

                detail = []
                if mission.get("count"):
                    detail.append(f"x{mission['count']}")
                for key in ("commodity", "target", "target_faction"):
                    if mission.get(key):
                        detail.append(str(mission[key]))
                if mission.get("passengers"):
                    detail.append(f"{mission['passengers']} pax")
                if mission.get("destination"):
                    detail.append(f"→ {mission['destination']}")
                if mission.get("status") and mission["status"] != "Active":
                    detail.append(f"[green]{mission['status']}[/green]")
                if detail:
                    rows.append(self.text("      " + "  ·  ".join(detail), "dim"))
        return rows

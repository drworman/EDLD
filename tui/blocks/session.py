"""
tui/blocks/session.py — Session window (Textual).

Current-session activity, split out of the Career block's Summary tab into
a window of its own so the session view and the career view each get full
height instead of sharing one tab.

Content comes from ``core.summary_model.session_sections()`` — the same
model the Career block's Summary tab renders at lifetime scope.  The two
windows therefore show the same sections, in the same order, with the same
meaning; only the scope differs.  Anything added to the model appears in
both.

Because this window no longer shares space with the wealth breakdown, it
renders each activity provider's full tab rows rather than the condensed
summary rows the Career block used to inline — notable bodies, habitable
zones, in-progress bio scans, per-commodity trade profit, limpet
efficiency, per-system merits.

A second tab carries the mission board: the massacre stack exactly as the
former Massacre Mission Stack window rendered it, followed by every other
mission the commander is holding, grouped by type.  That window is gone —
missions are session-scoped work, so they belong beside the session summary
rather than occupying a panel of their own.

Reset with Ctrl+R, which routes to session_stats.on_new_session(0).
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane
from textual.containers import VerticalScroll

from tui.block_base     import TuiBlock, KVRow, SecHdr
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



class SessionBlock(TuiBlock):
    BLOCK_TITLE = "SESSION"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="session-tabs"):
            with TabPane("Session", id="session-tab-summary"):
                yield VerticalScroll(id="session-body")
            with TabPane("Missions", id="session-tab-missions"):
                yield VerticalScroll(id="missions-scroll")

    def refresh_data(self) -> None:
        self._refresh_summary()
        self._refresh_massacre()
        self._refresh_all_missions()

    def _refresh_summary(self) -> None:
        try:
            scroll = self.query_one("#session-body", VerticalScroll)
        except Exception:
            return

        try:
            sections = session_sections(self.core)
        except Exception:
            sections = []

        widgets: list = []
        for section in sections:
            widgets.append(SecHdr(section["title"]))
            for row in section["rows"]:
                if row["kind"] == "sub":
                    widgets.append(Label(row["label"], classes="dim"))
                    continue
                value = row["value"]
                if row.get("rate"):
                    value = f"{value}  {row['rate']}"
                widgets.append(KVRow(row["label"], value))

        scroll.remove_children()
        if not widgets:
            scroll.mount(Label("No session activity yet", classes="dim"))
            return
        scroll.mount(*widgets)

    def _refresh_massacre(self) -> None:
        s      = self.state  # noqa: F841 (used by the lifted massacre renderer)
        detail = getattr(s, "mission_detail_map", {}) or {}

        try:
            scroll = self.query_one("#missions-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()

        if not detail:
            # No massacres does not mean no missions — the general board is
            # appended by _refresh_all_missions() after this returns.
            self._no_massacres = True
            return
        self._no_massacres = False

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
        # Result:  "  118  |   103.3M"  — | always at same position
        def _val(count_str: str, reward: int | None = None) -> str:
            c = f"{count_str:>5}"
            if reward is not None:
                return f"{c}  |  {_fmt_rew(reward):>8}"
            # Pad to same visible width (18) so count column aligns with credit rows
            return f"{c}             "

        rows: list = []
        active_str = f"{n_missions}/{full_stack}"
        rows.append(KVRow("Active", _val(active_str)))
        if done > 0:
            rows.append(KVRow("Redirected", _val(f"{done}/{n_missions}")))
        rows.append(SecHdr("By Source Faction"))

        for faction in sorted(factions, key=lambda f: -factions[f]["kill_count"]):
            info  = factions[faction]
            kc    = info["kill_count"]
            rew_f = info["reward"]
            rows.append(KVRow(faction, _val(str(kc), rew_f)))

        rows.append(Label("─" * 40, classes="sep"))
        # Stack height: kills | total credit value — matches the dashboard layout.
        rows.append(KVRow("Stack height", _val(str(stack_height), total_reward)))

        if len(target_factions) > 1:
            rows.append(Label(f"[yellow]⚠ Mixed targets: {', '.join(sorted(target_factions))}[/yellow]"))
        if len(target_types) > 1:
            rows.append(Label(f"[yellow]⚠ Mixed types: {', '.join(sorted(target_types))}[/yellow]"))

        scroll.mount(*rows)

    def _refresh_all_missions(self) -> None:
        """Append every non-massacre mission, grouped by category.

        Massacres are already summarised above by source faction, so listing
        them again here would just repeat the stack.
        """
        try:
            scroll = self.query_one("#missions-scroll", VerticalScroll)
        except Exception:
            return

        board = getattr(self.state, "all_missions", {}) or {}
        others = {mid: m for mid, m in board.items()
                  if m.get("category") != "Massacre"}
        if not others:
            if getattr(self, "_no_massacres", False):
                scroll.mount(Label("No active missions", classes="dim"))
            return

        by_category: dict = {}
        for mission in others.values():
            by_category.setdefault(mission.get("category", "Other"), []).append(mission)

        rows: list = [SecHdr(f"Other Missions ({len(others)})")]
        for category in sorted(by_category):
            rows.append(Label(category, classes="dim"))
            for mission in sorted(by_category[category],
                                  key=lambda m: -int(m.get("reward", 0) or 0)):
                label = f"  {mission.get('name') or 'Mission'}"
                if mission.get("wing"):
                    label += "  [W]"
                rows.append(KVRow(label, _fmt_rew(int(mission.get("reward", 0) or 0))))

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
                    rows.append(Label("      " + "  ·  ".join(detail), classes="dim"))

        scroll.mount(*rows)

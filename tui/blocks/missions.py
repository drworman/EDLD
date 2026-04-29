"""tui/blocks/missions.py — Mission stack block."""
from __future__ import annotations
from textual.app        import ComposeResult
from textual.widgets    import Label
from textual.containers import VerticalScroll
from tui.block_base     import TuiBlock, KVRow, SecHdr


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


class MissionsBlock(TuiBlock):
    BLOCK_TITLE = "MISSION STACK"

    def _compose_body(self) -> ComposeResult:
        yield VerticalScroll(id="missions-scroll")

    def refresh_data(self) -> None:
        s      = self.state
        detail = getattr(s, "mission_detail_map", {}) or {}

        try:
            scroll = self.query_one("#missions-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()

        if not detail:
            scroll.mount(Label("[dim]No active massacre missions[/dim]", classes="dim"))
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
        # Result:  "  118  |   103.3M"  — | always at same position
        def _val(count_str: str, reward: int | None = None) -> str:
            c = f"{count_str:>5}"
            if reward is not None:
                return f"{c}  [dim]|  {_fmt_rew(reward):>8}[/dim]"
            # Pad to same visible width (18) so count column aligns with credit rows
            return f"{c}[dim]             [/dim]"

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
        # Stack height: kills | total credit value — matches GTK4 layout.
        # Wing credits noted in parentheses when present.
        total_wing = sum(
            int(info.get("reward", 0))
            for info in detail.values()
            if info.get("wing")
        )
        if total_wing:
            # Wing suffix can't fit inline; append to the credit string
            rew_display = f"{_fmt_rew(total_reward)} ({_fmt_rew(total_wing)}w)"
            rows.append(KVRow("[dim]Stack height[/dim]",
                              f"{str(stack_height):>5}  [dim]|  {rew_display:>12}[/dim]"))
        else:
            rows.append(KVRow("[dim]Stack height[/dim]", _val(str(stack_height), total_reward)))

        if len(target_factions) > 1:
            rows.append(Label(f"[yellow]⚠ Mixed targets: {', '.join(sorted(target_factions))}[/yellow]"))
        if len(target_types) > 1:
            rows.append(Label(f"[yellow]⚠ Mixed types: {', '.join(sorted(target_types))}[/yellow]"))

        scroll.mount(*rows)

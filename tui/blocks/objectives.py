"""
tui/blocks/objectives.py — Objectives window (Textual).

What the commander has taken on and has yet to finish: the mission board, and
colonisation construction sites awaiting deliveries.  Both are work with an
end state, which is what separates them from the running totals in the Session
window and from the ship's own contents.

    Missions        the massacre stack summarised by source faction, then
                    every other mission held, grouped by type
    Colonisation    construction sites, their outstanding requirements and
                    delivery progress

Missions previously shared the Session window and Colonisation shared Cargo.
Neither belonged there: a mission stack is not a session statistic, and a
depot's shopping list is not the hold.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane
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


class ObjectivesBlock(TuiBlock):
    BLOCK_TITLE = "OBJECTIVES"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="objectives-tabs"):
            with TabPane("Missions", id="obj-tab-missions"):
                yield VerticalScroll(id="missions-scroll")
            with TabPane("Colonisation", id="obj-tab-colon"):
                yield VerticalScroll(id="colon-scroll")

    def on_mount(self) -> None:
        # Collapse state carried over from the Colonisation window:
        # market_id -> bool and system_name -> bool (True = expanded).
        self._expanded: dict[int, bool] = {}
        self._expanded_sys: dict[str, bool] = {}

    def refresh_data(self) -> None:
        self._refresh_massacre()
        self._refresh_all_missions()
        self._refresh_colonisation()

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

    def _refresh_colonisation(self) -> None:
        s       = self.state
        sites   = getattr(s, "colonisation_sites",              [])
        cargo   = getattr(s, "cargo_items",                     {})
        docked  = getattr(s, "colonisation_docked",             False)
        cur_mid = getattr(s, "_colonisation_current_market_id", None)

        try:
            scroll = self.query_one("#colon-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()

        if not sites:
            scroll.mount(Label(
                "No construction sites tracked.\nDock at a depot to begin.",
                classes="dim"
            ))
            return

        rows: list = []

        active = [s_ for s_ in sites if not s_.get("complete") and not s_.get("failed")]
        done   = [s_ for s_ in sites if s_.get("complete")]
        failed = [s_ for s_ in sites if s_.get("failed")]

        # Group active sites by system name
        sys_order: list[str] = []
        sys_sites: dict[str, list] = {}
        for site in active:
            sys_name = site.get("system") or "Unknown"
            if sys_name not in sys_sites:
                sys_order.append(sys_name)
                sys_sites[sys_name] = []
            sys_sites[sys_name].append(site)

        for sys_name in sys_order:
            if sys_name not in self._expanded_sys:
                self._expanded_sys[sys_name] = True
            sys_exp = self._expanded_sys[sys_name]

            sys_arrow = "▼" if sys_exp else "▶"
            sys_hdr   = SecHdr(f"{sys_arrow} {sys_name}")
            sys_hdr.system_name = sys_name   # type: ignore[attr-defined]
            rows.append(sys_hdr)

            if not sys_exp:
                continue

            for site in sys_sites[sys_name]:
                mid        = site.get("market_id")
                is_current = docked and mid == cur_mid
                name       = site.get("station") or site.get("system", "Unknown")
                pct        = round(site.get("progress", 0.0) * 100)

                if mid not in self._expanded:
                    self._expanded[mid] = True
                expanded = self._expanded.get(mid, True)

                arrow   = "▼" if expanded else "▶"
                cur_pfx = "[bold cyan]▶ [/bold cyan]" if is_current else ""
                hdr_txt = f"  {arrow} {cur_pfx}[bold cyan]{name}[/bold cyan]  {pct}%"
                hdr     = SecHdr(hdr_txt)
                hdr.market_id = mid  # type: ignore[attr-defined]
                rows.append(hdr)

                if not expanded:
                    continue

                resources  = site.get("resources", {})
                site_cargo = cargo if is_current else {}
                if not resources:
                    rows.append(Label("     (dock to load requirements)"))
                    continue

                remaining = [
                    (k, inf) for k, inf in resources.items()
                    if inf["provided"] < inf["required"]
                ]
                if not remaining:
                    rows.append(Label("     [green]All resources delivered![/green]"))
                    continue

                remaining.sort(key=lambda x: -(x[1]["required"] - x[1]["provided"]))
                total_rem = 0
                for key, info in remaining:
                    display  = info.get("name") or key
                    needed   = info["required"] - info["provided"]
                    total_rem += needed
                    c        = site_cargo.get(key, {})
                    in_cargo = c.get("count", 0) if isinstance(c, dict) else int(c)
                    need_str = f"{needed:,} needed"
                    if in_cargo > 0:
                        can = min(in_cargo, needed)
                        need_str += f" ({can:,} in hold)"
                    if in_cargo >= needed:
                        kv = KVRow(f"   {display}", f"[green]{need_str}[/green]")
                    elif in_cargo > 0:
                        kv = KVRow(f"   {display}", f"[yellow]{need_str}[/yellow]")
                    else:
                        kv = KVRow(f"   {display}", need_str)
                    rows.append(kv)
                rows.append(KVRow("   Total remaining", f"{total_rem:,} t"))

        for site in done:
            name = site.get("station") or site.get("system", "Unknown")
            rows.append(Label(f"[green]✓ {name} — complete[/green]"))

        for site in failed:
            name = site.get("station") or site.get("system", "Unknown")
            rows.append(Label(f"[red]✗ {name} — failed[/red]"))

        scroll.mount(*rows)

    def on_click(self, event) -> None:
        """Toggle collapse when a site or system header is clicked."""
        node = event.widget
        while node is not None:
            if isinstance(node, SecHdr):
                if hasattr(node, "market_id") and node.market_id is not None:
                    mid = node.market_id
                    self._expanded[mid] = not self._expanded.get(mid, True)
                    self.refresh_data()
                    return
                if hasattr(node, "system_name") and node.system_name is not None:
                    sn = node.system_name
                    self._expanded_sys[sn] = not self._expanded_sys.get(sn, True)
                    self.refresh_data()
                    return
            node = getattr(node, "parent", None)

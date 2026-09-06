"""
gui/blocks/objectives.py — Objectives window (Qt).

What the commander has taken on and has yet to finish: the mission board, and
colonisation construction sites awaiting deliveries.  Both are work with an
end state, which is what separates them from the running totals in the Session
window and from the ship's own contents.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget

from gui.block_base import ClickableHdr, GuiBlock, RowScroll, SecHdr


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


class ObjectivesBlock(GuiBlock):
    BLOCK_TITLE = "OBJECTIVES"

    def _build_body(self, layout) -> None:
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._missions = RowScroll()
        self._tabs.addTab(self._missions, "Missions")

        # Collapse state carried over from the Colonisation window.
        self._expanded: dict[int, bool] = {}
        self._expanded_sys: dict[str, bool] = {}
        self._colon_scroll = RowScroll()
        self._tabs.addTab(self._colon_scroll, "Colonisation")

        layout.addWidget(self._tabs, 1)

    def refresh_data(self) -> None:
        self._refresh_massacre()
        self._refresh_colonisation()

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

    def _on_hdr_click(self, *, system_name=None, market_id=None) -> None:
        """Collapse or expand the group whose header was clicked.

        Qt does not bubble clicks from plain labels the way the terminal side
        walks up from the clicked widget, so ClickableHdr hands the identity
        of the group straight back here.
        """
        if market_id is not None:
            self._expanded[market_id] = not self._expanded.get(market_id, True)
        elif system_name is not None:
            self._expanded_sys[system_name] = not self._expanded_sys.get(
                system_name, True)
        else:
            return
        self._refresh_colonisation()

    def _refresh_colonisation(self) -> None:
        s       = self.state
        sites   = getattr(s, "colonisation_sites",              [])
        cargo   = getattr(s, "cargo_items",                     {})
        docked  = getattr(s, "colonisation_docked",             False)
        cur_mid = getattr(s, "_colonisation_current_market_id", None)

        if not sites:
            self._colon_scroll.set_rows([self.text(
                "No construction sites tracked.\nDock at a depot to begin.", "dim")])
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
            rows.append(ClickableHdr(
                f"{sys_arrow} {sys_name}", self.palette_map,
                self._on_hdr_click, system_name=sys_name))

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
                rows.append(ClickableHdr(
                    hdr_txt, self.palette_map, self._on_hdr_click, market_id=mid))

                if not expanded:
                    continue

                resources  = site.get("resources", {})
                site_cargo = cargo if is_current else {}
                if not resources:
                    rows.append(self.text("     (dock to load requirements)"))
                    continue

                remaining = [
                    (k, inf) for k, inf in resources.items()
                    if inf["provided"] < inf["required"]
                ]
                if not remaining:
                    rows.append(self.text("     [green]All resources delivered![/green]"))
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
                        kv = self.kv(f"   {display}", f"[green]{need_str}[/green]")
                    elif in_cargo > 0:
                        kv = self.kv(f"   {display}", f"[yellow]{need_str}[/yellow]")
                    else:
                        kv = self.kv(f"   {display}", need_str)
                    rows.append(kv)
                rows.append(self.kv("   Total remaining", f"{total_rem:,} t"))

        for site in done:
            name = site.get("station") or site.get("system", "Unknown")
            rows.append(self.text(f"[green]✓ {name} — complete[/green]"))

        for site in failed:
            name = site.get("station") or site.get("system", "Unknown")
            rows.append(self.text(f"[red]✗ {name} — failed[/red]"))

        self._colon_scroll.set_rows(rows)

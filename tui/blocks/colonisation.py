"""tui/blocks/colonisation.py — Colonisation construction site tracker."""
from __future__ import annotations
from textual.app        import ComposeResult
from textual.widgets    import Label
from textual.containers import VerticalScroll
from tui.block_base     import TuiBlock, KVRow, SecHdr


class ColonisationBlock(TuiBlock):
    BLOCK_TITLE = "COLONISATION"

    def _compose_body(self) -> ComposeResult:
        yield VerticalScroll(id="colon-scroll")

    def on_mount(self) -> None:
        # Collapse state: market_id -> bool (True = expanded)
        self._expanded: dict[int, bool] = {}
        # System-group collapse state: system_name -> bool (True = expanded)
        self._expanded_sys: dict[str, bool] = {}

    def refresh_data(self) -> None:
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
                "[dim]No construction sites tracked.\nDock at a depot to begin.[/dim]",
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
            sys_hdr   = SecHdr(f"{sys_arrow} [dim]{sys_name}[/dim]")
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
                hdr_txt = f"  {arrow} {cur_pfx}[bold cyan]{name}[/bold cyan]  [dim]{pct}%[/dim]"
                hdr     = SecHdr(hdr_txt)
                hdr.market_id = mid  # type: ignore[attr-defined]
                rows.append(hdr)

                if not expanded:
                    continue

                resources  = site.get("resources", {})
                site_cargo = cargo if is_current else {}
                if not resources:
                    rows.append(Label("     [dim](dock to load requirements)[/dim]"))
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
                rows.append(KVRow("   [dim]Total remaining[/dim]", f"{total_rem:,} t"))

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

"""gui/blocks/colonisation.py — Colonisation construction site tracker (Qt).

Site and system headers collapse when clicked, exactly as in the Textual
block.  Collapse state is held per market id and per system name on the widget
and survives refreshes, so a site you folded away stays folded while cargo
updates stream in.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from gui.block_base import GuiBlock, SecHdr


class ClickableHdr(SecHdr):
    """A section header that reports clicks back to the block.

    Carries the identity of whatever it toggles — a market id for a site, a
    system name for a system group — so the click handler doesn't have to
    reverse-engineer it from the label text.
    """

    def __init__(self, title: str, palette, on_click, market_id=None,
                 system_name=None) -> None:
        super().__init__(title, palette=palette)
        self.market_id = market_id
        self.system_name = system_name
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and callable(self._on_click):
            self._on_click(self)
            event.accept()
            return
        super().mousePressEvent(event)


class ColonisationBlock(GuiBlock):
    BLOCK_TITLE = "COLONISATION"

    def _build_body(self, layout) -> None:
        # Collapse state: market_id -> bool (True = expanded)
        self._expanded: dict[int, bool] = {}
        # System-group collapse state: system_name -> bool (True = expanded)
        self._expanded_sys: dict[str, bool] = {}
        self._scroll = self.scroll()
        layout.addWidget(self._scroll, 1)

    def _on_hdr_click(self, hdr: ClickableHdr) -> None:
        """Toggle collapse when a site or system header is clicked."""
        if hdr.market_id is not None:
            mid = hdr.market_id
            self._expanded[mid] = not self._expanded.get(mid, True)
            self.refresh_data()
            return
        if hdr.system_name is not None:
            sn = hdr.system_name
            self._expanded_sys[sn] = not self._expanded_sys.get(sn, True)
            self.refresh_data()

    def refresh_data(self) -> None:
        s       = self.state
        sites   = getattr(s, "colonisation_sites",              [])
        cargo   = getattr(s, "cargo_items",                     {})
        docked  = getattr(s, "colonisation_docked",             False)
        cur_mid = getattr(s, "_colonisation_current_market_id", None)

        if not sites:
            self._scroll.set_rows([self.text(
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

        self._scroll.set_rows(rows)

"""gui/blocks/cargo.py — Cargo manifest block with target market search (Qt).

The footer's "Set Target" control is a real push button here rather than the
TUI's clickable Static, but it opens the same search over the same
``spansh.search`` callable and stores the result through the same
``spansh.set_target`` call, so a target set in one front end is visible in the
other.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTabWidget, QWidget,
)

from gui.block_base import GuiBlock, RowScroll, SecHdr
from gui.markup import to_html


def _fmt_cr(v) -> str:
    if not v: return "—"
    v = int(v)
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.2f}B cr"
    if v >= 1_000_000:     return f"{v/1_000_000:.1f}M cr"
    if v >= 1_000:         return f"{v/1_000:.0f}K cr"
    return f"{v:,} cr"


class CargoBlock(GuiBlock):
    BLOCK_TITLE = "CARGO"

    def _build_body(self, layout) -> None:
        # The price-source label lives on the title bar, right-aligned, the
        # same place the TUI puts it.
        self._price_src = QLabel()
        self._price_src.setTextFormat(Qt.RichText)
        self._price_src.setProperty("role", "dim")
        self._price_src.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title_bar = self._title.parentWidget()
        # Rebuild the title row so the source label sits beside the title.
        hdr = QWidget()
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 8, 0)
        hl.setSpacing(8)
        self._title.setParent(None)
        hl.addWidget(self._title, 1)
        hl.addWidget(self._price_src, 0)
        outer = self.layout()
        outer.insertWidget(0, hdr)

        # Two tabs: Cargo is what the hold contains, Colonisation is what a
        # construction depot still needs.  Same activity from opposite ends.
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._scroll = RowScroll()
        self._tabs.addTab(self._scroll, "Cargo")

        # Collapse state carried over from the Colonisation window.
        self._expanded: dict[int, bool] = {}
        self._expanded_sys: dict[str, bool] = {}
        self._colon_scroll = RowScroll()
        self._tabs.addTab(self._colon_scroll, "Colonisation")

        layout.addWidget(self._tabs, 1)

        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(6, 2, 6, 2)
        fl.setSpacing(8)
        self._target_btn = QPushButton("Set Target")
        self._target_btn.setProperty("role", "link")
        self._target_btn.clicked.connect(self._on_set_target)
        self._target_lbl = QLabel()
        self._target_lbl.setProperty("role", "dim")
        self._target_lbl.setTextFormat(Qt.RichText)
        self._target_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fl.addWidget(self._target_btn, 0)
        fl.addWidget(self._target_lbl, 1)
        layout.addWidget(footer)

    # ── Target market search ──────────────────────────────────────────────────

    def _on_set_target(self) -> None:
        spansh = self.core._plugins.get("spansh")
        if spansh is None:
            return

        from gui.search_dialog import SearchDialog

        def _on_select(result: dict | None) -> None:
            if not result:
                return
            name    = result.get("name", "")
            raw_rec = result.get("_rec") or result
            spansh.set_target(name, result.get("system", ""), _record=raw_rec)
            self.refresh_data()

        dlg = SearchDialog(
            parent       = self.window(),
            title        = "Set Target Market",
            placeholder  = "Station name…",
            search_fn    = spansh.search,
            result_label = lambda r: f"{r['name']}  {r.get('system', '')}",
            theme        = self.theme,
        )
        dlg.accepted_result.connect(_on_select)
        dlg.exec()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        self._refresh_colonisation()
        s     = self.state
        items = getattr(s, "cargo_items",    {})
        cap   = getattr(s, "cargo_capacity", 0)
        used  = sum(i.get("count", 0) for i in items.values())

        # ── Price source label (top-right of header) ──────────────────────────
        tgt_info  = getattr(s, "cargo_target_market", {})
        tgt_name  = getattr(s, "cargo_target_market_name", "") or ""
        mkt_info  = getattr(s, "cargo_market_info", {})
        tgt_comms = tgt_info.get("commodities", {})
        gal_comms = mkt_info.get("commodities", {})
        # has_target_name: user has selected a station (show its name in header)
        # has_target_prices: station market data was loaded (use for prices)
        has_target_name   = bool(tgt_name)
        has_target_prices = has_target_name and bool(tgt_comms)

        if has_target_name:
            stn  = tgt_info.get("station_name", "") or ""
            sys_ = tgt_info.get("star_system",  "") or ""
            src_label = f"{stn} · {sys_}" if stn and sys_ else (tgt_name or "Target")
        else:
            stn  = mkt_info.get("station_name", "") or ""
            sys_ = mkt_info.get("star_system",  "") or ""
            src_label = (f"{stn} · {sys_}" if stn and sys_ else
                         stn or sys_ or "Gal. Avg")

        self._price_src.setText(to_html(f" {src_label} ", self.palette_map))
        self._target_lbl.setText(to_html(
            f"→ {tgt_name}" if tgt_name else "No target set", self.palette_map))

        cap_str = f"{used}/{cap} t" if cap else (f"{used} t" if used else "—")

        # An empty hold renders the same layout as a loaded one — no items, then
        # the separator and Totals line, where "0 / capacity" reads as empty on
        # its own.  No special-case notice.

        # ── Build enriched item list ──────────────────────────────────────────
        enriched = []
        mean_prices = getattr(s, "cargo_mean_prices", {}) or {}
        for key, info in items.items():
            count = info.get("count", 0)
            if count <= 0:
                continue
            gal  = gal_comms.get(key, {})
            tgt  = tgt_comms.get(key, {})
            name = (gal.get("name_local")
                    or tgt.get("name_local")
                    or info.get("name_local")
                    or key.replace("_", " ").title())
            # Fall back to persisted mean_prices when cargo_market_info has no entry
            # (e.g. when docked at FC or no station market loaded yet)
            gal_avg     = int(gal.get("mean_price") or mean_prices.get(key, 0))
            tgt_sell    = int(tgt.get("sell_price", 0))
            docked_sell = int(gal.get("sell_price", 0))
            if has_target_prices:
                price = tgt_sell or gal_avg
            else:
                price = docked_sell or gal_avg
            stolen = info.get("stolen", False)
            enriched.append(dict(name=name, count=count,
                                 price=price, stolen=stolen))

        enriched.sort(key=lambda x: x["name"].lower())

        # ── Render rows: qty  |  credits ─────────────────────────────────────
        rows: list = []
        total = 0

        for item in enriched:
            count  = item["count"]
            price  = item["price"]
            total += price * count
            name   = ("⚠ " if item["stolen"] else "") + item["name"]
            # Both columns fixed-width (qty right-justified to 4, price to 9) so
            # the whole value string is constant width.  The value labels render
            # in a monospace family, so a constant width puts the | in the same
            # column on every row.
            val_str = f"{count:>4} t  | {_fmt_cr(price):>9}"
            rows.append(self.kv(name, val_str))

        # ── Totals, lifted away from the manifest ────────────────────────────
        cr_total = _fmt_cr(total) if total else "—"
        rows.append(self.kv("", ""))          # blank spacer row
        rows.append(self.rule())              # visible separator line
        rows.append(self.kv("Totals", f"{cap_str}  | {cr_total:>9}"))

        self._scroll.set_rows(rows)

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

"""tui/blocks/cargo.py — Cargo manifest and colonisation contributions.

Two tabs.  Cargo is what the hold currently contains; Colonisation is what a
construction depot still needs.  They are the same activity from opposite
ends — the question during a hauling run is "what do I still need to carry" —
and answering it used to mean reading two separate windows side by side.

Cargo also collapses to a couple of rows on a carrier run, which is exactly
when a construction site is likely to be live, so the space is well shared.
"""
from __future__ import annotations
from textual.app        import ComposeResult
from textual.widgets    import Label, Static, TabbedContent, TabPane
from textual.containers import VerticalScroll, Horizontal
from tui.block_base     import TuiBlock, KVRow, SecHdr


def _fmt_cr(v) -> str:
    if not v: return "—"
    v = int(v)
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.2f}B cr"
    if v >= 1_000_000:     return f"{v/1_000_000:.1f}M cr"
    if v >= 1_000:         return f"{v/1_000:.0f}K cr"
    return f"{v:,} cr"


class CargoBlock(TuiBlock):
    BLOCK_TITLE = "CARGO"

    def compose(self) -> ComposeResult:
        # Header row: left = "CARGO", right = price source label
        with Horizontal(id="cargo-hdr-row"):
            yield Label("CARGO", id="cargo-title", classes="block-title")
            yield Label("", id="cargo-price-src", classes="block-title")
        with TabbedContent(id="cargo-tabs"):
            with TabPane("Cargo", id="cargo-tab-hold"):
                with VerticalScroll(id="cargo-scroll"):
                    yield Label("No cargo", id="cargo-empty")
            with TabPane("Colonisation", id="cargo-tab-colon"):
                yield VerticalScroll(id="colon-scroll")
        with Horizontal(id="cargo-footer"):
            yield Static(">> Set Target", id="cargo-target-btn",
                         classes="footer-lbl")
            yield Label("", id="cargo-target-lbl", classes="dim")

    def on_mount(self) -> None:
        # Collapse state carried over from the Colonisation window:
        # market_id -> bool and system_name -> bool (True = expanded).
        self._expanded: dict[int, bool] = {}
        self._expanded_sys: dict[str, bool] = {}

    def on_click(self, event) -> None:
        if str(getattr(event.widget, "id", "")) != "cargo-target-btn":
            return
        event.stop()
        spansh = self.core._plugins.get("spansh")
        if spansh is None:
            return

        def _on_select(result: dict | None) -> None:
            if not result:
                return
            name    = result.get("name", "")
            raw_rec = result.get("_rec") or result
            spansh.set_target(name, result.get("system", ""), _record=raw_rec)

        from tui.search_modal import SearchModal
        self.app.push_screen(SearchModal(
            title        = "Set Target Market",
            placeholder  = "Station name…",
            search_fn    = spansh.search,
            result_label = lambda r: (
                f"{r['name']}  {r.get('system', '')}"
            ),
            callback     = _on_select,
        ))

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

        try:
            self.query_one("#cargo-price-src", Label).update(
                f" {src_label} "
            )
        except Exception:
            pass

        # ── Target label in footer ────────────────────────────────────────────
        try:
            self.query_one("#cargo-target-lbl", Label).update(
                f"→ {tgt_name}" if tgt_name else "No target set"
            )
        except Exception:
            pass

        try:
            scroll = self.query_one("#cargo-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()

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
            # the whole value string is constant width.  KVRow right-aligns the
            # value, so a constant width puts the | in the same screen column on
            # every row.
            val_str = f"{count:>4} t  | {_fmt_cr(price):>9}"
            rows.append(KVRow(name, val_str))

        # ── Totals, lifted away from the manifest ────────────────────────────
        # A blank row and a separator line (the app's own .sep styling) set the
        # totals apart from the manifest.  The tonnage reads used / capacity, so
        # the vessel's maximum hold is always shown — an empty hold simply reads
        # "0 / capacity" here rather than needing a separate notice.
        cr_total = _fmt_cr(total) if total else "—"
        rows.append(KVRow("", ""))                       # blank spacer row
        rows.append(Static("─" * 40, classes="sep"))     # visible separator line
        rows.append(KVRow("Totals", f"{cap_str}  | {cr_total:>9}"))

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

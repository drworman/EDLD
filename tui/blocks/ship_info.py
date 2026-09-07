"""
tui/blocks/ship_info.py — Ship window (Textual).

Everything about the vessel itself, behind one header naming it: what it is
carrying, what it is fitted with, and what is in the material store.

    Header      ship name, ident and type, on one line
    Cargo       the hold
    Modules     every fitted module, sorted by power priority ascending,
                then by health ascending within each priority group
    Engineering the material store by grade

Modules is built for neutron hopping, where the question before every leg is
simply "does anything need repairing before I carry on?".

The secondary sort is the point: whatever most needs an AFM unit pointed at
it floats to the top of its power group, so a damaged module cannot hide in
the middle of a thirty-row list.

Priority is displayed 1-based to match the in-game power distribution panel;
the journal reports it 0-based and core/summary data keeps the raw value.

Hull, shields and fuel live in the Commander window's Info tab, which is the
default view and therefore the one place they cost nothing to reach.  This
window is about the ship's contents and fitting.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label, Static, TabbedContent, TabPane
from textual.containers import VerticalScroll, Horizontal

from tui.block_base     import TuiBlock, KVRow, HRule, SecHdr, _health_cls
from core.state         import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD


def _cargo_cols(count: int, unit_price: int, line_value: int) -> str:
    """Units | price per unit | line value, at fixed widths.

    Constant width matters: KVRow right-aligns its value, so every row's
    separators land in the same screen column only if the string does not
    change length.
    """
    # Nine characters of tonnage, matching the "used/capacity t" the Totals
    # line puts in the same column, so the separators line up on every row.
    return (f"{f'{count} t':>10} | {_fmt_cr(unit_price):>9} "
            f"| {_fmt_cr(line_value):>10}")


def _is_limpet(name: str) -> bool:
    """True for the limpet/drone commodity, however it is spelled."""
    return "limpet" in (name or "").lower() or (name or "").lower() == "drones"


def _fmt_cr(v) -> str:
    """Compact credit formatting for the cargo manifest."""
    if not v:
        return "—"
    v = int(v)
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.2f}B cr"
    if v >= 1_000_000:     return f"{v/1_000_000:.1f}M cr"
    if v >= 1_000:         return f"{v/1_000:.0f}K cr"
    return f"{v:,} cr"


#: Material grades, in the order the Engineering tab presents them.
_TABS = [
    ("raw",          "Raw"),
    ("manufactured", "Mfg"),
    ("encoded",      "Enc"),
    ("components",   "Comp"),
    ("items",        "Items"),
    ("consumables",  "Cons"),
    ("data",         "Data"),
]


def _fmt_health(fraction: float) -> str:
    """Render a 0.0–1.0 health fraction.

    Wear accumulates slowly, so a module at 99.2% would round to a flat
    "99%" and look identical to one at 98.6%.  One decimal place is kept
    below full health to keep that difference visible; a genuinely pristine
    module shows a clean "100%".
    """
    pct = max(0.0, min(1.0, fraction)) * 100
    if pct >= 99.95:
        return "100%"
    return f"{pct:.1f}%"


class ShipInfoBlock(TuiBlock):
    BLOCK_TITLE = "SHIP"

    def compose(self) -> ComposeResult:
        # One header line naming the vessel.  The focus of this window is the
        # ship, not its condition, so the identity is the whole heading.
        yield Label("", id="sh-hdr1", classes="block-title")
        yield from self._compose_body()

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="ship-tabs"):
            # Cargo leads: it changes constantly and is checked far more often
            # than a module list that only moves when something takes damage.
            with TabPane("Cargo", id="ship-tab-cargo"):
                yield from self._compose_cargo()
            with TabPane("Modules", id="ship-tab-modules"):
                yield SecHdr("Modules", id="sh-modules-hdr")
                yield VerticalScroll(id="sh-modules")
            with TabPane("Engineering", id="ship-tab-engineering"):
                yield from self._compose_engineering()

    def _compose_cargo(self) -> ComposeResult:
        with VerticalScroll(id="cargo-scroll"):
            yield Label("No cargo", id="cargo-empty")
        with Horizontal(id="cargo-footer"):
            yield Static(">> Set Target", id="cargo-target-btn",
                         classes="footer-lbl")
            yield Label("", id="cargo-target-lbl", classes="dim")

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

    def _compose_engineering(self) -> ComposeResult:
        with TabbedContent(id="eng-tabs"):
            for key, label in _TABS:
                with TabPane(label, id=f"eng-pane-{key}"):
                    yield VerticalScroll(id=f"eng-scroll-{key}")


    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        state  = self.core.state
        plugin = self.core._plugins.get("ship_health")

        self._refresh_header(state)
        self._refresh_modules(state, plugin)
        self._refresh_cargo()
        self._refresh_engineering()

    # ── Header ────────────────────────────────────────────────────────────────

    def _refresh_header(self, state) -> None:
        """Ship name, ident and type, on one line."""
        name  = (getattr(state, "ship_name", "")  or "").upper()
        ident = (getattr(state, "ship_ident", "") or "").upper()
        stype = (getattr(state, "pilot_ship", "") or "").upper()

        parts = [p for p in (name, ident, stype) if p]
        self._set_label("sh-hdr1", " - ".join(parts) or "SHIP")

    def _set_label(self, node_id: str, text: str) -> None:
        try:
            label = self.query_one(f"#{node_id}", Label)
            label.update(text)
            label.display = bool(text)
        except Exception:
            pass

    def _refresh_modules(self, state, plugin) -> None:
        try:
            scroll = self.query_one("#sh-modules", VerticalScroll)
        except Exception:
            return

        if plugin is not None:
            modules = plugin.modules_sorted()
        else:
            # Component unavailable — sort here so the window still works.
            modules = sorted(
                list(getattr(state, "ship_modules", []) or []),
                key=lambda m: (int(m.get("priority", 0) or 0),
                               float(m.get("health", 1.0) or 0.0),
                               m.get("name_display", "")),
            )

        self._update_header(modules)

        scroll.remove_children()
        if not modules:
            scroll.mount(Label("No loadout data yet — dock or jump to populate.",
                               classes="dim"))
            return

        rows: list = []
        for m in modules:
            health   = float(m.get("health", 1.0) or 0.0)
            pct      = int(health * 100)
            # Journal priority is 0-based; the in-game panel labels the same
            # group one higher.
            priority = int(m.get("priority", 0) or 0) + 1
            name     = m.get("name_display") or m.get("slot") or "—"
            powered  = m.get("on", True)

            key = f"{priority}  {name}"
            if not powered:
                key += " (off)"

            cls = f"val {_health_cls(pct)}" if health < 1.0 else "val dim"
            rows.append(KVRow(key, _fmt_health(health), val_classes=cls))
        scroll.mount(*rows)

    def _update_header(self, modules: list) -> None:
        """Put the count needing attention in the Modules header itself."""
        damaged = sum(1 for m in modules
                      if float(m.get("health", 1.0) or 0.0) < 1.0)
        if damaged:
            text = f"MODULES — {damaged} damaged"
        elif modules:
            text = f"MODULES — {len(modules)} all nominal"
        else:
            text = "MODULES"
        try:
            self.query_one("#sh-modules-hdr", SecHdr).update(text)
        except Exception:
            pass

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set(self, row_id: str, text: str, classes: str = "val") -> None:
        try:
            self.query_one(f"#{row_id}", KVRow).set_value(text, classes)
        except Exception:
            pass

    def _refresh_cargo(self) -> None:
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

        # Limpets are consumables rather than freight — never sold, and their
        # count is what tells you whether the run can continue — so they sit
        # apart, below a blank line and immediately above the totals.
        limpets  = [x for x in enriched if _is_limpet(x["name"])]
        enriched = [x for x in enriched if not _is_limpet(x["name"])]

        # Cheapest per unit first.  With a full hold the question is what to
        # jettison, and that is answered by whatever is worth least per tonne
        # — so it belongs at the top rather than buried alphabetically.
        enriched.sort(key=lambda x: (x["price"], x["name"].lower()))

        # ── Render rows: qty  |  credits ─────────────────────────────────────
        # The ship's hold is one section and the SRV's is another; heading
        # each keeps them apart when both are carrying something.
        rows: list = [SecHdr("Ship"), HRule()]
        total = 0

        # Three fixed-width columns — units, price per unit, line value.  KVRow
        # right-aligns the value, so a constant width puts both separators in
        # the same screen column on every row.
        for item in enriched:
            count  = item["count"]
            price  = item["price"]
            line   = price * count
            total += line
            name   = ("⚠ " if item["stolen"] else "") + item["name"]
            rows.append(KVRow(name, _cargo_cols(count, price, line)))

        # ── Totals, lifted away from the manifest ────────────────────────────
        # A blank row and a separator line (the app's own .sep styling) set the
        # totals apart from the manifest.  The tonnage reads used / capacity, so
        # the vessel's maximum hold is always shown — an empty hold simply reads
        # "0 / capacity" here rather than needing a separate notice.
        # Limpets last, set off by a blank line so they read as a separate
        # thing rather than the cheapest item in the manifest.
        if limpets:
            rows.append(KVRow("", ""))
        for item in limpets:
            count  = item["count"]
            line   = item["price"] * count
            total += line
            rows.append(KVRow(item["name"],
                              _cargo_cols(count, item["price"], line)))

        cr_total = _fmt_cr(total) if total else "—"
        rows.append(KVRow("", ""))                       # blank spacer row
        rows.append(Static("─" * 40, classes="sep"))     # visible separator line
        # Totals carries no per-unit price, so that column stays empty and
        # the line value lands under the column it totals.
        rows.append(KVRow("Totals", f"{cap_str:>10} | {'':>9} | {cr_total:>10}"))

        # ── SRV hold ─────────────────────────────────────────────────────────
        # Only while an SRV is out.  The journal reports a count for it and
        # never an inventory, so tonnage is all there is to show — saying so
        # beats an empty section that looks like a failed read.
        if self._srv_deployed():
            srv_items = getattr(s, "srv_cargo_items", None) or {}
            srv_used  = int(getattr(s, "srv_cargo_count", 0) or 0)
            rows.append(KVRow("", ""))
            rows.append(SecHdr("SRV"))
            rows.append(HRule())

            srv_total = 0
            for key, item in sorted(srv_items.items(),
                                    key=lambda kv: (mean_prices.get(kv[0], 0),
                                                    kv[0])):
                count = int(item.get("count", 0) or 0)
                price = int(mean_prices.get(key, 0) or 0)
                line  = price * count
                srv_total += line
                name  = ("⚠ " if item.get("stolen") else "") + (
                    item.get("name_local") or key.title())
                rows.append(KVRow(name, _cargo_cols(count, price, line)))

            if srv_items:
                rows.append(KVRow("Totals", _cargo_cols(srv_used, 0, srv_total)
                                  .replace(f"{_fmt_cr(0):>9}", f"{'':>9}")))
            else:
                rows.append(KVRow("Carrying", f"{srv_used:>5} t"))

        scroll.mount(*rows)

    def _srv_deployed(self) -> bool:
        """True while the commander has an SRV out."""
        s = self.state
        return bool(getattr(s, "srv_type", "")
                    or str(getattr(s, "vessel_mode", "")).lower() == "srv")

    def _refresh_engineering(self) -> None:
        s  = self.state
        lk = getattr(s, "engineering_locker", {})

        buckets = {
            "raw":          getattr(s, "materials_raw",          {}),
            "manufactured": getattr(s, "materials_manufactured", {}),
            "encoded":      getattr(s, "materials_encoded",      {}),
            "components":   lk.get("components", {}),
            "items":        lk.get("items",       {}),
            "consumables":  lk.get("consumables", {}),
            "data":         lk.get("data",        {}),
        }

        for key, items in buckets.items():
            try:
                scroll = self.query_one(f"#eng-scroll-{key}", VerticalScroll)
            except Exception:
                continue

            scroll.remove_children()

            if not items:
                scroll.mount(Label("— none —", classes="dim"))
                continue

            sorted_items = sorted(
                items.items(),
                key=lambda kv: kv[1].get("name_local", kv[0]).lower()
            )
            # No totals row: the sum across a material grade is not a
            # number anyone acts on, and it cost a line at the top of every
            # tab.
            rows: list = []
            for _, data in sorted_items:
                name  = data.get("name_local", "")
                count = data.get("count", 0)
                rows.append(KVRow(name, str(count)))

            scroll.mount(*rows)

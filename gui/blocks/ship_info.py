"""
gui/blocks/ship_health.py — Ship Health window (Qt).

Built for neutron hopping, where the question before every leg is simply
"does anything need repairing before I carry on?".

Layout, top to bottom:

    Hull        integrity percentage
    Shields     up / down / recharging
    ─────────
    MODULES     header, with a count of anything below full health
                every fitted module, sorted by power priority ascending,
                then by health ascending within each priority group

The secondary sort is the point: whatever most needs an AFM unit pointed at
it floats to the top of its power group, so a damaged module cannot hide in
the middle of a thirty-row list.

Priority is displayed 1-based to match the in-game power distribution panel;
the journal reports it 0-based and core/summary data keeps the raw value.

Hull and shields are read from ``state`` where the commander and alerts
components maintain them, so this window never becomes a second source of
truth for either figure.  Per-module health comes from the ship_health
component.
"""

from __future__ import annotations

from core.state import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)
from gui.markup import to_html
from gui.block_base import GuiBlock, RowScroll, SecHdr, _health_cls


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


def _fmt_cr(v) -> str:
    """Compact credit formatting for the cargo manifest."""
    if not v:
        return "—"
    v = int(v)
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.2f}B cr"
    if v >= 1_000_000:     return f"{v/1_000_000:.1f}M cr"
    if v >= 1_000:         return f"{v/1_000:.0f}K cr"
    return f"{v:,} cr"


def _cargo_cols(count: int, unit_price: int, line_value: int) -> str:
    """Units | price per unit | line value, at fixed widths.

    Nine characters of tonnage, matching the "used/capacity t" the Totals
    line puts in the same column, so the separators line up on every row.
    """
    return (f"{f'{count} t':>10} | {_fmt_cr(unit_price):>9} "
            f"| {_fmt_cr(line_value):>10}")


def _is_limpet(name: str) -> bool:
    """True for the limpet/drone commodity, however it is spelled."""
    return "limpet" in (name or "").lower() or (name or "").lower() == "drones"


class ShipInfoBlock(GuiBlock):
    BLOCK_TITLE = "SHIP"

    def _build_body(self, layout) -> None:
        # One header line naming the vessel.  The focus of this window is the
        # ship, not its condition, so the identity is the whole heading.
        self._hdr1 = self.text("", "section-hdr")
        layout.addWidget(self._hdr1)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # Cargo leads: it changes constantly and is checked far more often
        # than a module list that only moves when something takes damage.
        cargo_page = QWidget()
        cargo_page_layout = QVBoxLayout(cargo_page)
        cargo_page_layout.setContentsMargins(0, 0, 0, 0)

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

        self._cargo_scroll = RowScroll()

        cargo_page_layout.addWidget(self._cargo_scroll, 1)

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
        cargo_page_layout.addWidget(footer)
        self._tabs.addTab(cargo_page, "Cargo")

        modules_page = QWidget()
        modules_layout = QVBoxLayout(modules_page)
        modules_layout.setContentsMargins(0, 0, 0, 0)
        self._modules_hdr = self.hdr("Modules")
        self._scroll = self.scroll()
        modules_layout.addWidget(self._modules_hdr)
        modules_layout.addWidget(self._scroll, 1)
        self._tabs.addTab(modules_page, "Modules")

        eng_page = QWidget()
        eng_layout = QVBoxLayout(eng_page)
        eng_layout.setContentsMargins(0, 0, 0, 0)

        self._eng_tabs = QTabWidget()
        self._eng_tabs.setDocumentMode(True)
        self._scrolls: dict[str, RowScroll] = {}
        for key, label in _TABS:
            scroll = RowScroll()
            self._scrolls[key] = scroll
            self._eng_tabs.addTab(scroll, label)
        eng_layout.addWidget(self._eng_tabs, 1)
        self._tabs.addTab(eng_page, "Engineering")

        layout.addWidget(self._tabs, 1)

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
        state = self.core.state
        plugin = self.core._plugins.get("ship_health")
        self._refresh_modules(state, plugin)
        self._refresh_cargo()
        self._refresh_engineering()
        self._refresh_header(state)

    def _refresh_header(self, state) -> None:
        """Ship name / ident on the first row, hull type on the second.

        Rendered without parentheses: the type gets its own row rather than
        being bracketed onto the end of the name, which is how it read when
        this lived in the Commander header.
        """
        name  = (getattr(state, "ship_name", "")  or "").upper()
        ident = (getattr(state, "ship_ident", "") or "").upper()
        stype = (getattr(state, "pilot_ship", "") or "").upper()

        parts = [p for p in (name, ident, stype) if p]
        self._hdr1.set_text(" - ".join(parts) or "SHIP")

    def _refresh_modules(self, state, plugin) -> None:
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

        if not modules:
            self._scroll.set_rows([
                self.text("No loadout data yet — dock or jump to populate.", "dim")
            ])
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
            rows.append(self.kv(key, _fmt_health(health), cls))
        self._scroll.set_rows(rows)

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
        self._modules_hdr.set_title(text)

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

        # Limpets are consumables rather than freight — never sold, and their
        # count is what tells you whether the run can continue — so they sit
        # apart, below a blank line and immediately above the totals.
        limpets  = [x for x in enriched if _is_limpet(x["name"])]
        enriched = [x for x in enriched if not _is_limpet(x["name"])]

        # Cheapest per unit first.  With a full hold the question is what to
        # jettison, and that is answered by whatever is worth least per tonne.
        enriched.sort(key=lambda x: (x["price"], x["name"].lower()))

        # ── Render rows: qty  |  credits ─────────────────────────────────────
        # The ship's hold is one section and the SRV's is another; heading
        # each keeps them apart when both are carrying something.
        rows: list = [self.hdr("Ship"), self.rule()]
        total = 0

        for item in enriched:
            count  = item["count"]
            price  = item["price"]
            line   = price * count
            total += line
            name   = ("⚠ " if item["stolen"] else "") + item["name"]
            # Both columns fixed-width (qty right-justified to 4, price to 9) so
            # the whole value string is constant width.  The value labels render
            # in a monospace family, so a constant width puts the | in the same
            # column on every row.
            val_str = _cargo_cols(count, price, line)
            rows.append(self.kv(name, val_str))

        # ── Totals, lifted away from the manifest ────────────────────────────
        # Limpets last, just above the separator.
        if limpets:
            rows.append(self.kv("", ""))
        for item in limpets:
            count  = item["count"]
            line   = item["price"] * count
            total += line
            rows.append(self.kv(item["name"],
                                _cargo_cols(count, item["price"], line)))

        cr_total = _fmt_cr(total) if total else "—"
        rows.append(self.kv("", ""))          # blank spacer row
        rows.append(self.rule())              # visible separator line
        rows.append(self.kv("Totals", f"{cap_str:>10} | {'':>9} | {cr_total:>10}"))

        # ── SRV hold ─────────────────────────────────────────────────────────
        # Only while an SRV is out.  The journal reports a count for it and
        # never an inventory, so tonnage is all there is to show.
        if self._srv_deployed():
            srv_items = getattr(s, "srv_cargo_items", None) or {}
            srv_used  = int(getattr(s, "srv_cargo_count", 0) or 0)
            rows.append(self.kv("", ""))
            rows.append(self.hdr("SRV"))
            rows.append(self.rule())

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
                rows.append(self.kv(name, _cargo_cols(count, price, line)))

            if srv_items:
                rows.append(self.kv("Totals",
                                    _cargo_cols(srv_used, 0, srv_total)
                                    .replace(f"{_fmt_cr(0):>9}", f"{'':>9}")))
            else:
                rows.append(self.kv("Carrying", f"{srv_used:>5} t"))

        self._cargo_scroll.set_rows(rows)

    def _srv_deployed(self) -> bool:
        """True while the commander has an SRV out."""
        s = self.state
        return bool(getattr(s, "srv_type", "")
                    or str(getattr(s, "vessel_mode", "")).lower() == "srv")

    def _refresh_engineering(self) -> None:
        s = self.state
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
            scroll = self._scrolls.get(key)
            if scroll is None:
                continue

            if not items:
                scroll.set_rows([self.text("— none —", "dim")])
                continue

            sorted_items = sorted(
                items.items(),
                key=lambda kv: kv[1].get("name_local", kv[0]).lower()
            )

            # No totals row: the sum across a material grade is not a number
            # anyone acts on, and it cost a line at the top of every tab.
            rows: list = []
            for _, data in sorted_items:
                name = data.get("name_local", "")
                count = data.get("count", 0)
                rows.append(self.kv(name, str(count)))

            scroll.set_rows(rows)

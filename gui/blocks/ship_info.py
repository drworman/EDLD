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
from core.ui_helpers import (cargo_cols, cargo_manifest,
                             cargo_price_context, cargo_totals_cols,
                             fmt_cargo_cr, is_limpet, srv_tonnage)
from data.ships       import srv_cargo_capacity
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


# Re-exported from core.ui_helpers so both front ends and both holds share one
# set of column widths; imported from here by tests and by the rest of this
# module.
_fmt_cr     = fmt_cargo_cr
_cargo_cols = cargo_cols





# Re-exported from core.ui_helpers so the ship and SRV manifests share one
# definition; imported from here by tests and by the rest of this module.
_is_limpet = is_limpet


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
        # has_target_name drives the header label only: the station's name is
        # shown as soon as one is selected, but pricing waits for its market to
        # load.  That distinction lives in cargo_price_context() now, so the
        # two holds below cannot disagree about which market they are quoting.
        has_target_name = bool(tgt_name)

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
        # One price context for the whole panel, so every hold below is valued
        # against the same market the header names.
        price_ctx = cargo_price_context(s)
        enriched, limpets = cargo_manifest(items, price_ctx)

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
        rows.append(self.kv("Totals", cargo_totals_cols(cap_str, total)))

        # ── SRV hold ─────────────────────────────────────────────────────────
        # Only while an SRV is out.  The journal reports a count for it and
        # never an inventory, so tonnage is all there is to show.
        if self._srv_deployed():
            srv_items = getattr(s, "srv_cargo_items", None) or {}
            srv_used  = int(getattr(s, "srv_cargo_count", 0) or 0)
            rows.append(self.kv("", ""))
            rows.append(self.hdr("SRV"))
            rows.append(self.rule())

            # Same price context and the same ordering rules as the ship's
            # hold: a tonne is worth what the chosen market pays for it,
            # whichever vessel is carrying it.
            srv_freight, srv_limpets = cargo_manifest(srv_items, price_ctx)

            srv_total = 0
            for item in srv_freight:
                count  = item["count"]
                price  = item["price"]
                line   = price * count
                srv_total += line
                name   = ("⚠ " if item["stolen"] else "") + item["name"]
                rows.append(self.kv(name, _cargo_cols(count, price, line)))

            if srv_limpets:
                rows.append(self.kv("", ""))
            for item in srv_limpets:
                count  = item["count"]
                line   = item["price"] * count
                srv_total += line
                rows.append(self.kv(item["name"],
                                    _cargo_cols(count, item["price"], line)))

            # The journal never reports a surface vehicle's capacity, so the
            # denominator comes from a table and is omitted for vehicles whose
            # capacity is not established rather than guessed at.
            tonnage = srv_tonnage(srv_used,
                                  srv_cargo_capacity(getattr(s, "srv_type", "")))
            if srv_items:
                rows.append(self.kv("Totals", cargo_totals_cols(tonnage, srv_total)))
            else:
                # Count-only cargo event: tonnage is known, contents are not.
                rows.append(self.kv("Carrying", cargo_totals_cols(tonnage, 0)))

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

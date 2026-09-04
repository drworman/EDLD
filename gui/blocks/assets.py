"""gui/blocks/assets.py — Wallet, ships, modules, carrier, at-risk holdings (Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from gui.block_base import GuiBlock, RowScroll, _fmt_credits


class AssetsBlock(GuiBlock):
    BLOCK_TITLE = "ASSETS"

    def _build_body(self, layout) -> None:
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # ── Wallet ────────────────────────────────────────────────────────────
        self._wallet = RowScroll()
        self._w: dict[str, object] = {}

        def _row(key, wid):
            r = self.kv(key)
            self._w[wid] = r
            self._wallet.add_row(r)

        self._wallet.add_row(self.hdr("Currencies"))
        _row("Credits", "aw-credits")
        self._wallet.add_row(self.hdr("Fleet"))
        _row("Ships", "aw-ships")
        _row("Modules", "aw-modules")
        self._wallet.add_row(self.hdr("Fleet Carrier"))
        _row("Balance", "aw-carrier-balance")
        _row("Hull (decom.)", "aw-carrier-hull")
        _row("Market listings", "aw-carrier-cargo")
        self._wallet.add_row(self.hdr("Assets at Risk"))
        _row("Bounties", "aw-bounties")
        _row("Combat bonds", "aw-bonds")
        _row("Trade vouchers", "aw-trade")
        _row("Cartography (est.)", "aw-carto")
        _row("Exobiology (est.)", "aw-exobio")
        self._wallet.add_row(self.hdr("Net Worth"))
        _row("Total", "aw-networth")
        self._tabs.addTab(self._wallet, "Wallet")

        # ── Ships / Modules ───────────────────────────────────────────────────
        self._ships = RowScroll()
        self._tabs.addTab(self._ships, "Ships")
        self._modules = RowScroll()
        self._tabs.addTab(self._modules, "Modules")

        # ── Fleet Carrier ─────────────────────────────────────────────────────
        self._carrier = RowScroll()
        self._c: dict[str, object] = {}

        def _crow(key, wid):
            r = self.kv(key)
            self._c[wid] = r
            self._carrier.add_row(r)

        _crow("Name", "ac-name")
        _crow("Callsign", "ac-callsign")
        _crow("System", "ac-system")
        _crow("Fuel", "ac-fuel")
        self._carrier.add_row(self.hdr("Finance"))
        _crow("Balance", "ac-balance")
        _crow("Reserve", "ac-reserve")
        _crow("Upkeep/wk", "ac-upkeep")
        self._carrier.add_row(self.hdr("Cargo"))
        _crow("Stored", "ac-stored")
        _crow("Free", "ac-free")
        _crow("Market listings", "ac-inv-val")
        self._tabs.addTab(self._carrier, "Fleet Carrier")

        layout.addWidget(self._tabs, 1)

    def refresh_data(self) -> None:
        self._refresh_wallet()
        self._refresh_ships()
        self._refresh_modules()
        self._refresh_carrier()

    def _refresh_wallet(self) -> None:
        s       = self.state
        bal     = getattr(s, "assets_balance", None)
        current = getattr(s, "assets_current_ship",  None)
        stored  = list(getattr(s, "assets_stored_ships", []))
        cid     = (current or {}).get("ship_id")
        if cid:
            stored = [x for x in stored if x.get("ship_id") != cid]
        all_ships = ([current] if current else []) + stored
        ships_val = sum(x.get("value", 0) for x in all_ships if x)
        mods_val  = sum(m.get("value", 0)
                        for m in getattr(s, "assets_stored_modules", []))

        # Carrier rows — mirror the shared asset logic exactly
        carrier  = getattr(s, "assets_carrier", None)
        fc_mats  = getattr(s, "assets_fc_materials", None) or []
        carrier_cargo_val = sum(m.get("price", 0) * m.get("stock", 0) for m in fc_mats)
        if carrier:
            ctype = carrier.get("carrier_type", "FleetCarrier")
            carrier_hull_val = 24_850_000_000 if "Squadron" in ctype else 4_850_000_000
            self._kv("aw-carrier-balance", _fmt_credits(carrier.get("balance")) if carrier.get("balance") else "—")
            self._kv("aw-carrier-hull",    _fmt_credits(carrier_hull_val))
            self._kv("aw-carrier-cargo",   _fmt_credits(carrier_cargo_val) if carrier_cargo_val else "—")
        else:
            carrier_hull_val = 0
            self._kv("aw-carrier-balance", "—")
            self._kv("aw-carrier-hull",    "—")
            self._kv("aw-carrier-cargo",   "—")

        h = {
            "bounties": getattr(s, "holdings_bounties",    0),
            "bonds":    getattr(s, "holdings_bonds",       0),
            "trade":    getattr(s, "holdings_trade",       0),
            "carto":    getattr(s, "holdings_cartography", 0),
            "exobio":   getattr(s, "holdings_exobiology",  0),
        }
        risk_total = sum(h.values())

        self._kv("aw-credits",  _fmt_credits(bal))
        self._kv("aw-ships",    _fmt_credits(ships_val))
        self._kv("aw-modules",  _fmt_credits(mods_val))
        self._kv("aw-bounties", _fmt_credits(h["bounties"]))
        self._kv("aw-bonds",    _fmt_credits(h["bonds"]))
        self._kv("aw-trade",    _fmt_credits(h["trade"]))
        self._kv("aw-carto",    _fmt_credits(h["carto"]))
        self._kv("aw-exobio",   _fmt_credits(h["exobio"]))

        # Net worth: use Statistics-sourced total_wealth + extras if available
        total_wealth = getattr(s, "assets_total_wealth", None)
        if total_wealth is not None:
            nw = int(total_wealth) + carrier_cargo_val + risk_total + carrier_hull_val
        else:
            nw = (bal or 0) + ships_val + mods_val + carrier_hull_val + carrier_cargo_val + risk_total
        self._kv("aw-networth", _fmt_credits(nw) if nw else "—")

    def _refresh_ships(self) -> None:
        s       = self.state
        current = getattr(s, "assets_current_ship", None)
        stored  = list(getattr(s, "assets_stored_ships", []))
        cid     = (current or {}).get("ship_id")
        if cid:
            stored = [x for x in stored if x.get("ship_id") != cid]
        all_ships = ([current] if current else []) + stored

        if not all_ships:
            self._ships.set_rows([self.text("No ship data", "dim")])
            return

        rows: list = []
        for i, ship in enumerate(all_ships):
            if ship is None:
                continue
            name    = ship.get("type_display") or ship.get("type", "Unknown")
            ident   = ship.get("name", "")
            station = ship.get("station") or ""
            system  = ship.get("system")  or ""
            tag     = "[green]▶[/green] " if i == 0 else "  "
            label   = f"{tag}[bold]{name}[/bold]" + (f"  {ident}" if ident else "")
            if station and system and station != system:
                loc = f"{station}  ({system})"
            elif system:
                loc = system
            else:
                loc = "—"
            rows.append(self.kv(label, f"{loc}"))
        self._ships.set_rows(rows or [self.text("No ships", "dim")])

    def _refresh_modules(self) -> None:
        modules = getattr(self.state, "assets_stored_modules", [])
        if not modules:
            self._modules.set_rows([self.text("No stored modules", "dim")])
            return

        by_system: dict[str, list] = {}
        for m in modules:
            sys = m.get("system") or "Unknown"
            by_system.setdefault(sys, []).append(m)

        mod_rows: list = []
        for sys_name in sorted(by_system):
            mod_rows.append(self.hdr(sys_name))
            for m in sorted(by_system[sys_name],
                            key=lambda x: x.get("name_display", "").lower()):
                name = m.get("name_display") or m.get("name_internal", "Unknown")
                val  = m.get("value", 0)
                eng  = m.get("engineering", {})
                bp   = eng.get("BlueprintName", "")
                lv   = eng.get("Level")
                hot  = m.get("hot", False)
                hot_tag = "[red]⚠[/red] " if hot else ""
                eng_tag = f"  G{lv}" if (bp and lv) else ""
                key_str = f"{hot_tag}{name}{eng_tag}"
                mod_rows.append(self.kv(key_str, _fmt_credits(val)))
        self._modules.set_rows(mod_rows)

    def _refresh_carrier(self) -> None:
        carrier = getattr(self.state, "assets_carrier", None)
        if not carrier:
            for wid in ("ac-name", "ac-callsign", "ac-system", "ac-fuel",
                        "ac-balance", "ac-reserve", "ac-upkeep",
                        "ac-stored", "ac-free", "ac-inv-val"):
                self._ckv(wid, "—")
            return

        fuel = int(carrier.get("fuel", 0) or 0)
        self._ckv("ac-name",     carrier.get("name",     "—") or "—")
        self._ckv("ac-callsign", carrier.get("callsign", "—") or "—")
        self._ckv("ac-system",   carrier.get("system",   "—") or "—")
        self._ckv("ac-fuel",     f"{fuel}/1000  ({fuel // 10}%)")
        self._ckv("ac-balance",  _fmt_credits(carrier.get("balance")))
        self._ckv("ac-reserve",  _fmt_credits(carrier.get("reserve_balance")))
        self._ckv("ac-upkeep",   _fmt_credits(carrier.get("coreCost")))
        cap  = carrier.get("capacity", {})
        used = cap.get("cargo", 0)
        free = cap.get("freeSpace", 0)
        self._ckv("ac-stored", str(used) if (used or free) else "—")
        self._ckv("ac-free",   str(free) if (used or free) else "—")
        fc_mats = getattr(self.state, "assets_fc_materials", None) or []
        inv_val = sum(m.get("price", 0) * m.get("stock", 0) for m in fc_mats)
        self._ckv("ac-inv-val", _fmt_credits(inv_val) if inv_val else "—")

    def _kv(self, wid: str, text: str, classes: str = "val") -> None:
        row = self._w.get(wid)
        if row is not None:
            row.set_value(text, classes)

    def _ckv(self, wid: str, text: str, classes: str = "val") -> None:
        row = self._c.get(wid)
        if row is not None:
            row.set_value(text, classes)

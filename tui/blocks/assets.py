"""tui/blocks/assets.py — Wallet, ships, modules, carrier, at-risk holdings."""
from __future__ import annotations
from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane
from textual.containers import VerticalScroll
from tui.block_base     import TuiBlock, KVRow, SecHdr, _fmt_credits


class AssetsBlock(TuiBlock):
    BLOCK_TITLE = "ASSETS"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="assets-tabs"):

            with TabPane("Wallet", id="assets-tab-wallet"):
                with VerticalScroll():
                    yield SecHdr("Currencies")
                    yield KVRow("Credits",             id="aw-credits")
                    yield SecHdr("Fleet")
                    yield KVRow("Ships",               id="aw-ships")
                    yield KVRow("Modules",             id="aw-modules")
                    yield SecHdr("Fleet Carrier")
                    yield KVRow("Balance",          id="aw-carrier-balance")
                    yield KVRow("Hull (decom.)",    id="aw-carrier-hull")
                    yield KVRow("Market listings",  id="aw-carrier-cargo")
                    yield SecHdr("Assets at Risk")
                    yield KVRow("Bounties",            id="aw-bounties")
                    yield KVRow("Combat bonds",        id="aw-bonds")
                    yield KVRow("Trade vouchers",      id="aw-trade")
                    yield KVRow("Cartography (est.)",  id="aw-carto")
                    yield KVRow("Exobiology (est.)",   id="aw-exobio")
                    yield SecHdr("Net Worth")
                    yield KVRow("Total",               id="aw-networth")

            with TabPane("Ships", id="assets-tab-ships"):
                with VerticalScroll():
                    yield Label("—", id="assets-ships")

            with TabPane("Modules", id="assets-tab-modules"):
                with VerticalScroll():
                    yield Label("No stored modules", id="assets-modules")

            with TabPane("Fleet Carrier", id="assets-tab-carrier"):
                with VerticalScroll():
                    yield KVRow("Name",      id="ac-name")
                    yield KVRow("Callsign",  id="ac-callsign")
                    yield KVRow("System",    id="ac-system")
                    yield KVRow("Fuel",      id="ac-fuel")
                    yield SecHdr("Finance")
                    yield KVRow("Balance",   id="ac-balance")
                    yield KVRow("Reserve",   id="ac-reserve")
                    yield KVRow("Upkeep/wk", id="ac-upkeep")
                    yield SecHdr("Cargo")
                    yield KVRow("Stored",          id="ac-stored")
                    yield KVRow("Free",            id="ac-free")
                    yield KVRow("Market listings", id="ac-inv-val")

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
            self._lbl("assets-ships", "No ship data")
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
            rows.append(KVRow(label, f"{loc}"))
        if rows:
            try:
                scroll = self.query_one("#assets-tab-ships > VerticalScroll")
                scroll.remove_children()
                scroll.mount(*rows)
                return
            except Exception:
                pass
        self._lbl("assets-ships", "No ships")

    def _refresh_modules(self) -> None:
        modules = getattr(self.state, "assets_stored_modules", [])
        if not modules:
            self._lbl("assets-modules", "No stored modules")
            return

        by_system: dict[str, list] = {}
        for m in modules:
            sys = m.get("system") or "Unknown"
            by_system.setdefault(sys, []).append(m)

        try:
            scroll = self.query_one("#assets-tab-modules > VerticalScroll")
        except Exception:
            scroll = None
        mod_rows: list = []
        for sys_name in sorted(by_system):
            mod_rows.append(SecHdr(sys_name))
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
                mod_rows.append(KVRow(key_str, _fmt_credits(val)))
        if scroll is not None:
            scroll.remove_children()
            scroll.mount(*mod_rows)
        else:
            self._lbl("assets-modules", "No stored modules")

    def _refresh_carrier(self) -> None:
        carrier = getattr(self.state, "assets_carrier", None)
        if not carrier:
            for wid in ("ac-name", "ac-callsign", "ac-system", "ac-fuel",
                        "ac-balance", "ac-reserve", "ac-upkeep",
                        "ac-stored", "ac-free", "ac-inv-val"):
                self._kv(wid, "—")
            return

        fuel = int(carrier.get("fuel", 0) or 0)
        self._kv("ac-name",     carrier.get("name",     "—") or "—")
        self._kv("ac-callsign", carrier.get("callsign", "—") or "—")
        self._kv("ac-system",   carrier.get("system",   "—") or "—")
        self._kv("ac-fuel",     f"{fuel}/1000  ({fuel // 10}%)")
        self._kv("ac-balance",  _fmt_credits(carrier.get("balance")))
        self._kv("ac-reserve",  _fmt_credits(carrier.get("reserve_balance")))
        self._kv("ac-upkeep",   _fmt_credits(carrier.get("coreCost")))
        cap  = carrier.get("capacity", {})
        used = cap.get("cargo", 0)
        free = cap.get("freeSpace", 0)
        self._kv("ac-stored", str(used) if (used or free) else "—")
        self._kv("ac-free",   str(free) if (used or free) else "—")
        fc_mats = getattr(self.state, "assets_fc_materials", None) or []
        inv_val = sum(m.get("price", 0) * m.get("stock", 0) for m in fc_mats)
        self._kv("ac-inv-val", _fmt_credits(inv_val) if inv_val else "—")

    def _kv(self, wid: str, text: str, classes: str = "val") -> None:
        try:
            self.query_one(f"#{wid}", KVRow).set_value(text, classes)
        except Exception:
            pass

    def _lbl(self, wid: str, text: str) -> None:
        try:
            self.query_one(f"#{wid}", Label).update(text)
        except Exception:
            pass

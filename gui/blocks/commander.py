"""gui/blocks/commander.py — Commander / ship / location / vitals block (Qt)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTabWidget, QWidget,
)

from gui.block_base import GuiBlock, RowScroll, _health_cls
from gui.markup import to_html
from core.state import (
    CAPI_RANK_SKILLS, FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD,
)
from core.ui_helpers import carrier_display_sections, normalise_carrier
from gui.block_base import _fmt_credits

# ── Inline helpers (no UI-framework dependency) ───────────────────────────────

def fmt_shield(shields_up, recharging: bool) -> str:
    if shields_up is None: return "—"
    if shields_up:         return "Up"
    if recharging:         return "Recharging"
    return "Down"


def hull_css(pct: int) -> str:
    if pct > 75:  return "health-good"
    if pct >= 25: return "health-warn"
    return "health-crit"


def _pp_merits_for_rank(rank: int) -> int:
    if rank <= 1:   return 0
    if rank == 2:   return 2_000
    if rank == 3:   return 5_000
    if rank == 4:   return 9_000
    if rank == 5:   return 15_000
    if rank <= 100: return 15_000 + (rank - 5) * 8_000
    return 775_000 + (rank - 100) * 8_000


def pp_rank_progress(rank: int, total_merits: int) -> tuple:
    floor = _pp_merits_for_rank(rank)
    ceil  = _pp_merits_for_rank(rank + 1)
    span  = ceil - floor
    earned = max(0, total_merits - floor)
    fraction = min(1.0, earned / span) if span > 0 else 1.0
    return fraction, earned, span, rank + 1


class CommanderBlock(GuiBlock):
    BLOCK_TITLE = "COMMANDER"

    def _build_body(self, layout) -> None:
        self._hdr1 = QLabel()
        self._hdr1.setTextFormat(Qt.RichText)
        self._hdr1.setProperty("role", "hdrkey")
        self._hdr1.setContentsMargins(6, 0, 6, 0)
        self._hdr2 = QLabel()
        self._hdr2.setTextFormat(Qt.RichText)
        self._hdr2.setProperty("role", "hdrkey")
        self._hdr2.setContentsMargins(6, 0, 6, 0)
        layout.addWidget(self._hdr1)
        layout.addWidget(self._hdr2)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        info = RowScroll()
        self._r: dict[str, object] = {}

        def _row(key, wid):
            r = self.kv(key)
            self._r[wid] = r
            info.add_row(r)

        info.add_row(self.rule())
        _row("Mode", "kv-mode")
        _row("Home System", "kv-home")
        _row("Current System", "kv-system")
        _row("Location", "kv-body")
        info.add_row(self.rule())
        _row("Power", "kv-pp")
        _row("PP Rank", "kv-pprank")
        # Ship condition sits with the commander again: it is the first thing
        # looked at and the Info tab is the default view.
        info.add_row(self.rule())
        _row("Shields", "kv-shields")
        _row("Hull", "kv-hull")
        _row("Fuel", "kv-fuel")
        self._tabs.addTab(info, "Info")

        self._ranks = RowScroll()
        self._tabs.addTab(self._ranks, "Ranks")

        # ── Assets tabs ───────────────────────────────────────────────────
        # Absorbed from the former Assets window.  Everything about the
        # commander — who they are, what they have ranked, and what they own
        # — now lives behind one set of tabs instead of two windows competing
        # for the same grid space.
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
        # Rebuilt on every refresh rather than a fixed row set: which rows
        # apply depends on the carrier and on whether CAPI has polled, and
        # rendering absent data as a column of dashes reads like a bug.
        self._carrier = RowScroll()
        # Added on refresh only when a carrier is actually owned.
        self._carrier_added = False


        # Squadron carriers are rare, so this tab is only added when the
        # commander actually has one; an empty tab implying a carrier they do
        # not own would be worse than no tab.
        self._sqcarrier = RowScroll()
        self._sqcarrier_added = False

        layout.addWidget(self._tabs, 1)

        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(6, 2, 6, 2)
        fl.setSpacing(8)
        self._home_btn = QPushButton("Set Home")
        self._home_btn.setProperty("role", "link")
        self._home_btn.clicked.connect(self._on_set_home)
        self._home_lbl = QLabel()
        self._home_lbl.setProperty("role", "dim")
        self._home_lbl.setTextFormat(Qt.RichText)
        self._home_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fl.addWidget(self._home_btn, 0)
        fl.addWidget(self._home_lbl, 1)
        layout.addWidget(footer)

    # ── Footer: home search ───────────────────────────────────────────────────

    def _on_set_home(self) -> None:
        cmdr_plugin = self.core._plugins.get("commander")
        spansh      = self.core._plugins.get("spansh")
        if not spansh:
            return

        from gui.search_dialog import SearchDialog

        def _on_select(result: dict | None) -> None:
            if not result or not cmdr_plugin:
                return
            cmdr_plugin.set_home_location(
                result.get("name", ""),
                result.get("system", ""),
                result.get("star_pos"),
            )
            name = result.get("name", "")
            self._home_lbl.setText(to_html(f"→ {name}" if name else "",
                                           self.palette_map))
            self.refresh_data()

        dlg = SearchDialog(
            parent       = self.window(),
            title        = "Set Home Location",
            placeholder  = "System or station name…",
            search_fn    = spansh.search_home,
            result_label = lambda r: (
                f"{'🚉' if r.get('is_station') else '⭐'} {r['name']}"
                + (f"  {r.get('system', '')}" if r.get("is_station") else "")
            ),
            theme        = self.theme,
        )
        dlg.accepted_result.connect(_on_select)
        dlg.exec()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh_assets(self) -> None:
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
            carrier_hull_val = normalise_carrier(carrier)["hull_value"]
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
        rows = []
        for title, entries in carrier_display_sections(
            getattr(self.state, "assets_carrier", None),
            getattr(self.state, "assets_fc_materials", None),
            getattr(self.state, "assets_carrier_hold", None),
            getattr(self.state, "pilot_squadron_name", "") or "",
        ):
            rows.append(self.hdr(title))
            for label, value in entries:
                rows.append(self.kv(label, value))
        self._carrier.set_rows(rows)

    def _refresh_fuel(self, state) -> None:
        """Main-tank percentage, with endurance when the burn rate is known."""
        current = getattr(state, "fuel_current", None)
        tank    = getattr(state, "fuel_tank_size", None)
        if current is None or not tank or tank <= 0:
            self._kv("kv-fuel", "—", "val dim")
            return

        text = f"{current / tank * 100:.0f}%"
        burn = getattr(state, "fuel_burn_rate", None)
        if burn and burn > 0:
            secs = (current / burn) * 3600
            hours, mins = int(secs // 3600), int((secs % 3600) // 60)
            text += f"  (~{hours}h {mins}m)" if hours else f"  (~{mins}m)"

        if current < tank * FUEL_CRIT_THRESHOLD:
            cls = "val health-crit"
        elif current < tank * FUEL_WARN_THRESHOLD:
            cls = "val health-warn"
        else:
            cls = "val health-good"
        self._kv("kv-fuel", text, cls)


    # ── Hull ──────────────────────────────────────────────────────────────────

    def _refresh_hull(self, state) -> None:
        # ship_hull_exact carries full precision from Loadout/HullDamage;
        # ship_hull is the rounded integer the commander component keeps.
        exact = getattr(state, "ship_hull_exact", None)
        if exact is not None:
            text = _fmt_health(exact)
            pct = int(exact * 100)
        else:
            pct = getattr(state, "ship_hull", None)
            if pct is None:
                self._kv("kv-hull", "—", "val dim")
                return
            text = f"{pct}%"
        self._kv("kv-hull", text, f"val {_health_cls(pct)}")

    # ── Shields ───────────────────────────────────────────────────────────────

    def _refresh_shields(self, state) -> None:
        up = getattr(state, "ship_shields", None)
        recharging = getattr(state, "ship_shields_recharging", False)
        if up is None:
            self._kv("kv-shields", "—", "val dim")
        elif up:
            self._kv("kv-shields", "Up", "val health-good")
        elif recharging:
            self._kv("kv-shields", "Recharging", "val health-warn")
        else:
            self._kv("kv-shields", "Down", "val health-crit")

    # ── Modules ───────────────────────────────────────────────────────────────

    def _kv(self, wid: str, text: str, classes: str = "val") -> None:
        row = self._w.get(wid)
        if row is not None:
            row.set_value(text, classes)

    def _refresh_carrier_tab(self) -> None:
        """Add or remove the Carrier tab with ownership.

        An empty tab implying a carrier the commander does not own is worse
        than no tab; the squadron carrier already worked this way.
        """
        carrier = getattr(self.state, "assets_carrier", None)
        if not carrier:
            if self._carrier_added:
                index = self._tabs.indexOf(self._carrier)
                if index >= 0:
                    self._tabs.removeTab(index)
                self._carrier_added = False
            return
        if not self._carrier_added:
            self._tabs.insertTab(self._tabs.count(), self._carrier, "Carrier")
            self._carrier_added = True

    def _refresh_squadron_carrier(self) -> None:
        """Render the squadron carrier, adding or removing its tab.

        Uses exactly the same section builder as the fleet carrier, so the
        two tabs show the same fields from the same code path rather than a
        second, drifting implementation.
        """
        squadron = getattr(self.state, "assets_squadron_carrier", None)
        if not squadron:
            if self._sqcarrier_added:
                index = self._tabs.indexOf(self._sqcarrier)
                if index >= 0:
                    self._tabs.removeTab(index)
                self._sqcarrier_added = False
            return

        if not self._sqcarrier_added:
            self._tabs.addTab(self._sqcarrier, "S. Carrier")
            self._sqcarrier_added = True

        rows: list = []
        for title, entries in carrier_display_sections(
            squadron,
            getattr(self.state, "assets_squadron_fc_materials", None),
            getattr(self.state, "assets_squadron_carrier_hold", None),
            getattr(self.state, "pilot_squadron_name", "") or "",
        ):
            rows.append(self.hdr(title))
            for label, value in entries:
                rows.append(self.kv(label, value))
        self._sqcarrier.set_rows(rows)

    def refresh_data(self) -> None:
        s = self.state
        self._refresh_assets()
        self._refresh_carrier_tab()
        self._refresh_squadron_carrier()

        # ── Header ────────────────────────────────────────────────────────────
        # Line 1: CMDR <n> - <VESSEL> (<DETAIL>)
        # Line 2: <SQUADRON RANK> - <SQUADRON NAME> [<TAG>]
        vessel_mode  = getattr(s, "vessel_mode",  "ship")
        srv_type     = getattr(s, "srv_type",     "")
        suit_name    = getattr(s, "suit_name",    "")
        suit_loadout = getattr(s, "suit_loadout", "")
        name         = s.pilot_name or ""

        if name:
            if vessel_mode == "on_foot":
                suit_str   = suit_name.upper() if suit_name else "ON FOOT"
                detail_str = suit_loadout.upper() if suit_loadout else ""
                hdr1 = (f"CMDR {name} - {detail_str} ({suit_str})"
                        if detail_str else f"CMDR {name} - {suit_str}")
            elif vessel_mode == "srv":
                hdr1 = f"CMDR {name} - {srv_type.upper() or 'SRV'}"
            else:
                # In the ship: the vessel is described by the Ship Health
                # header, so only note it when the commander is somewhere
                # other than their own cockpit.
                hdr1 = f"CMDR {name}"
                if s.cmdr_in_slf:
                    hdr1 += " [IN FIGHTER]"
        else:
            hdr1 = "COMMANDER"

        # Line 2: squadron identity — reads the commander state fields.
        # The TUI escapes the opening bracket so Rich does not eat it; here
        # the tag is written plainly and the converter preserves it.
        sq_rank = getattr(s, "pilot_squadron_rank", "")
        sq_name = getattr(s, "pilot_squadron_name", "")
        sq_tag  = getattr(s, "pilot_squadron_tag",  "")
        if sq_name:
            tag_part  = f" [{sq_tag.upper()}]" if sq_tag else ""
            rank_part = f"{sq_rank.upper()} - " if sq_rank else ""
            hdr2 = f"{rank_part}{sq_name.upper()}{tag_part}"
        else:
            hdr2 = ""

        # The squadron tag renders as [SOL] and the fighter marker as
        # [IN FIGHTER]; the converter passes unrecognised bracketed tokens
        # through as literal text, so both survive intact.
        self._hdr1.setText(to_html(hdr1, self.palette_map))
        self._hdr2.setText(to_html(hdr2, self.palette_map))

        # ── Location ─────────────────────────────────────────────────────────
        self._kv("kv-mode", s.pilot_mode or "—")
        self._refresh_shields(s)
        self._refresh_hull(s)
        self._refresh_fuel(s)
        self._kv("kv-system", s.pilot_system or "—")

        # Home
        cmdr_plugin = self.core._plugins.get("commander") if self.core else None
        if cmdr_plugin:
            home = cmdr_plugin.get_home_location()
            if home:
                home_name = home["name"]
                home_sys  = home.get("system", home_name)
                is_stn    = home.get("is_station", home_name != home_sys and bool(home_sys))
                if is_stn and home_sys and home_sys != home_name:
                    display = f"{home_name}  ({home_sys})"
                else:
                    display = home_name
                dist = cmdr_plugin.home_distance_ly(getattr(s, "pilot_star_pos", None))
                if dist is not None:
                    display += f"  |  {dist:,.0f} ly"
                self._kv("kv-home", display)
                self._home_lbl.setText(
                    to_html(f"→ {home['name']}", self.palette_map))
            else:
                self._kv("kv-home", "unknown")
        else:
            self._kv("kv-home", "—")

        # Body
        if s.pilot_body:
            body_str = s.pilot_body
            if s.pilot_system and body_str.startswith(s.pilot_system):
                body_str = body_str[len(s.pilot_system):].lstrip()
            self._kv("kv-body", body_str or "—")
        else:
            self._kv("kv-body", "—")

        # ── Powerplay ─────────────────────────────────────────────────────────
        self._kv("kv-pp", s.pp_power or "—")
        if s.pp_rank:
            merits = s.pp_merits_total
            if merits is not None:
                frac, earned, span, nxt = pp_rank_progress(s.pp_rank, merits)
                self._kv("kv-pprank", f"Rank {s.pp_rank}  {int(frac*100)}%")
            else:
                self._kv("kv-pprank", f"Rank {s.pp_rank}")
        else:
            self._kv("kv-pprank", "—")

        # ── Ranks tab ─────────────────────────────────────────────────────────
        capi_ranks = getattr(s, "capi_ranks", None)
        capi_prog  = getattr(s, "capi_rank_progress", None) or {}
        if capi_ranks:
            rows: list = []
            for capi_key, display_lbl, table in CAPI_RANK_SKILLS:
                idx = capi_ranks.get(capi_key)
                if idx is None:
                    continue
                rank_name = table[idx] if 0 <= idx < len(table) else str(idx)
                prog = capi_prog.get(capi_key)
                val  = f"{rank_name}  +{prog}%" if prog is not None else rank_name
                rows.append(self.kv(display_lbl, val))
            self._ranks.set_rows(rows)
        else:
            self._ranks.set_rows([self.text("Awaiting CAPI data…", "dim")])

    def _kv(self, wid: str, text: str, classes: str = "val") -> None:
        row = self._r.get(wid)
        if row is not None:
            row.set_value(text, classes)

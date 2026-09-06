"""tui/blocks/commander.py — Commander / ship / location / vitals block."""
from __future__ import annotations
from textual.app     import ComposeResult
from textual.widgets import Label, TabbedContent, TabPane, Static
from textual.widget  import Widget
from textual.containers import VerticalScroll, Horizontal
from tui.block_base  import TuiBlock, KVRow, SepRow, SecHdr, _health_cls, _fmt_credits
# ── Inline helpers (no UI-framework dependency) ───────────────────────────────────────

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
from core.state      import (
    CAPI_RANK_SKILLS, FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD,
)
from core.ui_helpers import carrier_display_sections, normalise_carrier


def _fmt_health(fraction: float) -> str:
    """Render a 0.0-1.0 health fraction.

    Wear accumulates slowly, so a module at 99.2% would round to a flat "99%"
    and look identical to one at 98.6%.  One decimal place is kept below full
    health to keep that difference visible; a genuinely pristine module shows
    a clean "100%".
    """
    pct = max(0.0, min(1.0, fraction)) * 100
    if pct >= 99.95:
        return "100%"
    return f"{pct:.1f}%"


class CommanderBlock(TuiBlock):
    BLOCK_TITLE = "COMMANDER"

    def compose(self) -> ComposeResult:
        yield Label("", id="cmdr-hdr1", classes="block-title")
        yield Label("", id="cmdr-hdr2", classes="block-title")
        with TabbedContent(id="cmdr-tabs"):
            with TabPane("Info", id="tab-info"):
                with VerticalScroll():
                    yield KVRow("Mode",           id="kv-mode")
                    yield KVRow("Home System",    id="kv-home")
                    yield KVRow("Current System", id="kv-system")
                    yield KVRow("Location",       id="kv-body")
                    yield SepRow()
                    yield KVRow("Power",          id="kv-pp")
                    yield KVRow("PP Rank",        id="kv-pprank")
                    # Ship condition sits with the commander again: it is the
                    # first thing looked at and the Info tab is the default
                    # view, so it should not need a window change to see.
                    yield SepRow()
                    yield KVRow("Shields",        id="kv-shields")
                    yield KVRow("Hull",           id="kv-hull")
                    yield KVRow("Fuel",           id="kv-fuel")
            with TabPane("Ranks", id="tab-ranks"):
                with VerticalScroll(id="ranks-scroll"):
                    yield Label("Awaiting CAPI data…", id="ranks-placeholder", classes="dim")

            # ── Assets tabs ───────────────────────────────────────────────
            # Absorbed from the former Assets window.  Everything about the
            # commander — who they are, what they have ranked, and what they
            # own — now lives behind one set of tabs instead of two windows
            # competing for the same grid space.
            with TabPane("Wallet", id="tab-wallet"):
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

            with TabPane("Ships", id="tab-ships"):
                with VerticalScroll():
                    yield Label("—", id="assets-ships")

            with TabPane("Modules", id="tab-modules"):
                with VerticalScroll():
                    yield Label("No stored modules", id="assets-modules")

            with TabPane("Carrier", id="tab-carrier"):
                # Rebuilt on every refresh rather than a fixed row set: which
                # rows apply depends on the carrier and on whether CAPI has
                # polled, and rendering absent data as a column of dashes
                # reads like a bug.
                yield VerticalScroll(id="assets-carrier-scroll")

            # Squadron carriers are rare, so this pane is hidden unless the
            # commander actually has one; an empty tab implying a carrier
            # they do not own would be worse than no tab.
            with TabPane("S. Carrier", id="tab-sqcarrier"):
                yield VerticalScroll(id="assets-sqcarrier-scroll")
        with Horizontal(id="cmdr-footer"):
            yield Static(">> Set Home System", id="cmdr-home-btn", classes="footer-lbl")
            yield Label("", id="cmdr-home-lbl", classes="dim")

    def refresh_data(self) -> None:
        s = self.state
        self._refresh_wallet()
        self._refresh_ships()
        self._refresh_modules()
        self._refresh_carrier()
        self._refresh_squadron_carrier()

        # ── Header ────────────────────────────────────────────────────────────
        # Line 1: CMDR <NAME>, plus what they are currently in when it is not
        # the ship.  The ship's own name, ident and type moved to the Ship
        # Health header, so this line no longer restates them.
        # Line 2: <SQUADRON RANK> - <SQUADRON NAME> [<TAG>]
        # Both lines share the accent colour (section-hdr class).
        vessel_mode  = getattr(s, "vessel_mode",  "ship")
        srv_type     = getattr(s, "srv_type",     "")
        suit_name    = getattr(s, "suit_name",    "")
        suit_loadout = getattr(s, "suit_loadout", "")
        name         = s.pilot_name or ""

        if name:
            if vessel_mode == "on_foot":
                # CMDR NAME - XBIO (ARTEMIS SUIT)
                suit_str   = suit_name.upper() if suit_name else "ON FOOT"
                detail_str = suit_loadout.upper() if suit_loadout else ""
                hdr1 = (f"CMDR {name} - {detail_str} ({suit_str})"
                        if detail_str else f"CMDR {name} - {suit_str}")
            elif vessel_mode == "srv":
                # CMDR NAME - SRV  (no extra detail)
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

        # Line 2: squadron identity — reads the commander state fields
        sq_rank = getattr(s, "pilot_squadron_rank", "")
        sq_name = getattr(s, "pilot_squadron_name", "")
        sq_tag  = getattr(s, "pilot_squadron_tag",  "")
        if sq_name:
            tag_part  = r" \[" + sq_tag.upper() + "]" if sq_tag else ""
            rank_part = f"{sq_rank.upper()} - " if sq_rank else ""
            hdr2 = f"{rank_part}{sq_name.upper()}{tag_part}"
        else:
            hdr2 = ""

        self._set_label("cmdr-hdr1", hdr1)
        self._set_label("cmdr-hdr2", hdr2)

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
                try:
                    self.query_one("#cmdr-home-lbl", Label).update(
                        f"→ {home['name']}"
                    )
                except Exception:
                    pass
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
        try:
            scroll = self.query_one("#ranks-scroll")
            ph     = self.query_one("#ranks-placeholder", Label)
            if capi_ranks:
                ph.display = False
                # Clear previous dynamic rank rows
                for w in list(scroll.query(KVRow)):
                    w.remove()
                for capi_key, display_lbl, table in CAPI_RANK_SKILLS:
                    idx = capi_ranks.get(capi_key)
                    if idx is None:
                        continue
                    rank_name = table[idx] if 0 <= idx < len(table) else str(idx)
                    prog = capi_prog.get(capi_key)
                    val  = f"{rank_name}  +{prog}%" if prog is not None else rank_name
                    scroll.mount(KVRow(display_lbl, val))
            else:
                ph.display = True
        except Exception:
            pass

    # ── Footer: home search ───────────────────────────────────────────────────

    def on_click(self, event) -> None:
        if str(getattr(event.widget, "id", "")) != "cmdr-home-btn":
            return
        event.stop()
        cmdr_plugin = self.core._plugins.get("commander")
        spansh      = self.core._plugins.get("spansh")
        if not spansh:
            return

        def _on_select(result: dict | None) -> None:
            if not result or not cmdr_plugin:
                return
            cmdr_plugin.set_home_location(
                result.get("name", ""),
                result.get("system", ""),
                result.get("star_pos"),
            )
            name = result.get("name", "")
            try:
                self.query_one("#cmdr-home-lbl", Label).update(
                    f"→ {name}" if name else ""
                )
            except Exception:
                pass

        from tui.search_modal import SearchModal
        self.app.push_screen(SearchModal(
            title        = "Set Home Location",
            placeholder  = "System or station name…",
            search_fn    = spansh.search_home,
            result_label = lambda r: (
                f"{'🚉' if r.get('is_station') else '⭐'} {r['name']}"
                + (f"  {r.get('system', '')}" if r.get("is_station") else "")
            ),
            callback     = _on_select,
        ))

    # ── Internal helpers ──────────────────────────────────────────────────────

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
            self._label_text("assets-ships", "No ship data")
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
                scroll = self.query_one("#tab-ships VerticalScroll")
                scroll.remove_children()
                scroll.mount(*rows)
                return
            except Exception:
                pass
        self._label_text("assets-ships", "No ships")

    def _refresh_modules(self) -> None:
        modules = getattr(self.state, "assets_stored_modules", [])
        if not modules:
            self._label_text("assets-modules", "No stored modules")
            return

        by_system: dict[str, list] = {}
        for m in modules:
            sys = m.get("system") or "Unknown"
            by_system.setdefault(sys, []).append(m)

        try:
            scroll = self.query_one("#tab-modules VerticalScroll")
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
            self._label_text("assets-modules", "No stored modules")

    def _refresh_carrier(self) -> None:
        """Render the fleet carrier, or hide the tab when there is none.

        A commander who owns no carrier has no use for an empty tab implying
        one; the same rule already applied to the squadron carrier.
        """
        carrier = getattr(self.state, "assets_carrier", None)
        try:
            pane = self.query_one("#tab-carrier", TabPane)
        except Exception:
            pane = None
        if pane is not None:
            pane.display = bool(carrier)
        if not carrier:
            return
        self._render_carrier()

    def _render_carrier(self) -> None:
        try:
            scroll = self.query_one("#assets-carrier-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()

        rows: list = []
        for title, entries in carrier_display_sections(
            getattr(self.state, "assets_carrier", None),
            getattr(self.state, "assets_fc_materials", None),
            getattr(self.state, "assets_carrier_hold", None),
            getattr(self.state, "pilot_squadron_name", "") or "",
        ):
            rows.append(SecHdr(title))
            for label, value in entries:
                rows.append(KVRow(label, value))
        scroll.mount(*rows)

    def _refresh_squadron_carrier(self) -> None:
        """Render the squadron carrier, or hide the tab when there is none.

        Uses exactly the same section builder as the fleet carrier, so the
        two tabs show the same fields from the same code path rather than a
        second, drifting implementation.
        """
        squadron = getattr(self.state, "assets_squadron_carrier", None)
        try:
            pane = self.query_one("#tab-sqcarrier", TabPane)
        except Exception:
            return

        if not squadron:
            pane.display = False
            return
        pane.display = True

        try:
            scroll = self.query_one("#assets-sqcarrier-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()

        rows: list = []
        for title, entries in carrier_display_sections(
            squadron,
            getattr(self.state, "assets_squadron_fc_materials", None),
            getattr(self.state, "assets_squadron_carrier_hold", None),
            getattr(self.state, "pilot_squadron_name", "") or "",
        ):
            rows.append(SecHdr(title))
            for label, value in entries:
                rows.append(KVRow(label, value))
        scroll.mount(*rows)

    def _label_text(self, widget_id: str, text: str) -> None:
        """Set a plain Label's text (used by the lifted Assets renderers)."""
        try:
            self.query_one(f"#{widget_id}", Label).update(text)
        except Exception:
            pass

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
            pct  = int(exact * 100)
        else:
            pct = getattr(state, "ship_hull", None)
            if pct is None:
                self._kv("kv-hull", "—", "val dim")
                return
            text = f"{pct}%"
        self._kv("kv-hull", text, f"val {_health_cls(pct)}")

    # ── Shields ───────────────────────────────────────────────────────────────

    def _refresh_shields(self, state) -> None:
        up         = getattr(state, "ship_shields", None)
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

    def _kv(self, widget_id: str, text: str, classes: str = "val") -> None:
        try:
            self.query_one(f"#{widget_id}", KVRow).set_value(text, classes)
        except Exception:
            pass

    def _set_label(self, widget_id: str, text: str) -> None:
        try:
            self.query_one(f"#{widget_id}", Label).update(text)
        except Exception:
            pass

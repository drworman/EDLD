"""
tui/blocks/career.py — Career block (Textual).

Mirrors the GTK4 Career block: nine tabs in fixed order — Summary,
Combat, Explore, Exobio, Mining, Trade, Credits, Carrier, PPlay.

The Summary tab is session-scoped at the top and shows a live wealth
breakdown (Net worth, Liquid credits, Carrier bank) using the same
state attributes the Wallet/Assets block uses.  All other tabs are
lifetime activity sourced from the journal_history scan plus the most
recent in-game Statistics event.

The Credits tab carries the journal-derived earnings/spending ledger
introduced in v20260515.  In-game Statistics fields like
``Trading.Goods_Sold`` sit at zero for many commanders even after
hundreds of tonnes sold; journal events are authoritative.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane
from textual.containers import VerticalScroll

from tui.block_base     import TuiBlock, KVRow, SecHdr, _fmt, _fmt_credits


_ALL_TABS = [
    ("Summary", "car-tab-summary"),
    ("Combat",  "car-tab-combat"),
    ("Explore", "car-tab-explore"),
    ("Exobio",  "car-tab-exobio"),
    ("Mining",  "car-tab-mining"),
    ("Trade",   "car-tab-trade"),
    ("Credits", "car-tab-credits"),
    ("Carrier", "car-tab-carrier"),
    ("PPlay",   "car-tab-powerplay"),
]


def _fmt_distance(n) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M ly"
    if v >= 1_000:
        return f"{v:,.0f} ly"
    return f"{v:.2f} ly"


class CareerBlock(TuiBlock):
    BLOCK_TITLE = "CAREER"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="car-tabs"):
            for title, pane_id in _ALL_TABS:
                with TabPane(title, id=pane_id):
                    yield VerticalScroll(id=f"{pane_id}-scroll")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        # ── Summary tab — session activity + live wealth breakdown ────────────
        # Top: live wealth breakdown (Net worth / Liquid / Carrier bank),
        # same data sources as the Assets/Wallet block.  Bottom: current
        # session activity from session_providers (reset via Ctrl+R).
        state = getattr(self.core, "state", None)
        summary: list = []

        summary.extend(self._wealth_rows(state))

        providers = getattr(self.core, "session_providers", [])
        plugin    = self.core._plugins.get("session_stats")
        dur_s     = plugin.session_duration_seconds() if plugin else 0.0
        sess_rows: list = []
        if dur_s > 0:
            sess_rows.append(KVRow("Duration", self.fmt_duration(dur_s)))
        for p in sorted(providers,
                        key=lambda p: getattr(p, "ACTIVITY_TAB_TITLE", "")):
            try:
                if not p.has_activity():
                    continue
                rows = p.get_summary_rows()
            except Exception:
                continue
            kvrows = self._build_kv_rows(rows)
            if not kvrows:
                continue
            title = getattr(p, "ACTIVITY_TAB_TITLE", "")
            if title:
                sess_rows.append(SecHdr(title))
            sess_rows.extend(kvrows)
        if sess_rows:
            summary.append(SecHdr("Current session"))
            summary.extend(sess_rows)

        if not summary:
            summary.append(Label("[dim]No data yet[/dim]", classes="dim"))
        self._repopulate("car-tab-summary", summary)

        # ── Lifetime activity tabs ────────────────────────────────────────────
        hist = self.core._plugins.get("journal_history")
        if hist is None or not hist.scan_done.is_set():
            placeholder = Label("[dim]Lifetime scan in progress…[/dim]",
                                classes="dim")
            for _title, pane_id in _ALL_TABS:
                if pane_id == "car-tab-summary":
                    continue
                self._repopulate(pane_id, [placeholder])
            return

        r       = hist.results
        stats   = r.get("statistics", {})
        bank    = stats.get("Bank_Account", {})
        expl    = stats.get("Exploration",  {})
        exo     = stats.get("Exobiology",   {})
        cmb     = stats.get("Combat",       {})
        mine    = stats.get("Mining",       {})
        trd     = stats.get("Trading",      {})
        smg     = stats.get("Smuggling",    {})
        fc_stat = stats.get("FLEETCARRIER", {})
        career  = r.get("career",      {})
        combat  = r.get("combat",      {})
        carto   = r.get("cartography", {})
        exobio  = r.get("exobiology",  {})
        finance = r.get("finance",     {})
        carrier = r.get("carrier",     {})
        pp      = r.get("powerplay",   {})

        self._refresh_combat (cmb, bank, combat, finance)
        self._refresh_explore(expl, carto, career)
        self._refresh_exobio (exo, exobio)
        self._refresh_mining (mine)
        self._refresh_trade  (trd, smg, finance)
        self._refresh_credits(finance, carrier, state)
        self._refresh_carrier(carrier, fc_stat, state)
        self._refresh_pplay  (pp)

    # ── Wealth breakdown ──────────────────────────────────────────────────────

    def _wealth_rows(self, state) -> list:
        """Build the wealth breakdown shown at the top of the Summary tab.

        Liquid credits, ship+module value, and the carrier bank balance
        are all maintained on live state by the Assets plugin (CAPI +
        LoadGame + Commander + CarrierFinance events).  Those are the
        authoritative numbers — fresher than a one-shot journal scan.
        Statistics.Current_Wealth is the floor: if our computed sum is
        bigger (credits earned since the last Statistics event fired),
        the computed sum wins.
        """
        rows: list = []
        if state is None:
            return rows

        hist = self.core._plugins.get("journal_history")
        scan_results = hist.results if hist and hist.scan_done.is_set() else {}
        finance      = scan_results.get("finance",  {})
        carrier_scan = scan_results.get("carrier",  {})
        stats        = scan_results.get("statistics", {})
        bank         = stats.get("Bank_Account", {})

        live_bal = getattr(state, "assets_balance", None)
        liquid   = int(live_bal) if live_bal is not None else (
                   finance.get("liquid_credits", 0))

        cur = getattr(state, "assets_current_ship", None) or {}
        stored_ships   = getattr(state, "assets_stored_ships",   []) or []
        stored_modules = getattr(state, "assets_stored_modules", []) or []
        cur_id     = cur.get("ship_id")
        all_ships  = ([cur] if cur else []) + [
            s for s in stored_ships
            if isinstance(s, dict) and s.get("ship_id") != cur_id
        ]
        ships_val  = sum(s.get("value", 0) for s in all_ships if s)
        mods_val   = sum(m.get("value", 0) for m in stored_modules
                         if isinstance(m, dict))

        live_carrier = getattr(state, "assets_carrier", None) or {}
        cbank        = (live_carrier.get("balance")
                        or carrier_scan.get("bank_balance", 0)
                        or 0)

        risk = 0
        for attr in ("holdings_bounties", "holdings_bonds",
                     "holdings_trade",    "holdings_cartography",
                     "holdings_exobiology"):
            risk += getattr(state, attr, 0) or 0

        stat_wealth = bank.get("Current_Wealth", 0) or 0
        computed    = liquid + ships_val + mods_val + cbank + risk
        net_worth   = max(stat_wealth, computed)

        if net_worth or liquid or cbank:
            rows.append(SecHdr("Wealth"))
        if net_worth:
            rows.append(KVRow("Net worth", _fmt_credits(net_worth)))
        if liquid:
            rows.append(KVRow("  Liquid credits", _fmt_credits(liquid)))
        if cbank:
            rows.append(KVRow("  Carrier bank",   _fmt_credits(cbank)))
        return rows

    # ── Combat ────────────────────────────────────────────────────────────────

    def _refresh_combat(self, cmb, bank, combat, finance) -> None:
        rows = []
        kills = cmb.get("Bounties_Claimed", 0) or combat.get("kill_count", 0)
        if kills:
            rows.append(KVRow("Kills", _fmt(kills)))
        bp = _fmt_credits(cmb.get("Bounty_Hunting_Profit")
                          or combat.get("bounties_earned"))
        if bp != "—":
            rows.append(KVRow("Bounties earned", bp))
        cb = _fmt_credits(cmb.get("Combat_Bond_Profits")
                          or combat.get("bonds_earned"))
        if cb != "—":
            rows.append(KVRow("Combat bonds", cb))
        if cmb.get("Assassinations"):
            rows.append(KVRow("Assassinations", _fmt(cmb.get("Assassinations"))))
        if bank.get("Insurance_Claims"):
            rows.append(KVRow("Deaths", _fmt(bank.get("Insurance_Claims"))))
        if bank.get("Spent_On_Insurance"):
            rows.append(KVRow("Rebuy costs",
                              _fmt_credits(bank.get("Spent_On_Insurance"))))

        # Voucher status — issued vs redeemed.  Many bounties sit
        # unclaimed for ages until you station-hop.
        vouchers = finance.get("vouchers", {})
        bi = vouchers.get("bounty_issued",   0)
        br = vouchers.get("bounty_redeemed", 0)
        ki = vouchers.get("bonds_issued",    0)
        kr = vouchers.get("bonds_redeemed",  0)
        if bi or br or ki or kr:
            rows.append(SecHdr("Voucher status"))
            if bi:
                rows.append(KVRow("Bounties issued",   _fmt_credits(bi)))
                rows.append(KVRow("Bounties redeemed", _fmt_credits(br)))
                pending = max(bi - br, 0)
                if pending:
                    rows.append(KVRow("Bounties unredeemed",
                                      _fmt_credits(pending)))
            if ki:
                rows.append(KVRow("Bonds issued",      _fmt_credits(ki)))
                rows.append(KVRow("Bonds redeemed",    _fmt_credits(kr)))
                pending = max(ki - kr, 0)
                if pending:
                    rows.append(KVRow("Bonds unredeemed",
                                      _fmt_credits(pending)))

        if not rows:
            rows.append(Label("[dim]No combat activity logged[/dim]",
                              classes="dim"))
        self._repopulate("car-tab-combat", rows)

    # ── Explore ───────────────────────────────────────────────────────────────

    def _refresh_explore(self, expl, carto, career) -> None:
        # Journal-derived FSS/DSS counts are authoritative — the
        # Statistics Planets_Scanned_To_Level_2/3 fields are unreliable.
        fss = career.get("fss_scanned") or expl.get("Planets_Scanned_To_Level_2")
        dss = career.get("dss_mapped")  or expl.get("Planets_Scanned_To_Level_3")

        rows = [
            KVRow("Systems visited",  _fmt(expl.get("Systems_Visited"))),
            KVRow("Hyperspace jumps", _fmt(expl.get("Total_Hyperspace_Jumps"))),
            KVRow("Distance",
                  _fmt_distance(expl.get("Total_Hyperspace_Distance"))),
            KVRow("Planets FSS-scanned", _fmt(fss)),
            KVRow("Planets DSS-mapped",  _fmt(dss)),
            KVRow("First discoveries",
                  _fmt(career.get("first_discoveries"))),
            KVRow("First mapped",
                  _fmt(career.get("first_mapped"))),
            KVRow("Exploration profit",
                  _fmt_credits(expl.get("Exploration_Profits")
                               or carto.get("sold_total"))),
            KVRow("Highest payout",
                  _fmt_credits(expl.get("Highest_Payout"))),
        ]
        for key, label in (
            ("elw",           "Earth-likes"),
            ("water_world",   "Water worlds"),
            ("ammonia_world", "Ammonia worlds"),
            ("terraformable", "Terraformables"),
            ("neutron_star",  "Neutron stars"),
            ("black_hole",    "Black holes"),
        ):
            n = career.get(key)
            if n:
                rows.append(KVRow(label, _fmt(n)))
        self._repopulate("car-tab-explore", rows)

    # ── Exobiology ────────────────────────────────────────────────────────────

    def _refresh_exobio(self, exo, exobio) -> None:
        rows = [
            KVRow("Samples analysed",
                  _fmt(exo.get("Organic_Data") or exobio.get("sample_count"))),
            KVRow("Species encountered",
                  _fmt(exo.get("Organic_Species_Encountered"))),
            KVRow("Genera encountered",
                  _fmt(exo.get("Organic_Genus_Encountered"))),
            KVRow("Systems",  _fmt(exo.get("Organic_Systems"))),
            KVRow("Total sold",
                  _fmt_credits(exo.get("Organic_Data_Profits")
                               or exobio.get("sold_total"))),
            KVRow("First-logged",       _fmt(exo.get("First_Logged"))),
            KVRow("First-logged profit",
                  _fmt_credits(exo.get("First_Logged_Profits"))),
        ]
        by_genus = exobio.get("by_genus_value", {}) or exobio.get("by_genus", {})
        if by_genus:
            rows.append(SecHdr("Credits by genus"))
            for genus, val in list(by_genus.items())[:15]:
                rows.append(KVRow(genus, _fmt_credits(val)))
        self._repopulate("car-tab-exobio", rows)

    # ── Mining ────────────────────────────────────────────────────────────────

    def _refresh_mining(self, mine) -> None:
        qty    = mine.get("Quantity_Mined", 0)
        mats   = mine.get("Materials_Collected", 0)
        profit = mine.get("Mining_Profits", 0)
        rows = []
        if qty:
            rows.append(KVRow("Tonnes refined", f"{qty:,} t"))
        if mats:
            rows.append(KVRow("Materials collected", _fmt(mats)))
        if profit:
            rows.append(KVRow("Mining profit", _fmt_credits(profit)))
            if qty:
                rows.append(KVRow("Per tonne", _fmt_credits(profit / qty)))
        if not rows:
            rows.append(Label("[dim]No mining activity logged[/dim]",
                              classes="dim"))
        self._repopulate("car-tab-mining", rows)

    # ── Trade ─────────────────────────────────────────────────────────────────

    def _refresh_trade(self, trd, smg, finance) -> None:
        # Journal-derived figures are authoritative.  Statistics.Trading.
        # Goods_Sold sits at 0 for many commanders despite hundreds of
        # tonnes sold — max() preserves whichever is higher.
        ms = finance.get("market_sell", {})
        j_count   = ms.get("count",   0)
        j_revenue = ms.get("revenue", 0)
        j_profit  = ms.get("profit",  0)

        market_profit = max(trd.get("Market_Profits", 0), j_profit)
        markets       = trd.get("Markets_Traded_With", 0)
        resources     = max(trd.get("Resources_Traded", 0), j_count)
        highest       = trd.get("Highest_Single_Transaction", 0)
        avg           = trd.get("Average_Profit", 0)

        rows = []
        if markets:   rows.append(KVRow("Markets visited", _fmt(markets)))
        if resources: rows.append(KVRow("Tonnes sold",     f"{resources:,} t"))
        if j_revenue: rows.append(KVRow("Gross revenue",   _fmt_credits(j_revenue)))
        if market_profit:
            rows.append(KVRow("Net profit", _fmt_credits(market_profit)))
        if highest:
            rows.append(KVRow("Largest transaction", _fmt_credits(highest)))
        if avg:
            rows.append(KVRow("Average per trade", _fmt_credits(avg)))
        if resources and market_profit:
            rows.append(KVRow("Profit per tonne",
                              _fmt_credits(market_profit / resources)))

        smg_profit  = smg.get("Black_Markets_Profits", 0)
        smg_markets = smg.get("Black_Markets_Traded_With", 0)
        if smg_profit or smg_markets:
            rows.append(SecHdr("Black market"))
            if smg_markets:
                rows.append(KVRow("Black markets used", _fmt(smg_markets)))
            if smg_profit:
                rows.append(KVRow("Smuggling profit", _fmt_credits(smg_profit)))

        if not rows:
            rows.append(Label("[dim]No trade activity logged[/dim]",
                              classes="dim"))
        self._repopulate("car-tab-trade", rows)

    # ── Credits ───────────────────────────────────────────────────────────────

    def _refresh_credits(self, finance, carrier_scan, state) -> None:
        """Earnings & spending ledger + carrier-bank flow + voucher
        reconciliation.  Mirrors gui/blocks/career.py:_refresh_income.

        No journaled-vs-actual reconciliation row — earnings and spending
        from journals don't sum to net worth (pre-journal wealth and
        asset values muddy the equation) and showing a Reconciliation
        section only confused users.
        """
        f_in     = finance.get("in",  {}) or {}
        f_out    = finance.get("out", {}) or {}
        vouchers = finance.get("vouchers", {})

        rows: list = []
        if not f_in and not f_out:
            rows.append(Label("[dim]No financial events logged yet[/dim]",
                              classes="dim"))
            self._repopulate("car-tab-credits", rows)
            return

        total_in = sum(f_in.values())
        if f_in:
            rows.append(SecHdr("Lifetime earnings"))
            for k, v in f_in.items():
                pct = (f"  [dim]{v / total_in * 100:.1f}%[/dim]"
                       if total_in else "")
                rows.append(KVRow(k, f"{_fmt_credits(v)}{pct}"))
            rows.append(KVRow("[b]Total earnings[/b]",
                              f"[b]{_fmt_credits(total_in)}[/b]"))

        total_out = sum(f_out.values())
        if f_out:
            rows.append(SecHdr("Lifetime spending"))
            for k, v in f_out.items():
                pct = (f"  [dim]{v / total_out * 100:.1f}%[/dim]"
                       if total_out else "")
                rows.append(KVRow(k, f"{_fmt_credits(v)}{pct}"))
            rows.append(KVRow("[b]Total spending[/b]",
                              f"[b]{_fmt_credits(total_out)}[/b]"))

        # Carrier bank flow — live balance preferred.
        live_carrier = (getattr(state, "assets_carrier", None) or {}
                        if state else {})
        cbb = (live_carrier.get("balance")
               or carrier_scan.get("bank_balance", 0))
        cbr = carrier_scan.get("bank_reserve",     0)
        cba = carrier_scan.get("bank_available",   0)
        cbd = carrier_scan.get("bank_deposits",    0)
        cbw = carrier_scan.get("bank_withdrawals", 0)
        if cbb or cbd or cbw:
            rows.append(SecHdr("Carrier bank"))
            if cbb: rows.append(KVRow("Current balance",      _fmt_credits(cbb)))
            if cbr: rows.append(KVRow("Reserve (locked)",     _fmt_credits(cbr)))
            if cba: rows.append(KVRow("Available",            _fmt_credits(cba)))
            if cbd: rows.append(KVRow("Lifetime deposits",    _fmt_credits(cbd)))
            if cbw: rows.append(KVRow("Lifetime withdrawals", _fmt_credits(cbw)))

        # Voucher reconciliation.
        bi = vouchers.get("bounty_issued",   0)
        br = vouchers.get("bounty_redeemed", 0)
        ki = vouchers.get("bonds_issued",    0)
        kr = vouchers.get("bonds_redeemed",  0)
        if bi or br or ki or kr:
            rows.append(SecHdr("Voucher reconciliation"))
            if bi:
                rows.append(KVRow("Bounty vouchers issued",   _fmt_credits(bi)))
                rows.append(KVRow("Bounty vouchers redeemed", _fmt_credits(br)))
                pending = max(bi - br, 0)
                if pending:
                    rows.append(KVRow("Bounty vouchers unredeemed",
                                      _fmt_credits(pending)))
            if ki:
                rows.append(KVRow("Combat bonds issued",   _fmt_credits(ki)))
                rows.append(KVRow("Combat bonds redeemed", _fmt_credits(kr)))
                pending = max(ki - kr, 0)
                if pending:
                    rows.append(KVRow("Combat bonds unredeemed",
                                      _fmt_credits(pending)))

        self._repopulate("car-tab-credits", rows)

    # ── Carrier ───────────────────────────────────────────────────────────────

    def _refresh_carrier(self, carrier, fc_stat, state) -> None:
        if not carrier.get("stats") and not fc_stat:
            self._repopulate("car-tab-carrier",
                             [Label("[dim]No fleet carrier data[/dim]",
                                    classes="dim")])
            return

        rows: list = []
        cstats = carrier.get("stats", {}) or {}

        rows.append(SecHdr("Carrier"))
        if carrier.get("name"):
            rows.append(KVRow("Name", carrier.get("name")))
        if carrier.get("callsign"):
            rows.append(KVRow("Callsign", carrier.get("callsign")))
        ctype = carrier.get("type", "")
        if ctype:
            rows.append(KVRow(
                "Type",
                "Squadron carrier" if ctype.lower().startswith("squadron")
                else "Fleet carrier"))
        usage = cstats.get("SpaceUsage", {})
        if usage:
            used = usage.get("TotalCapacity", 0) - usage.get("FreeSpace", 0)
            rows.append(KVRow(
                "Capacity used",
                f"{used:,} / {usage.get('TotalCapacity', 0):,} t"))
        if carrier.get("fuel_level"):
            rows.append(KVRow("Tritium on board",
                              f"{int(carrier.get('fuel_level')):,} t"))
        if carrier.get("jump_range"):
            rows.append(KVRow("Current jump range",
                              _fmt_distance(carrier.get("jump_range"))))

        live_carrier = (getattr(state, "assets_carrier", None) or {}
                        if state else {})
        cbb = (live_carrier.get("balance")
               or carrier.get("bank_balance", 0))
        cbr = carrier.get("bank_reserve",     0)
        cba = carrier.get("bank_available",   0)
        cbd = carrier.get("bank_deposits",    0)
        cbw = carrier.get("bank_withdrawals", 0)
        if cbb or cbd or cbw:
            rows.append(SecHdr("Bank"))
            if cbb: rows.append(KVRow("Current balance",      _fmt_credits(cbb)))
            if cbr: rows.append(KVRow("Reserve (locked)",     _fmt_credits(cbr)))
            if cba: rows.append(KVRow("Available",            _fmt_credits(cba)))
            if cbd: rows.append(KVRow("Lifetime deposits",    _fmt_credits(cbd)))
            if cbw: rows.append(KVRow("Lifetime withdrawals", _fmt_credits(cbw)))

        jumps    = fc_stat.get("FLEETCARRIER_TOTAL_JUMPS") or 0
        distance = fc_stat.get("FLEETCARRIER_DISTANCE_TRAVELLED") or 0
        if jumps or distance:
            rows.append(SecHdr("Lifetime travel"))
            if jumps:    rows.append(KVRow("Total jumps", _fmt(jumps)))
            if distance: rows.append(KVRow("Total distance",
                                           _fmt_distance(distance)))
            if jumps and distance:
                rows.append(KVRow("Average jump",
                                  _fmt_distance(distance / jumps)))

        rearm   = fc_stat.get("FLEETCARRIER_REARM_TOTAL")   or 0
        refuel  = fc_stat.get("FLEETCARRIER_REFUEL_TOTAL")  or 0
        repairs = fc_stat.get("FLEETCARRIER_REPAIRS_TOTAL") or 0
        if rearm or refuel or repairs:
            rows.append(SecHdr("Services rendered"))
            if refuel:  rows.append(KVRow("Refuel services",  _fmt(refuel)))
            if rearm:   rows.append(KVRow("Rearm services",   _fmt(rearm)))
            if repairs: rows.append(KVRow("Repair services",  _fmt(repairs)))

        self._repopulate("car-tab-carrier", rows)

    # ── PowerPlay ─────────────────────────────────────────────────────────────

    def _refresh_pplay(self, pp) -> None:
        live_merits = getattr(self.core.state, "pp_merits_total", None)
        pp_total    = live_merits if live_merits else pp.get("total_merits", 0)
        pp_power    = getattr(self.core.state, "pp_power", None) or ""
        pp_rank     = getattr(self.core.state, "pp_rank", None)

        rows = []
        if pp_power:    rows.append(KVRow("Power", pp_power))
        if pp_rank is not None: rows.append(KVRow("Rank", str(pp_rank)))
        if pp_total:    rows.append(KVRow("Merits total", _fmt(pp_total)))

        by_act = pp.get("by_activity", {}) or {}
        if by_act:
            rows.append(SecHdr("Merits by activity"))
            for act, m in by_act.items():
                rows.append(KVRow(act, _fmt(m)))

        by_sys = pp.get("system_merits", {}) or pp.get("by_system", {})
        if by_sys:
            rows.append(SecHdr("Merits by system (top 20)"))
            sys_total = sum(by_sys.values())
            for sys_name, merits in list(by_sys.items())[:20]:
                pct = (f"  [dim]{merits / sys_total * 100:.0f}%[/dim]"
                       if sys_total else "")
                rows.append(KVRow(sys_name, f"{_fmt(merits)}{pct}"))

        if not rows:
            rows.append(Label("[dim]No PowerPlay activity[/dim]",
                              classes="dim"))
        self._repopulate("car-tab-powerplay", rows)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _repopulate(self, pane_id: str, rows: list) -> None:
        try:
            scroll = self.query_one(f"#{pane_id}-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        scroll.mount(*(rows or [Label("[dim]—[/dim]", classes="dim")]))

    def _build_kv_rows(self, raw_rows: list) -> list:
        """Convert provider summary rows (label/value/rate dicts) into KVRow
        widgets.  Plain-string section dividers (rows starting with "─")
        are skipped; SecHdr is used for grouping instead."""
        out: list = []
        for row in raw_rows:
            lbl  = row.get("label", "")
            val  = row.get("value", "—")
            rate = row.get("rate")
            if lbl.startswith("─"):
                continue
            out.append(KVRow(lbl, f"{val}  [dim]{rate}[/dim]" if rate else val))
        return out

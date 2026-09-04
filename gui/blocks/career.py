"""
gui/blocks/career.py — Career block (Qt).

Nine tabs in fixed order — Summary, Combat, Explore, Exobio, Mining, Trade,
Credits, Carrier, PPlay.

The Summary tab is a genuine career summary: it pulls the headline figures
from every other tab into one place — wealth, combat, exploration, exobiology,
mining, trade, missions, on-foot, PowerPlay, fleet carrier, and the top earning
and spending categories — so the tab answers "how is my career going" without
tabbing through the other eight.  It is built from
``core.summary_model.career_sections()``.

That model is shared with the Session window, which renders the same sections
in the same order at session scope.  All other tabs are lifetime activity
sourced from the journal_history scan plus the most recent in-game Statistics
event.

The Credits tab carries the journal-derived earnings/spending ledger.  In-game
Statistics fields like ``Trading.Goods_Sold`` sit at zero for many commanders
even after hundreds of tonnes sold; journal events are authoritative.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from gui.block_base import GuiBlock, RowScroll, _fmt, _fmt_credits
from core.summary_model import career_sections

_ALL_TABS = [
    ("Summary", "summary"),
    ("Combat",  "combat"),
    ("Explore", "explore"),
    ("Exobio",  "exobio"),
    ("Mining",  "mining"),
    ("Trade",   "trade"),
    ("Credits", "credits"),
    ("Carrier", "carrier"),
    ("PPlay",   "powerplay"),
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


def _fmt_pledged(iso_ts) -> str:
    """Render a pledge start as a date plus elapsed days."""
    if not iso_ts:
        return ""
    try:
        from datetime import datetime, timezone
        when = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    days = (datetime.now(timezone.utc) - when).days
    stamp = when.strftime("%Y-%m-%d")
    if days < 0:
        return stamp
    if days == 0:
        return f"{stamp}  (today)"
    if days == 1:
        return f"{stamp}  (1 day)"
    return f"{stamp}  ({days} days)"


class CareerBlock(GuiBlock):
    BLOCK_TITLE = "CAREER"

    def _build_body(self, layout) -> None:
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._panes: dict[str, RowScroll] = {}
        for title, key in _ALL_TABS:
            scroll = RowScroll()
            self._panes[key] = scroll
            self._tabs.addTab(scroll, title)
        layout.addWidget(self._tabs, 1)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        state = getattr(self.core, "state", None)

        self._refresh_summary()

        # ── Lifetime activity tabs ────────────────────────────────────────────
        hist = self.core._plugins.get("journal_history")
        if hist is None or not hist.scan_done.is_set():
            for _title, key in _ALL_TABS:
                if key == "summary":
                    continue
                self._repopulate(key, [self.text("Lifetime scan in progress…", "dim")])
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

    # ── Summary tab ───────────────────────────────────────────────────────────

    def _refresh_summary(self) -> None:
        """Render the career-scoped summary from the shared summary model."""
        try:
            sections = career_sections(self.core)
        except Exception:
            sections = []

        if not sections:
            hist = self.core._plugins.get("journal_history")
            msg = ("Lifetime scan in progress…"
                   if hist is not None and not hist.scan_done.is_set()
                   else "No career data yet")
            self._repopulate("summary", [self.text(msg, "dim")])
            return

        widgets: list = []
        for section in sections:
            widgets.append(self.hdr(section["title"]))
            for row in section["rows"]:
                if row["kind"] == "sub":
                    widgets.append(self.text(row["label"], "dim"))
                    continue
                value = row["value"]
                if row.get("rate"):
                    value = f"{value}  {row['rate']}"
                widgets.append(self.kv(row["label"], value))
        self._repopulate("summary", widgets)

    # ── Combat ────────────────────────────────────────────────────────────────

    def _refresh_combat(self, cmb, bank, combat, finance) -> None:
        rows = []
        kills = cmb.get("Bounties_Claimed", 0) or combat.get("kill_count", 0)
        if kills:
            rows.append(self.kv("Kills", _fmt(kills)))
        bp = _fmt_credits(cmb.get("Bounty_Hunting_Profit")
                          or combat.get("bounties_earned"))
        if bp != "—":
            rows.append(self.kv("Bounties earned", bp))
        cb = _fmt_credits(cmb.get("Combat_Bond_Profits")
                          or combat.get("bonds_earned"))
        if cb != "—":
            rows.append(self.kv("Combat bonds", cb))
        if cmb.get("Assassinations"):
            rows.append(self.kv("Assassinations", _fmt(cmb.get("Assassinations"))))
        if bank.get("Insurance_Claims"):
            rows.append(self.kv("Deaths", _fmt(bank.get("Insurance_Claims"))))
        if bank.get("Spent_On_Insurance"):
            rows.append(self.kv("Rebuy costs",
                                _fmt_credits(bank.get("Spent_On_Insurance"))))

        # Voucher status — issued vs redeemed.  Many bounties sit
        # unclaimed for ages until you station-hop.
        vouchers = finance.get("vouchers", {})
        bi = vouchers.get("bounty_issued",   0)
        br = vouchers.get("bounty_redeemed", 0)
        ki = vouchers.get("bonds_issued",    0)
        kr = vouchers.get("bonds_redeemed",  0)
        if bi or br or ki or kr:
            rows.append(self.hdr("Voucher status"))
            if bi:
                rows.append(self.kv("Bounties issued",   _fmt_credits(bi)))
                rows.append(self.kv("Bounties redeemed", _fmt_credits(br)))
                pending = max(bi - br, 0)
                if pending:
                    rows.append(self.kv("Bounties unredeemed", _fmt_credits(pending)))
            if ki:
                rows.append(self.kv("Bonds issued",      _fmt_credits(ki)))
                rows.append(self.kv("Bonds redeemed",    _fmt_credits(kr)))
                pending = max(ki - kr, 0)
                if pending:
                    rows.append(self.kv("Bonds unredeemed", _fmt_credits(pending)))

        if not rows:
            rows.append(self.text("No combat activity logged", "dim"))
        self._repopulate("combat", rows)

    # ── Explore ───────────────────────────────────────────────────────────────

    def _refresh_explore(self, expl, carto, career) -> None:
        # Journal-derived FSS/DSS counts are authoritative — the
        # Statistics Planets_Scanned_To_Level_2/3 fields are unreliable.
        fss = career.get("fss_scanned") or expl.get("Planets_Scanned_To_Level_2")
        dss = career.get("dss_mapped")  or expl.get("Planets_Scanned_To_Level_3")

        rows = [
            self.kv("Systems visited",  _fmt(expl.get("Systems_Visited"))),
            self.kv("Hyperspace jumps", _fmt(expl.get("Total_Hyperspace_Jumps"))),
            self.kv("Distance",
                    _fmt_distance(expl.get("Total_Hyperspace_Distance"))),
            self.kv("Planets FSS-scanned", _fmt(fss)),
            self.kv("Planets DSS-mapped",  _fmt(dss)),
            self.kv("First discoveries", _fmt(career.get("first_discoveries"))),
            self.kv("First mapped",      _fmt(career.get("first_mapped"))),
            self.kv("Exploration profit",
                    _fmt_credits(expl.get("Exploration_Profits")
                                 or carto.get("sold_total"))),
            self.kv("Highest payout", _fmt_credits(expl.get("Highest_Payout"))),
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
                rows.append(self.kv(label, _fmt(n)))
        self._repopulate("explore", rows)

    # ── Exobiology ────────────────────────────────────────────────────────────

    def _refresh_exobio(self, exo, exobio) -> None:
        rows = [
            self.kv("Samples analysed",
                    _fmt(exo.get("Organic_Data") or exobio.get("sample_count"))),
            self.kv("Species encountered", _fmt(exo.get("Organic_Species_Encountered"))),
            self.kv("Genera encountered",  _fmt(exo.get("Organic_Genus_Encountered"))),
            self.kv("Systems",  _fmt(exo.get("Organic_Systems"))),
            self.kv("Total sold",
                    _fmt_credits(exo.get("Organic_Data_Profits")
                                 or exobio.get("sold_total"))),
            self.kv("First-logged",       _fmt(exo.get("First_Logged"))),
            self.kv("First-logged profit", _fmt_credits(exo.get("First_Logged_Profits"))),
        ]
        by_genus = exobio.get("by_genus_value", {}) or exobio.get("by_genus", {})
        if by_genus:
            rows.append(self.hdr("Credits by genus"))
            for genus, val in list(by_genus.items())[:15]:
                rows.append(self.kv(genus, _fmt_credits(val)))
        self._repopulate("exobio", rows)

    # ── Mining ────────────────────────────────────────────────────────────────

    def _refresh_mining(self, mine) -> None:
        qty    = mine.get("Quantity_Mined", 0)
        mats   = mine.get("Materials_Collected", 0)
        profit = mine.get("Mining_Profits", 0)
        rows = []
        if qty:
            rows.append(self.kv("Tonnes refined", f"{qty:,} t"))
        if mats:
            rows.append(self.kv("Materials collected", _fmt(mats)))
        if profit:
            rows.append(self.kv("Mining profit", _fmt_credits(profit)))
            if qty:
                rows.append(self.kv("Per tonne", _fmt_credits(profit / qty)))
        if not rows:
            rows.append(self.text("No mining activity logged", "dim"))
        self._repopulate("mining", rows)

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
        if markets:   rows.append(self.kv("Markets visited", _fmt(markets)))
        if resources: rows.append(self.kv("Tonnes sold",     f"{resources:,} t"))
        if j_revenue: rows.append(self.kv("Gross revenue",   _fmt_credits(j_revenue)))
        if market_profit:
            rows.append(self.kv("Net profit", _fmt_credits(market_profit)))
        if highest:
            rows.append(self.kv("Largest transaction", _fmt_credits(highest)))
        if avg:
            rows.append(self.kv("Average per trade", _fmt_credits(avg)))
        if resources and market_profit:
            rows.append(self.kv("Profit per tonne",
                                _fmt_credits(market_profit / resources)))

        smg_profit  = smg.get("Black_Markets_Profits", 0)
        smg_markets = smg.get("Black_Markets_Traded_With", 0)
        if smg_profit or smg_markets:
            rows.append(self.hdr("Black market"))
            if smg_markets:
                rows.append(self.kv("Black markets used", _fmt(smg_markets)))
            if smg_profit:
                rows.append(self.kv("Smuggling profit", _fmt_credits(smg_profit)))

        if not rows:
            rows.append(self.text("No trade activity logged", "dim"))
        self._repopulate("trade", rows)

    # ── Credits ───────────────────────────────────────────────────────────────

    def _refresh_credits(self, finance, carrier_scan, state) -> None:
        """Earnings & spending ledger + carrier-bank flow + voucher
        reconciliation.

        No journaled-vs-actual reconciliation row — earnings and spending
        from journals don't sum to net worth (pre-journal wealth and asset
        values muddy the equation) and showing a Reconciliation section only
        confused users.
        """
        f_in     = finance.get("in",  {}) or {}
        f_out    = finance.get("out", {}) or {}
        vouchers = finance.get("vouchers", {})

        rows: list = []
        if not f_in and not f_out:
            rows.append(self.text("No financial events logged yet", "dim"))
            self._repopulate("credits", rows)
            return

        total_in = sum(f_in.values())
        if f_in:
            rows.append(self.hdr("Lifetime earnings"))
            for k, v in f_in.items():
                pct = (f"  {v / total_in * 100:.1f}%" if total_in else "")
                rows.append(self.kv(k, f"{_fmt_credits(v)}{pct}"))
            rows.append(self.kv("[b]Total earnings[/b]",
                                f"[b]{_fmt_credits(total_in)}[/b]"))

        total_out = sum(f_out.values())
        if f_out:
            rows.append(self.hdr("Lifetime spending"))
            for k, v in f_out.items():
                pct = (f"  {v / total_out * 100:.1f}%" if total_out else "")
                rows.append(self.kv(k, f"{_fmt_credits(v)}{pct}"))
            rows.append(self.kv("[b]Total spending[/b]",
                                f"[b]{_fmt_credits(total_out)}[/b]"))

        # Carrier bank flow — live balance preferred.
        live_carrier = (getattr(state, "assets_carrier", None) or {}
                        if state else {})
        cbb = (live_carrier.get("balance") or carrier_scan.get("bank_balance", 0))
        cbr = carrier_scan.get("bank_reserve",     0)
        cba = carrier_scan.get("bank_available",   0)
        cbd = carrier_scan.get("bank_deposits",    0)
        cbw = carrier_scan.get("bank_withdrawals", 0)
        if cbb or cbd or cbw:
            rows.append(self.hdr("Carrier bank"))
            if cbb: rows.append(self.kv("Current balance",      _fmt_credits(cbb)))
            if cbr: rows.append(self.kv("Reserve (locked)",     _fmt_credits(cbr)))
            if cba: rows.append(self.kv("Available",            _fmt_credits(cba)))
            if cbd: rows.append(self.kv("Lifetime deposits",    _fmt_credits(cbd)))
            if cbw: rows.append(self.kv("Lifetime withdrawals", _fmt_credits(cbw)))

        # Voucher reconciliation.
        bi = vouchers.get("bounty_issued",   0)
        br = vouchers.get("bounty_redeemed", 0)
        ki = vouchers.get("bonds_issued",    0)
        kr = vouchers.get("bonds_redeemed",  0)
        if bi or br or ki or kr:
            rows.append(self.hdr("Voucher reconciliation"))
            if bi:
                rows.append(self.kv("Bounty vouchers issued",   _fmt_credits(bi)))
                rows.append(self.kv("Bounty vouchers redeemed", _fmt_credits(br)))
                pending = max(bi - br, 0)
                if pending:
                    rows.append(self.kv("Bounty vouchers unredeemed",
                                        _fmt_credits(pending)))
            if ki:
                rows.append(self.kv("Combat bonds issued",   _fmt_credits(ki)))
                rows.append(self.kv("Combat bonds redeemed", _fmt_credits(kr)))
                pending = max(ki - kr, 0)
                if pending:
                    rows.append(self.kv("Combat bonds unredeemed",
                                        _fmt_credits(pending)))

        self._repopulate("credits", rows)

    # ── Carrier ───────────────────────────────────────────────────────────────

    def _refresh_carrier(self, carrier, fc_stat, state) -> None:
        if not carrier.get("stats") and not fc_stat:
            self._repopulate("carrier", [self.text("No fleet carrier data", "dim")])
            return

        rows: list = []
        cstats = carrier.get("stats", {}) or {}

        rows.append(self.hdr("Carrier"))
        if carrier.get("name"):
            rows.append(self.kv("Name", carrier.get("name")))
        if carrier.get("callsign"):
            rows.append(self.kv("Callsign", carrier.get("callsign")))
        ctype = carrier.get("type", "")
        if ctype:
            rows.append(self.kv(
                "Type",
                "Squadron carrier" if ctype.lower().startswith("squadron")
                else "Fleet carrier"))
        usage = cstats.get("SpaceUsage", {})
        if usage:
            used = usage.get("TotalCapacity", 0) - usage.get("FreeSpace", 0)
            rows.append(self.kv(
                "Capacity used",
                f"{used:,} / {usage.get('TotalCapacity', 0):,} t"))
        if carrier.get("fuel_level"):
            rows.append(self.kv("Tritium on board",
                                f"{int(carrier.get('fuel_level')):,} t"))
        if carrier.get("jump_range"):
            rows.append(self.kv("Current jump range",
                                _fmt_distance(carrier.get("jump_range"))))

        live_carrier = (getattr(state, "assets_carrier", None) or {}
                        if state else {})
        cbb = (live_carrier.get("balance") or carrier.get("bank_balance", 0))
        cbr = carrier.get("bank_reserve",     0)
        cba = carrier.get("bank_available",   0)
        cbd = carrier.get("bank_deposits",    0)
        cbw = carrier.get("bank_withdrawals", 0)
        if cbb or cbd or cbw:
            rows.append(self.hdr("Bank"))
            if cbb: rows.append(self.kv("Current balance",      _fmt_credits(cbb)))
            if cbr: rows.append(self.kv("Reserve (locked)",     _fmt_credits(cbr)))
            if cba: rows.append(self.kv("Available",            _fmt_credits(cba)))
            if cbd: rows.append(self.kv("Lifetime deposits",    _fmt_credits(cbd)))
            if cbw: rows.append(self.kv("Lifetime withdrawals", _fmt_credits(cbw)))

        jumps    = fc_stat.get("FLEETCARRIER_TOTAL_JUMPS") or 0
        distance = fc_stat.get("FLEETCARRIER_DISTANCE_TRAVELLED") or 0
        if jumps or distance:
            rows.append(self.hdr("Lifetime travel"))
            if jumps:    rows.append(self.kv("Total jumps", _fmt(jumps)))
            if distance: rows.append(self.kv("Total distance", _fmt_distance(distance)))
            if jumps and distance:
                rows.append(self.kv("Average jump", _fmt_distance(distance / jumps)))

        rearm   = fc_stat.get("FLEETCARRIER_REARM_TOTAL")   or 0
        refuel  = fc_stat.get("FLEETCARRIER_REFUEL_TOTAL")  or 0
        repairs = fc_stat.get("FLEETCARRIER_REPAIRS_TOTAL") or 0
        if rearm or refuel or repairs:
            rows.append(self.hdr("Services rendered"))
            if refuel:  rows.append(self.kv("Refuel services",  _fmt(refuel)))
            if rearm:   rows.append(self.kv("Rearm services",   _fmt(rearm)))
            if repairs: rows.append(self.kv("Repair services",  _fmt(repairs)))

        self._repopulate("carrier", rows)

    # ── PowerPlay ─────────────────────────────────────────────────────────────

    def _refresh_pplay(self, pp) -> None:
        """PowerPlay tab — scoped to the current pledge.

        Merits earned under a former allegiance are not shown.  They bought
        standing with a power the commander has since left and say nothing
        about where they stand now, so journal_history clears its merit
        accumulators at every pledge boundary and what arrives here belongs
        to one allegiance.

        Two measures coexist and are labelled separately because they count
        different things: the server's TotalMerits resets every cycle, while
        the journal tally runs from the pledge date.
        """
        live_merits = getattr(self.core.state, "pp_merits_total", None)
        cycle_total = live_merits if live_merits else pp.get("total_merits", 0)
        pp_power    = (getattr(self.core.state, "pp_power", None)
                       or pp.get("power") or "")
        pp_rank     = getattr(self.core.state, "pp_rank", None)

        rows = []
        if pp_power:
            rows.append(self.kv("Pledged to", pp_power))
            since = _fmt_pledged(pp.get("pledged_since"))
            if since:
                rows.append(self.kv("  Since", since))
        if pp_rank is not None:
            rows.append(self.kv("Rank", str(pp_rank)))
        if cycle_total:
            rows.append(self.kv("Merits this cycle", _fmt(cycle_total)))

        by_act  = {a: m for a, m in (pp.get("by_activity", {}) or {}).items() if m}
        pledge  = pp.get("pledge_merits", 0) or sum(by_act.values())
        if pledge:
            rows.append(self.kv("Merits this pledge", _fmt(pledge)))

        if by_act:
            rows.append(self.hdr("Merits by activity"))
            for act, m in by_act.items():
                pct = f"  {m / pledge * 100:.0f}%" if pledge else ""
                rows.append(self.kv(act, f"{_fmt(m)}{pct}"))

        by_sys = pp.get("system_merits", {}) or pp.get("by_system", {})
        by_sys = {s: m for s, m in by_sys.items() if m}
        if by_sys:
            rows.append(self.hdr("Merits by system (top 20)"))
            sys_total = sum(by_sys.values())
            for sys_name, merits in list(by_sys.items())[:20]:
                pct = (f"  {merits / sys_total * 100:.0f}%" if sys_total else "")
                rows.append(self.kv(sys_name, f"{_fmt(merits)}{pct}"))

        if not rows:
            rows.append(self.text("Not pledged to a power", "dim"))
        self._repopulate("powerplay", rows)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _repopulate(self, key: str, rows: list) -> None:
        scroll = self._panes.get(key)
        if scroll is None:
            return
        scroll.set_rows(rows or [self.text("—", "dim")])

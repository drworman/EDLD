"""tui/blocks/career.py — Career lifetime statistics block.

Mirrors the GTK4 career block exactly in terms of data fields, sections,
and ordering within each tab.  Tab labels are abbreviated to fit the TUI
tab bar width.
"""
from __future__ import annotations
from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane
from textual.containers import VerticalScroll
from tui.block_base     import TuiBlock, KVRow, SecHdr, _fmt, _fmt_credits


class CareerBlock(TuiBlock):
    BLOCK_TITLE = "CAREER"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="career-tabs"):
            with TabPane("Summary", id="career-pane-summary"):
                with VerticalScroll(id="career-summary-scroll"):
                    yield Label("[dim]Scanning journals…[/dim]",
                                id="career-summary-placeholder", classes="dim")

            with TabPane("Combat", id="career-pane-combat"):
                with VerticalScroll():
                    yield KVRow("Kills",           id="cc-kills")
                    yield KVRow("Bounties earned", id="cc-bounties")
                    yield KVRow("Combat bonds",    id="cc-bonds")
                    yield KVRow("Assassinations",  id="cc-assassinations")
                    yield KVRow("Deaths",          id="cc-deaths")
                    yield KVRow("Rebuy costs",     id="cc-rebuy")

            with TabPane("Explore", id="career-pane-expl"):
                with VerticalScroll():
                    yield KVRow("Systems visited",    id="ce-systems")
                    yield KVRow("Hyperspace jumps",   id="ce-jumps")
                    yield KVRow("Distance",           id="ce-dist")
                    yield KVRow("Planets FSS",        id="ce-fss")
                    yield KVRow("Planets DSS",        id="ce-dss")
                    yield KVRow("First footfalls",    id="ce-footfalls")
                    yield KVRow("Exploration profit", id="ce-carto")
                    yield KVRow("Highest payout",     id="ce-highest")

            with TabPane("Exobio", id="career-pane-exo"):
                with VerticalScroll():
                    yield KVRow("Samples analysed",    id="cex-samples")
                    yield KVRow("Species found",        id="cex-species")
                    yield KVRow("Genus found",          id="cex-genus")
                    yield KVRow("Systems",              id="cex-systems")
                    yield KVRow("Planets",              id="cex-planets")
                    yield KVRow("Total sold",           id="cex-sold")
                    yield KVRow("First logged",         id="cex-first-logged")
                    yield KVRow("First logged profits", id="cex-first-profit")

            with TabPane("Mine", id="career-pane-mining"):
                with VerticalScroll():
                    yield KVRow("Tonnes mined",  id="cm-qty")
                    yield KVRow("Mining profits",id="cm-profit")
                    yield KVRow("Materials",     id="cm-materials")

            with TabPane("Trade", id="career-pane-trade"):
                with VerticalScroll():
                    yield KVRow("Market profits",   id="ct-profit")
                    yield KVRow("Markets visited",  id="ct-markets")
                    yield KVRow("Resources traded", id="ct-resources")
                    yield KVRow("Mission income",   id="ct-mission")

            with TabPane("PPlay", id="career-pane-pp"):
                with VerticalScroll(id="career-pp-scroll"):
                    yield KVRow("Power",        id="cp-power")
                    yield KVRow("Rank",         id="cp-rank")
                    yield KVRow("Merits total", id="cp-merits")

    def refresh_data(self) -> None:
        hist = self.core._plugins.get("journal_history")
        if hist is None or not hist.scan_done.is_set():
            return

        r      = hist.results
        stats  = r.get("statistics", {})
        bank   = stats.get("Bank_Account", {})
        expl   = stats.get("Exploration",  {})
        exo    = stats.get("Exobiology",   {})
        cmb    = stats.get("Combat",       {})
        mine   = stats.get("Mining",       {})
        trd    = stats.get("Trading",      {})
        combat = r.get("combat",      {})
        income = r.get("income",      {})
        pp     = r.get("powerplay",   {})

        from core.emit import fmt_duration

        # ── Summary tab ───────────────────────────────────────────────────────
        try:
            scroll = self.query_one("#career-summary-scroll", VerticalScroll)
            scroll.remove_children()
            rows: list = []

            time_s = expl.get("Time_Played", 0)
            if time_s:
                rows.append(KVRow("Time played", fmt_duration(int(time_s))))

            kills = cmb.get("Bounties_Claimed", 0) or combat.get("kill_count", 0)
            bp    = cmb.get("Bounty_Hunting_Profit", 0)
            if kills or bp:
                rows.append(SecHdr("Combat"))
                rows.append(KVRow("Kills",    _fmt(kills)))
                rows.append(KVRow("Bounties", _fmt_credits(bp)))

            sys_vis = expl.get("Systems_Visited", 0)
            ep      = expl.get("Exploration_Profits", 0)
            if sys_vis or ep:
                rows.append(SecHdr("Exploration"))
                rows.append(KVRow("Systems",     _fmt(sys_vis)))
                rows.append(KVRow("Cartography", _fmt_credits(ep)))

            samples = exo.get("Organic_Data", 0)
            exo_p   = exo.get("Organic_Data_Profits", 0)
            if samples or exo_p:
                rows.append(SecHdr("Exobiology"))
                rows.append(KVRow("Samples", _fmt(samples)))
                rows.append(KVRow("Sold",    _fmt_credits(exo_p)))

            mined  = mine.get("Quantity_Mined", 0)
            mine_p = mine.get("Mining_Profits", 0)
            if mined or mine_p:
                rows.append(SecHdr("Mining"))
                rows.append(KVRow("Mined",  f"{_fmt(mined)} t" if mined else "—"))
                rows.append(KVRow("Profit", _fmt_credits(mine_p)))

            trd_p = trd.get("Market_Profits", 0)
            if trd_p:
                rows.append(SecHdr("Trade"))
                rows.append(KVRow("Profit",  _fmt_credits(trd_p)))
                rows.append(KVRow("Markets", _fmt(trd.get("Markets_Traded_With", 0))))

            live_merits = getattr(self.core.state, "pp_merits_total", None)
            pp_total    = live_merits if live_merits else pp.get("total_merits", 0)
            power       = getattr(self.core.state, "pp_power", None)
            if pp_total and power:
                rows.append(SecHdr("PowerPlay"))
                rows.append(KVRow("Merits", _fmt(pp_total)))

            if not rows:
                rows.append(Label("[dim]No career data[/dim]", classes="dim"))
            scroll.mount(*rows)
        except Exception:
            pass

        # ── Combat tab ────────────────────────────────────────────────────────
        kills = cmb.get("Bounties_Claimed", 0) or combat.get("kill_count", 0)
        self._kv("cc-kills",         _fmt(kills))
        self._kv("cc-bounties",      _fmt_credits(cmb.get("Bounty_Hunting_Profit")
                                                   or combat.get("bounties_earned")))
        self._kv("cc-bonds",         _fmt_credits(cmb.get("Combat_Bond_Profits")
                                                   or combat.get("bonds_earned")))
        self._kv("cc-assassinations",_fmt(cmb.get("Assassinations")))
        self._kv("cc-deaths",        _fmt(bank.get("Insurance_Claims") or 0))
        self._kv("cc-rebuy",         _fmt_credits(bank.get("Spent_On_Insurance")))

        # ── Exploration tab ───────────────────────────────────────────────────
        dist = expl.get("Total_Hyperspace_Distance", 0)
        self._kv("ce-systems",   _fmt(expl.get("Systems_Visited")))
        self._kv("ce-jumps",     _fmt(expl.get("Total_Hyperspace_Jumps")))
        self._kv("ce-dist",      f"{dist:,.0f} ly" if dist else "—")
        self._kv("ce-fss",       _fmt(expl.get("Planets_Scanned_To_Level_2")))
        self._kv("ce-dss",       _fmt(expl.get("Planets_Scanned_To_Level_3")))
        self._kv("ce-footfalls", _fmt(expl.get("First_Footfalls")))
        self._kv("ce-carto",     _fmt_credits(expl.get("Exploration_Profits")))
        self._kv("ce-highest",   _fmt_credits(expl.get("Highest_Payout")))

        # ── Exobiology tab ────────────────────────────────────────────────────
        self._kv("cex-samples",      _fmt(exo.get("Organic_Data")))
        self._kv("cex-species",      _fmt(exo.get("Organic_Species_Encountered")))
        self._kv("cex-genus",        _fmt(exo.get("Organic_Genus_Encountered")))
        self._kv("cex-systems",      _fmt(exo.get("Organic_Systems")))
        self._kv("cex-planets",      _fmt(exo.get("Organic_Planets")))
        self._kv("cex-sold",         _fmt_credits(exo.get("Organic_Data_Profits")))
        self._kv("cex-first-logged", _fmt(exo.get("First_Logged")))
        self._kv("cex-first-profit", _fmt_credits(exo.get("First_Logged_Profits")))

        # ── Mining tab ────────────────────────────────────────────────────────
        mined_qty = mine.get("Quantity_Mined", 0)
        self._kv("cm-qty",       f"{_fmt(mined_qty)} t" if mined_qty else "—")
        self._kv("cm-profit",    _fmt_credits(mine.get("Mining_Profits")))
        self._kv("cm-materials", _fmt(mine.get("Materials_Collected")))

        # ── Trade tab ─────────────────────────────────────────────────────────
        self._kv("ct-profit",    _fmt_credits(trd.get("Market_Profits")))
        self._kv("ct-markets",   _fmt(trd.get("Markets_Traded_With")))
        self._kv("ct-resources", _fmt(trd.get("Resources_Traded")))
        self._kv("ct-mission",   _fmt_credits(income.get("missions")))

        # ── PowerPlay tab ─────────────────────────────────────────────────────
        live_merits = getattr(self.core.state, "pp_merits_total", None)
        pp_total    = live_merits if live_merits else pp.get("total_merits", 0)
        pp_power    = getattr(self.core.state, "pp_power", None) or ""
        pp_rank     = getattr(self.core.state, "pp_rank", None)
        self._kv("cp-power",  pp_power or "—")
        self._kv("cp-rank",   str(pp_rank) if pp_rank is not None else "—")
        self._kv("cp-merits", _fmt(pp_total) if pp_total else "—")

        # By-system breakdown (dynamic rows appended after the fixed KVRows)
        by_sys = pp.get("by_system", {}) or pp.get("system_merits", {})
        if by_sys:
            try:
                scroll = self.query_one("#career-pp-scroll", VerticalScroll)
                # Remove any previously-appended dynamic rows
                for w in list(scroll.query(KVRow)):
                    if str(w.id or "").startswith("pp-sys-"):
                        w.remove()
                sys_total = sum(by_sys.values())
                for sys_name, merits in sorted(by_sys.items(), key=lambda x: -x[1])[:20]:
                    pct_str = f"{merits / sys_total * 100:.0f}%" if sys_total else ""
                    row = KVRow(sys_name, f"{_fmt(merits)}  {pct_str}")
                    row.id = f"pp-sys-{hash(sys_name) & 0xFFFF}"
                    scroll.mount(row)
            except Exception:
                pass

    def _kv(self, wid: str, text: str, classes: str = "val") -> None:
        try:
            self.query_one(f"#{wid}", KVRow).set_value(text, classes)
        except Exception:
            pass

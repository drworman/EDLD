"""
gui/blocks/career.py — Career statistics block.

Mirrors the Session Stats block structure exactly — same tab/grid layout,
same _append_rows rendering — but spans the commander's entire career
rather than the current session.

Summary tab: top-level lifetime figures drawn from the game's Statistics
event (authoritative Frontier server totals) plus journal-derived combat
and income figures.

Activity tabs (one per domain with career data):
  Combat      — kills, bounties, bonds, deaths
  Exploration — systems, jumps, planets, cartography
  Exobiology  — samples, species, sold value
  Mining      — quantity mined, profits
  Trade       — profits, markets
  PowerPlay   — current merits, by-system breakdown

Data source: JournalHistoryPlugin background scan.  Shows "Scanning…"
until the scan completes; refreshes on `career_update` gui_queue message.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget


def _fmt(n) -> str:
    if not n:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _fmt_cr(n) -> str:
    if not n:
        return "—"
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B cr"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M cr"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K cr"
    return f"{v} cr"


class CareerBlock(BlockWidget):
    BLOCK_TITLE = "Career"
    BLOCK_CSS   = "stats-block"

    DEFAULT_COL    = 8
    DEFAULT_ROW    = 34
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 16

    _TAB_SUMMARY = "Summary"

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)

        tab_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar.add_css_class("mat-tab-bar")
        self._tab_bar.set_hexpand(True)
        tab_row.append(self._tab_bar)
        body.append(tab_row)

        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        body.append(self._stack)

        self._tab_btns: dict[str, Gtk.Button] = {}
        self._active_tab: str = self._TAB_SUMMARY

        self._build_tab(self._TAB_SUMMARY)
        self._set_active_tab(self._TAB_SUMMARY)

    # ── Tab infrastructure (identical to session_stats) ───────────────────────

    def _build_tab(self, title: str) -> Gtk.Box:
        btn = Gtk.Button(label=title)
        btn.add_css_class("mat-tab-btn")
        btn.connect("clicked", lambda _b, t=title: self._set_active_tab(t))
        self._tab_bar.append(btn)
        self._tab_btns[title] = btn

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_margin_end(12)
        scroll  = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")
        scroll.set_child(content)
        self._stack.add_named(scroll, title)
        return content

    def _set_active_tab(self, title: str) -> None:
        self._active_tab = title
        self._stack.set_visible_child_name(title)
        for t, btn in self._tab_btns.items():
            if t == title:
                btn.add_css_class("mat-tab-active")
            else:
                btn.remove_css_class("mat-tab-active")

    def _get_or_create_tab(self, title: str) -> Gtk.Box:
        page = self._stack.get_child_by_name(title)
        if page is not None:
            vp = page.get_child()
            return vp.get_child() if hasattr(vp, "get_child") else vp
        return self._build_tab(title)

    def _clear_tab(self, title: str) -> Gtk.Box:
        page = self._stack.get_child_by_name(title)
        if page is not None:
            vp    = page.get_child()
            inner = vp.get_child() if hasattr(vp, "get_child") else vp
            child = inner.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                inner.remove(child)
                child = nxt
            return inner
        return self._get_or_create_tab(title)

    def _remove_stale_tabs(self, active_titles: set) -> None:
        to_remove = [t for t in self._tab_btns if t not in active_titles]
        for t in to_remove:
            btn = self._tab_btns.pop(t)
            self._tab_bar.remove(btn)
            page = self._stack.get_child_by_name(t)
            if page:
                self._stack.remove(page)
        if self._active_tab not in self._tab_btns:
            self._set_active_tab(self._TAB_SUMMARY)

    def _append_rows(self, grid: Gtk.Grid, rows: list[dict],
                     start_row: int = 0) -> int:
        """Identical to session_stats._append_rows."""
        row_idx = start_row
        for r in rows:
            label = r["label"]
            value = r.get("value", "")
            rate  = r.get("rate")

            if not value and not rate:
                sep = Gtk.Label(label=label)
                sep.add_css_class("data-key")
                sep.set_xalign(0.0)
                sep.set_margin_top(4)
                grid.attach(sep, 0, row_idx, 4, 1)
                row_idx += 1
                continue

            lbl = Gtk.Label(label=label)
            lbl.add_css_class("data-key")
            lbl.set_xalign(0.0)
            lbl.set_hexpand(True)
            grid.attach(lbl, 0, row_idx, 1, 1)

            if rate:
                val_lbl = Gtk.Label(label=value)
                val_lbl.add_css_class("data-value")
                val_lbl.set_xalign(1.0)
                grid.attach(val_lbl, 1, row_idx, 1, 1)

                pipe = Gtk.Label(label="|")
                pipe.add_css_class("data-key")
                pipe.set_xalign(0.5)
                grid.attach(pipe, 2, row_idx, 1, 1)

                rate_lbl = Gtk.Label(label=rate)
                rate_lbl.add_css_class("stat-line")
                rate_lbl.set_xalign(1.0)
                grid.attach(rate_lbl, 3, row_idx, 1, 1)
            else:
                val_lbl = Gtk.Label(label=value)
                val_lbl.add_css_class("data-value")
                val_lbl.set_xalign(1.0)
                grid.attach(val_lbl, 1, row_idx, 3, 1)

            row_idx += 1
        return row_idx

    def _section_header_in_grid(self, grid: Gtk.Grid, title: str,
                                 row_idx: int) -> int:
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_top(6)
        hbox.set_margin_bottom(2)
        lbl = Gtk.Label(label=title)
        lbl.add_css_class("section-header")
        lbl.set_xalign(0.0)
        hbox.append(lbl)
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_hexpand(True)
        sep.set_valign(Gtk.Align.CENTER)
        hbox.append(sep)
        grid.attach(hbox, 0, row_idx, 4, 1)
        return row_idx + 1

    def _new_grid(self) -> Gtk.Grid:
        g = Gtk.Grid()
        g.set_column_spacing(4)
        g.set_row_spacing(1)
        g.add_css_class("stats-grid")
        return g

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _rows_for(self, title: str, r: dict, stats: dict) -> list[dict]:
        """Return tab rows for a given career domain."""
        expl = stats.get("Exploration", {})
        exo  = stats.get("Exobiology", {})
        bank = stats.get("Bank_Account", {})
        cmb  = stats.get("Combat", {})
        mine = stats.get("Mining", {})
        trd  = stats.get("Trading", {})

        combat  = r.get("combat",     {})
        carto   = r.get("cartography",{})
        exobio  = r.get("exobiology", {})
        pp      = r.get("powerplay",  {})
        income  = r.get("income",     {})

        if title == "Combat":
            kills = cmb.get("Bounties_Claimed", 0) or combat.get("kill_count", 0)
            rows = [
                {"label": "Kills",           "value": _fmt(kills)},
                {"label": "Bounties earned", "value": _fmt_cr(cmb.get("Bounty_Hunting_Profit") or combat.get("bounties_earned"))},
                {"label": "Combat bonds",    "value": _fmt_cr(cmb.get("Combat_Bond_Profits") or combat.get("bonds_earned"))},
                {"label": "Assassinations",  "value": _fmt(cmb.get("Assassinations"))},
                {"label": "Deaths",          "value": _fmt(bank.get("Insurance_Claims") or 0)},
                {"label": "Rebuy costs",     "value": _fmt_cr(bank.get("Spent_On_Insurance"))},
            ]
            return [r for r in rows if r["value"] != "—"]

        elif title == "Exploration":
            return [
                {"label": "Systems visited",    "value": _fmt(expl.get("Systems_Visited"))},
                {"label": "Hyperspace jumps",   "value": _fmt(expl.get("Total_Hyperspace_Jumps"))},
                {"label": "Distance",           "value": f"{expl.get('Total_Hyperspace_Distance', 0):,.0f} ly"},
                {"label": "Planets FSS",        "value": _fmt(expl.get("Planets_Scanned_To_Level_2"))},
                {"label": "Planets DSS",        "value": _fmt(expl.get("Planets_Scanned_To_Level_3"))},
                {"label": "First footfalls",    "value": _fmt(expl.get("First_Footfalls"))},
                {"label": "Exploration profit", "value": _fmt_cr(expl.get("Exploration_Profits"))},
                {"label": "Highest payout",     "value": _fmt_cr(expl.get("Highest_Payout"))},
            ]

        elif title == "Exobiology":
            return [
                {"label": "Samples analysed",   "value": _fmt(exo.get("Organic_Data"))},
                {"label": "Species found",       "value": _fmt(exo.get("Organic_Species_Encountered"))},
                {"label": "Genus found",         "value": _fmt(exo.get("Organic_Genus_Encountered"))},
                {"label": "Systems",             "value": _fmt(exo.get("Organic_Systems"))},
                {"label": "Planets",             "value": _fmt(exo.get("Organic_Planets"))},
                {"label": "Total sold",          "value": _fmt_cr(exo.get("Organic_Data_Profits"))},
                {"label": "First logged",        "value": _fmt(exo.get("First_Logged"))},
                {"label": "First logged profits","value": _fmt_cr(exo.get("First_Logged_Profits"))},
            ]

        elif title == "Mining":
            return [
                {"label": "Tonnes mined",   "value": _fmt(mine.get("Quantity_Mined"))},
                {"label": "Mining profits", "value": _fmt_cr(mine.get("Mining_Profits"))},
                {"label": "Materials",      "value": _fmt(mine.get("Materials_Collected"))},
            ]

        elif title == "Trade":
            return [
                {"label": "Market profits", "value": _fmt_cr(trd.get("Market_Profits"))},
                {"label": "Markets visited","value": _fmt(trd.get("Markets_Traded_With"))},
                {"label": "Resources",      "value": _fmt(trd.get("Resources_Traded"))},
                {"label": "Mission income", "value": _fmt_cr(income.get("missions"))},
            ]

        elif title == "PowerPlay":
            live_total = getattr(self.core.state, "pp_merits_total", None)
            pp_total   = live_total if live_total else pp.get("total_merits", 0)
            power  = getattr(self.core.state, "pp_power", None) or ""
            rank   = getattr(self.core.state, "pp_rank", None)
            rows = []
            if power:
                rows.append({"label": "Power", "value": power})
            if rank is not None:
                rows.append({"label": "Rank",  "value": str(rank)})
            rows.append({"label": "Total merits", "value": _fmt(pp_total)})
            rows.append({"label": "─── By system ───", "value": "", "rate": None})
            sys_merits  = pp.get("system_merits", {})
            sys_total   = sum(sys_merits.values())
            for system, merits in list(sys_merits.items())[:20]:
                pct = f"{merits / sys_total * 100:.0f}%" if sys_total else ""
                rows.append({"label": f"  {system}", "value": _fmt(merits), "rate": pct})
            return rows

        return []

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        hist = self.core._plugins.get("journal_history")

        # ── Summary tab ───────────────────────────────────────────────────────
        summary_box  = self._clear_tab(self._TAB_SUMMARY)
        summary_grid = self._new_grid()
        summary_box.append(summary_grid)
        grid_row = 0

        if hist is None or not hist.scan_done.is_set():
            loading = Gtk.Label(label="Scanning journals…")
            loading.add_css_class("data-value")
            summary_box.append(loading)
            return

        r     = hist.results
        stats = r.get("statistics", {})
        expl  = stats.get("Exploration", {})
        exo   = stats.get("Exobiology", {})
        cmb   = stats.get("Combat", {})
        bank  = stats.get("Bank_Account", {})
        mine  = stats.get("Mining", {})
        trd   = stats.get("Trading", {})
        pp    = r.get("powerplay", {})

        # Time played
        time_s = expl.get("Time_Played", 0)
        if time_s:
            grid_row = self._append_rows(summary_grid, [{
                "label": "Time played",
                "value": self.fmt_duration(time_s),
                "rate":  None,
            }], start_row=grid_row)

        # Combat summary
        kills = cmb.get("Bounties_Claimed", 0)
        bounty_profit = cmb.get("Bounty_Hunting_Profit", 0)
        if kills or bounty_profit:
            grid_row = self._section_header_in_grid(summary_grid, "Combat", grid_row)
            grid_row = self._append_rows(summary_grid, [
                {"label": "Kills",    "value": _fmt(kills),          "rate": _fmt_cr(bounty_profit)},
            ], start_row=grid_row)

        # Exploration summary
        systems = expl.get("Systems_Visited", 0)
        expl_profit = expl.get("Exploration_Profits", 0)
        if systems or expl_profit:
            grid_row = self._section_header_in_grid(summary_grid, "Exploration", grid_row)
            grid_row = self._append_rows(summary_grid, [
                {"label": "Systems",  "value": _fmt(systems),        "rate": _fmt_cr(expl_profit)},
                {"label": "Planets DSS", "value": _fmt(expl.get("Planets_Scanned_To_Level_3")), "rate": None},
            ], start_row=grid_row)

        # Exobiology summary
        samples = exo.get("Organic_Data", 0)
        exo_profit = exo.get("Organic_Data_Profits", 0)
        if samples or exo_profit:
            grid_row = self._section_header_in_grid(summary_grid, "Exobiology", grid_row)
            grid_row = self._append_rows(summary_grid, [
                {"label": "Samples",  "value": _fmt(samples),        "rate": _fmt_cr(exo_profit)},
            ], start_row=grid_row)

        # Mining summary
        mined = mine.get("Quantity_Mined", 0)
        mine_profit = mine.get("Mining_Profits", 0)
        if mined or mine_profit:
            grid_row = self._section_header_in_grid(summary_grid, "Mining", grid_row)
            grid_row = self._append_rows(summary_grid, [
                {"label": "Mined",    "value": f"{_fmt(mined)} t",   "rate": _fmt_cr(mine_profit)},
            ], start_row=grid_row)

        # Trade summary
        trd_profit = trd.get("Market_Profits", 0)
        if trd_profit:
            grid_row = self._section_header_in_grid(summary_grid, "Trade", grid_row)
            grid_row = self._append_rows(summary_grid, [
                {"label": "Profit",   "value": _fmt_cr(trd_profit),  "rate": None},
            ], start_row=grid_row)

        # PowerPlay summary
        live_total = getattr(self.core.state, "pp_merits_total", None)
        pp_total   = live_total if live_total else pp.get("total_merits", 0)
        power      = getattr(self.core.state, "pp_power", None)
        if pp_total and power:
            grid_row = self._section_header_in_grid(summary_grid, "PowerPlay", grid_row)
            grid_row = self._append_rows(summary_grid, [
                {"label": "Merits",   "value": _fmt(pp_total),       "rate": None},
            ], start_row=grid_row)

        # ── Activity tabs ─────────────────────────────────────────────────────
        # Only show tabs that have non-trivial data
        tab_defs = [
            ("Combat",      bool(cmb.get("Bounties_Claimed"))),
            ("Exploration", bool(expl.get("Systems_Visited"))),
            ("Exobiology",  bool(exo.get("Organic_Data"))),
            ("Mining",      bool(mine.get("Quantity_Mined"))),
            ("Trade",       bool(trd.get("Market_Profits"))),
            ("PowerPlay",   bool(pp_total)),
        ]

        active_titles = {self._TAB_SUMMARY}
        for title, has_data in tab_defs:
            if not has_data:
                continue
            rows = self._rows_for(title, r, stats)
            if not rows:
                continue
            active_titles.add(title)
            tab_box  = self._clear_tab(title)
            tab_grid = self._new_grid()
            tab_box.append(tab_grid)
            self._append_rows(tab_grid, rows, start_row=0)

        self._remove_stale_tabs(active_titles)

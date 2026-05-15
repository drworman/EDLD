"""
gui/blocks/career.py — Career block.

Tab structure (compact labels to fit in width=11 columns):

  Summary   lifetime career highlights, pulling the headline figure from
            every other tab — plus a "Current Session" section at the top
            so live session activity has a home (the standalone Session
            Stats block was retired)
  Combat    lifetime combat: kills, bounties, bonds, assassinations,
            deaths/rebuy — every row tooltipped with what it counts
  Explore   lifetime exploration: systems, jumps, distance, FSS/DSS,
            greatest-distance-from-start, profit + highest payout
  Exobio    lifetime exobiology: samples, species/genus, total credits,
            per-genus credit breakdown, first-discovery bonuses
  Mining    lifetime mining: quantity, profit, materials, ratio
  Trade     lifetime trade: profit, markets, resources, largest single
  Income    lifetime credits by source — every standard source listed
            even at zero so nothing looks "missing"
  Carrier   fleet carrier: identity, jumps/distance, services rendered,
            trade — ambiguous Statistics fields are labelled plainly and
            tooltipped, not dressed up as things they aren't
  PPlay     PowerPlay: Pledge -> By Activity -> By System

Reset button (↺) sits next to the tab bar and calls
``session_stats.on_new_session(0)``.

Tab styling uses the project's standard `mat-tab-bar` / `mat-tab-btn` /
`mat-tab-active` / `mat-tab-label` classes so the accent-coloured
underline indicator matches Assets, Commander, etc.
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
    """Credits with magnitude suffix.  Returns '0 cr' (not '—') for an
    explicit zero so the Income tab can show every source unconditionally."""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "—"
    if v == 0:
        return "0 cr"
    neg = v < 0
    v = abs(v)
    if v >= 1_000_000_000:
        s = f"{v / 1_000_000_000:.2f}B cr"
    elif v >= 1_000_000:
        s = f"{v / 1_000_000:.1f}M cr"
    elif v >= 1_000:
        s = f"{v / 1_000:.1f}K cr"
    else:
        s = f"{v} cr"
    return f"-{s}" if neg else s


def _fmt_hours(seconds) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if s <= 0:
        return "—"
    h = s // 3600
    if h >= 24:
        d = h // 24
        return f"{d}d {h % 24}h"
    return f"{h}h"


def _fmt_distance(ly) -> str:
    try:
        v = float(ly)
    except (TypeError, ValueError):
        return "—"
    if v <= 0:
        return "—"
    if v >= 1000:
        return f"{v:,.0f} ly"
    return f"{v:.1f} ly"


# Tab declarations — (internal_name, label, tooltip).
_TABS: list[tuple[str, str, str]] = [
    ("summary",  "Summary", "Career highlights + current session"),
    ("combat",   "Combat",  "Lifetime combat stats"),
    ("explore",  "Explore", "Lifetime exploration stats"),
    ("exobio",   "Exobio",  "Lifetime exobiology stats"),
    ("mining",   "Mining",  "Lifetime mining stats"),
    ("trade",    "Trade",   "Lifetime trade stats"),
    ("income",   "Credits", "Lifetime earnings, spending, and carrier-bank flow"),
    ("carrier",  "Carrier", "Fleet carrier stats"),
    ("pplay",    "PPlay",   "PowerPlay merits & systems"),
]


class CareerBlock(BlockWidget):
    BLOCK_TITLE = "Career"
    BLOCK_CSS   = "stats-block"

    DEFAULT_COL    = 21
    DEFAULT_ROW    = 61
    DEFAULT_WIDTH  = 11
    DEFAULT_HEIGHT = 40

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        body.set_spacing(0)

        # Tab row: bar (fills) + reset button (right-aligned, fixed width).
        tab_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_row.set_hexpand(True)

        self._tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar.add_css_class("mat-tab-bar")
        self._tab_bar.set_hexpand(True)
        tab_row.append(self._tab_bar)

        reset_btn = Gtk.Button(label="↺")
        reset_btn.add_css_class("mat-tab-btn")
        reset_btn.add_css_class("career-reset-btn")
        reset_btn.set_tooltip_text("Reset session counters")
        reset_btn.set_can_focus(False)
        reset_btn.connect("clicked", self._on_reset_session)
        tab_row.append(reset_btn)
        body.append(tab_row)

        body.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Stack expands in BOTH axes so the block's content fills the grid
        # cell — without set_hexpand(True) the block leaves a gutter on the
        # right and the drag-ghost preview reports the wrong width.
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        body.append(self._stack)

        self._tab_btns:    dict[str, Gtk.Button] = {}
        self._tab_scrolls: dict[str, Gtk.Box]    = {}
        for name, label, tooltip in _TABS:
            btn = Gtk.Button()
            btn.add_css_class("mat-tab-btn")
            btn.set_hexpand(True)
            btn.set_can_focus(False)
            btn.set_tooltip_text(tooltip)
            lbl = Gtk.Label(label=label)
            lbl.add_css_class("mat-tab-label")
            btn.set_child(lbl)
            btn.connect("clicked", lambda _b, n=name: self._set_active_tab(n))
            self._tab_bar.append(btn)
            self._tab_btns[name] = btn

            sc = Gtk.ScrolledWindow()
            sc.add_css_class("mat-tab-scroll")
            sc.set_hexpand(True)
            sc.set_vexpand(True)
            sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            inner.set_margin_start(6)
            inner.set_margin_end(12)
            inner.set_margin_top(4)
            inner.set_margin_bottom(4)
            sc.set_child(inner)
            self._stack.add_named(sc, name)
            self._tab_scrolls[name] = inner

        self._active_tab = "summary"
        self._set_active_tab(self._active_tab)

    # ── Tab state ─────────────────────────────────────────────────────────────

    def _set_active_tab(self, name: str) -> None:
        if name not in self._tab_btns:
            return
        for n, b in self._tab_btns.items():
            if n == name:
                b.add_css_class("mat-tab-active")
            else:
                b.remove_css_class("mat-tab-active")
        self._stack.set_visible_child_name(name)
        self._active_tab = name

    def _on_reset_session(self, _btn) -> None:
        try:
            self.core.plugin_call("session_stats", "on_new_session", 0)
        except Exception:
            pass
        gq = self.core.gui_queue
        if gq:
            gq.put(("stats_update", None))

    # ── Page primitives ───────────────────────────────────────────────────────
    # Each tab page renders into a single Gtk.Grid with aligned columns —
    # the same layout the Massacre Mission Stack block uses, which keeps
    # values lined up vertically and reads much cleaner than per-row boxes.
    # The next-free-row index is tracked as an attribute on the grid so the
    # refresh methods don't have to thread a counter through every call.

    def _clear_page(self, name: str) -> Gtk.Grid:
        """Empty the tab's scroll box and install a fresh aligned grid.
        Returns the grid; callers pass it to _add_section_header / _add_kv."""
        box = self._tab_scrolls[name]
        while True:
            ch = box.get_first_child()
            if ch is None:
                break
            box.remove(ch)
        grid = Gtk.Grid()
        grid.set_column_spacing(4)
        grid.set_row_spacing(1)
        grid.add_css_class("stats-grid")
        grid.set_hexpand(True)
        grid._next_row = 0          # row cursor — see _grid_row()
        box.append(grid)
        return grid

    @staticmethod
    def _grid_row(grid: Gtk.Grid) -> int:
        r = getattr(grid, "_next_row", 0)
        grid._next_row = r + 1
        return r

    def _add_section_header(self, grid: Gtk.Grid, title: str,
                            tooltip: str = "") -> None:
        row = self._grid_row(grid)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_top(4)
        hbox.set_margin_bottom(2)
        if tooltip:
            hbox.set_tooltip_text(tooltip)
        lbl = Gtk.Label(label=title)
        lbl.add_css_class("section-header")
        lbl.set_xalign(0.0)
        hbox.append(lbl)
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_hexpand(True)
        sep.set_valign(Gtk.Align.CENTER)
        hbox.append(sep)
        # Header spans all four columns.
        grid.attach(hbox, 0, row, 4, 1)

    def _add_kv(self, grid: Gtk.Grid, key: str, value: str,
                aux: str = "", tooltip: str = "") -> None:
        """Attach one data row: label | value | (pipe | aux).

        When `aux` is given the row is label | value | "|" | aux — exactly
        the four-column shape the Massacre Mission Stack uses.  Without
        `aux`, the value spans the remaining three columns so single-value
        rows still right-align cleanly.
        """
        row = self._grid_row(grid)

        k = Gtk.Label(label=key)
        k.add_css_class("data-key")
        k.set_xalign(0.0)
        k.set_hexpand(True)
        if tooltip:
            k.set_tooltip_text(tooltip)
        grid.attach(k, 0, row, 1, 1)

        if aux:
            v = Gtk.Label(label=value)
            v.add_css_class("data-value")
            v.set_xalign(1.0)
            grid.attach(v, 1, row, 1, 1)

            pipe = Gtk.Label(label="|")
            pipe.add_css_class("data-key")
            pipe.set_xalign(0.5)
            grid.attach(pipe, 2, row, 1, 1)

            a = Gtk.Label(label=aux)
            a.add_css_class("stat-line")
            a.set_xalign(1.0)
            grid.attach(a, 3, row, 1, 1)
        else:
            v = Gtk.Label(label=value)
            v.add_css_class("data-value")
            v.set_xalign(1.0)
            grid.attach(v, 1, row, 3, 1)

        if tooltip:
            v.set_tooltip_text(tooltip)

    def _add_empty(self, grid: Gtk.Grid, msg: str = "No data yet") -> None:
        row = self._grid_row(grid)
        l = Gtk.Label(label=msg)
        l.add_css_class("data-key")
        l.set_xalign(0.5)
        l.set_margin_top(12)
        grid.attach(l, 0, row, 4, 1)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        hist = self.core._plugins.get("journal_history")
        scan_ready = hist is not None and hist.scan_done.is_set()
        r     = hist.results if scan_ready else {}
        stats = r.get("statistics", {})

        # Summary always renders — it has a session section that doesn't
        # depend on the lifetime scan, and falls back gracefully if the
        # scan isn't done yet.
        self._refresh_summary(r, stats, scan_ready)

        if not scan_ready:
            for name, _, _ in _TABS:
                if name == "summary":
                    continue
                box = self._clear_page(name)
                self._add_empty(box, "Lifetime scan in progress…")
            return

        self._refresh_combat (r, stats)
        self._refresh_explore(r, stats)
        self._refresh_exobio (r, stats)
        self._refresh_mining (r, stats)
        self._refresh_trade  (r, stats)
        self._refresh_income (r, stats)
        self._refresh_carrier(r, stats)
        self._refresh_pplay  (r, stats)

    # ── Summary: current session + career highlights ─────────────────────────

    def _refresh_summary(self, r: dict, stats: dict, scan_ready: bool) -> None:
        box = self._clear_page("summary")

        # ── Current Session ──────────────────────────────────────────────
        # The retired Session Stats block's content lives here now.
        self._add_section_header(box, "Current Session",
                                 "Activity since the last session reset")
        plugin    = self.core._plugins.get("session_stats")
        providers = getattr(self.core, "session_providers", [])
        dur_s = plugin.session_duration_seconds() if plugin else 0.0
        self._add_kv(box, "Duration",
                     self.fmt_duration(dur_s) if dur_s > 0 else "—")

        sess_rows = 0
        for p in sorted(providers,
                        key=lambda p: getattr(p, "ACTIVITY_TAB_TITLE", "")):
            try:
                if not p.has_activity():
                    continue
                rows = p.get_summary_rows() or []
            except Exception:
                continue
            for row in rows:
                lbl = row.get("label", "")
                if lbl.startswith("─"):
                    continue
                self._add_kv(box,
                             f"{getattr(p, 'ACTIVITY_TAB_TITLE', '')}: {lbl}",
                             row.get("value", "—"), row.get("rate", ""))
                sess_rows += 1
        if sess_rows == 0 and dur_s <= 0:
            self._add_kv(box, "Status", "No activity yet")

        # ── Career Highlights ────────────────────────────────────────────
        if not scan_ready:
            self._add_section_header(box, "Career Highlights")
            self._add_empty(box, "Lifetime scan in progress…")
            return

        carto  = r.get("cartography", {})
        exobio = r.get("exobiology",  {})
        carrier = r.get("carrier",    {})
        cmb    = stats.get("Combat",      {})
        expl   = stats.get("Exploration", {})
        exo    = stats.get("Exobiology",  {})
        mine   = stats.get("Mining",      {})
        trd    = stats.get("Trading",     {})
        bank   = stats.get("Bank_Account", {})

        self._add_section_header(box, "Career Highlights",
                                 "The headline figure from each tab")

        # ── Wealth breakdown ─────────────────────────────────────────────
        # Liquid credits, ship/module value, and the carrier bank balance
        # are all maintained on live state by the Assets plugin (it
        # ingests CAPI snapshots, LoadGame, Commander, Statistics, and
        # CarrierFinance as they fire).  Those are the authoritative
        # numbers — strictly fresher than anything we'd compute from a
        # one-shot journal scan, so prefer them and fall back to scan
        # values only when live state hasn't been populated yet.
        finance       = r.get("finance", {})
        carrier_data  = r.get("carrier", {})
        state         = getattr(self.core, "state", None)

        # Liquid credits — live state.assets_balance, journal-derived
        # latest LoadGame.Credits as fallback.
        live_bal = getattr(state, "assets_balance", None) if state else None
        liquid   = int(live_bal) if live_bal is not None else (
                   finance.get("liquid_credits", 0))

        # Ships value — sum of hull+loadout values cached on state by
        # the Assets plugin (sourced from CAPI's /profile snapshot).
        current_ship = (getattr(state, "assets_current_ship", None) or {}
                        if state else {})
        stored_ships = (getattr(state, "assets_stored_ships", []) or []
                        if state else [])
        cur_id     = current_ship.get("ship_id")
        all_ships  = ([current_ship] if current_ship else []) + \
                     [s for s in stored_ships
                      if isinstance(s, dict) and s.get("ship_id") != cur_id]
        ships_val  = sum(s.get("value", 0) for s in all_ships if s)
        modules    = (getattr(state, "assets_stored_modules", []) or []
                      if state else [])
        mods_val   = sum(m.get("value", 0) for m in modules if isinstance(m, dict))

        # Carrier bank balance — prefer the live snapshot maintained by
        # the Assets plugin, fall back to the journal-derived
        # CarrierFinance from the scan.
        live_carrier = (getattr(state, "assets_carrier", None) or {}
                        if state else {})
        cbank        = (live_carrier.get("balance")
                        or carrier_data.get("bank_balance", 0)
                        or 0)

        # At-risk holdings — pending payouts that are part of net worth
        # even though they haven't been redeemed yet.
        risk = 0
        if state:
            for attr in ("holdings_bounties", "holdings_bonds",
                         "holdings_trade",    "holdings_cartography",
                         "holdings_exobiology"):
                risk += getattr(state, attr, 0) or 0

        # Net worth — sum of everything we can value precisely.  This is
        # always at least liquid + ship value + carrier bank, which is
        # bigger and fresher than Statistics.Bank_Account.Current_Wealth
        # when the commander has earned credits since the last Statistics
        # event fired.  Current_Wealth is the floor, not the ceiling.
        stat_wealth = bank.get("Current_Wealth", 0) or 0
        computed    = liquid + ships_val + mods_val + cbank + risk
        net_worth   = max(stat_wealth, computed)

        if net_worth:
            self._add_kv(box, "Net worth", _fmt_cr(net_worth),
                         tooltip="Liquid credits + ship value + module "
                                 "value + carrier bank + pending vouchers. "
                                 "Uses live state where available; falls "
                                 "back to Statistics.Current_Wealth.")
        if liquid:
            self._add_kv(box, "  Liquid credits", _fmt_cr(liquid),
                         tooltip="state.assets_balance — updated live "
                                 "from CAPI + LoadGame + Commander events")
        if cbank:
            self._add_kv(box, "  Carrier bank", _fmt_cr(cbank),
                         tooltip="Credits sitting in the fleet carrier's "
                                 "bank, from CarrierFinance")

        # Combat: lead with kills, else assassination profit.
        kills = cmb.get("Bounties_Claimed", 0) or r.get("combat", {}).get("kill_count", 0)
        if kills:
            self._add_kv(box, "Combat", f"{_fmt(kills)} kills")
        elif cmb.get("Assassination_Profits"):
            self._add_kv(box, "Combat",
                         _fmt_cr(cmb.get("Assassination_Profits")) + " assassinations")

        # Exploration
        sys_visited = expl.get("Systems_Visited")
        expl_profit = expl.get("Exploration_Profits") or carto.get("sold_total") or 0
        if sys_visited or expl_profit:
            self._add_kv(box, "Exploration",
                         f"{_fmt(sys_visited)} systems",
                         _fmt_cr(expl_profit))

        # Exobiology
        exo_samples = exo.get("Organic_Data") or exobio.get("sample_count") or 0
        exo_credits = exo.get("Organic_Data_Profits") or exobio.get("sold_total") or 0
        if exo_samples or exo_credits:
            self._add_kv(box, "Exobiology",
                         f"{_fmt(exo_samples)} samples",
                         _fmt_cr(exo_credits))

        # Mining
        if mine.get("Mining_Profits"):
            self._add_kv(box, "Mining", _fmt_cr(mine.get("Mining_Profits")))

        # Trade
        if trd.get("Market_Profits"):
            self._add_kv(box, "Trade", _fmt_cr(trd.get("Market_Profits")))

        # Carrier
        if carrier.get("stats"):
            cname = carrier.get("name") or carrier.get("callsign") or "Fleet carrier"
            jumps = carrier.get("stats", {}).get("SpaceUsage") and None
            fc_jumps = stats.get("FLEETCARRIER", {}).get("FLEETCARRIER_TOTAL_JUMPS", 0)
            self._add_kv(box, "Carrier", cname,
                         f"{_fmt(fc_jumps)} jumps" if fc_jumps else "")

        # PowerPlay
        pp = r.get("powerplay", {})
        live_total = getattr(self.core.state, "pp_merits_total", None)
        pp_total = live_total if live_total else pp.get("total_merits", 0)
        power = getattr(self.core.state, "pp_power", None) or ""
        if power or pp_total:
            self._add_kv(box, "PowerPlay",
                         power or "Pledged",
                         f"{_fmt(pp_total)} merits" if pp_total else "")

    # ── Combat ────────────────────────────────────────────────────────────────

    def _refresh_combat(self, r: dict, stats: dict) -> None:
        box   = self._clear_page("combat")
        cmb   = stats.get("Combat", {})
        bank  = stats.get("Bank_Account", {})
        scan_combat = r.get("combat", {})

        # Statistics is authoritative; the journal-scan accumulator is the
        # fallback when Statistics hasn't caught up.
        kills          = cmb.get("Bounties_Claimed", 0) or scan_combat.get("kill_count", 0)
        bounty_profit  = cmb.get("Bounty_Hunting_Profit") or scan_combat.get("bounties_earned") or 0
        bond_profit    = cmb.get("Combat_Bond_Profits")   or scan_combat.get("bonds_earned")    or 0
        bonds_count    = cmb.get("Combat_Bonds", 0)
        highest_bounty = cmb.get("Highest_Single_Reward", 0)
        assassinations = cmb.get("Assassinations", 0)
        assassin_prof  = cmb.get("Assassination_Profits", 0)
        skimmers       = cmb.get("Skimmers_Killed", 0)

        if not any((kills, bounty_profit, bond_profit, assassinations,
                    assassin_prof, bonds_count, skimmers)):
            self._add_empty(box, "No combat activity logged")
            return

        self._add_section_header(box, "Bounty hunting",
                                 "Ships killed for bounty vouchers")
        if kills:
            self._add_kv(box, "Ships killed", _fmt(kills),
                         tooltip="Bounty vouchers claimed (Statistics: "
                                 "Bounties_Claimed)")
        if bounty_profit:
            self._add_kv(box, "Bounty credits", _fmt_cr(bounty_profit),
                         tooltip="Total credits from redeemed bounty vouchers")
        if highest_bounty:
            self._add_kv(box, "Highest single bounty", _fmt_cr(highest_bounty),
                         tooltip="Largest single bounty voucher redeemed")
        if kills and bounty_profit:
            self._add_kv(box, "Average per kill", _fmt_cr(bounty_profit / kills),
                         tooltip="Bounty credits ÷ ships killed")
        if skimmers:
            self._add_kv(box, "Skimmers destroyed", _fmt(skimmers),
                         tooltip="Surface skimmer drones destroyed")

        if bonds_count or bond_profit:
            self._add_section_header(box, "Combat bonds",
                                     "Kills for faction warzone bonds")
            if bonds_count:
                self._add_kv(box, "Bonds awarded", _fmt(bonds_count),
                             tooltip="Faction kill bonds earned (Statistics: "
                                     "Combat_Bonds)")
            if bond_profit:
                self._add_kv(box, "Bond credits", _fmt_cr(bond_profit),
                             tooltip="Total credits from redeemed combat bonds")

        if assassinations or assassin_prof:
            self._add_section_header(box, "Assassinations",
                                     "Assassination mission targets eliminated")
            if assassinations:
                self._add_kv(box, "Targets eliminated", _fmt(assassinations),
                             tooltip="Assassination mission kills (Statistics: "
                                     "Assassinations)")
            if assassin_prof:
                self._add_kv(box, "Assassination credits", _fmt_cr(assassin_prof),
                             tooltip="Total reward credits from assassination "
                                     "missions")

        # Losses — only shown when Statistics carries the figures.
        deaths      = bank.get("Insurance_Claims") or 0
        rebuy_total = bank.get("Spent_On_Insurance") or 0
        if deaths or rebuy_total:
            self._add_section_header(box, "Losses",
                                     "Ship destruction and rebuy costs")
            if deaths:
                self._add_kv(box, "Ships lost", _fmt(deaths),
                             tooltip="Insurance claims filed (Statistics: "
                                     "Insurance_Claims)")
            if rebuy_total:
                self._add_kv(box, "Total rebuy cost", _fmt_cr(rebuy_total),
                             tooltip="Credits spent on ship insurance rebuys")
            if deaths and rebuy_total:
                self._add_kv(box, "Average rebuy", _fmt_cr(rebuy_total / deaths))

        # Voucher reconciliation — vouchers earned at the kill aren't
        # credits until they're redeemed at a station, and many sit
        # unclaimed for ages.  This makes the difference visible.
        voucher = r.get("finance", {}).get("vouchers", {})
        bi = voucher.get("bounty_issued",   0)
        br = voucher.get("bounty_redeemed", 0)
        ki = voucher.get("bonds_issued",    0)
        kr = voucher.get("bonds_redeemed",  0)
        if bi or br or ki or kr:
            self._add_section_header(
                box, "Voucher status",
                "Bounty vouchers and combat bonds are issued at the kill "
                "but don't become credits until redeemed at a station. "
                "Unredeemed = pending payouts (or claimed before the "
                "current journal window).",
            )
            if bi:
                self._add_kv(box, "Bounties issued",   _fmt_cr(bi),
                             tooltip="Σ TotalReward across Bounty events")
                self._add_kv(box, "Bounties redeemed", _fmt_cr(br),
                             tooltip="Σ Amount across RedeemVoucher (bounty)")
                pending = max(bi - br, 0)
                if pending:
                    self._add_kv(box, "Bounties unredeemed", _fmt_cr(pending))
            if ki:
                self._add_kv(box, "Bonds issued",      _fmt_cr(ki))
                self._add_kv(box, "Bonds redeemed",    _fmt_cr(kr))
                pending = max(ki - kr, 0)
                if pending:
                    self._add_kv(box, "Bonds unredeemed",  _fmt_cr(pending))

    # ── Explore ───────────────────────────────────────────────────────────────

    def _refresh_explore(self, r: dict, stats: dict) -> None:
        box  = self._clear_page("explore")
        expl = stats.get("Exploration", {})
        carto = r.get("cartography", {})

        if not expl and not carto.get("sold_total"):
            self._add_empty(box, "No exploration activity logged")
            return

        self._add_section_header(box, "Travel")
        self._add_kv(box, "Systems visited",  _fmt(expl.get("Systems_Visited")))
        self._add_kv(box, "Hyperspace jumps", _fmt(expl.get("Total_Hyperspace_Jumps")))
        self._add_kv(box, "Distance",         _fmt_distance(expl.get("Total_Hyperspace_Distance")))
        greatest = expl.get("Greatest_Distance_From_Start")
        if greatest:
            self._add_kv(box, "Farthest from start", _fmt_distance(greatest))
        time_played = expl.get("Time_Played")
        if time_played:
            self._add_kv(box, "Time played", _fmt_hours(time_played))

        # FSS / DSS counts come from the journal scan, NOT from
        # Statistics — the in-game Planets_Scanned_To_Level_2 / _Level_3
        # fields are unreliable (they routinely report identical values
        # that don't match what the commander actually did).  The journal
        # scan counts unique bodies from Scan events (FSS detail scans) and
        # SAAScanComplete events (DSS maps).
        career = r.get("career", {})
        fss = career.get("fss_scanned", 0)
        dss = career.get("dss_mapped", 0)
        eff = expl.get("Efficient_Scans") or 0
        if fss or dss or eff:
            self._add_section_header(box, "Scanning",
                                     "FSS/DSS counts are derived from the "
                                     "journal — the in-game Statistics "
                                     "scan-level fields are unreliable")
            if fss: self._add_kv(box, "Planets FSS-scanned", _fmt(fss),
                                 tooltip="Unique planet bodies detail-scanned "
                                         "(journal Scan events)")
            if dss: self._add_kv(box, "Planets DSS-mapped",  _fmt(dss),
                                 tooltip="Unique bodies surface-mapped "
                                         "(journal SAAScanComplete events)")
            if eff: self._add_kv(box, "Efficient scans",     _fmt(eff))

        footfalls   = expl.get("Planet_Footfalls") or 0
        settlements = expl.get("Settlements_Visited") or 0
        onfoot_m    = expl.get("OnFoot_Distance_Travelled") or 0
        if footfalls or settlements or onfoot_m:
            self._add_section_header(box, "On foot")
            if footfalls:   self._add_kv(box, "First footfalls",     _fmt(footfalls))
            if settlements: self._add_kv(box, "Settlements visited",  _fmt(settlements))
            if onfoot_m:    self._add_kv(box, "On-foot distance",     f"{int(onfoot_m):,} m")

        profit  = expl.get("Exploration_Profits") or carto.get("sold_total") or 0
        highest = expl.get("Highest_Payout") or 0
        if profit or highest:
            self._add_section_header(box, "Earnings")
            if profit:  self._add_kv(box, "Total profit",   _fmt_cr(profit))
            if highest: self._add_kv(box, "Highest payout", _fmt_cr(highest))
            if profit and fss:
                self._add_kv(box, "Average per FSS scan", _fmt_cr(profit / fss))

    # ── Exobio ────────────────────────────────────────────────────────────────

    def _refresh_exobio(self, r: dict, stats: dict) -> None:
        box    = self._clear_page("exobio")
        exo    = stats.get("Exobiology", {})
        exobio = r.get("exobiology", {})

        sample_count   = exo.get("Organic_Data") or exobio.get("sample_count") or 0
        # Credits: Statistics is authoritative, journal-scan is the fallback.
        sold_total     = exo.get("Organic_Data_Profits") or exobio.get("sold_total") or 0
        first_bonus    = exobio.get("first_bonus", 0)
        by_genus_value = exobio.get("by_genus_value", {})
        by_genus_count = exobio.get("by_genus", {})

        if not sample_count and not sold_total and not by_genus_count:
            self._add_empty(box, "No exobiology activity logged")
            return

        # Discoveries
        self._add_section_header(box, "Discoveries")
        self._add_kv(box, "Samples analysed", _fmt(sample_count))
        self._add_kv(box, "Species encountered", _fmt(exo.get("Organic_Species_Encountered")))
        self._add_kv(box, "Genus encountered",   _fmt(exo.get("Organic_Genus_Encountered")))
        if exo.get("Organic_Variant_Encountered"):
            self._add_kv(box, "Variants encountered", _fmt(exo.get("Organic_Variant_Encountered")))
        self._add_kv(box, "Systems with biology", _fmt(exo.get("Organic_Systems")))
        self._add_kv(box, "Planets with biology", _fmt(exo.get("Organic_Planets")))

        # Earnings — total, base vs first-discovery bonus.
        self._add_section_header(box, "Earnings",
                                 "Credits from selling organic data at "
                                 "Vista Genomics")
        self._add_kv(box, "Total credits earned", _fmt_cr(sold_total),
                     tooltip="All credits from sold organic data, "
                             "including first-discovery bonuses")
        if first_bonus:
            base = max(sold_total - first_bonus, 0)
            self._add_kv(box, "Base value", _fmt_cr(base),
                         tooltip="Sale value before first-discovery bonuses")
            self._add_kv(box, "First-discovery bonus", _fmt_cr(first_bonus),
                         tooltip="Premium for being first to log a species "
                                 "(Σ Bonus field on SellOrganicData)")
        if sample_count and sold_total:
            self._add_kv(box, "Average per sample", _fmt_cr(sold_total / sample_count))

        # Per-genus credit breakdown — the meat of the tab.
        if by_genus_value:
            self._add_section_header(box, "Credits by genus",
                                     "Total credits earned per genus sold")
            genus_total = sum(by_genus_value.values()) or 1
            for genus, credits in sorted(by_genus_value.items(),
                                          key=lambda kv: -kv[1]):
                if credits <= 0:
                    continue
                pct = f"{credits / genus_total * 100:.0f}%"
                self._add_kv(box, genus, _fmt_cr(credits), pct)
        elif by_genus_count:
            # Sold nothing yet, but samples logged — show sample counts so
            # the tab isn't empty.
            self._add_section_header(box, "Samples by genus",
                                     "Organic samples analysed per genus "
                                     "(not yet sold)")
            for genus, n in sorted(by_genus_count.items(),
                                    key=lambda kv: -kv[1]):
                self._add_kv(box, genus or "(unknown)", _fmt(n))

    # ── Mining ────────────────────────────────────────────────────────────────

    def _refresh_mining(self, r: dict, stats: dict) -> None:
        box  = self._clear_page("mining")
        mine = stats.get("Mining", {})

        qty    = mine.get("Quantity_Mined", 0)
        profit = mine.get("Mining_Profits", 0)
        mats   = mine.get("Materials_Collected", 0)

        if not any((qty, profit, mats)):
            self._add_empty(box, "No mining activity logged")
            return

        self._add_section_header(box, "Yield")
        if qty:  self._add_kv(box, "Tonnes refined",       f"{qty:,} t",
                              tooltip="Statistics: Quantity_Mined")
        if mats: self._add_kv(box, "Materials collected",  _fmt(mats),
                              tooltip="Raw materials picked up while mining")

        if profit:
            self._add_section_header(box, "Earnings")
            self._add_kv(box, "Mining profit", _fmt_cr(profit))
            if qty:
                self._add_kv(box, "Average per tonne", _fmt_cr(profit / qty))

    # ── Trade ─────────────────────────────────────────────────────────────────

    def _refresh_trade(self, r: dict, stats: dict) -> None:
        box = self._clear_page("trade")
        trd = stats.get("Trading", {})
        smg = stats.get("Smuggling", {})

        # Journal-derived figures are authoritative.  Statistics.Trading.
        # Goods_Sold and Data_Sold sit at 0 for many commanders even when
        # they've sold hundreds of tonnes; the MarketSell journal events
        # are the truth.  Use max() so whichever is higher wins (recent
        # journals fall back to Statistics if scan is incomplete).
        ms = r.get("finance", {}).get("market_sell", {})
        j_count   = ms.get("count",   0)
        j_revenue = ms.get("revenue", 0)
        j_profit  = ms.get("profit",  0)

        market_profit = max(trd.get("Market_Profits", 0), j_profit)
        markets       = trd.get("Markets_Traded_With", 0)
        resources     = max(trd.get("Resources_Traded", 0), j_count)
        highest       = trd.get("Highest_Single_Transaction", 0)
        avg           = trd.get("Average_Profit", 0)

        if not any((market_profit, markets, resources, highest, j_revenue)):
            self._add_empty(box, "No trade activity logged")
            return

        self._add_section_header(box, "Markets")
        if markets:
            self._add_kv(box, "Markets visited", _fmt(markets),
                         tooltip="Statistics: Markets_Traded_With")
        if resources:
            self._add_kv(box, "Tonnes sold", _fmt(resources),
                         tooltip="Total tonnage from MarketSell events "
                                 "(Statistics.Trading.Resources_Traded is "
                                 "often stale or zero — journal is "
                                 "authoritative)")

        self._add_section_header(box, "Earnings")
        if j_revenue:
            self._add_kv(box, "Gross revenue", _fmt_cr(j_revenue),
                         tooltip="Σ TotalSale across MarketSell events")
        if market_profit:
            self._add_kv(box, "Net profit", _fmt_cr(market_profit),
                         tooltip="Revenue minus cost basis (AvgPricePaid). "
                                 "Falls back to Statistics.Market_Profits "
                                 "if the journal scan is partial.")
        if highest:
            self._add_kv(box, "Largest transaction", _fmt_cr(highest))
        if avg:
            self._add_kv(box, "Average per trade", _fmt_cr(avg))
        if resources and market_profit:
            self._add_kv(box, "Profit per tonne",
                         _fmt_cr(market_profit / resources))

        smg_profit  = smg.get("Black_Markets_Profits", 0)
        smg_markets = smg.get("Black_Markets_Traded_With", 0)
        if smg_profit or smg_markets:
            self._add_section_header(box, "Black market")
            if smg_markets: self._add_kv(box, "Black markets used", _fmt(smg_markets))
            if smg_profit:  self._add_kv(box, "Smuggling profit",   _fmt_cr(smg_profit))

    # ── Earnings & Spending ──────────────────────────────────────────────────

    def _refresh_income(self, r: dict, stats: dict) -> None:
        """Earnings & Spending tab — formerly "Income".

        Lists every journal-derived income and expense category, the
        carrier-bank flow, and a voucher-issued-vs-redeemed breakdown.
        These figures come from journal events directly because several
        Statistics fields are unreliable — Trading.Goods_Sold sits at 0
        for many commanders even with hundreds of tonnes sold.

        Carrier-bank flow is neutral for net worth (the credits move
        between the commander's wallet and their carrier) but is shown
        separately so the deposit/withdrawal history is visible.
        """
        box     = self._clear_page("income")
        finance = r.get("finance", {})
        f_in    = finance.get("in",  {})
        f_out   = finance.get("out", {})
        vouchers = finance.get("vouchers", {})
        carrier  = r.get("carrier", {})
        state    = getattr(self.core, "state", None)

        if not f_in and not f_out:
            self._add_empty(box, "No financial events logged yet")
            return

        # ── Lifetime earnings ─────────────────────────────────────────────
        total_in = sum(f_in.values())
        if f_in:
            self._add_section_header(
                box, "Lifetime earnings",
                "Credits earned per source, derived from journal events. "
                "This is GROSS earnings — it does not equal net worth, "
                "since most of it has been spent on ships, outfitting, "
                "and the carrier.",
            )
            for k, v in f_in.items():
                pct = f"{v / total_in * 100:.1f}%" if total_in else "—"
                self._add_kv(box, k, _fmt_cr(v), pct)
            self._add_kv(box, "  Total earnings", _fmt_cr(total_in))

        # ── Lifetime spending ─────────────────────────────────────────────
        total_out = sum(f_out.values())
        if f_out:
            self._add_section_header(
                box, "Lifetime spending",
                "Credits spent per category, derived from journal events. "
                "Carrier purchase + outfitting typically dominate; "
                "buy-orders are tracked as pending commitments since "
                "the cost only materialises if the order fills.",
            )
            for k, v in f_out.items():
                pct = f"{v / total_out * 100:.1f}%" if total_out else "—"
                self._add_kv(box, k, _fmt_cr(v), pct)
            self._add_kv(box, "  Total spending", _fmt_cr(total_out))

        # ── Carrier bank flow ─────────────────────────────────────────────
        # Current balance preferentially from live state (updated on
        # every CarrierFinance + CarrierBankTransfer); journal scan as
        # fallback for the first launch before the plugin sees an event.
        cbd = carrier.get("bank_deposits", 0)
        cbw = carrier.get("bank_withdrawals", 0)
        live_carrier = (getattr(state, "assets_carrier", None) or {}
                        if state else {})
        cbb = live_carrier.get("balance") or carrier.get("bank_balance", 0)
        if cbd or cbw or cbb:
            self._add_section_header(
                box, "Carrier bank",
                "Credits moved between your wallet and your carrier's "
                "bank. Neutral for net worth — the money just changes "
                "pockets.",
            )
            if cbb:  self._add_kv(box, "Current balance",      _fmt_cr(cbb))
            cbr = carrier.get("bank_reserve", 0)
            cba = carrier.get("bank_available", 0)
            if cbr:  self._add_kv(box, "Reserve (locked)",     _fmt_cr(cbr),
                                  tooltip="Held in reserve to keep the "
                                          "carrier running")
            if cba:  self._add_kv(box, "Available",            _fmt_cr(cba),
                                  tooltip="Free to withdraw or spend on "
                                          "carrier orders")
            if cbd:  self._add_kv(box, "Lifetime deposits",    _fmt_cr(cbd))
            if cbw:  self._add_kv(box, "Lifetime withdrawals", _fmt_cr(cbw))

        # ── Voucher reconciliation ────────────────────────────────────────
        bi = vouchers.get("bounty_issued",   0)
        br = vouchers.get("bounty_redeemed", 0)
        ki = vouchers.get("bonds_issued",    0)
        kr = vouchers.get("bonds_redeemed",  0)
        if bi or br or ki or kr:
            self._add_section_header(
                box, "Voucher reconciliation",
                "Bounties and combat bonds are issued at the kill but "
                "only convert to credits when redeemed at a station. "
                "The gap is unclaimed vouchers.",
            )
            if bi:
                pending = max(bi - br, 0)
                self._add_kv(box, "Bounty vouchers issued",   _fmt_cr(bi))
                self._add_kv(box, "Bounty vouchers redeemed", _fmt_cr(br))
                if pending:
                    self._add_kv(box, "Bounty vouchers unredeemed",
                                 _fmt_cr(pending),
                                 tooltip="Issued but not yet cashed in at "
                                         "a station (or claimed in earlier "
                                         "journal sessions)")
            if ki:
                pending = max(ki - kr, 0)
                self._add_kv(box, "Combat bonds issued",   _fmt_cr(ki))
                self._add_kv(box, "Combat bonds redeemed", _fmt_cr(kr))
                if pending:
                    self._add_kv(box, "Combat bonds unredeemed",
                                 _fmt_cr(pending))

    # ── Carrier ───────────────────────────────────────────────────────────────

    def _refresh_carrier(self, r: dict, stats: dict) -> None:
        box     = self._clear_page("carrier")
        carrier = r.get("carrier", {})
        fc      = stats.get("FLEETCARRIER", {})
        cstats  = carrier.get("stats", {})

        if not cstats and not fc:
            self._add_empty(box, "No fleet carrier data")
            return

        # Identity + current state — sourced from the live CarrierStats
        # journal event, which is unambiguous and accurate.
        if cstats:
            self._add_section_header(box, "Carrier",
                                     "From the most recent CarrierStats "
                                     "journal event")
            name = carrier.get("name") or "—"
            self._add_kv(box, "Name", name)
            if carrier.get("callsign"):
                self._add_kv(box, "Callsign", carrier.get("callsign"))
            ctype = carrier.get("type") or ""
            if ctype:
                self._add_kv(box, "Type",
                             "Squadron carrier" if ctype.lower().startswith("squadron")
                             else "Fleet carrier")
            usage = cstats.get("SpaceUsage", {})
            if usage:
                self._add_kv(box, "Capacity used",
                             f"{usage.get('TotalCapacity', 0) - usage.get('FreeSpace', 0):,}"
                             f" / {usage.get('TotalCapacity', 0):,} t",
                             tooltip="Total used capacity vs total capacity — "
                                     "this is the figure Spansh wants for "
                                     "carrier route planning")
            if carrier.get("fuel_level"):
                self._add_kv(box, "Tritium on board",
                             f"{carrier.get('fuel_level'):,} t")
            if carrier.get("jump_range"):
                self._add_kv(box, "Current jump range",
                             _fmt_distance(carrier.get("jump_range")))

        # Carrier bank — current balance from the most recent
        # CarrierFinance event, plus lifetime deposit/withdrawal flow
        # from CarrierBankTransfer events.
        cb_balance   = carrier.get("bank_balance",   0)
        cb_reserve   = carrier.get("bank_reserve",   0)
        cb_available = carrier.get("bank_available", 0)
        cb_deposits  = carrier.get("bank_deposits",  0)
        cb_withdraws = carrier.get("bank_withdrawals", 0)
        if cb_balance or cb_deposits or cb_withdraws:
            self._add_section_header(
                box, "Bank",
                "Carrier bank holdings (CarrierFinance) and lifetime "
                "deposit / withdrawal flow (CarrierBankTransfer events). "
                "Bank balance counts toward your net worth.",
            )
            if cb_balance:
                self._add_kv(box, "Current balance", _fmt_cr(cb_balance),
                             tooltip="CarrierFinance.CarrierBalance — "
                                     "total credits in the carrier's bank")
            if cb_reserve:
                self._add_kv(box, "Reserve (locked)", _fmt_cr(cb_reserve),
                             tooltip="Credits held in reserve to keep "
                                     "the carrier running")
            if cb_available:
                self._add_kv(box, "Available", _fmt_cr(cb_available),
                             tooltip="Credits free to withdraw or spend "
                                     "on carrier orders / services")
            if cb_deposits:
                self._add_kv(box, "Lifetime deposits", _fmt_cr(cb_deposits),
                             tooltip="Σ Deposit on CarrierBankTransfer "
                                     "events (commander → carrier)")
            if cb_withdraws:
                self._add_kv(box, "Lifetime withdrawals", _fmt_cr(cb_withdraws),
                             tooltip="Σ Withdraw on CarrierBankTransfer "
                                     "events (carrier → commander)")

        # Lifetime travel — these FLEETCARRIER Statistics fields are
        # well-understood and accurate.
        jumps    = fc.get("FLEETCARRIER_TOTAL_JUMPS") or 0
        distance = fc.get("FLEETCARRIER_DISTANCE_TRAVELLED") or 0
        if jumps or distance:
            self._add_section_header(box, "Lifetime travel")
            if jumps:
                self._add_kv(box, "Total jumps", _fmt(jumps),
                             tooltip="Statistics: FLEETCARRIER_TOTAL_JUMPS")
            if distance:
                self._add_kv(box, "Total distance", _fmt_distance(distance),
                             tooltip="Statistics: FLEETCARRIER_DISTANCE_TRAVELLED")
            if jumps and distance:
                self._add_kv(box, "Average jump", _fmt_distance(distance / jumps))

        # Services rendered — counts of services the carrier has provided
        # to docked commanders.  These are reliable.
        rearm   = fc.get("FLEETCARRIER_REARM_TOTAL")   or 0
        refuel  = fc.get("FLEETCARRIER_REFUEL_TOTAL")  or 0
        repairs = fc.get("FLEETCARRIER_REPAIRS_TOTAL") or 0
        if rearm or refuel or repairs:
            self._add_section_header(box, "Services rendered",
                                     "Services the carrier has provided to "
                                     "docked commanders")
            if refuel:  self._add_kv(box, "Refuel services",  _fmt(refuel),
                                     tooltip="Statistics: FLEETCARRIER_REFUEL_TOTAL")
            if rearm:   self._add_kv(box, "Rearm services",   _fmt(rearm),
                                     tooltip="Statistics: FLEETCARRIER_REARM_TOTAL")
            if repairs: self._add_kv(box, "Repair services",  _fmt(repairs),
                                     tooltip="Statistics: FLEETCARRIER_REPAIRS_TOTAL")

        # Trade — Frontier does not publish definitions for the
        # EXPORT/IMPORT_TOTAL fields and their meaning is genuinely
        # ambiguous (they do NOT correspond to buy/sell orders set on the
        # carrier's market).  Trade *profit* is well-understood; the
        # export/import counts are shown only with an explicit "meaning
        # unclear" tooltip so they aren't mistaken for order counts.
        trade_profit = fc.get("FLEETCARRIER_TRADEPROFIT_TOTAL") or 0
        exports      = fc.get("FLEETCARRIER_EXPORT_TOTAL") or 0
        imports      = fc.get("FLEETCARRIER_IMPORT_TOTAL") or 0
        if trade_profit or exports or imports:
            self._add_section_header(box, "Trade")
            if trade_profit:
                self._add_kv(box, "Trade profit", _fmt_cr(trade_profit),
                             tooltip="Statistics: FLEETCARRIER_TRADEPROFIT_TOTAL — "
                                     "net credits from the carrier's market")
            if exports:
                self._add_kv(box, "Export total (?)", _fmt(exports),
                             tooltip="Statistics: FLEETCARRIER_EXPORT_TOTAL — "
                                     "Frontier publishes no definition for "
                                     "this field; it does NOT equal the number "
                                     "of sell orders set on the carrier market")
            if imports:
                self._add_kv(box, "Import total (?)", _fmt(imports),
                             tooltip="Statistics: FLEETCARRIER_IMPORT_TOTAL — "
                                     "Frontier publishes no definition for "
                                     "this field; it does NOT equal the number "
                                     "of buy orders set on the carrier market")

    # ── PowerPlay ─────────────────────────────────────────────────────────────

    def _refresh_pplay(self, r: dict, stats: dict) -> None:
        box = self._clear_page("pplay")
        pp  = r.get("powerplay", {})

        live_total = getattr(self.core.state, "pp_merits_total", None)
        pp_total   = live_total if live_total else pp.get("total_merits", 0)
        power      = getattr(self.core.state, "pp_power", None) or ""
        rank       = getattr(self.core.state, "pp_rank",  None)

        if not pp_total and not power:
            self._add_empty(box, "Not pledged to a Power")
            return

        # 1. Pledge
        self._add_section_header(box, "Pledge")
        if power:            self._add_kv(box, "Power", power)
        if rank is not None: self._add_kv(box, "Rank", str(rank))
        if pp_total:         self._add_kv(box, "Total merits", _fmt(pp_total))

        # 2. By activity — merits attributed to the activity that earned
        #    them (heuristic: dominant activity in the events preceding
        #    each PowerplayMerits grant).
        by_activity = pp.get("by_activity", {})
        if by_activity and any(by_activity.values()):
            self._add_section_header(box, "By activity",
                                     "Merits grouped by the activity that "
                                     "earned them (inferred from journal "
                                     "context)")
            act_total = sum(by_activity.values()) or 1
            for activity, merits in sorted(by_activity.items(),
                                            key=lambda kv: -kv[1]):
                if merits <= 0:
                    continue
                pct = f"{merits / act_total * 100:.0f}%"
                self._add_kv(box, activity, _fmt(merits), pct)

        # 3. By system
        by_sys = pp.get("system_merits", {}) or pp.get("by_system", {})
        if by_sys:
            self._add_section_header(box, "By system",
                                     "Merits earned per system")
            sys_total = sum(by_sys.values()) or 1
            for sys_name, merits in sorted(by_sys.items(),
                                            key=lambda x: -x[1])[:20]:
                pct = f"{merits / sys_total * 100:.0f}%"
                self._add_kv(box, sys_name, _fmt(merits), pct)

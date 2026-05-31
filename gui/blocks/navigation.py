"""
gui/blocks/navigation.py — Navigation block.

Three route planners, one per tab:

  FSD       plain jump-by-jump routing via EDSM's system database
            (From / To / Range) — Spansh has no plain-FSD endpoint, so
            this does a greedy best-first search through EDSM instead
  Neutron   neutron-boosted routing via Spansh /api/route
            (From / To / Range / Efficiency)
  Carrier   fleet carrier routing via Spansh's carrier router
            (From / To / Used capacity / Tritium)

The Carrier tab takes the carrier's *used capacity* and *tritium on
board* — carrier jump range depends on laden mass, and Spansh needs both
to plan refuel stops.  Both auto-fill from the latest CarrierStats
journal event.  System names are resolved to id64 via EDSM because the
carrier endpoint requires IDs, not names.

Each tab is a form; "Plot" dispatches the request on a background thread
so the UI stays responsive while the route is computed (Spansh jobs run
1–60 s; carrier jobs can take minutes).  Results render as a waypoint
list under the form.

Failures are reported in detail — Spansh rejection reasons, EDSM
unknown-system errors, network errors, and timeouts all surface through
the status label.

Tab styling matches the rest of the dashboard via the project-standard
`mat-tab-bar` / `mat-tab-btn` / `mat-tab-active` / `mat-tab-label` classes.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

import threading

from gui.block_base import BlockWidget


def _fmt_ly(d) -> str:
    try:
        v = float(d)
    except (TypeError, ValueError):
        return "—"
    if v >= 1000:
        return f"{v:,.0f} ly"
    return f"{v:.2f} ly"


# Tab declarations.  Order matters — Carrier is third because it's the
# slowest to plot (long routes can take ~30 s) and the form is the most
# constrained.
_TABS: list[tuple[str, str, str]] = [
    ("fsd",     "FSD",     "Vanilla-FSD route planning"),
    ("neutron", "Neutron", "Neutron-star boosted route planning"),
    ("carrier", "Carrier⚠",
     "Fleet carrier route planning — UNFINISHED, currently disabled"),
]


class NavigationBlock(BlockWidget):
    BLOCK_TITLE = "Navigation"
    BLOCK_CSS   = "stats-block"

    DEFAULT_COL    = 0
    DEFAULT_ROW    = 40
    DEFAULT_WIDTH  = 11
    DEFAULT_HEIGHT = 38

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        body.set_spacing(0)

        # Tab bar — same pattern as Assets / Career.
        self._tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar.add_css_class("mat-tab-bar")
        self._tab_bar.set_hexpand(True)
        body.append(self._tab_bar)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        body.append(self._stack)

        self._tab_btns: dict[str, Gtk.Button] = {}
        # Per-tab state: each entry holds the input widgets, status label,
        # results container, and an in-flight flag so we ignore re-clicks
        # while a plot is still running.
        self._state: dict[str, dict] = {}

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

            if name == "carrier":
                page = self._build_carrier_tab()
            else:
                page = self._build_route_tab(name, is_neutron=(name == "neutron"))
            self._stack.add_named(page, name)

        self._active_tab = "fsd"
        self._set_active_tab(self._active_tab)

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

    # ── Route tab construction ────────────────────────────────────────────────

    def _make_scroll(self) -> tuple[Gtk.ScrolledWindow, Gtk.Box]:
        sc = Gtk.ScrolledWindow()
        sc.add_css_class("mat-tab-scroll")
        sc.set_hexpand(True)
        sc.set_vexpand(True)
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.set_margin_start(6)
        inner.set_margin_end(12)
        inner.set_margin_top(4)
        inner.set_margin_bottom(4)
        sc.set_child(inner)
        return sc, inner

    def _make_compact_entry(self, placeholder: str = "",
                            value: str = "") -> Gtk.Entry:
        """Slim Entry with reduced padding so three of them stack neatly
        in an 11-column-wide block.  The `nav-entry` CSS class trims
        the GTK4 default vertical padding which would otherwise leave
        a lot of whitespace inside each field."""
        e = Gtk.Entry()
        if placeholder: e.set_placeholder_text(placeholder)
        if value:       e.set_text(value)
        e.add_css_class("nav-entry")
        e.set_hexpand(True)
        return e

    def _form_row(self, form: Gtk.Grid, row: int, label: str,
                  widget: Gtk.Widget) -> None:
        lbl = Gtk.Label(label=label)
        lbl.add_css_class("data-key")
        lbl.set_xalign(0.0)
        form.attach(lbl, 0, row, 1, 1)
        form.attach(widget, 1, row, 1, 1)

    def _build_route_tab(self, name: str, is_neutron: bool) -> Gtk.Widget:
        sc, box = self._make_scroll()

        form = Gtk.Grid()
        form.set_column_spacing(6)
        form.set_row_spacing(3)
        form.set_margin_bottom(4)
        box.append(form)

        from_entry  = self._make_compact_entry("current system")
        to_entry    = self._make_compact_entry("destination system")
        range_entry = self._make_compact_entry("laden range, ly (e.g. 45.7)")
        self._form_row(form, 0, "From",  from_entry)
        self._form_row(form, 1, "To",    to_entry)
        self._form_row(form, 2, "Range", range_entry)

        eff_entry = None
        if is_neutron:
            eff_entry = self._make_compact_entry("1–100 (default 60)", "60")
            self._form_row(form, 3, "Efficiency", eff_entry)

        # Action row: Plot button + status label.
        action = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        plot_btn = Gtk.Button(label="Plot")
        plot_btn.add_css_class("suggested-action")
        plot_btn.add_css_class("nav-plot-btn")
        action.append(plot_btn)
        status_lbl = Gtk.Label(label="")
        status_lbl.add_css_class("data-key")
        status_lbl.set_xalign(0.0)
        status_lbl.set_hexpand(True)
        status_lbl.set_wrap(True)
        action.append(status_lbl)
        box.append(action)

        # Divider + results grid.
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        results = Gtk.Grid()
        results.set_column_spacing(8)
        results.set_row_spacing(1)
        results.add_css_class("stats-grid")
        box.append(results)

        self._state[name] = {
            "from":       from_entry,
            "to":         to_entry,
            "range":      range_entry,
            "efficiency": eff_entry,
            "is_neutron": is_neutron,
            "is_carrier": False,
            "status":     status_lbl,
            "results":    results,
            "in_flight":  False,
        }
        plot_btn.connect("clicked", lambda _b, n=name: self._on_plot_click(n))
        return sc

    def _build_carrier_tab(self) -> Gtk.Widget:
        sc, box = self._make_scroll()

        # ── UNFINISHED banner ────────────────────────────────────────────
        # Carrier routing through Spansh isn't working reliably — the API
        # responds 202 to the POST but the resulting job UUID resolves
        # nowhere we've tried (/api/results, /api/fleetcarrier/results,
        # /api/fleet-carrier/results, /api/fleetcarrier/route).  The form
        # is preserved so the integration work can resume from where it
        # stands, but the plot button is disabled to keep users from
        # burning poll time on a known-broken path.
        banner = Gtk.Label(label=(
            "⚠ UNFINISHED FEATURE — carrier routing is currently disabled.\n"
            "The Spansh fleet-carrier API integration is unfinished; the "
            "plot button is inactive until result-endpoint discovery is "
            "resolved.  Use the in-game carrier galaxy map for now."
        ))
        banner.add_css_class("nav-unfinished-banner")
        banner.set_wrap(True)
        banner.set_xalign(0.0)
        banner.set_margin_bottom(8)
        box.append(banner)

        form = Gtk.Grid()
        form.set_column_spacing(6)
        form.set_row_spacing(3)
        form.set_margin_bottom(4)
        box.append(form)

        from_entry = self._make_compact_entry("source system (carrier's location)")
        to_entry   = self._make_compact_entry("destination system")
        # Used capacity — everything loaded onto the carrier (cargo +
        # tritium + crew + ship/module packs).  Carrier jump range is a
        # function of laden mass, so this materially affects the route and
        # where tritium refuel stops land.  Auto-filled from the latest
        # CarrierStats journal event in refresh().
        cap_entry  = self._make_compact_entry("used capacity, t (auto-filled)")
        # Tritium currently in the carrier's fuel tank — also auto-filled.
        trit_entry = self._make_compact_entry("tritium on board, t (auto-filled)")
        self._form_row(form, 0, "From",     from_entry)
        self._form_row(form, 1, "To",       to_entry)
        self._form_row(form, 2, "Used cap", cap_entry)
        self._form_row(form, 3, "Tritium",  trit_entry)

        # Carrier type — fleet vs squadron.  Squadron carriers (Javelin-
        # class) are physically larger (32 landing pads vs 16) and have
        # different mass / tritium-burn characteristics, which the route
        # planner needs to know to estimate refuel stops correctly.
        type_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        type_lbl = Gtk.Label(label="Type")
        type_lbl.add_css_class("data-key")
        type_lbl.set_xalign(0.0)
        fleet_radio = Gtk.CheckButton(label="Fleet")
        fleet_radio.set_active(True)
        fleet_radio.add_css_class("data-key")
        squad_radio = Gtk.CheckButton(label="Squadron")
        squad_radio.add_css_class("data-key")
        squad_radio.set_group(fleet_radio)
        type_row.append(fleet_radio)
        type_row.append(squad_radio)
        form.attach(type_lbl, 0, 4, 1, 1)
        form.attach(type_row, 1, 4, 1, 1)

        # Tritium top-up toggle — let Spansh plan refuel stops if needed.
        topup = Gtk.CheckButton(label="Plan tritium refuel stops as needed")
        topup.set_active(True)
        topup.add_css_class("data-key")
        form.attach(topup, 1, 5, 1, 1)

        action = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        plot_btn = Gtk.Button(label="Plot carrier route")
        plot_btn.add_css_class("suggested-action")
        plot_btn.add_css_class("nav-plot-btn")
        plot_btn.set_sensitive(False)   # UNFINISHED — see banner above
        action.append(plot_btn)
        status_lbl = Gtk.Label(label="Carrier routing is unfinished — "
                                     "see banner above.")
        status_lbl.add_css_class("data-key")
        status_lbl.set_xalign(0.0)
        status_lbl.set_hexpand(True)
        status_lbl.set_wrap(True)
        action.append(status_lbl)
        box.append(action)

        # Also dim the form inputs to reinforce the disabled state.
        for w in (from_entry, to_entry, cap_entry, trit_entry,
                  fleet_radio, squad_radio, topup):
            w.set_sensitive(False)

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        results = Gtk.Grid()
        results.set_column_spacing(8)
        results.set_row_spacing(1)
        results.add_css_class("stats-grid")
        box.append(results)

        self._state["carrier"] = {
            "from":        from_entry,
            "to":          to_entry,
            "capacity":    cap_entry,
            "tritium":     trit_entry,
            "fleet_radio": fleet_radio,
            "squad_radio": squad_radio,
            "topup":       topup,
            "is_neutron":  False,
            "is_carrier":  True,
            "status":      status_lbl,
            "results":     results,
            "in_flight":   False,
            "cap_autofilled": False,
        }
        plot_btn.connect("clicked", lambda _b: self._on_plot_click("carrier"))
        return sc

    # ── Plot dispatch ─────────────────────────────────────────────────────────

    def _on_plot_click(self, name: str) -> None:
        st = self._state.get(name)
        if not st or st["in_flight"]:
            return

        # Pre-fill From with the current system if blank — saves typing.
        src = st["from"].get_text().strip()
        if not src:
            src = (getattr(self.core.state, "pilot_system", None) or "").strip()
            if src:
                st["from"].set_text(src)
        dst = st["to"].get_text().strip()

        if st["is_carrier"]:
            is_squadron = bool(st["squad_radio"].get_active())
            # Total capacity differs by carrier type.  Fleet carriers are
            # 25,000 t; squadron (Javelin-class) carriers are larger.  The
            # exact squadron total capacity isn't publicly documented in a
            # form I can pin down precisely; 50,000 t reflects the wiki's
            # "twice as many landing pads" doubling.  The user can override
            # via the Used cap field — it's the relative mass that matters
            # for jump-range / burn-rate calculations on Spansh's side.
            total_capacity = 50000 if is_squadron else 25000

            cap_str = st["capacity"].get_text().strip()
            if not cap_str:
                st["status"].set_text(
                    "Used capacity required — it's shown top-right of the "
                    "carrier management screen (auto-fills from your "
                    "journal once the scan completes)."
                )
                return
            try:
                capacity_used = int(float(cap_str))
            except ValueError:
                st["status"].set_text("Used capacity must be a number.")
                return
            if not 0 <= capacity_used <= total_capacity:
                st["status"].set_text(
                    f"Used capacity must be 0–{total_capacity:,} t "
                    f"for a {'squadron' if is_squadron else 'fleet'} carrier."
                )
                return
            # Tritium on board — optional, defaults to 0 (Spansh will then
            # calculate the starting fuel itself).
            trit_str = st["tritium"].get_text().strip()
            current_fuel = 0
            if trit_str:
                try:
                    current_fuel = int(float(trit_str))
                except ValueError:
                    st["status"].set_text("Tritium must be a number.")
                    return
                if not 0 <= current_fuel <= 1000:
                    st["status"].set_text("Tritium must be 0–1,000 t.")
                    return
            calc_starting_fuel = bool(st["topup"].get_active())
            if not src or not dst:
                st["status"].set_text("Source and destination required.")
                return
        else:
            range_str = st["range"].get_text().strip()
            if not src or not dst or not range_str:
                st["status"].set_text("Source, destination, and range required.")
                return
            try:
                rng = float(range_str)
            except ValueError:
                st["status"].set_text("Range must be a number.")
                return
            if not 0 < rng <= 1000:
                st["status"].set_text("Range must be 0–1000 ly.")
                return
            eff = 60
            if st["is_neutron"] and st["efficiency"] is not None:
                try:
                    eff = int(st["efficiency"].get_text().strip() or "60")
                except ValueError:
                    st["status"].set_text("Efficiency must be an integer.")
                    return
                if not 1 <= eff <= 100:
                    st["status"].set_text("Efficiency must be 1–100.")
                    return

        # Lock further clicks until the result lands.
        st["in_flight"] = True
        st["status"].set_text("Plotting…")
        self._clear_grid(st["results"])

        def _worker():
            try:
                if st["is_carrier"]:
                    result = self.core.plugin_call(
                        "spansh", "plot_carrier_route",
                        src, dst, capacity_used, total_capacity, current_fuel,
                        calc_starting_fuel,
                    )
                elif st["is_neutron"]:
                    result = self.core.plugin_call(
                        "spansh", "plot_neutron_route",
                        src, dst, rng, eff,
                    )
                else:
                    result = self.core.plugin_call(
                        "spansh", "plot_fsd_route",
                        src, dst, rng,
                    )
            except Exception as exc:
                result = {"_error": f"{type(exc).__name__}: {exc}"}
            GLib.idle_add(self._on_plot_done, name, result)

        threading.Thread(target=_worker, daemon=True,
                         name=f"nav-plot-{name}").start()

    def _on_plot_done(self, name: str, result) -> bool:
        st = self._state[name]
        st["in_flight"] = False

        # Spansh returns either None (the pre-error-dict legacy path, in
        # theory shouldn't happen now) or a dict.  A dict with "_error"
        # carries a useful diagnostic; anything else is a real route.
        if result is None:
            st["status"].set_text(
                "Plot failed — Spansh returned no response. "
                "Check network and try again."
            )
            return False
        if isinstance(result, dict) and result.get("_error"):
            st["status"].set_text(f"Plot failed: {result['_error']}")
            return False

        if st["is_carrier"]:
            self._render_carrier_result(st, result)
        else:
            self._render_ship_result(st, result)
        return False

    def _render_ship_result(self, st: dict, result: dict) -> None:
        """Render an FSD / neutron route.

        Spansh's ship-route response (the inner `result` object) has:
          system_jumps : list of WAYPOINTS — each is a galaxy-map plot,
                         not necessarily a single jump.  Per-waypoint
                         fields: system, distance_jumped (leg distance),
                         distance_left, jumps (ACTUAL FSD jumps to reach
                         this waypoint), neutron_star (bool).
          total_jumps  : count of waypoints / galaxy-map plots.
          distance     : total route distance in ly.

        The important subtlety: total_jumps is the number of galaxy-map
        entries, while the real FSD jump count is the SUM of the per-
        waypoint `jumps` field.  For a neutron route those differ a lot
        (e.g. 129 map plots ≈ 165 actual jumps).
        """
        waypoints = result.get("system_jumps") or result.get("route") or []
        if not waypoints:
            st["status"].set_text(
                "Plot returned no waypoints.  Spansh accepted the job but "
                "produced an empty route — check the system names."
            )
            return

        total_distance = result.get("distance") or result.get("total_distance") or 0
        # Waypoints / galaxy-map plots.
        map_plots = result.get("total_jumps")
        if map_plots is None:
            # start system is usually included as waypoint 0
            map_plots = max(len(waypoints) - 1, 0)
        # Actual FSD jumps = sum of per-waypoint jump counts.
        actual_jumps = sum(int(w.get("jumps", 0) or 0) for w in waypoints)
        neutron_plots = sum(1 for w in waypoints if w.get("neutron_star"))

        if st["is_neutron"]:
            extra = f" · {neutron_plots} via neutron stars" if neutron_plots else ""
            st["status"].set_text(
                f"{map_plots} galaxy-map plots · {actual_jumps} jumps · "
                f"{total_distance:,.0f} ly{extra}"
            )
        elif result.get("_source") == "EDSM":
            # Plain-FSD route from the EDSM router: every waypoint is
            # exactly one jump, so "plots" and "jumps" are the same number
            # — report it plainly.
            st["status"].set_text(
                f"{actual_jumps} jumps · {total_distance:,.0f} ly  "
                f"(via EDSM system data)"
            )
        else:
            st["status"].set_text(
                f"{map_plots} galaxy-map plots · {actual_jumps} jumps · "
                f"{total_distance:,.0f} ly"
            )

        grid = st["results"]
        # Columns: # | System | Leg | Jumps/Note.  "Leg" is the distance
        # to that waypoint; "Jumps" is how many FSD jumps that leg takes
        # (so the user knows a 110 ly leg is several jumps, not one).
        self._add_grid_row(grid, 0, "#", "System", "Leg", "Jumps", header=True)
        for i, w in enumerate(waypoints):
            name  = w.get("system") or w.get("name") or "—"
            leg   = w.get("distance_jumped") or 0
            jcnt  = int(w.get("jumps", 0) or 0)
            if i == 0:
                note = "start"
            elif w.get("neutron_star"):
                note = f"{jcnt}  ★" if jcnt else "★"
            else:
                note = str(jcnt) if jcnt else "—"
            leg_str = _fmt_ly(leg) if leg else ("—" if i == 0 else _fmt_ly(leg))
            self._add_grid_row(grid, i + 1, str(i), name, leg_str, note)

    def _render_carrier_result(self, st: dict, result: dict) -> None:
        """Render a fleet/squadron carrier route.

        Spansh's carrier-route response (inner `result`) has:
          jumps : list of waypoints — each with name, distance (leg ly),
                  distance_to_destination, fuel_used, fuel_in_tank,
                  must_restock (bool/int), restock_amount (tritium to buy),
                  tritium_in_market, has_icy_ring (mineable tritium),
                  is_desired_destination.
          tritium_stored / fuel_loaded / capacity / capacity_used / mass.

        Carrier "jumps" ARE individual carrier jumps (≤500 ly each), so
        unlike the ship routers the waypoint count is the jump count.
        """
        waypoints = result.get("jumps") or []
        if not waypoints:
            st["status"].set_text(
                "Plot returned no waypoints.  Spansh accepted the job but "
                "produced an empty route — check the system names."
            )
            return

        # Last waypoint's distance_to_destination at index 0 is the total.
        total_distance = 0
        if waypoints:
            total_distance = waypoints[0].get("distance_to_destination") or 0
        n_jumps     = max(len(waypoints) - 1, 0)   # exclude the start system
        total_fuel  = sum(int(w.get("fuel_used", 0) or 0) for w in waypoints)
        restocks    = sum(1 for w in waypoints if w.get("must_restock"))
        total_restock = sum(int(w.get("restock_amount", 0) or 0)
                            for w in waypoints if w.get("must_restock"))

        msg = (f"{n_jumps} carrier jumps · {total_distance:,.0f} ly · "
               f"{total_fuel:,} t tritium used")
        if restocks:
            msg += f" · {restocks} refuel stops ({total_restock:,} t)"
        st["status"].set_text(msg)

        grid = st["results"]
        # Columns: # | System | Leg | Tritium/Note
        self._add_grid_row(grid, 0, "#", "System", "Leg", "Tritium", header=True)
        for i, w in enumerate(waypoints):
            name = w.get("name") or w.get("system") or "—"
            leg  = w.get("distance") or 0
            if i == 0:
                note = "start"
            elif w.get("must_restock"):
                amt = int(w.get("restock_amount", 0) or 0)
                ring = " ⛏" if w.get("has_icy_ring") else ""
                note = f"⛽ {amt:,}t{ring}"
            elif w.get("has_icy_ring"):
                note = "⛏ ice"
            else:
                fu = int(w.get("fuel_used", 0) or 0)
                note = f"-{fu}t" if fu else "—"
            leg_str = _fmt_ly(leg) if leg else "—"
            self._add_grid_row(grid, i + 1, str(i), name, leg_str, note)

    def _clear_grid(self, grid: Gtk.Grid) -> None:
        while True:
            ch = grid.get_first_child()
            if ch is None:
                break
            grid.remove(ch)

    def _add_grid_row(self, grid: Gtk.Grid, row: int,
                       col0: str, col1: str, col2: str, col3: str,
                       header: bool = False) -> None:
        css = "section-header" if header else "data-value"
        for col_idx, text, xalign, hexpand in (
            (0, col0, 1.0, False),
            (1, col1, 0.0, True),
            (2, col2, 1.0, False),
            (3, col3, 0.0, False),
        ):
            lbl = Gtk.Label(label=text)
            lbl.add_css_class(css)
            lbl.set_xalign(xalign)
            lbl.set_hexpand(hexpand)
            grid.attach(lbl, col_idx, row, 1, 1)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        # Auto-fill "From" entries with the current system if empty.
        cur = (getattr(self.core.state, "pilot_system", None) or "").strip()
        if cur:
            for st in self._state.values():
                try:
                    if not st["from"].get_text().strip():
                        st["from"].set_text(cur)
                except Exception:
                    pass

        # Auto-fill the carrier tab's used-capacity + tritium from the
        # latest CarrierStats journal event (surfaced by journal_history).
        # Only done once, and only while the user hasn't typed their own
        # value — so we never clobber manual input.
        cst = self._state.get("carrier")
        if cst is not None and not cst.get("cap_autofilled"):
            hist = self.core._plugins.get("journal_history")
            if hist is not None and hist.scan_done.is_set():
                carrier = hist.results.get("carrier", {})
                cstats  = carrier.get("stats", {})
                usage   = cstats.get("SpaceUsage", {}) if cstats else {}
                if usage:
                    used = usage.get("TotalCapacity", 0) - usage.get("FreeSpace", 0)
                    if used > 0 and not cst["capacity"].get_text().strip():
                        cst["capacity"].set_text(str(int(used)))
                # Tritium currently in the carrier's tank.
                fuel = carrier.get("fuel_level") or cstats.get("FuelLevel") or 0
                if fuel and not cst["tritium"].get_text().strip():
                    cst["tritium"].set_text(str(int(fuel)))
                # Carrier type radio — match the journal's CarrierType so a
                # squadron-carrier commander doesn't have to flip the radio
                # every session.  The CarrierType field is "FleetCarrier"
                # for personal carriers; squadron carriers carry a different
                # value (per Vanguards journal docs).
                ctype = (carrier.get("type") or "").lower()
                if ctype.startswith("squadron"):
                    cst["squad_radio"].set_active(True)
                elif ctype:
                    cst["fleet_radio"].set_active(True)
                # Mark done once we've seen a usable CarrierStats snapshot.
                if cstats:
                    cst["cap_autofilled"] = True

"""
gui/blocks/commander.py — Commander, ship, location, powerplay block.

Three-tab layout (matching Assets block pattern):
  Info  — ship identity, vitals (shields/hull/fuel), location, mode, powerplay
  Ranks — CAPI combat/trade/explore/CQC/mercenary/exobio ranks with progress
  Rep   — CAPI superpower reputation (Federation, Empire, Alliance, Independent)

Powerplay stays on the Info tab. Combat rank moves to Ranks tab.
Ranks and Rep tabs are CAPI-sourced; they stay hidden until first poll.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

import threading

from gui.block_base import BlockWidget
from gui.helpers    import hull_css, fmt_shield, pp_rank_progress

_TABS = [
    ("info",   "Info"),
    ("ranks",  "Ranks"),
    ("rep",    "Rep"),
]


class CommanderBlock(BlockWidget):
    BLOCK_TITLE = "Commander"
    BLOCK_CSS   = "commander-block"

    # ── Build ──────────────────────────────────────────────────────────────────

    def build(self, parent: Gtk.Box) -> None:
        # ── Two-line header ───────────────────────────────────────────────────
        hdr_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        # Line 1: CMDR NAME — RANK (left)  |  SHIP TYPE (right)
        hdr_line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._cmdr_header_lbl = Gtk.Label(label="COMMANDER")
        self._cmdr_header_lbl.set_xalign(0.0)
        self._cmdr_header_lbl.set_hexpand(True)
        hdr_line1.append(self._cmdr_header_lbl)
        self._cmdr_ship_type_hdr = Gtk.Label(label="")
        self._cmdr_ship_type_hdr.set_xalign(1.0)
        hdr_line1.append(self._cmdr_ship_type_hdr)
        hdr_outer.append(hdr_line1)

        # Line 2: SQUADRON NAME [TAG] (left)  |  SHIP NAME | IDENT (right)
        hdr_line2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._cmdr_squadron_lbl = Gtk.Label(label="")
        self._cmdr_squadron_lbl.set_xalign(0.0)
        self._cmdr_squadron_lbl.set_hexpand(True)
        self._cmdr_squadron_lbl.set_visible(False)
        self._cmdr_squadron_lbl.add_css_class("section-header")
        hdr_line2.append(self._cmdr_squadron_lbl)
        self._cmdr_ship_ident_hdr = Gtk.Label(label="")
        self._cmdr_ship_ident_hdr.set_xalign(1.0)
        self._cmdr_ship_ident_hdr.set_visible(False)
        self._cmdr_ship_ident_hdr.add_css_class("section-header")
        hdr_line2.append(self._cmdr_ship_ident_hdr)
        self._hdr_line2 = hdr_line2
        hdr_outer.append(hdr_line2)

        body = self._build_section(parent, title_widget=hdr_outer)

        # ── Tab scaffold ──────────────────────────────────────────────────────
        self._layout_stack = Gtk.Stack()
        self._layout_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._layout_stack.set_vexpand(True)
        self._layout_stack.set_hexpand(True)
        body.append(self._layout_stack)

        self._tab_btns:   dict[str, Gtk.Button] = {}
        self._active_tab: str = "info"

        self._build_tabbed_layout()
        self._layout_stack.set_visible_child_name("tabbed")

        # Defer footer home search UI (footer doesn't exist during build())
        self._has_home_search    = False
        self._home_search_timer  = None
        self._home_updating_entry = False
        GLib.idle_add(self._build_footer_home_search)

    # ── Tab scaffold ───────────────────────────────────────────────────────────

    def _build_tabbed_layout(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_vexpand(True)

        tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_bar.add_css_class("mat-tab-bar")
        page.append(tab_bar)
        page.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.NONE)
        stack.set_vexpand(True)
        stack.set_hexpand(True)
        page.append(stack)
        self._tab_stack = stack

        for cat, label in _TABS:
            btn = Gtk.Button()
            btn.add_css_class("mat-tab-btn")
            btn.set_hexpand(True)
            btn.set_can_focus(False)
            tab_bar.append(btn)
            lbl = Gtk.Label(label=label)
            lbl.add_css_class("mat-tab-label")
            btn.set_child(lbl)
            btn.connect("clicked", self._on_tab_click, cat)
            self._tab_btns[cat] = btn

            if cat == "info":
                tab_page = self._build_info_tab()
            elif cat == "ranks":
                tab_page = self._build_ranks_tab()
            else:
                tab_page = self._build_rep_tab()
            stack.add_named(tab_page, cat)

        self._set_active_tab("info")
        self._layout_stack.add_named(page, "tabbed")

    # ── Info tab ───────────────────────────────────────────────────────────────

    def _build_info_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(4)

        # Single shared grid so all key labels size to the same column width
        # and all value labels align perfectly regardless of label length.
        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(2)
        box.append(grid)

        gr = 0   # current grid row index

        def _kv(key_text):
            """Attach a key+value row to the shared grid; return (key_label, value_label)."""
            nonlocal gr
            k = self.make_label(key_text, css_class="data-key")
            k.set_xalign(0.0)
            grid.attach(k, 0, gr, 1, 1)
            v = self.make_label("—", css_class="data-value")
            v.set_xalign(1.0)
            v.set_hexpand(True)
            grid.attach(v, 1, gr, 1, 1)
            gr += 1
            return v, k

        def _sep():
            """Full-width separator spanning both grid columns."""
            nonlocal gr
            s = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            s.add_css_class("vitals-sep")
            grid.attach(s, 0, gr, 2, 1)
            gr += 1

        def _bar_row(bar_widget):
            """Full-width progress bar row spanning both grid columns."""
            nonlocal gr
            wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            wrap.add_css_class("pp-rank-bar-row")
            bar_widget.set_hexpand(True)
            wrap.append(bar_widget)
            grid.attach(wrap, 0, gr, 2, 1)
            gr += 1

        self._cmdr_shields, self._cmdr_shields_key = _kv("Shields")
        self._cmdr_hull,    self._cmdr_hull_key    = _kv("Hull")
        self._cmdr_fuel                            = _kv("Fuel")[0]

        _sep()

        self._cmdr_mode     = _kv("Mode")[0]
        self._cmdr_home     = _kv("Home System")[0]
        self._cmdr_system   = _kv("Current System")[0]
        self._cmdr_location = _kv("Location")[0]
        self._cmdr_pp       = _kv("Power")[0]
        self._cmdr_pprank   = _kv("PP Rank")[0]

        self._pp_rank_bar = Gtk.ProgressBar()
        self._pp_rank_bar.set_fraction(0.0)
        self._pp_rank_bar.add_css_class("pp-rank-bar")
        self._pp_rank_bar.set_show_text(False)
        self._pp_rank_bar.set_size_request(40, 4)
        _bar_row(self._pp_rank_bar)

        return box

    # ── Home location footer search ───────────────────────────────────────────

    def _build_footer_home_search(self) -> bool:
        """Idle callback: insert home location search widgets into footer."""
        ft = self.footer()
        if ft is None:
            return False
        if self._get_commander_plugin() is None:
            return False
        self._has_home_search = True

        # Entry
        self._home_entry = Gtk.Entry()
        self._home_entry.set_placeholder_text("Set Home Location…")
        self._home_entry.set_width_chars(16)
        self._home_entry.set_hexpand(False)
        self._home_entry.set_valign(Gtk.Align.CENTER)
        self._home_entry.add_css_class("data-entry")
        self._home_entry.connect("activate", self._on_home_activate)
        self._home_entry.connect("changed",  self._on_home_changed)
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", lambda c, k, hw, mod: False)
        self._home_entry.add_controller(key_ctrl)

        # Clear button
        self._home_clear_btn = Gtk.Button(label="✕")
        self._home_clear_btn.add_css_class("cmdr-footer-btn")
        self._home_clear_btn.add_css_class("cargo-clear-btn")
        self._home_clear_btn.set_can_focus(False)
        self._home_clear_btn.set_sensitive(False)
        self._home_clear_btn.set_tooltip_text("Clear home location")
        self._home_clear_btn.connect("clicked", self._on_home_clear_clicked)

        # Autocomplete popover
        self._home_popover = Gtk.Popover()
        self._home_popover.set_autohide(True)
        self._home_popover.set_has_arrow(False)
        self._home_popover.set_parent(self._home_entry)
        self._home_popover.set_position(Gtk.PositionType.TOP)
        self._home_results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._home_popover.set_child(self._home_results_box)

        ft.prepend(self._home_clear_btn)
        ft.prepend(self._home_entry)

        # Populate entry if home already set
        plugin = self._get_commander_plugin()
        if plugin:
            home = plugin.get_home_location()
            if home:
                self._home_updating_entry = True
                self._home_entry.set_text("")
                self._home_updating_entry = False
                self._home_clear_btn.set_sensitive(True)
        return False

    def _on_home_changed(self, entry: Gtk.Entry) -> None:
        if not self._has_home_search or self._home_updating_entry:
            return
        text = entry.get_text().strip()
        self._home_clear_btn.set_sensitive(bool(text))
        if self._home_search_timer:
            GLib.source_remove(self._home_search_timer)
        if len(text) < 3:
            self._home_popover.popdown()
            return
        self._home_search_timer = GLib.timeout_add(400, self._do_home_search_bg, text)

    def _on_home_activate(self, entry: Gtk.Entry) -> None:
        if self._home_search_timer:
            GLib.source_remove(self._home_search_timer)
            self._home_search_timer = None
        text = entry.get_text().strip()
        if len(text) >= 3:
            self._home_popover.popdown()
            self._fetch_home(text)

    def _on_home_clear_clicked(self, btn: Gtk.Button) -> None:
        self._home_updating_entry = True
        self._home_entry.set_text("")
        self._home_updating_entry = False
        self._home_clear_btn.set_sensitive(False)
        self._home_popover.popdown()
        plugin = self._get_commander_plugin()
        if plugin:
            plugin.clear_home_location()
        root = self._home_entry.get_root()
        if root and hasattr(root, "set_focus"):
            root.set_focus(None)
        self.refresh()

    def _do_home_search_bg(self, query: str) -> bool:
        self._home_search_timer = None
        def _run():
            try:
                spansh = self._get_spansh()
                if not spansh:
                    return
                results = spansh.search_home(query)
                GLib.idle_add(self._show_home_results, results)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True, name="spansh-home-search").start()
        return False

    def _show_home_results(self, results: list) -> bool:
        child = self._home_results_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._home_results_box.remove(child)
            child = nxt
        if not results:
            lbl = Gtk.Label(label="No results found")
            lbl.add_css_class("data-key")
            lbl.set_margin_start(8); lbl.set_margin_end(8)
            lbl.set_margin_top(4);   lbl.set_margin_bottom(4)
            self._home_results_box.append(lbl)
            self._home_popover.popup()
            return False
        for r in results:
            is_stn = r.get("is_station", False)
            system = r.get("system", "")
            prefix = "🚉 " if is_stn else "⭐ "
            label  = f"{prefix}{r['name']}"
            if is_stn and system and system != r["name"]:
                label += f"  |  {system}"
            btn = Gtk.Button(label=label)
            btn.add_css_class("mat-tab-btn")
            btn.set_can_focus(False)
            btn.connect("clicked", self._on_home_result_picked, r)
            self._home_results_box.append(btn)
        self._home_popover.popup()
        return False

    def _on_home_result_picked(self, btn, result: dict) -> None:
        self._home_popover.popdown()
        name     = result["name"]
        system   = result.get("system", name)
        star_pos = result.get("star_pos")
        self._home_updating_entry = True
        self._home_entry.set_text("")
        self._home_updating_entry = False
        self._home_clear_btn.set_sensitive(True)
        plugin = self._get_commander_plugin()
        if plugin:
            plugin.set_home_location(name, system, star_pos)
        # Surrender focus back to the window so the entry loses its cursor
        root = self._home_entry.get_root()
        if root and hasattr(root, "set_focus"):
            root.set_focus(None)
        self.refresh()

    def _fetch_home(self, query: str) -> None:
        """Fetch home by name when user presses Enter (no popover selection)."""
        def _run():
            try:
                spansh = self._get_spansh()
                if not spansh:
                    return
                results = spansh.search_home(query)
                if results:
                    GLib.idle_add(self._on_home_result_picked, None, results[0])
                # No result: popover will have shown "No results found" already
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True, name="spansh-home-fetch").start()

    def _get_commander_plugin(self):
        try:
            return self.core._plugins.get("commander")
        except Exception:
            return None

    def _get_spansh(self):
        try:
            return self.core._plugins.get("spansh")
        except Exception:
            return None

        # ── Ranks tab ──────────────────────────────────────────────────────────────

    def _build_ranks_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_vexpand(True)
        box.set_margin_top(4)
        box.set_margin_end(12)   # clear GTK4 overlay scrollbar track
        scroll.set_child(box)

        self._no_ranks_lbl = Gtk.Label(label="Awaiting CAPI data…")
        self._no_ranks_lbl.add_css_class("data-key")
        self._no_ranks_lbl.set_xalign(0.5)
        self._no_ranks_lbl.set_margin_top(8)
        box.append(self._no_ranks_lbl)

        # Shared grid: all rank key labels share column 0 so values align.
        # Each rank occupies two grid rows: text row + progress-bar row.
        rank_grid = Gtk.Grid()
        rank_grid.set_column_spacing(8)
        rank_grid.set_row_spacing(2)
        rank_grid.set_margin_top(2)
        box.append(rank_grid)

        # dict: capi_key -> (key_label, value_label, progress_bar, bar_wrapper)
        self._rank_rows: dict = {}
        _gr = 0

        from core.state import CAPI_RANK_SKILLS
        for capi_key, display_label, _table in CAPI_RANK_SKILLS:
            k = self.make_label(display_label, css_class="data-key")
            k.set_xalign(0.0)
            k.set_visible(False)
            rank_grid.attach(k, 0, _gr, 1, 1)

            v = self.make_label("—", css_class="data-value")
            v.set_xalign(1.0)
            v.set_hexpand(True)
            v.set_visible(False)
            rank_grid.attach(v, 1, _gr, 1, 1)
            _gr += 1

            bar = Gtk.ProgressBar()
            bar.set_fraction(0.0)
            bar.add_css_class("pp-rank-bar")
            bar.set_show_text(False)
            bar.set_size_request(40, 3)
            bar.set_hexpand(True)
            bar_wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            bar_wrap.add_css_class("pp-rank-bar-row")
            bar_wrap.append(bar)
            bar_wrap.set_visible(False)
            rank_grid.attach(bar_wrap, 0, _gr, 2, 1)
            _gr += 1

            self._rank_rows[capi_key] = (k, v, bar, bar_wrap)

        # Engineer ranks section (dynamic rows built in refresh)
        eng_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        eng_sep.set_margin_top(6)
        box.append(eng_sep)
        self._eng_hdr = Gtk.Label(label="ENGINEERS")
        self._eng_hdr.add_css_class("data-key")
        self._eng_hdr.set_xalign(0.0)
        self._eng_hdr.set_margin_top(4)
        self._eng_hdr.set_margin_bottom(2)
        self._eng_hdr.set_visible(False)
        box.append(self._eng_hdr)
        self._eng_none_lbl = Gtk.Label(label="No engineers unlocked yet")
        self._eng_none_lbl.add_css_class("data-key")
        self._eng_none_lbl.set_xalign(0.5)
        self._eng_none_lbl.set_margin_top(4)
        box.append(self._eng_none_lbl)
        self._eng_rows: dict = {}   # name -> (row_box, val_lbl, bar, bar_wrap)
        self._eng_box  = box

        return scroll

    # ── Rep tab ────────────────────────────────────────────────────────────────

    def _build_rep_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_vexpand(True)
        box.set_margin_top(4)
        box.set_margin_end(12)   # clear GTK4 overlay scrollbar track
        scroll.set_child(box)

        self._no_rep_lbl = Gtk.Label(label="Awaiting login data…")
        self._no_rep_lbl.add_css_class("data-key")
        self._no_rep_lbl.set_xalign(0.5)
        self._no_rep_lbl.set_margin_top(8)
        box.append(self._no_rep_lbl)

        # ── Major factions ────────────────────────────────────────────────────
        major_hdr = Gtk.Label(label="MAJOR FACTIONS")
        major_hdr.add_css_class("section-sub-header")
        major_hdr.set_xalign(0.0)
        major_hdr.set_margin_top(4)
        major_hdr.set_margin_bottom(2)
        box.append(major_hdr)
        self._major_hdr = major_hdr

        self._rep_rows: dict[str, Gtk.Label] = {}
        for faction in ("Federation", "Empire", "Alliance", "Independent"):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            row.add_css_class("data-row")
            k = self.make_label(faction, css_class="data-key")
            k.set_hexpand(False)
            row.append(k)
            v = self.make_label("—", css_class="data-value")
            v.set_hexpand(True)
            v.set_xalign(1.0)
            row.append(v)
            row.set_visible(False)
            box.append(row)
            self._rep_rows[faction] = v

        # ── Minor factions (current system, populated from FSDJump/Location) ──
        minor_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        minor_sep.add_css_class("vitals-sep")
        minor_sep.set_margin_top(4)
        box.append(minor_sep)
        self._minor_sep = minor_sep

        minor_hdr = Gtk.Label(label="LOCAL FACTIONS")
        minor_hdr.add_css_class("section-sub-header")
        minor_hdr.set_xalign(0.0)
        minor_hdr.set_margin_top(2)
        minor_hdr.set_margin_bottom(2)
        box.append(minor_hdr)
        self._minor_hdr = minor_hdr

        self._minor_none_lbl = Gtk.Label(label="Jump to a system to see local standings")
        self._minor_none_lbl.add_css_class("data-key")
        self._minor_none_lbl.set_xalign(0.5)
        self._minor_none_lbl.set_wrap(True)
        self._minor_none_lbl.set_margin_top(4)
        box.append(self._minor_none_lbl)

        # Minor faction rows are built dynamically in refresh()
        self._minor_rep_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._minor_rep_box.set_visible(False)
        box.append(self._minor_rep_box)
        self._minor_rep_rows: dict[str, Gtk.Label] = {}

        return scroll

    # ── Tab switching ──────────────────────────────────────────────────────────

    def _on_tab_click(self, _btn, cat: str) -> None:
        self._set_active_tab(cat)

    def _set_active_tab(self, cat: str) -> None:
        self._active_tab = cat
        self._tab_stack.set_visible_child_name(cat)
        for key, btn in self._tab_btns.items():
            if key == cat:
                btn.add_css_class("mat-tab-active")
            else:
                btn.remove_css_class("mat-tab-active")

    def on_resize(self, w: int, h: int) -> None:
        super().on_resize(w, h)

    # ── Refresh ────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        s = self.state

        # ── Header ────────────────────────────────────────────────────────────
        sq_rank = getattr(s, "pilot_squadron_rank", "")
        sq_name = getattr(s, "pilot_squadron_name", "")
        sq_tag  = getattr(s, "pilot_squadron_tag",  "")

        if s.pilot_name:
            # Line 1: full caps — "CMDR NAME — SQUADRON RANK"
            if sq_rank:
                lbl = f"CMDR {s.pilot_name}  —  {sq_rank.upper()}"
            elif s.cmdr_in_slf:
                lbl = f"CMDR {s.pilot_name}  [IN FIGHTER]"
            elif getattr(s, "vessel_mode", "ship") == "on_foot":
                lbl = f"CMDR {s.pilot_name}  [ON FOOT]"
            elif getattr(s, "vessel_mode", "ship") == "srv":
                lbl = f"CMDR {s.pilot_name}  [IN SRV]"
            else:
                lbl = f"CMDR {s.pilot_name}"
            self._cmdr_header_lbl.set_label(lbl)
        else:
            self._cmdr_header_lbl.set_label("COMMANDER")
        # Right side of header line 1 and line 2 depend on vehicle mode
        vessel_mode  = getattr(s, "vessel_mode",  "ship")
        srv_type     = getattr(s, "srv_type",     "")
        suit_name    = getattr(s, "suit_name",    "")
        suit_loadout = getattr(s, "suit_loadout", "")

        if vessel_mode == "on_foot":
            self._cmdr_ship_type_hdr.set_label(suit_name.upper() if suit_name else "ON FOOT")
            ident_str = suit_loadout.upper() if suit_loadout else ""
        elif vessel_mode == "srv":
            self._cmdr_ship_type_hdr.set_label(srv_type.upper() if srv_type else "SRV")
            ident_str = ""
        else:
            self._cmdr_ship_type_hdr.set_label((s.pilot_ship or "").upper())
            parts = [p for p in [s.ship_name, s.ship_ident] if p]
            ident_str = " | ".join(parts)

        if ident_str:
            self._cmdr_ship_ident_hdr.set_label(ident_str)
            self._cmdr_ship_ident_hdr.set_visible(True)
        else:
            self._cmdr_ship_ident_hdr.set_visible(False)

        # Line 2 visibility: show if squadron or ship ident is present
        if sq_name:
            tag_str = f"  [{sq_tag.upper()}]" if sq_tag else ""
            self._cmdr_squadron_lbl.set_label(f"{sq_name.upper()}{tag_str}")
            self._cmdr_squadron_lbl.set_visible(True)
        else:
            self._cmdr_squadron_lbl.set_visible(False)
        # Show line2 box if either child is visible
        self._hdr_line2.set_visible(
            self._cmdr_squadron_lbl.get_visible() or
            self._cmdr_ship_ident_hdr.get_visible()
        )

        # ── Info tab: Mode ────────────────────────────────────────────────────
        self._cmdr_mode.set_label(s.pilot_mode or "—")

        # ── Info tab: Current System ──────────────────────────────────────────────────
        if s.pilot_system:
            self._cmdr_system.set_label(s.pilot_system)
            self._cmdr_system.get_parent().set_visible(True)
        else:
            self._cmdr_system.set_label("—")
            self._cmdr_system.get_parent().set_visible(False)

        # ── Info tab: Home System ────────────────────────────────────────────────────
        cmdr_plugin = self.core._plugins.get("commander") if self.core else None
        if cmdr_plugin:
            home = cmdr_plugin.get_home_location()
            if home:
                home_name    = home["name"]
                home_system  = home.get("system", home_name)
                home_star_pos = home.get("star_pos")
                # Format: SYSTEM or STATION (SYSTEM)
                is_station   = home.get("is_station", home_name != home_system and bool(home_system))
                if is_station and home_system and home_system != home_name:
                    display = f"{home_name}  ({home_system})"
                else:
                    display = home_name
                # Append distance if current position is known
                dist = cmdr_plugin.home_distance_ly(getattr(s, "pilot_star_pos", None))
                if dist is not None:
                    display += f"  |  {dist:,.0f} ly away"
                self._cmdr_home.set_label(display)
                self._cmdr_home.get_parent().set_visible(True)
            else:
                self._cmdr_home.set_label("unknown")
                self._cmdr_home.get_parent().set_visible(True)
        else:
            self._cmdr_home.get_parent().set_visible(False)

        # ── Info tab: Location ────────────────────────────────────────────────────
        if s.pilot_body:
            body_str = s.pilot_body
            if s.pilot_system and body_str.startswith(s.pilot_system):
                body_str = body_str[len(s.pilot_system):].lstrip()
            self._cmdr_location.set_label(body_str or "—")
            self._cmdr_location.get_parent().set_visible(True)
        else:
            self._cmdr_location.set_label("—")
            self._cmdr_location.get_parent().set_visible(False)

        # ── Info tab: Fuel ────────────────────────────────────────────────────
        fuel_current = s.fuel_current
        fuel_tank    = s.fuel_tank_size
        if fuel_current is not None and fuel_tank and fuel_tank > 0:
            fuel_pct = fuel_current / fuel_tank * 100
            fuel_str = f"{fuel_pct:.0f}%"
            burn = getattr(s, "fuel_burn_rate", None)
            if burn and burn > 0:
                secs_remain = (fuel_current / burn) * 3600
                h_rem = int(secs_remain // 3600)
                m_rem = int((secs_remain % 3600) // 60)
                if h_rem > 0:
                    fuel_str += f"  (~{h_rem}h {m_rem}m)"
                else:
                    fuel_str += f"  (~{m_rem}m)"
            self._cmdr_fuel.set_label(fuel_str)
            self._cmdr_fuel.get_parent().set_visible(True)
            from core.state import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD
            for cls in ("health-good", "health-warn", "health-crit"):
                self._cmdr_fuel.remove_css_class(cls)
            if fuel_current < fuel_tank * FUEL_CRIT_THRESHOLD:
                self._cmdr_fuel.add_css_class("health-crit")
            elif fuel_current < fuel_tank * FUEL_WARN_THRESHOLD:
                self._cmdr_fuel.add_css_class("health-warn")
            else:
                self._cmdr_fuel.add_css_class("health-good")
        else:
            self._cmdr_fuel.get_parent().set_visible(False)

        # ── Info tab: Powerplay ───────────────────────────────────────────────
        has_power = bool(s.pp_power)
        self._cmdr_pp.get_parent().set_visible(has_power)
        self._cmdr_pprank.get_parent().set_visible(has_power)
        self._cmdr_pp.set_label(s.pp_power or "—")

        if s.pp_rank:
            merits = s.pp_merits_total
            if merits is not None:
                fraction, earned, span, next_rank = pp_rank_progress(s.pp_rank, merits)
                pct     = int(fraction * 100)
                pp_lbl  = f"Rank {s.pp_rank}  {pct}%"
                tooltip = (
                    f"{earned:,} / {span:,} merits to Rank {next_rank} "
                    f"({span - earned:,} remaining)"
                )
            else:
                pp_lbl   = f"Rank {s.pp_rank}"
                fraction = 0.0
                tooltip  = "Earn merits to populate progress"
            self._cmdr_pprank.set_label(pp_lbl)
            self._pp_rank_bar.set_fraction(fraction)
            self._pp_rank_bar.set_tooltip_text(tooltip)
            self._pp_rank_bar.set_visible(True)
        else:
            self._cmdr_pprank.set_label("—")
            self._pp_rank_bar.set_fraction(0.0)
            self._pp_rank_bar.set_visible(False)

        # ── Info tab: Shields / Hull — context-aware ─────────────────────────
        vm = getattr(s, "vessel_mode", "ship")

        # Update Shields label
        for cls in ("health-good", "health-warn", "health-crit"):
            self._cmdr_shields.remove_css_class(cls)
        if vm == "on_foot":
            suit_up = getattr(s, "suit_shields", True)
            self._cmdr_shields.set_label("Up" if suit_up else "Down")
            self._cmdr_shields.add_css_class("health-good" if suit_up else "health-crit")
        elif vm == "srv":
            # SRVs have no shields
            self._cmdr_shields.set_label("—")
        else:
            shield_str = fmt_shield(s.ship_shields, s.ship_shields_recharging)
            self._cmdr_shields.set_label(shield_str)
            if s.ship_shields is None:
                pass
            elif not s.ship_shields:
                self._cmdr_shields.add_css_class(
                    "health-warn" if s.ship_shields_recharging else "health-crit"
                )
            else:
                self._cmdr_shields.add_css_class("health-good")

        # Update Hull label — show SRV hull when in SRV, hide when on foot
        for cls in ("health-good", "health-warn", "health-crit"):
            self._cmdr_hull.remove_css_class(cls)
        if vm == "on_foot":
            # On-foot health not available from journal alone
            self._cmdr_hull.set_label("—")
        elif vm == "srv":
            hull_pct = getattr(s, "srv_hull", 100)
            self._cmdr_hull.set_label(f"{hull_pct}%")
            self._cmdr_hull.add_css_class(hull_css(hull_pct))
        else:
            hull_pct = s.ship_hull
            self._cmdr_hull.set_label(f"{hull_pct}%" if hull_pct is not None else "—")
            if hull_pct is not None:
                self._cmdr_hull.add_css_class(hull_css(hull_pct))

        # Update hull row key label to match vehicle context
        self._cmdr_hull_key.set_label("Health" if vm == "on_foot" else "Hull")

        # ── Home location footer search ───────────────────────────────────────────

    def _build_footer_home_search(self) -> bool:
        """Idle callback: insert home location search widgets into footer."""
        ft = self.footer()
        if ft is None:
            return False
        if self._get_commander_plugin() is None:
            return False
        self._has_home_search = True

        # Entry
        self._home_entry = Gtk.Entry()
        self._home_entry.set_placeholder_text("Set Home Location…")
        self._home_entry.set_width_chars(16)
        self._home_entry.set_hexpand(False)
        self._home_entry.set_valign(Gtk.Align.CENTER)
        self._home_entry.add_css_class("data-entry")
        self._home_entry.connect("activate", self._on_home_activate)
        self._home_entry.connect("changed",  self._on_home_changed)
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", lambda c, k, hw, mod: False)
        self._home_entry.add_controller(key_ctrl)

        # Clear button
        self._home_clear_btn = Gtk.Button(label="✕")
        self._home_clear_btn.add_css_class("cmdr-footer-btn")
        self._home_clear_btn.add_css_class("cargo-clear-btn")
        self._home_clear_btn.set_can_focus(False)
        self._home_clear_btn.set_sensitive(False)
        self._home_clear_btn.set_tooltip_text("Clear home location")
        self._home_clear_btn.connect("clicked", self._on_home_clear_clicked)

        # Autocomplete popover
        self._home_popover = Gtk.Popover()
        self._home_popover.set_autohide(True)
        self._home_popover.set_has_arrow(False)
        self._home_popover.set_parent(self._home_entry)
        self._home_popover.set_position(Gtk.PositionType.TOP)
        self._home_results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._home_popover.set_child(self._home_results_box)

        ft.prepend(self._home_clear_btn)
        ft.prepend(self._home_entry)

        # Populate entry if home already set
        plugin = self._get_commander_plugin()
        if plugin:
            home = plugin.get_home_location()
            if home:
                self._home_updating_entry = True
                self._home_entry.set_text("")
                self._home_updating_entry = False
                self._home_clear_btn.set_sensitive(True)
        return False

    def _on_home_changed(self, entry: Gtk.Entry) -> None:
        if not self._has_home_search or self._home_updating_entry:
            return
        text = entry.get_text().strip()
        self._home_clear_btn.set_sensitive(bool(text))
        if self._home_search_timer:
            GLib.source_remove(self._home_search_timer)
        if len(text) < 3:
            self._home_popover.popdown()
            return
        self._home_search_timer = GLib.timeout_add(400, self._do_home_search_bg, text)

    def _on_home_activate(self, entry: Gtk.Entry) -> None:
        if self._home_search_timer:
            GLib.source_remove(self._home_search_timer)
            self._home_search_timer = None
        text = entry.get_text().strip()
        if len(text) >= 3:
            self._home_popover.popdown()
            self._fetch_home(text)

    def _on_home_clear_clicked(self, btn: Gtk.Button) -> None:
        self._home_updating_entry = True
        self._home_entry.set_text("")
        self._home_updating_entry = False
        self._home_clear_btn.set_sensitive(False)
        self._home_popover.popdown()
        plugin = self._get_commander_plugin()
        if plugin:
            plugin.clear_home_location()
        root = self._home_entry.get_root()
        if root and hasattr(root, "set_focus"):
            root.set_focus(None)
        self.refresh()

    def _do_home_search_bg(self, query: str) -> bool:
        self._home_search_timer = None
        def _run():
            try:
                spansh = self._get_spansh()
                if not spansh:
                    return
                results = spansh.search_home(query)
                GLib.idle_add(self._show_home_results, results)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True, name="spansh-home-search").start()
        return False

    def _show_home_results(self, results: list) -> bool:
        child = self._home_results_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._home_results_box.remove(child)
            child = nxt
        if not results:
            lbl = Gtk.Label(label="No results found")
            lbl.add_css_class("data-key")
            lbl.set_margin_start(8); lbl.set_margin_end(8)
            lbl.set_margin_top(4);   lbl.set_margin_bottom(4)
            self._home_results_box.append(lbl)
            self._home_popover.popup()
            return False
        for r in results:
            is_stn = r.get("is_station", False)
            system = r.get("system", "")
            prefix = "🚉 " if is_stn else "⭐ "
            label  = f"{prefix}{r['name']}"
            if is_stn and system and system != r["name"]:
                label += f"  |  {system}"
            btn = Gtk.Button(label=label)
            btn.add_css_class("mat-tab-btn")
            btn.set_can_focus(False)
            btn.connect("clicked", self._on_home_result_picked, r)
            self._home_results_box.append(btn)
        self._home_popover.popup()
        return False

    def _on_home_result_picked(self, btn, result: dict) -> None:
        self._home_popover.popdown()
        name     = result["name"]
        system   = result.get("system", name)
        star_pos = result.get("star_pos")
        self._home_updating_entry = True
        self._home_entry.set_text("")
        self._home_updating_entry = False
        self._home_clear_btn.set_sensitive(True)
        plugin = self._get_commander_plugin()
        if plugin:
            plugin.set_home_location(name, system, star_pos)
        # Surrender focus back to the window so the entry loses its cursor
        root = self._home_entry.get_root()
        if root and hasattr(root, "set_focus"):
            root.set_focus(None)
        self.refresh()

    def _fetch_home(self, query: str) -> None:
        """Fetch home by name when user presses Enter (no popover selection)."""
        def _run():
            try:
                spansh = self._get_spansh()
                if not spansh:
                    return
                results = spansh.search_home(query)
                if results:
                    GLib.idle_add(self._on_home_result_picked, None, results[0])
                # No result: popover will have shown "No results found" already
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True, name="spansh-home-fetch").start()

    def _get_commander_plugin(self):
        try:
            return self.core._plugins.get("commander")
        except Exception:
            return None

    def _get_spansh(self):
        try:
            return self.core._plugins.get("spansh")
        except Exception:
            return None

        # ── Ranks tab ─────────────────────────────────────────────────────────
        capi_ranks    = getattr(s, "capi_ranks",    None)
        capi_progress = getattr(s, "capi_progress", None)
        has_ranks = bool(capi_ranks)
        self._no_ranks_lbl.set_visible(not has_ranks)

        if has_ranks:
            from core.state import CAPI_RANK_SKILLS
            for capi_key, _display, table in CAPI_RANK_SKILLS:
                k_lbl, v_lbl, bar, bar_wrap = self._rank_rows[capi_key]
                idx = capi_ranks.get(capi_key)
                if idx is None:
                    k_lbl.set_visible(False)
                    v_lbl.set_visible(False)
                    bar_wrap.set_visible(False)
                    continue
                rank_name = table[idx] if 0 <= idx < len(table) else str(idx)
                prog      = (capi_progress or {}).get(capi_key)
                pct_str   = f" +{prog}%" if prog is not None else ""
                v_lbl.set_label(f"{rank_name}{pct_str}")
                k_lbl.set_visible(True)
                v_lbl.set_visible(True)
                if prog is not None:
                    bar.set_fraction(min(prog / 100.0, 1.0))
                    bar_wrap.set_visible(True)
                else:
                    bar_wrap.set_visible(False)

        # ── Rep tab ───────────────────────────────────────────────────────────
        # Engineer ranks (from CAPI capi_engineer_ranks)
        # Journal EngineerProgress (pilot_engineer_ranks) is primary — fires at every
        # login with full data. Fall back to CAPI if journal hasn't fired yet.
        eng_data = getattr(s, "pilot_engineer_ranks", None) or \
                   getattr(s, "capi_engineer_ranks", None) or []
        unlocked = [e for e in eng_data if e.get("unlocked")]
        self._eng_hdr.set_visible(bool(unlocked))
        self._eng_none_lbl.set_visible(not bool(unlocked))
        seen_eng: set = set()
        for eng in sorted(unlocked, key=lambda e: (-(e.get("rank") or 0), e.get("name", ""))):
            name = eng.get("name", "")
            if not name:
                continue
            seen_eng.add(name)
            rank    = eng.get("rank") or 0
            prog    = eng.get("progress")
            val_str = f"G{rank}" if rank else "Invited"
            if prog is not None and rank < 5:
                val_str += f" +{prog}%"
            if name not in self._eng_rows:
                erow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                erow.add_css_class("data-row")
                ek = self.make_label(name, css_class="data-key")
                ek.set_hexpand(False)
                erow.append(ek)
                evl = self.make_label("—", css_class="data-value")
                evl.set_hexpand(True)
                evl.set_xalign(1.0)
                erow.append(evl)
                ebar = Gtk.ProgressBar()
                ebar.set_fraction(0.0)
                ebar.add_css_class("pp-rank-bar")
                ebar.set_show_text(False)
                ebar.set_size_request(40, 3)
                ebar.set_hexpand(True)
                ebw = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
                ebw.add_css_class("pp-rank-bar-row")
                ebw.append(ebar)
                ebw.set_visible(False)
                self._eng_box.append(erow)
                self._eng_box.append(ebw)
                self._eng_rows[name] = (erow, evl, ebar, ebw)
            _, evl, ebar, ebw = self._eng_rows[name]
            evl.set_label(val_str)
            if prog is not None and rank < 5:
                ebar.set_fraction(min(prog / 100.0, 1.0))
                ebw.set_visible(True)
            else:
                ebw.set_visible(False)
        for name, (erow, _evl, _eb, ebw) in self._eng_rows.items():
            erow.set_visible(name in seen_eng)
            if name not in seen_eng:
                ebw.set_visible(False)

    # Major faction standing: Journal Reputation event is primary;
        # fall back to capi_reputation when journal not yet available.
        pilot_rep = getattr(s, "pilot_reputation", None) or {}
        if not pilot_rep:
            _capi_rep = getattr(s, "capi_reputation", None) or {}
            pilot_rep = {k.title(): v for k, v in _capi_rep.items()}
        has_rep   = bool(pilot_rep)
        self._no_rep_lbl.set_visible(not has_rep)
        self._major_hdr.set_visible(has_rep)
        self._minor_sep.set_visible(has_rep)
        self._minor_hdr.set_visible(has_rep)

        for faction, v_lbl in self._rep_rows.items():
            val = (pilot_rep or {}).get(faction)
            if val is not None:
                v_lbl.set_label(f"{val:.1f}%")
                v_lbl.get_parent().set_visible(True)
            else:
                v_lbl.get_parent().set_visible(False)

        # Minor/local faction standing: FSDJump/Location Factions[].MyReputation
        minor_rep = getattr(s, "pilot_minor_reputation", None)
        if minor_rep:
            self._minor_none_lbl.set_visible(False)
            self._minor_rep_box.set_visible(True)
            seen = set()
            for name, val in sorted(minor_rep.items(), key=lambda kv: -kv[1]):
                seen.add(name)
                if name not in self._minor_rep_rows:
                    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                    row.add_css_class("data-row")
                    k = self.make_label(name, css_class="data-key")
                    k.set_hexpand(False)
                    row.append(k)
                    v = self.make_label("—", css_class="data-value")
                    v.set_hexpand(True)
                    v.set_xalign(1.0)
                    row.append(v)
                    self._minor_rep_box.append(row)
                    self._minor_rep_rows[name] = v
                self._minor_rep_rows[name].set_label(f"{val:.1f}%")
            # Hide rows for factions no longer in current system
            for name, v_lbl in self._minor_rep_rows.items():
                v_lbl.get_parent().set_visible(name in seen)
        else:
            self._minor_none_lbl.set_visible(has_rep)
            self._minor_rep_box.set_visible(False)

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Zero all progress bars before window teardown — prevents GTK gizmo warning."""
        if hasattr(self, "_pp_rank_bar"):
            self._pp_rank_bar.set_fraction(0.0)
            self._pp_rank_bar.set_visible(False)
        if hasattr(self, "_rank_rows"):
            for _k_lbl, _lbl, bar, bar_wrap in self._rank_rows.values():
                bar.set_fraction(0.0)
                bar_wrap.set_visible(False)
        if hasattr(self, "_eng_rows"):
            for _row, _lbl, bar, bar_wrap in self._eng_rows.values():
                bar.set_fraction(0.0)
                bar_wrap.set_visible(False)

"""
gui/blocks/cargo.py — Cargo hold inventory block.

Target market search is in the block footer (left of the resize handle) so it
sits outside the draggable grid area and cannot cause focus lock.

Footer layout:  [Entry "Target market…"] [✓ green] [✕ red]  [spacer]  [⤡]

Column layout (self._cargo_grid — NOT self._grid):
  0  name     hexpand
  1  qty      fixed _W_QTY  margin_end _M_QTY
  2  sell     fixed _W_SELL  (last docked station)
  3  target   fixed _W_TGT   (Spansh target OR Gal. Avg when none set)
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Pango, GLib
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

import threading
from gui.block_base import BlockWidget

_W_QTY  = 46
_W_SELL = 82
_W_TGT  = 82
_M_QTY  = 8


def _fmt_cr(val) -> str:
    if not val: return "—"
    if val >= 1_000_000_000: return f"{val/1_000_000_000:.1f}B"
    if val >= 1_000_000:     return f"{val/1_000_000:.1f}M"
    if val >= 1_000:         return f"{val/1_000:.0f}K"
    return f"{int(val):,}"


def _lbl(text="", xalign=0.0, css="data-value", hexpand=False,
         width=-1, margin_end=0, ellipsize=False) -> Gtk.Label:
    l = Gtk.Label(label=text)
    l.set_xalign(xalign)
    l.add_css_class(css)
    l.set_hexpand(hexpand)
    if width > 0:
        l.set_size_request(width, -1)
        l.set_hexpand(False)
    if margin_end:
        l.set_margin_end(margin_end)
    if ellipsize:
        l.set_ellipsize(Pango.EllipsizeMode.END)
    return l


class CargoBlock(BlockWidget):
    BLOCK_TITLE = "CARGO"
    BLOCK_CSS   = "cargo-block"

    _FIRST_DATA_ROW = 3  # row 0=market ref, 1=col labels, 2=sep, 3+=data

    def build(self, parent: Gtk.Box) -> None:
        # ── Block header ─────────────────────────────────────────────────────
        hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._cargo_title = Gtk.Label(label="CARGO")
        self._cargo_title.set_xalign(0.0)
        self._cargo_title.set_hexpand(True)
        hdr_box.append(self._cargo_title)
        self._cargo_usage = Gtk.Label(label="")
        self._cargo_usage.set_xalign(1.0)
        self._cargo_usage.add_css_class("data-key")
        hdr_box.append(self._cargo_usage)

        body = self._build_section(parent, title_widget=hdr_box)

        # ── ScrolledWindow + single grid ─────────────────────────────────────
        # empty_lbl lives OUTSIDE the scroll/grid so it never collides with
        # data rows that occupy the same grid cells (GTK4 Grid.attach does not
        # evict existing occupants, so a label at row 3 and the empty marker
        # at row 3 would stack invisibly and ghost after the item is removed).
        self._empty_lbl = _lbl("— empty —", xalign=0.5, css="data-key", hexpand=True)
        self._empty_lbl.set_margin_top(8)
        self._empty_lbl.set_visible(False)   # hidden until refresh confirms empty hold
        body.append(self._empty_lbl)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")
        self._cargo_scroll = scroll
        body.append(scroll)

        # NOTE: _cargo_grid NOT _grid — _grid is BlockWidget's layout manager
        self._cargo_grid = Gtk.Grid()
        self._cargo_grid.set_column_spacing(4)
        self._cargo_grid.set_row_spacing(0)
        self._cargo_grid.set_margin_start(4)
        self._cargo_grid.set_margin_end(12)
        self._cargo_grid.set_hexpand(True)
        scroll.set_child(self._cargo_grid)

        # ── Row 0: docked station | target station ────────────────────────────
        self._mkt_loc_lbl = _lbl("", xalign=0.5, css="data-key",
                                   width=_W_SELL, ellipsize=True)
        self._tgt_loc_lbl = _lbl("Gal. Avg", xalign=1.0, css="data-key",
                                   width=_W_TGT, ellipsize=True)
        self._cargo_grid.attach(_lbl("", hexpand=True),            0, 0, 1, 1)
        self._cargo_grid.attach(_lbl("", css="data-key",
                                      width=_W_QTY, margin_end=_M_QTY), 1, 0, 1, 1)
        self._cargo_grid.attach(self._mkt_loc_lbl,                 2, 0, 1, 1)
        self._cargo_grid.attach(self._tgt_loc_lbl,                 3, 0, 1, 1)

        # ── Row 1: column labels ──────────────────────────────────────────────
        self._sell_col_lbl = _lbl("Sell", xalign=1.0, css="data-key", width=_W_SELL)
        self._tgt_col_lbl  = _lbl("",     xalign=1.0, css="data-key", width=_W_TGT)
        self._cargo_grid.attach(_lbl("Item", css="data-key", hexpand=True), 0, 1, 1, 1)
        self._cargo_grid.attach(_lbl("Qty.", xalign=1.0, css="data-key",
                                      width=_W_QTY, margin_end=_M_QTY),    1, 1, 1, 1)
        self._cargo_grid.attach(self._sell_col_lbl,                         2, 1, 1, 1)
        self._cargo_grid.attach(self._tgt_col_lbl,                          3, 1, 1, 1)

        # ── Row 2: separator ─────────────────────────────────────────────────
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._cargo_grid.attach(sep, 0, 2, 4, 1)

        # ── Data row bookkeeping ──────────────────────────────────────────────
        self._item_grid_rows: dict = {}
        self._cat_grid_rows:  dict = {}
        self._totals_row:     int  = -1
        self._search_timer          = None
        self._updating_entry        = False   # suppress change signal on programmatic set_text

        # ── Footer search UI — deferred: footer doesn't exist during build() ─
        self._has_spansh = False
        GLib.idle_add(self._build_footer_search)

    def _build_footer_search(self) -> bool:
        """Idle callback: insert search widgets into footer.
        No-op (and returns False to deregister) if spansh is not loaded.
        Footer is guaranteed to exist by the time this idle fires.
        """
        ft = self.footer()
        if ft is None:
            return False
        if self._get_spansh() is None:
            return False   # spansh disabled — no search UI, no breakage
        self._has_spansh = True


        # Entry
        self._search_entry = Gtk.Entry()
        self._search_entry.set_placeholder_text("Target market…")
        self._search_entry.set_width_chars(16)
        self._search_entry.set_hexpand(False)
        self._search_entry.set_valign(Gtk.Align.CENTER)
        self._search_entry.add_css_class("data-entry")
        self._search_entry.connect("activate",  self._on_search_activate)
        self._search_entry.connect("changed",   self._on_search_changed)
        # Stop propagation of key events so drag gesture doesn't steal them
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", lambda c, k, hw, mod: False)
        self._search_entry.add_controller(key_ctrl)

        # Accept button (green ✓)
        self._accept_btn = Gtk.Button(label="✓")
        self._accept_btn.add_css_class("mat-tab-btn")
        self._accept_btn.add_css_class("cargo-accept-btn")
        self._accept_btn.set_can_focus(False)
        self._accept_btn.set_sensitive(False)
        self._accept_btn.set_tooltip_text("Set as target market")
        self._accept_btn.connect("clicked", self._on_accept_clicked)

        # Clear button (red ✕)
        self._clear_btn = Gtk.Button(label="✕")
        self._clear_btn.add_css_class("mat-tab-btn")
        self._clear_btn.add_css_class("cargo-clear-btn")
        self._clear_btn.set_can_focus(False)
        self._clear_btn.set_sensitive(False)
        self._clear_btn.set_tooltip_text("Clear target market")
        self._clear_btn.connect("clicked", self._on_clear_clicked)

        # Autocomplete popover anchored to entry
        self._search_popover = Gtk.Popover()
        self._search_popover.set_autohide(True)
        self._search_popover.set_has_arrow(False)
        self._search_popover.set_parent(self._search_entry)
        self._search_popover.set_position(Gtk.PositionType.TOP)
        self._results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._search_popover.set_child(self._results_box)

        # Insert at front of footer (before the hexpand spacer)
        ft.prepend(self._clear_btn)
        ft.prepend(self._accept_btn)
        ft.prepend(self._search_entry)

    # ── Search event handlers ─────────────────────────────────────────────────

    def _on_search_changed(self, entry: Gtk.Entry) -> None:
        if not self._has_spansh or self._updating_entry:
            return
        text = entry.get_text().strip()
        self._accept_btn.set_sensitive(len(text) >= 3)
        self._clear_btn.set_sensitive(bool(text))
        if self._search_timer:
            GLib.source_remove(self._search_timer)
        if len(text) < 3:
            self._search_popover.popdown()
            return
        self._search_timer = GLib.timeout_add(400, self._do_search_bg, text)

    def _on_search_activate(self, entry: Gtk.Entry) -> None:
        """Enter key: accept current text immediately."""
        if self._search_timer:
            GLib.source_remove(self._search_timer)
            self._search_timer = None
        text = entry.get_text().strip()
        if len(text) >= 3:
            self._search_popover.popdown()
            self._fetch_target(text)

    def _on_accept_clicked(self, btn: Gtk.Button) -> None:
        text = self._search_entry.get_text().strip()
        if len(text) >= 3:
            self._search_popover.popdown()
            self._fetch_target(text)

    def _on_clear_clicked(self, btn: Gtk.Button) -> None:
        self._updating_entry = True
        self._search_entry.set_text("")
        self._updating_entry = False
        self._accept_btn.set_sensitive(False)
        self._clear_btn.set_sensitive(False)
        self._search_popover.popdown()
        try:
            p = self._get_spansh()
            if p:
                p.clear_target()
        except Exception:
            pass

    def _do_search_bg(self, query: str) -> bool:
        self._search_timer = None
        # Show spinner while searching
        def _run():
            try:
                p = self._get_spansh()
                if not p:
                    return
                results = p.search(query)
                GLib.idle_add(self._show_results, results)
            except Exception as exc:
                pass
        threading.Thread(target=_run, daemon=True, name="spansh-search").start()
        return False

    def _show_results(self, results: list) -> bool:
        child = self._results_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._results_box.remove(child)
            child = nxt
        if not results:
            # Show "no results" feedback rather than silently doing nothing
            no_lbl = Gtk.Label(label="No results — check station name")
            no_lbl.add_css_class("data-key")
            no_lbl.set_margin_start(8)
            no_lbl.set_margin_end(8)
            no_lbl.set_margin_top(4)
            no_lbl.set_margin_bottom(4)
            self._results_box.append(no_lbl)
            self._search_popover.popup()
            return False
        for r in results:
            age = f"  ({r['updated'][:10]})" if r.get("updated") else ""
            btn = Gtk.Button(label=f"{r['name']}  |  {r['system']}{age}")
            btn.add_css_class("mat-tab-btn")
            btn.set_can_focus(False)
            btn.connect("clicked", self._on_result_picked, r)
            self._results_box.append(btn)
        self._search_popover.popup()
        return False

    def _on_result_picked(self, btn, result: dict) -> None:
        self._search_popover.popdown()
        name = result["name"]
        self._updating_entry = True
        self._search_entry.set_text("")
        self._updating_entry = False
        self._accept_btn.set_sensitive(False)
        self._clear_btn.set_sensitive(True)
        try:
            p = self._get_spansh()
            if p:
                # Pass _rec so plugin uses inline market data — no second fetch
                p.set_target(name, result.get("system", ""),
                             _record=result.get("_rec"))
        except Exception:
            pass

    def _fetch_target(self, query: str) -> None:
        try:
            p = self._get_spansh()
            if p:
                p.set_target(query)
        except Exception:
            pass

    def _get_spansh(self):
        try:
            return self.core._plugins.get("spansh")
        except Exception:
            return None

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        s           = self.state
        items       = getattr(s, "cargo_items",            {})
        cap         = getattr(s, "cargo_capacity",         0)
        mkt_info    = getattr(s, "cargo_market_info",      {})
        tgt_info    = getattr(s, "cargo_target_market",    {})
        tgt_name    = getattr(s, "cargo_target_market_name", "")
        commodities = mkt_info.get("commodities", {})
        tgt_comms   = tgt_info.get("commodities", {})
        has_target  = bool(tgt_name)

        used = sum(v["count"] for v in items.values())

        # Capacity label
        if cap > 0:
            self._cargo_usage.set_label(f"{used} / {cap} t")
        elif used > 0:
            self._cargo_usage.set_label(f"{used} t")
        else:
            self._cargo_usage.set_label("")
        for cls in ("cargo-full", "cargo-warn", "cargo-ok"):
            self._cargo_usage.remove_css_class(cls)
        if cap > 0:
            pct = used / cap
            if pct >= 1.0:    self._cargo_usage.add_css_class("cargo-full")
            elif pct >= 0.75: self._cargo_usage.add_css_class("cargo-warn")
            else:              self._cargo_usage.add_css_class("cargo-ok")

        # Row 0 + 1: column headers
        # When target set: col2 = target station, col3 = Gal. Avg
        # When no target:  col2 = docked station, col3 = Gal. Avg
        if has_target:
            tgt_stn_name = tgt_info.get("station_name", "")
            tgt_sys_name = tgt_info.get("star_system", "")
            col2_loc = (f"{tgt_stn_name} | {tgt_sys_name}"
                        if (tgt_stn_name and tgt_sys_name) else tgt_stn_name or tgt_name)
        else:
            stn  = mkt_info.get("station_name", "")
            sys_ = mkt_info.get("star_system",  "")
            col2_loc = f"{stn} | {sys_}" if (stn and sys_) else stn or sys_
        self._mkt_loc_lbl.set_label(col2_loc)
        self._tgt_loc_lbl.set_label("Gal. Avg")
        self._sell_col_lbl.set_label("Sell")
        self._tgt_col_lbl.set_label("Avg")
        # Sync search entry text when target is known
        if has_target and self._has_spansh and hasattr(self, "_search_entry"):
            self._clear_btn.set_sensitive(True)

        # Rebuild data rows
        self._clear_data_rows()

        if used == 0:
            self._empty_lbl.set_visible(True)
            self._cargo_scroll.set_visible(False)
            return
        self._empty_lbl.set_visible(False)
        self._cargo_scroll.set_visible(True)

        enriched = []
        mean_prices = getattr(s, "cargo_mean_prices", {}) or {}
        for key, data in items.items():
            count = data.get("count", 0)
            if count <= 0:
                continue
            mkt = commodities.get(key, {})
            tgt = tgt_comms.get(key, {})
            mean_price = mkt.get("mean_price") or mean_prices.get(key, 0)
            enriched.append({
                "key":        key,
                "name":       mkt.get("name_local") or data["name_local"],
                "category":   mkt.get("category_local", "Uncategorised"),
                "count":      count,
                "stolen":     data.get("stolen", False),
                "sell_price": mkt.get("sell_price", 0),
                "mean_price": mean_price,
                "tgt_price":  tgt.get("sell_price", 0) if has_target else 0,
            })

        row = self._FIRST_DATA_ROW
        total_sell = total_tgt = total_avg = 0

        for item in enriched:
            count  = item["count"]
            docked = item["sell_price"]     # from Market.json
            avg    = item["mean_price"]     # galactic average
            tgt_p  = item["tgt_price"]      # Spansh target
            col2_price = tgt_p  if has_target else docked
            col3_price = avg
            total_sell += col2_price * count
            total_avg  += col3_price * count
            total_tgt  += 0   # unused

            col3 = _fmt_cr(col3_price)

            n_lbl = _lbl(("⚠ " if item["stolen"] else "") + item["name"],
                          css="data-value", hexpand=True, ellipsize=True)
            if item["stolen"]:
                n_lbl.add_css_class("cargo-stolen")
            n_lbl.set_margin_start(12)

            self._cargo_grid.attach(n_lbl,                                           0, row, 1, 1)
            self._cargo_grid.attach(_lbl(f"{count} t", 1.0, "data-key",
                                          width=_W_QTY, margin_end=_M_QTY),          1, row, 1, 1)
            self._cargo_grid.attach(_lbl(_fmt_cr(col2_price), 1.0, "data-key",
                                          width=_W_SELL),                             2, row, 1, 1)
            self._cargo_grid.attach(_lbl(col3, 1.0, "data-key", width=_W_TGT),       3, row, 1, 1)
            self._item_grid_rows[item["key"]] = row
            row += 1

        # Totals row
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep2.set_margin_top(8)
        self._cargo_grid.attach(sep2, 0, row, 4, 1)
        row += 1

        tot3 = _fmt_cr(total_avg)
        self._cargo_grid.attach(_lbl("Totals", css="data-key", hexpand=True),        0, row, 1, 1)
        self._cargo_grid.attach(_lbl(f"{used} t", 1.0, "data-key",
                                      width=_W_QTY, margin_end=_M_QTY),              1, row, 1, 1)
        self._cargo_grid.attach(_lbl(_fmt_cr(total_sell), 1.0, "data-key",
                                      width=_W_SELL),                                 2, row, 1, 1)
        self._cargo_grid.attach(_lbl(tot3, 1.0, "data-key", width=_W_TGT),           3, row, 1, 1)
        self._totals_row = row

    def _clear_data_rows(self) -> None:
        for row_idx in set(self._item_grid_rows.values()):
            for col in range(4):
                child = self._cargo_grid.get_child_at(col, row_idx)
                if child:
                    self._cargo_grid.remove(child)
        self._item_grid_rows.clear()
        self._cat_grid_rows.clear()
        if self._totals_row >= 0:
            for r in (self._totals_row - 1, self._totals_row):
                for col in range(4):
                    child = self._cargo_grid.get_child_at(col, r)
                    if child:
                        self._cargo_grid.remove(child)
            self._totals_row = -1

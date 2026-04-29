"""
gui/blocks/colonisation.py — Colonisation construction site tracker block.

Shows active construction sites with resource requirements, delivery progress,
and remaining quantities. Sites are collapsable — click the header to toggle.
If docked at a construction depot the current site is expanded by default and
highlighted in the accent colour.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget


class ColonisationBlock(BlockWidget):
    BLOCK_TITLE = "Colonisation"
    BLOCK_CSS   = "colonisation-block"

    DEFAULT_COL    = 0
    DEFAULT_ROW    = 9
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 5

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        self._scroll_body = self._make_scroll_body(body)

        self._status_label = self.make_label(
            "No construction sites tracked", css_class="data-value"
        )
        self._status_label.set_wrap(True)
        self._scroll_body.append(self._status_label)

        # Container rebuilt on each refresh
        self._sites_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._scroll_body.append(self._sites_box)

        # Collapse state: market_id -> bool (True = expanded)
        self._expanded: dict[int, bool] = {}
        # System-group collapse state: system_name -> bool (True = expanded)
        self._expanded_sys: dict[str, bool] = {}

    def refresh(self) -> None:
        state = self.state
        sites   = getattr(state, "colonisation_sites", [])
        docked  = getattr(state, "colonisation_docked", False)
        cur_mid = getattr(state, "_colonisation_current_market_id", None)
        cargo   = getattr(state, "cargo_items", {})

        # Clear previous site rows
        child = self._sites_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._sites_box.remove(child)
            child = nxt

        active = [s for s in sites if not s.get("complete") and not s.get("failed")]
        done   = [s for s in sites if s.get("complete")]
        failed = [s for s in sites if s.get("failed")]

        if not sites:
            self._status_label.set_label(
                "No construction sites tracked.\nDock at a construction depot to begin."
            )
            self._status_label.set_visible(True)
            return

        self._status_label.set_visible(False)

        # Group all active sites by system name
        sys_order: list[str] = []
        sys_sites: dict[str, list] = {}
        for site in active:
            sys_name = site.get("system") or "Unknown"
            if sys_name not in sys_sites:
                sys_order.append(sys_name)
                sys_sites[sys_name] = []
            sys_sites[sys_name].append(site)

        for sys_name in sys_order:
            # Default new systems to expanded
            if sys_name not in self._expanded_sys:
                self._expanded_sys[sys_name] = True
            sys_expanded = self._expanded_sys[sys_name]

            # System group header
            # spacing=0 + fixed-width arrow avoids the 80px min-width from data-key
            sys_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            sys_box.set_margin_top(4)

            sys_arrow = Gtk.Label(label="▼" if sys_expanded else "▶")
            sys_arrow.set_size_request(14, -1)   # fixed width — no min-width blowout
            sys_arrow.set_xalign(0.5)
            sys_arrow.set_margin_end(3)
            sys_box.append(sys_arrow)

            sys_lbl = self.make_label(sys_name, css_class="section-header")
            sys_lbl.set_hexpand(True)
            sys_box.append(sys_lbl)

            sys_gesture = Gtk.GestureClick.new()
            sys_gesture.connect("released", self._on_system_header_click, sys_name)
            sys_box.add_controller(sys_gesture)
            sys_box.set_cursor_from_name("pointer")
            self._sites_box.append(sys_box)

            if not sys_expanded:
                continue

            for site in sys_sites[sys_name]:
                is_current = docked and site.get("market_id") == cur_mid
                mid = site.get("market_id")
                if mid not in self._expanded:
                    self._expanded[mid] = True
                self._add_site_rows(site, cargo if is_current else {}, is_current)

        for site in done:
            lbl = self.make_label(
                f"✓ {site.get('station') or site.get('system', 'Unknown')} — complete",
                css_class="data-key"
            )
            lbl.add_css_class("status-ready")
            self._sites_box.append(lbl)

        for site in failed:
            lbl = self.make_label(
                f"✗ {site.get('station') or site.get('system', 'Unknown')} — failed",
                css_class="data-key"
            )
            lbl.add_css_class("status-alert")
            self._sites_box.append(lbl)

    def _add_site_rows(self, site: dict, cargo: dict, is_current: bool) -> None:
        mid      = site.get("market_id")
        name     = site.get("station") or site.get("system", "Unknown")
        pct      = round(site.get("progress", 0.0) * 100)
        expanded = self._expanded.get(mid, True)

        # Arrow layout: size_request(14) + margin_end(3) = 17px before the name.
        # hdr_box.margin_start=8 means the site name starts at 8+17=25px from the
        # block edge.  Resources use margin_start=25 to align with the name.
        _ARROW_W   = 14   # fixed arrow width (avoids data-key min-width:80px)
        _ARROW_GAP = 3    # gap between arrow and text
        _SITE_INDENT = 8  # hdr_box indent under system header
        _RES_INDENT  = _SITE_INDENT + _ARROW_W + _ARROW_GAP   # = 25px

        # ── Collapsable site header ───────────────────────────────────────────
        hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        hdr_box.set_margin_top(2)
        hdr_box.set_margin_start(_SITE_INDENT)

        arrow_lbl = Gtk.Label(label="▼" if expanded else "▶")
        arrow_lbl.set_size_request(_ARROW_W, -1)
        arrow_lbl.set_xalign(0.5)
        arrow_lbl.set_margin_end(_ARROW_GAP)
        hdr_box.append(arrow_lbl)

        if is_current:
            cur_lbl = self.make_label("▶ ", css_class="data-value")
            cur_lbl.add_css_class("status-active")
            hdr_box.append(cur_lbl)

        # section-header already applies color: var(--accent); no extra .accent needed
        name_lbl = self.make_label(name, css_class="section-header")
        name_lbl.set_hexpand(True)
        hdr_box.append(name_lbl)

        pct_lbl = self.make_label(f"{pct}%", css_class="data-value")
        pct_lbl.set_xalign(1.0)
        hdr_box.append(pct_lbl)

        gesture = Gtk.GestureClick.new()
        gesture.connect("released", self._on_site_header_click, mid)
        hdr_box.add_controller(gesture)
        hdr_box.set_cursor_from_name("pointer")
        self._sites_box.append(hdr_box)

        if not expanded:
            return

        # ── Resource rows (only when expanded) ───────────────────────────────
        resources = site.get("resources", {})
        if not resources:
            note = self.make_label("(dock to load requirements)", css_class="data-value")
            note.set_margin_start(_RES_INDENT)
            self._sites_box.append(note)
            return

        remaining_items = [
            (key, info) for key, info in resources.items()
            if info["provided"] < info["required"]
        ]

        if not remaining_items:
            done_lbl = self.make_label("All resources delivered!", css_class="data-value")
            done_lbl.add_css_class("status-ready")
            done_lbl.set_margin_start(_RES_INDENT)
            self._sites_box.append(done_lbl)
            return

        remaining_items.sort(key=lambda x: -(x[1]["required"] - x[1]["provided"]))

        res_grid = Gtk.Grid()
        res_grid.set_column_spacing(8)
        res_grid.set_row_spacing(2)
        res_grid.set_margin_top(2)
        res_grid.set_margin_start(_RES_INDENT)
        self._sites_box.append(res_grid)
        _gr = 0

        for key, info in remaining_items:
            display  = info.get("name") or key
            required = info["required"]
            provided = info["provided"]
            needed   = required - provided
            in_cargo = 0
            if cargo:
                in_cargo = (cargo.get(key, {}).get("count", 0)
                            if isinstance(cargo.get(key), dict)
                            else cargo.get(key, 0))

            need_str = f"{needed:,} needed"
            if in_cargo > 0:
                can_deliver = min(in_cargo, needed)
                need_str   += f"  ({can_deliver:,} in hold)"

            name_lbl = self.make_label(display, css_class="data-key")
            name_lbl.set_xalign(0.0)
            name_lbl.set_hexpand(True)
            res_grid.attach(name_lbl, 0, _gr, 1, 1)

            val_lbl = self.make_label(need_str, css_class="data-value")
            val_lbl.set_xalign(1.0)
            if in_cargo >= needed:
                val_lbl.add_css_class("status-ready")
            elif in_cargo > 0:
                val_lbl.add_css_class("status-active")
            res_grid.attach(val_lbl, 1, _gr, 1, 1)
            _gr += 1

        total_remaining = sum(
            max(0, i["required"] - i["provided"]) for i in resources.values()
        )
        if total_remaining > 0:
            total_key = self.make_label("Total remaining", css_class="data-key")
            total_key.set_xalign(0.0)
            total_key.set_hexpand(True)
            res_grid.attach(total_key, 0, _gr, 1, 1)
            total_val = self.make_label(f"{total_remaining:,} t", css_class="data-value")
            total_val.set_xalign(1.0)
            res_grid.attach(total_val, 1, _gr, 1, 1)

    def _on_site_header_click(self, gesture, n_press, x, y, market_id) -> None:
        if market_id is None:
            return
        self._expanded[market_id] = not self._expanded.get(market_id, True)
        self.refresh()

    def _on_system_header_click(self, gesture, n_press, x, y, sys_name) -> None:
        if sys_name is None:
            return
        self._expanded_sys[sys_name] = not self._expanded_sys.get(sys_name, True)
        self.refresh()

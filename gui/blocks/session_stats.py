"""
gui/blocks/session_stats.py — Tabbed session statistics block.

Summary tab: duration + collected rows from all active activity providers.
Activity tabs: one per registered provider that has_activity(), sorted A-Z.

Row format from providers:
    {"label": str, "value": str, "rate": str | None}
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget


class SessionStatsBlock(BlockWidget):
    BLOCK_TITLE = "Session Stats"
    BLOCK_CSS   = "stats-block"

    _TAB_SUMMARY = "Summary"

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)

        # Tab bar + clear button on same row
        tab_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar.add_css_class("mat-tab-bar")
        self._tab_bar.set_hexpand(True)
        tab_row.append(self._tab_bar)
        clear_btn = Gtk.Button(label="↺")
        clear_btn.add_css_class("mat-tab-btn")
        clear_btn.set_tooltip_text("Reset session counters")
        clear_btn.connect("clicked", self._on_clear_session)
        tab_row.append(clear_btn)
        body.append(tab_row)

        # Content stack — one page per tab
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        body.append(self._stack)

        self._tab_btns: dict[str, Gtk.Button] = {}
        self._active_tab: str = self._TAB_SUMMARY

        # Build the permanent Summary tab
        self._build_tab(self._TAB_SUMMARY)
        self._set_active_tab(self._TAB_SUMMARY)

    def _build_tab(self, title: str) -> Gtk.Box:
        """Create a scrollable tab page and its button. Return the content box."""
        # Tab button
        btn = Gtk.Button(label=title)
        btn.add_css_class("mat-tab-btn")
        btn.connect("clicked", lambda _b, t=title: self._set_active_tab(t))
        self._tab_bar.append(btn)
        self._tab_btns[title] = btn

        # Content box inside a scrolled window.
        # margin_end=12 keeps text clear of the GTK4 overlay scrollbar track.
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
        """Return the content box for a tab, creating it if needed."""
        page = self._stack.get_child_by_name(title)
        if page is not None:
            # GTK4: ScrolledWindow → Viewport → Box
            vp = page.get_child()
            return vp.get_child() if hasattr(vp, "get_child") else vp
        return self._build_tab(title)

    def _clear_tab(self, title: str) -> Gtk.Box:
        """Clear and return the content box for a tab."""
        page = self._stack.get_child_by_name(title)
        if page is not None:
            # GTK4: ScrolledWindow → Viewport → Box
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
        """Remove tabs for providers that no longer have activity."""
        to_remove = [t for t in self._tab_btns if t not in active_titles]
        for t in to_remove:
            btn = self._tab_btns.pop(t)
            self._tab_bar.remove(btn)
            page = self._stack.get_child_by_name(t)
            if page:
                self._stack.remove(page)
        if self._active_tab not in self._tab_btns:
            self._set_active_tab(self._TAB_SUMMARY)

    def _append_rows(self, grid: "Gtk.Grid", rows: list[dict],
                     start_row: int = 0) -> int:
        """Append provider rows into a shared Grid, returning next row index.

        Accepting an existing Grid (rather than creating one per section)
        ensures GTK sizes all value and rate columns globally, so the |
        separator lands at the same x position across every section.

        Grid columns:
          0 — label  (hexpand)
          1 — value  (right-aligned, width from widest value across ALL rows)
          2 — pipe   (only when rate exists)
          3 — rate   (right-aligned, width from widest rate across ALL rows)
        """
        row_idx = start_row
        for r in rows:
            label = r["label"]
            value = r["value"]
            rate  = r.get("rate")

            # Section dividers — span all 4 columns
            if not value and not rate:
                sep_lbl = Gtk.Label(label=label)
                sep_lbl.add_css_class("data-key")
                sep_lbl.set_xalign(0.0)
                sep_lbl.set_margin_top(4)
                grid.attach(sep_lbl, 0, row_idx, 4, 1)
                row_idx += 1
                continue

            # Col 0: label
            lbl = Gtk.Label(label=label)
            lbl.add_css_class("data-key")
            lbl.set_xalign(0.0)
            lbl.set_hexpand(True)
            grid.attach(lbl, 0, row_idx, 1, 1)

            if rate:
                # Col 1: value (right-aligned)
                val_lbl = Gtk.Label(label=value)
                val_lbl.add_css_class("data-value")
                val_lbl.set_xalign(1.0)
                grid.attach(val_lbl, 1, row_idx, 1, 1)

                # Col 2: pipe separator
                pipe_lbl = Gtk.Label(label="|")
                pipe_lbl.add_css_class("data-key")
                pipe_lbl.set_xalign(0.5)
                grid.attach(pipe_lbl, 2, row_idx, 1, 1)

                # Col 3: rate (right-aligned)
                rate_lbl = Gtk.Label(label=rate)
                rate_lbl.add_css_class("stat-line")
                rate_lbl.set_xalign(1.0)
                grid.attach(rate_lbl, 3, row_idx, 1, 1)
            else:
                # No rate — value spans cols 1-3
                val_lbl = Gtk.Label(label=value)
                val_lbl.add_css_class("data-value")
                val_lbl.set_xalign(1.0)
                grid.attach(val_lbl, 1, row_idx, 3, 1)

            row_idx += 1

        return row_idx


    def _on_clear_session(self, *_) -> None:
        """Reset all session counters via session_stats.on_new_session()."""
        try:
            self.core.plugin_call("session_stats", "on_new_session", 0)
        except Exception:
            pass
        gq = self.core.gui_queue
        if gq: gq.put(("stats_update", None))

    def _append_section_header(self, box: Gtk.Box, title: str) -> None:
        """Render a standalone section header box (used by activity tabs)."""
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

        box.append(hbox)

    def _section_header_in_grid(self, grid: "Gtk.Grid",
                                 title: str, row_idx: int) -> int:
        """Embed a section header as a spanning row inside a shared Grid."""
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


    def refresh(self) -> None:
        core      = self.core
        providers = getattr(core, "session_providers", [])
        plugin    = core._plugins.get("session_stats")

        # --- Summary tab ---
        summary_box = self._clear_tab(self._TAB_SUMMARY)

        # Build the entire Summary tab into ONE shared Grid so GTK sizes all
        # value and rate columns globally — keeps the | separator aligned
        # across Combat, Exploration, Missions, and every other section.
        summary_grid = Gtk.Grid()
        summary_grid.set_column_spacing(4)
        summary_grid.set_row_spacing(1)
        summary_grid.add_css_class("stats-grid")
        summary_box.append(summary_grid)

        grid_row = 0

        # Duration row at top
        dur_s = plugin.session_duration_seconds() if plugin else 0.0
        grid_row = self._append_rows(summary_grid, [
            {"label": "Duration",
             "value": self.fmt_duration(dur_s) if dur_s > 0 else "—",
             "rate": None},
        ], start_row=grid_row)

        # Provider sections sorted alphabetically by tab title
        active_providers = sorted(
            [p for p in providers if p.has_activity()],
            key=lambda p: getattr(p, "ACTIVITY_TAB_TITLE", ""),
        )
        for p in active_providers:
            rows = p.get_summary_rows()
            if not rows:
                continue
            title = getattr(p, "ACTIVITY_TAB_TITLE", "Activity")
            grid_row = self._section_header_in_grid(summary_grid, title, grid_row)
            grid_row = self._append_rows(summary_grid, rows, start_row=grid_row)

        # --- Activity tabs (each gets its own grid — per-tab alignment is fine) ---
        active_tab_titles = {self._TAB_SUMMARY}
        for p in providers:
            if not p.has_activity():
                continue
            tab_rows = p.get_tab_rows()
            if not tab_rows:
                continue
            title = getattr(p, "ACTIVITY_TAB_TITLE", "Activity")
            active_tab_titles.add(title)
            tab_box = self._clear_tab(title)
            tab_grid = Gtk.Grid()
            tab_grid.set_column_spacing(4)
            tab_grid.set_row_spacing(1)
            tab_grid.add_css_class("stats-grid")
            tab_box.append(tab_grid)
            self._append_rows(tab_grid, tab_rows, start_row=0)

        # Register permanent tabs before pruning so they are never removed

        self._remove_stale_tabs(active_tab_titles)

"""
gui/blocks/engineering.py — Combined engineering materials inventory block.

Displays all seven engineering material categories across Horizons and Odyssey
in a single flat tab bar with vertical scroll per tab.

  Horizons: Raw | Mfg | Enc
  Odyssey:  Comp | Items | Cons | Data

Layout
------
Single layout only — one tab is visible at a time, content scrolls vertically.
The wide three-column layout code from the former materials block is preserved
below (marked DORMANT) in case it is needed in future.  It is never registered
or rendered.

Tab bar uses the same hand-rolled Gtk.Button widgets and .mat-tab-* CSS classes
as the former materials block.  No changes to themes/base.css are required.

Scroll padding
--------------
Each tab's ScrolledWindow child box carries set_margin_end(12) to keep text
clear of the GTK4 overlay scrollbar track.  See _make_section_scroll().
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget

# ── Tab definitions ───────────────────────────────────────────────────────────
# Each entry: (state_key, short_label, group_label_for_dormant_wide_layout)
_TABS = [
    ("raw",          "Raw",   "Raw"),
    ("manufactured", "Mfg",   "Manufactured"),
    ("encoded",      "Enc",   "Encoded"),
    ("components",   "Comp",  "Components"),
    ("items",        "Items", "Items"),
    ("consumables",  "Cons",  "Consumables"),
    ("data",         "Data",  "Data"),
]

# Minimum block pixel width that *would* trigger a wide multi-column layout.
# The wide layout is currently dormant (single-layout-only as per spec) but
# this constant is retained so the threshold is defined in one place if the
# wide layout is ever reactivated.
WIDE_THRESHOLD = 380


class EngineeringBlock(BlockWidget):
    BLOCK_TITLE = "ENGINEERING"
    BLOCK_CSS   = "materials-block"   # reuse existing CSS — no theme changes needed

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        body.set_spacing(0)

        # ── Tab bar ───────────────────────────────────────────────────────────
        tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_bar.add_css_class("mat-tab-bar")
        body.append(tab_bar)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── Tab content stack ─────────────────────────────────────────────────
        self._tab_stack = Gtk.Stack()
        self._tab_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._tab_stack.set_vexpand(True)
        self._tab_stack.set_hexpand(True)
        body.append(self._tab_stack)

        self._tab_btns: dict[str, Gtk.Button] = {}
        self._sections: dict[str, dict]        = {}
        self._active_tab: str = "raw"

        for cat, short_label, _wide_label in _TABS:
            # ── Tab button ────────────────────────────────────────────────────
            btn = Gtk.Button()
            btn.add_css_class("mat-tab-btn")
            btn.set_hexpand(True)
            btn.set_can_focus(False)
            tab_bar.append(btn)
            self._tab_btns[cat] = btn

            btn_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            btn_inner.set_halign(Gtk.Align.CENTER)
            btn.set_child(btn_inner)

            tab_lbl = Gtk.Label(label=short_label)
            tab_lbl.add_css_class("mat-tab-label")
            btn_inner.append(tab_lbl)

            count_badge = Gtk.Label(label="0")
            count_badge.add_css_class("mat-tab-count")
            btn_inner.append(count_badge)

            btn.connect("clicked", self._on_tab_click, cat)

            # ── Tab scroll page ───────────────────────────────────────────────
            scroll, list_box, empty_lbl = self._make_section_scroll()
            self._tab_stack.add_named(scroll, cat)

            self._sections[cat] = {
                "count_lbl":  count_badge,
                "list_box":   list_box,
                "empty_lbl":  empty_lbl,
                "rows":       {},
            }

        self._set_active_tab("raw")

    # ── Shared scroll + list factory ──────────────────────────────────────────

    def _make_section_scroll(self):
        """Return (ScrolledWindow, list_box, empty_label) ready to populate.

        set_margin_end(12) keeps item text clear of the GTK4 overlay scrollbar.
        """
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")

        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        list_box.set_vexpand(True)
        list_box.set_margin_end(12)   # clear GTK4 overlay scrollbar track
        scroll.set_child(list_box)

        empty_lbl = Gtk.Label(label="— none —")
        empty_lbl.add_css_class("data-key")
        empty_lbl.set_xalign(0.5)
        empty_lbl.set_margin_top(6)
        empty_lbl.set_margin_bottom(4)
        list_box.append(empty_lbl)

        return scroll, list_box, empty_lbl

    # ── on_resize ─────────────────────────────────────────────────────────────

    def on_resize(self, w: int, h: int) -> None:
        """Called by the window after every set_size_request.

        Single-layout block — no layout switching is performed.
        The WIDE_THRESHOLD constant and the wide layout code below are retained
        for future use; this hook is the correct place to reactivate them.
        """
        super().on_resize(w, h)

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _on_tab_click(self, _btn: Gtk.Button, cat: str) -> None:
        self._set_active_tab(cat)

    def _set_active_tab(self, cat: str) -> None:
        self._active_tab = cat
        self._tab_stack.set_visible_child_name(cat)
        for key, btn in self._tab_btns.items():
            if key == cat:
                btn.add_css_class("mat-tab-active")
            else:
                btn.remove_css_class("mat-tab-active")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        s      = self.state
        locker = getattr(s, "engineering_locker", {})

        buckets: dict[str, dict] = {
            "raw":          getattr(s, "materials_raw",          {}),
            "manufactured": getattr(s, "materials_manufactured", {}),
            "encoded":      getattr(s, "materials_encoded",      {}),
            "components":   locker.get("components",  {}),
            "items":        locker.get("items",        {}),
            "consumables":  locker.get("consumables",  {}),
            "data":         locker.get("data",         {}),
        }

        for cat, items in buckets.items():
            self._refresh_section(items, self._sections[cat])

    def _refresh_section(self, items: dict, sec: dict) -> None:
        count_lbl = sec["count_lbl"]
        list_box  = sec["list_box"]
        empty_lbl = sec["empty_lbl"]
        rows      = sec["rows"]

        total = sum(v["count"] for v in items.values())
        count_lbl.set_label(str(total) if total else "0")

        if not items:
            empty_lbl.set_visible(True)
            for key in list(rows.keys()):
                row_box, _, _ = rows.pop(key)
                list_box.remove(row_box)
            return

        empty_lbl.set_visible(False)

        sorted_items  = sorted(items.items(), key=lambda kv: kv[1]["name_local"].lower())
        current_keys  = [k for k, _ in sorted_items]

        # Remove stale rows
        for key in list(rows.keys()):
            if key not in items:
                row_box, _, _ = rows.pop(key)
                list_box.remove(row_box)

        # Add / update
        for key, data in sorted_items:
            name_str  = data["name_local"]
            count_str = f"  {data['count']}"

            if key in rows:
                _, name_lbl_w, count_lbl_w = rows[key]
                name_lbl_w.set_label(name_str)
                count_lbl_w.set_label(count_str)
            else:
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                row_box.add_css_class("data-row")
                _mc = Gtk.EventControllerMotion()
                _mc.connect("enter",  lambda c, x, y, w=row_box: w.add_css_class("mat-row-hover"))
                _mc.connect("leave",  lambda c,       w=row_box: w.remove_css_class("mat-row-hover"))
                row_box.add_controller(_mc)

                name_lbl_w = Gtk.Label(label=name_str)
                name_lbl_w.set_xalign(0.0)
                name_lbl_w.set_hexpand(True)
                name_lbl_w.add_css_class("data-value")

                count_lbl_w = Gtk.Label(label=count_str)
                count_lbl_w.set_xalign(1.0)
                count_lbl_w.add_css_class("data-key")

                row_box.append(name_lbl_w)
                row_box.append(count_lbl_w)
                list_box.append(row_box)
                rows[key] = (row_box, name_lbl_w, count_lbl_w)

        # Re-order if needed
        existing_order = [k for k in rows if k in items]
        if existing_order != current_keys:
            for key in current_keys:
                if key in rows:
                    row_box, _, _ = rows[key]
                    list_box.remove(row_box)
                    list_box.append(row_box)


# ══ DORMANT — Wide multi-column layout ═══════════════════════════════════════
#
# The wide layout from the former materials block is preserved here for future
# use.  It is never instantiated — EngineeringBlock uses the single tabbed
# layout only.
#
# To reactivate:
#   1. Add a Gtk.Stack (_layout_stack) wrapping both "tabbed" and "wide" pages.
#   2. Call _build_wide_layout() in build() and add its page to _layout_stack.
#   3. Restore the layout-switching logic in on_resize() using WIDE_THRESHOLD.
#   4. Update refresh() to call _refresh_section() for both sets of section dicts.
#   5. The wide layout only renders the 3 Horizons columns — Odyssey categories
#      don't benefit from a side-by-side view given their typical column width.
#
# ── Former wide layout reference (3 Horizons columns) ───────────────────────
#
#   _WIDE_TABS = [("raw", "Raw"), ("manufactured", "Manufactured"), ("encoded", "Encoded")]
#
#   def _build_wide_layout(self) -> None:
#       page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
#       page.set_vexpand(True); page.set_hexpand(True)
#       for i, (cat, label) in enumerate(_WIDE_TABS):
#           col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
#           col.set_hexpand(True); col.set_vexpand(True)
#           hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
#           hdr.add_css_class("mat-col-hdr")
#           hdr.set_margin_start(4); hdr.set_margin_end(4)
#           hdr.set_margin_top(4);   hdr.set_margin_bottom(2)
#           hdr_lbl = Gtk.Label(label=label.upper())
#           hdr_lbl.add_css_class("mat-col-title"); hdr_lbl.set_xalign(0.0)
#           hdr_lbl.set_hexpand(True); hdr.append(hdr_lbl)
#           count_lbl = Gtk.Label(label="0")
#           count_lbl.add_css_class("data-key"); count_lbl.add_css_class("mat-col-count")
#           hdr.append(count_lbl); col.append(hdr)
#           col.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
#           scroll, list_box, empty_lbl = self._make_section_scroll()
#           col.append(scroll)
#           self._sections_wide[cat] = {
#               "count_lbl": count_lbl, "list_box": list_box,
#               "empty_lbl": empty_lbl, "rows": {},
#           }
#           page.append(col)
#           if i < len(_WIDE_TABS) - 1:
#               page.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
#       self._layout_stack.add_named(page, "wide")
#
# ═════════════════════════════════════════════════════════════════════════════

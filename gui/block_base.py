"""
gui/block_base.py — BlockWidget base class for all dashboard blocks.

Widget tree per block:
  Gtk.Frame  (.dashboard-block)          ← placed on canvas
    Gtk.Box  (vertical)
      [content from build() / _build_section()]
      Gtk.Box  (.block-footer)            ← gutter row, always at bottom
        [future status items …]
        Gtk.Label  ⤡  (.resize-handle)   ← pinned right

Drag:   grab the section-header label — leaf widget, no children, no CAPTURE needed.
Resize: grab the ⤡ handle in the footer — also a leaf widget.
Neither gesture interferes with the other.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk
except ImportError:
    raise ImportError(
        "PyGObject not found.\n"
        "  Arch/Manjaro:  pacman -S python-gobject gtk4\n"
        "  pip:           pip install PyGObject"
    )

from gui.helpers import make_label, make_section, make_row


class BlockWidget:
    BLOCK_TITLE: str = ""
    BLOCK_CSS:   str = "block"

    def __init__(self, core):
        self.core    = core
        self.state   = core.state
        self.session = core.active_session

        self._frame:  Gtk.Frame  | None = None
        self._root:   Gtk.Box    | None = None
        self._header: Gtk.Widget | None = None   # drag target
        self._footer: Gtk.Box    | None = None   # gutter row
        self._grid    = None
        self._window  = None
        self._name:   str = ""

        # Drag state
        self._drag_origin_x    = 0.0
        self._drag_origin_y    = 0.0
        self._drag_block_w     = 0
        self._drag_block_h     = 0
        self._dragging         = False
        self._drag_ghost_created = False
        self._drag_ghost: "Gtk.Frame | None" = None

        # Resize state
        self._resize_origin_w = 0.0
        self._resize_origin_h = 0.0
        self._resize_origin_x = 0.0
        self._resize_origin_y = 0.0
        self._resize_ghost: "Gtk.Frame | None" = None

        # Collapse state
        self._collapsed      = False
        self._section_sep:  "Gtk.Widget | None" = None  # separator below header
        self._section_body: "Gtk.Box    | None" = None  # inner content box
        self._header_height  = 0

    # ── Build ─────────────────────────────────────────────────────────────────

    def build_widget(self, name: str, grid, window) -> Gtk.Widget:
        self._name   = name
        self._grid   = grid
        self._window = window

        self._frame = Gtk.Frame()
        self._frame.add_css_class("dashboard-block")
        self._frame.set_hexpand(False)
        self._frame.set_vexpand(False)

        # Outer vertical box: content on top, footer gutter at bottom
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer_box.set_hexpand(True)
        outer_box.set_vexpand(True)
        self._frame.set_child(outer_box)

        # Content area — expands to fill available space above the footer
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content_box.set_hexpand(True)
        content_box.set_vexpand(True)
        outer_box.append(content_box)

        # Let subclass populate content_box; this also sets self._header
        self.build(content_box)

        # Footer gutter — fixed height, never overlaps content
        self._footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._footer.add_css_class("block-footer")
        self._footer.set_hexpand(True)
        self._footer.set_vexpand(False)
        outer_box.append(self._footer)

        # Spacer pushes handle to the right
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self._footer.append(spacer)

        # Resize handle in footer — leaf widget, plain BUBBLE gesture
        handle = Gtk.Label(label="⤡")
        handle.add_css_class("resize-handle")
        handle.set_halign(Gtk.Align.END)
        handle.set_valign(Gtk.Align.CENTER)
        handle.set_cursor(Gdk.Cursor.new_from_name("se-resize"))
        self._footer.append(handle)

        # Wire gestures
        self._wire_resize(handle)
        drag_target = self._header if self._header is not None else self._frame
        self._wire_drag(drag_target)

        if self._header is not None:
            self._header.set_cursor(Gdk.Cursor.new_from_name("grab"))
            self._wire_collapse(self._header)
            # Cache header height once allocated so _toggle_collapse has a
            # reliable value even when called before the first paint.
            self._header.connect("notify::height", self._on_header_height_changed)

        return self._frame

    def root_widget(self) -> Gtk.Widget | None:
        return self._frame

    # ── Footer access (for subclasses that want to add footer items) ──────────

    def footer(self) -> Gtk.Box | None:
        """Return the footer gutter box. Prepend items before the spacer."""
        return self._footer

    # ── Collapse on double-click ───────────────────────────────────────────────

    def _on_header_height_changed(self, widget, _param) -> None:
        h = widget.get_height()
        if h > 0:
            self._header_height = h

    def _wire_collapse(self, widget: Gtk.Widget) -> None:
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self._on_header_pressed)
        widget.add_controller(click)

    def _on_header_pressed(self, gesture, n_press, x, y) -> None:
        if n_press == 2:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self._toggle_collapse()

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        show = not self._collapsed
        # Hide only the section body and separator — the header (which is the
        # first child of panel-section, above the separator) stays visible so
        # the user can always see the block title and double-click to restore.
        if self._section_sep:
            self._section_sep.set_visible(show)
        if self._section_body:
            self._section_body.set_visible(show)
        if self._footer:
            self._footer.set_visible(show)
        if self._frame:
            cell = self._grid.cell_for(self._name)
            _, _, w, h = self._grid.pixel_rect(cell)
            if self._collapsed:
                hdr_h = self._header_height if self._header_height > 0 else 26
                self._frame.set_size_request(w, hdr_h + 6)
            else:
                self._frame.set_size_request(w, h)

    # ── Drag to move (header label only) ─────────────────────────────────────

    def _wire_drag(self, widget: Gtk.Widget) -> None:
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin",  self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end",    self._on_drag_end)
        widget.add_controller(drag)
        self._drag_gesture = drag

    def _on_drag_begin(self, gesture, start_x, start_y):
        # Don't claim the sequence or create the ghost here — a double-click
        # also triggers drag-begin on the first press.  We defer both until
        # actual movement is detected in drag-update.
        self._dragging = True
        self._drag_ghost_created = False
        cell = self._grid.cell_for(self._name)
        x, y, w, h = self._grid.pixel_rect(cell)
        self._drag_origin_x = float(x)
        self._drag_origin_y = float(y)
        self._drag_block_w  = w
        self._drag_block_h  = h

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if not self._dragging:
            return
        # Only start a real drag once the pointer has moved at least 4px.
        # This threshold prevents a double-click from accidentally dragging.
        DRAG_THRESHOLD = 4.0
        if abs(offset_x) < DRAG_THRESHOLD and abs(offset_y) < DRAG_THRESHOLD:
            return
        if not self._drag_ghost_created:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self._drag_ghost_created = True
            w = self._drag_block_w
            h = self._drag_block_h
            x = int(self._drag_origin_x)
            y = int(self._drag_origin_y)
            if self._header:
                self._header.set_cursor(Gdk.Cursor.new_from_name("grabbing"))
            ghost = Gtk.Frame()
            ghost.add_css_class("block-drag-ghost")
            ghost.set_size_request(w, h)
            self._window._canvas.put(ghost, x, y)
            ghost.set_visible(True)
            self._drag_ghost = ghost
            if self._frame:
                self._frame.add_css_class("block-dragging")
        # Move ghost within canvas bounds — prevents dragging past the edge
        # which would silently extend the Gtk.Fixed beyond the scroll viewport.
        canvas_w = self._window._grid._canvas_width
        canvas_h = self._window._scroll.get_height() or 99999
        ghost_w  = self._drag_block_w
        ghost_h  = self._drag_block_h
        nx = max(0.0, min(self._drag_origin_x + offset_x, canvas_w - ghost_w))
        ny = max(0.0, self._drag_origin_y + offset_y)
        self._window._canvas.move(self._drag_ghost, int(nx), int(ny))

    def _on_drag_end(self, gesture, offset_x, offset_y):
        was_dragging = self._drag_ghost_created
        self._dragging = False
        self._drag_ghost_created = False
        if self._header:
            self._header.set_cursor(Gdk.Cursor.new_from_name("grab"))
        if self._frame:
            self._frame.remove_css_class("block-dragging")

        # Destroy ghost
        if self._drag_ghost is not None:
            self._window._canvas.remove(self._drag_ghost)
            self._drag_ghost = None

        # If the pointer never moved past the drag threshold (e.g. a click or
        # double-click), skip the snap/commit entirely.  This prevents drag-end
        # from overwriting the frame size that _toggle_collapse just set.
        if not was_dragging:
            return

        # Snap and commit the real block to its new position
        final_x = self._drag_origin_x + offset_x
        final_y = self._drag_origin_y + offset_y
        col = self._grid.snap_to_col(final_x)
        row = self._grid.snap_to_row(final_y)
        self._grid.move_block(self._name, col, row)
        cell = self._grid.cell_for(self._name)
        x, y, w, h = self._grid.pixel_rect(cell)
        if self._frame:
            self._window._canvas.move(self._frame, x, y)
            if not self._collapsed:
                self._frame.set_size_request(w, h)
        self._grid.save()

    # ── Resize (⤡ handle in footer) ───────────────────────────────────────────

    def _wire_resize(self, handle: Gtk.Widget) -> None:
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin",  self._on_resize_begin)
        drag.connect("drag-update", self._on_resize_update)
        drag.connect("drag-end",    self._on_resize_end)
        handle.add_controller(drag)

    def _on_resize_begin(self, gesture, x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        cell = self._grid.cell_for(self._name)
        bx, by, w, h = self._grid.pixel_rect(cell)
        self._resize_origin_w = float(w)
        self._resize_origin_h = float(h)
        self._resize_origin_x = float(bx)
        self._resize_origin_y = float(by)
        if self._frame:
            self._frame.add_css_class("block-resizing")
        # Ghost overlay anchored at block origin — only the ghost resizes during drag
        ghost = Gtk.Frame()
        ghost.add_css_class("block-drag-ghost")
        ghost.set_size_request(w, h)
        self._window._canvas.put(ghost, bx, by)
        ghost.set_visible(True)
        self._resize_ghost = ghost

    def _on_resize_update(self, gesture, offset_x, offset_y):
        if self._resize_ghost is None:
            return
        nw = max(80.0, self._resize_origin_w + offset_x)
        nh = max(40.0, self._resize_origin_h + offset_y)
        self._resize_ghost.set_size_request(int(nw), int(nh))

    def _on_resize_end(self, gesture, offset_x, offset_y):
        if self._frame:
            self._frame.remove_css_class("block-resizing")
        if self._resize_ghost is not None:
            self._window._canvas.remove(self._resize_ghost)
            self._resize_ghost = None
        from gui.grid import ROW_PX
        cw   = self._grid.col_width()
        nw   = max(80.0,  self._resize_origin_w + offset_x)
        nh   = max(40.0,  self._resize_origin_h + offset_y)
        cols = max(4, round(nw / cw))
        rows = max(2, round(nh / ROW_PX))
        self._grid.resize_block(self._name, cols, rows)
        cell = self._grid.cell_for(self._name)
        _, _, w, h = self._grid.pixel_rect(cell)
        if self._frame:
            self._frame.set_size_request(w, h)
        self._grid.save()

    # ── Section scaffolding ───────────────────────────────────────────────────

    def _build_section(
        self,
        parent: Gtk.Box,
        title: str | None = None,
        title_widget: Gtk.Widget | None = None,
    ) -> Gtk.Box:
        t = title if title is not None else self.BLOCK_TITLE
        outer, inner = make_section(t, title_widget=title_widget)
        outer.add_css_class(self.BLOCK_CSS)
        outer.set_hexpand(True)
        outer.set_vexpand(True)
        parent.append(outer)
        self._root = outer
        # First child of outer is the header label — use it as drag target.
        # Second child is the separator; third is the inner content box.
        # We store all three so _toggle_collapse can hide sep+body while
        # keeping the header visible.
        self._header       = outer.get_first_child()
        self._section_sep  = self._header.get_next_sibling() if self._header else None
        self._section_body = inner
        return inner

    def _make_scroll_body(
        self,
        parent: Gtk.Box,
        spacing: int = 3,
        margin_end: int = 12,
        css_class: str = "mat-tab-scroll",
    ) -> Gtk.Box:
        """Return a vexpand-scrollable Box appended to *parent*.

        This is the standard scrollable content area used by all blocks.
        The inner box carries set_margin_end(12) to keep text clear of the
        GTK4 overlay scrollbar track.  Blocks that previously built their own
        ScrolledWindow should call this instead.

        Returns the inner Gtk.Box to populate with content rows.
        """
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class(css_class)
        parent.append(scroll)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        inner.set_vexpand(True)
        inner.set_margin_end(margin_end)
        scroll.set_child(inner)
        return inner

    # ── Visibility ────────────────────────────────────────────────────────────

    def set_visible(self, visible: bool) -> None:
        if self._root is not None:
            self._root.set_visible(visible)

    def is_visible(self) -> bool:
        return self._root.get_visible() if self._root is not None else False

    # ── Convenience re-exports ────────────────────────────────────────────────

    @staticmethod
    def make_label(text="", css_class=None, xalign=0.0):
        return make_label(text, css_class=css_class, xalign=xalign)

    @staticmethod
    def make_row(label_text, value_text="—"):
        return make_row(label_text, value_text)

    @staticmethod
    def make_section(title, title_widget=None):
        return make_section(title, title_widget=title_widget)

    def fmt_credits(self, n):
        return self.core.fmt_credits(n)

    def fmt_duration(self, s):
        return self.core.fmt_duration(s)

    def rate_per_hour(self, s, precision=None):
        return self.core.rate_per_hour(s, precision)

    # ── Subclass interface ────────────────────────────────────────────────────

    def build(self, parent: Gtk.Box) -> None:
        self._build_section(parent)

    def refresh(self) -> None:
        pass

    def on_resize(self, w: int, h: int) -> None:
        """Called by the window after every set_size_request on this block.
        Enforces collapsed height if the block is currently collapsed.
        Subclasses that override this should call super().on_resize(w, h) first."""
        if self._collapsed and self._frame:
            hdr_h = self._header_height if self._header_height > 0 else 26
            self._frame.set_size_request(w, hdr_h + 6)
# NOTE: _make_scroll_body helper appended below existing content — no edits needed above

"""
gui/docs_viewer.py — Native inline documentation viewer for EDLD.

Renders the docs/ directory as a browsable document reader with:
  - Sidebar tree: root docs + guides/ sub-section
  - Markdown renderer: headings, paragraphs, code blocks, lists, tables, HR
  - Forward / back navigation history
  - No external dependencies — pure GTK4 label rendering

All markdown rendering is intentional and opinionated — it targets the
actual docs shipped with EDLD, not a general-purpose parser.
"""

from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, GLib, Pango
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")


DOCS_DIR = Path(__file__).parents[1] / "docs"

# ── Document tree definition ──────────────────────────────────────────────────
# (display_title, relative_path_from_docs_dir)

DOC_TREE = [
    ("Configuration",       "CONFIGURATION.md"),
    ("Terminal Output",     "TERMINAL_OUTPUT.md"),
    ("Theming",             "THEMING.md"),
    ("Mission Bootstrap",   "MISSION_BOOTSTRAP.md"),
    ("─── Guides ───",      None),                          # section divider
    ("Linux Setup",         "guides/LINUX_SETUP.md"),
    ("Remote Access",       "guides/REMOTE_ACCESS.md"),
    ("Dual Pilot",          "guides/DUAL_PILOT.md"),
]


# ── Markdown → GTK renderer ───────────────────────────────────────────────────

def _render_markdown(md_text: str, box: Gtk.Box) -> None:
    """Render a markdown string into a Gtk.Box as native GTK widgets."""

    # Clear existing children
    while (child := box.get_first_child()):
        box.remove(child)

    lines = md_text.splitlines()
    i = 0

    def _append(widget: Gtk.Widget) -> None:
        widget.set_margin_start(0)
        widget.set_margin_end(0)
        box.append(widget)

    def _label(text: str, css: str, wrap=True, xalign=0.0, selectable=True) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.add_css_class(css)
        lbl.set_wrap(wrap)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl.set_xalign(xalign)
        lbl.set_selectable(selectable)
        lbl.set_hexpand(True)
        return lbl

    def _inline(text: str) -> str:
        """Convert inline markdown (bold, code, links) to Pango markup."""
        import re
        # Escape existing ampersands first
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # Inline code: `text`
        text = re.sub(r"`([^`]+)`", r'<tt>\1</tt>', text)
        # Bold: **text**
        text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
        # Italic: *text* or _text_
        text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)
        # Links: [text](url) — strip to just text
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        return text

    def _markup_label(text: str, css: str, xalign=0.0) -> Gtk.Label:
        lbl = Gtk.Label()
        lbl.set_markup(_inline(text))
        lbl.add_css_class(css)
        lbl.set_wrap(True)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl.set_xalign(xalign)
        lbl.set_selectable(True)
        lbl.set_hexpand(True)
        return lbl

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Blank line — small spacer
        if not stripped:
            sp = Gtk.Box()
            sp.set_size_request(-1, 4)
            _append(sp)
            i += 1
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___") or stripped.startswith("---"):
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.add_css_class("doc-hr")
            sep.set_margin_top(6)
            sep.set_margin_bottom(6)
            _append(sep)
            i += 1
            continue

        # ATX headings
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text  = stripped.lstrip("#").strip()
            css   = f"doc-h{min(level, 4)}"
            _append(_markup_label(text, css))
            i += 1
            continue

        # Fenced code block ```
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # consume closing ```
            code_text = "\n".join(code_lines)
            frame = Gtk.Frame()
            frame.add_css_class("doc-code-frame")
            frame.set_margin_top(4)
            frame.set_margin_bottom(4)
            sv = Gtk.ScrolledWindow()
            sv.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            sv.set_min_content_height(20)
            lbl = Gtk.Label(label=code_text)
            lbl.add_css_class("doc-code")
            lbl.set_xalign(0.0)
            lbl.set_yalign(0.0)
            lbl.set_selectable(True)
            lbl.set_wrap(False)
            lbl.set_margin_top(6)
            lbl.set_margin_bottom(6)
            lbl.set_margin_start(8)
            lbl.set_margin_end(8)
            sv.set_child(lbl)
            frame.set_child(sv)
            _append(frame)
            continue

        # Blockquote >
        if stripped.startswith(">"):
            text = stripped.lstrip(">").strip()
            frame = Gtk.Frame()
            frame.add_css_class("doc-blockquote")
            frame.set_margin_top(2)
            frame.set_margin_bottom(2)
            lbl = _markup_label(text, "doc-blockquote-text")
            lbl.set_margin_top(4)
            lbl.set_margin_bottom(4)
            lbl.set_margin_start(10)
            lbl.set_margin_end(6)
            frame.set_child(lbl)
            _append(frame)
            i += 1
            continue

        # Table — detect by | presence
        if "|" in stripped and i + 1 < len(lines) and "|" in lines[i + 1] and "---" in lines[i + 1]:
            # Collect table rows
            table_lines = []
            while i < len(lines) and "|" in lines[i]:
                table_lines.append(lines[i])
                i += 1
            if len(table_lines) >= 2:
                grid = Gtk.Grid()
                grid.add_css_class("doc-table")
                grid.set_column_spacing(12)
                grid.set_row_spacing(2)
                grid.set_margin_top(4)
                grid.set_margin_bottom(4)
                row_idx = 0
                for tline in table_lines:
                    if set(tline.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                        continue  # separator row
                    cells = [c.strip() for c in tline.strip().strip("|").split("|")]
                    for col_idx, cell in enumerate(cells):
                        lbl = Gtk.Label()
                        lbl.set_markup(_inline(cell))
                        lbl.set_xalign(0.0)
                        lbl.set_selectable(True)
                        lbl.set_wrap(True)
                        lbl.set_hexpand(True)
                        if row_idx == 0:
                            lbl.add_css_class("doc-table-header")
                        else:
                            lbl.add_css_class("doc-table-cell")
                        grid.attach(lbl, col_idx, row_idx, 1, 1)
                    row_idx += 1
                _append(grid)
            continue

        # Unordered list
        if stripped.startswith(("- ", "* ", "+ ")):
            # Collect contiguous list items
            list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            list_box.set_margin_start(12)
            list_box.set_margin_top(2)
            list_box.set_margin_bottom(2)
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ", "+ ")):
                item_text = lines[i].strip()[2:]
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                bullet = Gtk.Label(label="·")
                bullet.add_css_class("doc-bullet")
                bullet.set_valign(Gtk.Align.START)
                bullet.set_margin_top(1)
                item_lbl = Gtk.Label()
                item_lbl.set_markup(_inline(item_text))
                item_lbl.add_css_class("doc-li")
                item_lbl.set_wrap(True)
                item_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                item_lbl.set_xalign(0.0)
                item_lbl.set_selectable(True)
                item_lbl.set_hexpand(True)
                row.append(bullet)
                row.append(item_lbl)
                list_box.append(row)
                i += 1
            _append(list_box)
            continue

        # Numbered list
        import re
        if re.match(r"^\d+\. ", stripped):
            list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            list_box.set_margin_start(12)
            list_box.set_margin_top(2)
            list_box.set_margin_bottom(2)
            num = 1
            while i < len(lines) and re.match(r"^\d+\. ", lines[i].strip()):
                item_text = re.sub(r"^\d+\. ", "", lines[i].strip())
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                num_lbl = Gtk.Label(label=f"{num}.")
                num_lbl.add_css_class("doc-bullet")
                num_lbl.set_valign(Gtk.Align.START)
                num_lbl.set_margin_top(1)
                num_lbl.set_width_chars(3)
                num_lbl.set_xalign(1.0)
                item_lbl = Gtk.Label()
                item_lbl.set_markup(_inline(item_text))
                item_lbl.add_css_class("doc-li")
                item_lbl.set_wrap(True)
                item_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                item_lbl.set_xalign(0.0)
                item_lbl.set_selectable(True)
                item_lbl.set_hexpand(True)
                row.append(num_lbl)
                row.append(item_lbl)
                list_box.append(row)
                i += 1
                num += 1
            _append(list_box)
            continue

        # Regular paragraph
        _append(_markup_label(stripped, "doc-para"))
        i += 1


# ── DocsViewer window ─────────────────────────────────────────────────────────

class DocsViewer(Gtk.Window):
    """Native document viewer window."""

    def __init__(self, parent: Gtk.Window):
        super().__init__(title="EDLD Documentation")
        self.set_transient_for(parent)
        self.set_modal(False)
        self.set_default_size(900, 680)
        self.add_css_class("docs-viewer")

        self._history: list[str] = []
        self._history_pos: int   = -1

        self._build_ui()
        self._load_doc(DOC_TREE[0][1])   # open first doc by default

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctrl)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(outer)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.add_css_class("docs-toolbar")
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)
        toolbar.set_margin_start(8)
        toolbar.set_margin_end(8)
        outer.append(toolbar)

        self._btn_back = Gtk.Button(label="◀  Back")
        self._btn_back.add_css_class("docs-nav-btn")
        self._btn_back.connect("clicked", lambda *_: self._go_back())
        self._btn_back.set_sensitive(False)
        toolbar.append(self._btn_back)

        self._btn_fwd = Gtk.Button(label="Forward  ▶")
        self._btn_fwd.add_css_class("docs-nav-btn")
        self._btn_fwd.connect("clicked", lambda *_: self._go_forward())
        self._btn_fwd.set_sensitive(False)
        toolbar.append(self._btn_fwd)

        self._breadcrumb = Gtk.Label(label="")
        self._breadcrumb.add_css_class("docs-breadcrumb")
        self._breadcrumb.set_hexpand(True)
        self._breadcrumb.set_xalign(0.5)
        toolbar.append(self._breadcrumb)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        outer.append(sep)

        # ── Body: sidebar + content ───────────────────────────────────────────
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.set_vexpand(True)
        outer.append(body)

        # Sidebar
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.add_css_class("docs-sidebar-scroll")
        sidebar_scroll.set_size_request(190, -1)
        sidebar_scroll.set_vexpand(True)

        self._sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._sidebar.add_css_class("docs-sidebar")
        self._sidebar.set_margin_top(8)
        self._sidebar.set_margin_bottom(8)

        self._sidebar_btns: dict[str, Gtk.Button] = {}
        for title, path in DOC_TREE:
            if path is None:
                # Section divider
                lbl = Gtk.Label(label=title)
                lbl.add_css_class("docs-sidebar-section")
                lbl.set_xalign(0.5)
                lbl.set_margin_top(8)
                lbl.set_margin_bottom(4)
                self._sidebar.append(lbl)
            else:
                btn = Gtk.Button(label=title)
                btn.add_css_class("docs-sidebar-btn")
                btn.set_has_frame(False)
                btn.connect("clicked", self._on_sidebar_click, path)
                self._sidebar.append(btn)
                self._sidebar_btns[path] = btn

        sidebar_scroll.set_child(self._sidebar)
        body.append(sidebar_scroll)

        vsep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        body.append(vsep)

        # Content area
        self._content_scroll = Gtk.ScrolledWindow()
        self._content_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._content_scroll.set_hexpand(True)
        self._content_scroll.set_vexpand(True)
        self._content_scroll.add_css_class("docs-content-scroll")

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._content_box.add_css_class("docs-content")
        self._content_box.set_margin_top(16)
        self._content_box.set_margin_bottom(24)
        self._content_box.set_margin_start(24)
        self._content_box.set_margin_end(24)
        self._content_box.set_hexpand(True)

        self._content_scroll.set_child(self._content_box)
        body.append(self._content_scroll)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _load_doc(self, rel_path: str, push_history: bool = True) -> None:
        path = DOCS_DIR / rel_path
        if not path.exists():
            md = f"# Not found\n\nDocument `{rel_path}` does not exist."
        else:
            md = path.read_text(encoding="utf-8")

        if push_history:
            # Truncate forward history
            self._history = self._history[:self._history_pos + 1]
            self._history.append(rel_path)
            self._history_pos = len(self._history) - 1

        _render_markdown(md, self._content_box)

        # Scroll to top
        adj = self._content_scroll.get_vadjustment()
        adj.set_value(0)

        # Update breadcrumb
        title = next((t for t, p in DOC_TREE if p == rel_path), rel_path)
        self._breadcrumb.set_label(title)

        # Highlight active sidebar button
        for p, btn in self._sidebar_btns.items():
            if p == rel_path:
                btn.add_css_class("docs-sidebar-btn-active")
            else:
                btn.remove_css_class("docs-sidebar-btn-active")

        self._update_nav_buttons()

    def _go_back(self) -> None:
        if self._history_pos > 0:
            self._history_pos -= 1
            self._load_doc(self._history[self._history_pos], push_history=False)

    def _go_forward(self) -> None:
        if self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            self._load_doc(self._history[self._history_pos], push_history=False)

    def _update_nav_buttons(self) -> None:
        self._btn_back.set_sensitive(self._history_pos > 0)
        self._btn_fwd.set_sensitive(self._history_pos < len(self._history) - 1)

    def _on_sidebar_click(self, _btn, path: str) -> None:
        self._load_doc(path)

    def _on_key(self, ctrl, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval == Gdk.KEY_Left and (state & Gdk.ModifierType.ALT_MASK):
            self._go_back()
            return True
        if keyval == Gdk.KEY_Right and (state & Gdk.ModifierType.ALT_MASK):
            self._go_forward()
            return True
        return False

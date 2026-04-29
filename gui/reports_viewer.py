"""
gui/reports_viewer.py -- Statistical report viewer for EDLD.

Displays reports from core/reports.py with:
  - Sidebar list of available reports
  - Per-section sort controls (each section has independent sort state)
  - Loading spinner while scanning journals
  - Export to clipboard as TSV

Sort design: each rendered section owns a placeholder Gtk.Box that always
stays in the correct position in the layout.  Sorting replaces the grid
*inside* the placeholder, so no widgets are moved in the parent -- this
avoids the GTK4 Box limitation where append() always goes to the end.
Sort state is captured per-section in a closure dict, so multiple sections
on one report page do not interfere with each other.
"""

from __future__ import annotations
import threading
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, GLib
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from core.reports import REPORT_REGISTRY, ReportResult, ReportSection


class ReportsViewer(Gtk.Window):
    """Report viewer window -- non-modal, can stay open during play."""

    def __init__(self, parent: Gtk.Window, journal_dir: Path,
                 initial_key: str | None = None):
        super().__init__(title="EDLD Reports")
        self.set_transient_for(parent)
        self.set_modal(False)
        self.set_default_size(960, 700)
        self.add_css_class("reports-viewer")

        self._journal_dir  = journal_dir
        self._current_key  = None
        self._result_cache: dict[str, ReportResult] = {}
        self._loading      = False

        self._build_ui()

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctrl)

        if initial_key:
            self._on_report_click(None, initial_key)

    # ---- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(outer)

        # Toolbar
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.add_css_class("docs-toolbar")
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)
        toolbar.set_margin_start(8)
        toolbar.set_margin_end(8)
        outer.append(toolbar)

        self._title_lbl = Gtk.Label(label="Select a report")
        self._title_lbl.add_css_class("reports-title")
        self._title_lbl.set_hexpand(True)
        self._title_lbl.set_xalign(0.0)
        toolbar.append(self._title_lbl)

        self._refresh_btn = Gtk.Button(label="Refresh")
        self._refresh_btn.add_css_class("docs-nav-btn")
        self._refresh_btn.connect("clicked", lambda *_: self._reload_current())
        self._refresh_btn.set_sensitive(False)
        toolbar.append(self._refresh_btn)

        self._copy_btn = Gtk.Button(label="Copy TSV")
        self._copy_btn.add_css_class("docs-nav-btn")
        self._copy_btn.connect("clicked", lambda *_: self._copy_tsv())
        self._copy_btn.set_sensitive(False)
        toolbar.append(self._copy_btn)

        outer.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Body
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.set_vexpand(True)
        outer.append(body)

        # Sidebar
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_size_request(190, -1)
        sidebar_scroll.set_vexpand(True)
        sidebar_scroll.add_css_class("docs-sidebar-scroll")

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.add_css_class("docs-sidebar")
        sidebar.set_margin_top(8)
        sidebar.set_margin_bottom(8)

        self._sidebar_btns: dict[str, Gtk.Button] = {}
        for key, display, _fn in REPORT_REGISTRY:
            btn = Gtk.Button(label=display)
            btn.add_css_class("docs-sidebar-btn")
            btn.set_has_frame(False)
            btn.connect("clicked", self._on_report_click, key)
            sidebar.append(btn)
            self._sidebar_btns[key] = btn

        sidebar_scroll.set_child(sidebar)
        body.append(sidebar_scroll)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Content
        self._content_scroll = Gtk.ScrolledWindow()
        self._content_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._content_scroll.set_hexpand(True)
        self._content_scroll.set_vexpand(True)
        self._content_scroll.add_css_class("docs-content-scroll")

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._content_box.add_css_class("docs-content")
        self._content_box.set_margin_top(16)
        self._content_box.set_margin_bottom(24)
        self._content_box.set_margin_start(24)
        self._content_box.set_margin_end(24)
        self._content_box.set_hexpand(True)
        self._content_scroll.set_child(self._content_box)
        body.append(self._content_scroll)

    # ---- Report loading ------------------------------------------------------

    def _on_report_click(self, _btn, key: str) -> None:
        if self._loading:
            return
        self._current_key = key
        for k, btn in self._sidebar_btns.items():
            if k == key:
                btn.add_css_class("docs-sidebar-btn-active")
            else:
                btn.remove_css_class("docs-sidebar-btn-active")

        if key in self._result_cache:
            self._render_result(self._result_cache[key])
        else:
            self._run_report(key)

    def _reload_current(self) -> None:
        if self._current_key:
            self._result_cache.pop(self._current_key, None)
            self._run_report(self._current_key)

    def _run_report(self, key: str) -> None:
        fn = next((f for k, _, f in REPORT_REGISTRY if k == key), None)
        if fn is None:
            return

        self._loading = True
        self._refresh_btn.set_sensitive(False)
        self._copy_btn.set_sensitive(False)
        self._set_loading_state(True)

        def _worker():
            try:
                result = fn(self._journal_dir)
            except Exception as e:
                from core.reports import ReportResult
                result = ReportResult(title="Error", subtitle="", error=str(e))
            GLib.idle_add(self._on_result_ready, key, result)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_result_ready(self, key: str, result: ReportResult) -> None:
        self._loading = False
        self._result_cache[key] = result
        self._set_loading_state(False)
        self._refresh_btn.set_sensitive(True)
        if key == self._current_key:
            self._render_result(result)
        return False

    def _set_loading_state(self, loading: bool) -> None:
        self._clear_content()
        if loading:
            sp = Gtk.Spinner()
            sp.set_size_request(24, 24)
            sp.set_halign(Gtk.Align.CENTER)
            sp.start()
            lbl = Gtk.Label(label="Scanning journals...")
            lbl.add_css_class("reports-loading")
            lbl.set_halign(Gtk.Align.CENTER)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            box.set_vexpand(True)
            box.set_halign(Gtk.Align.CENTER)
            box.set_valign(Gtk.Align.CENTER)
            box.append(sp)
            box.append(lbl)
            self._content_box.append(box)

    # ---- Rendering -----------------------------------------------------------

    def _clear_content(self) -> None:
        while (c := self._content_box.get_first_child()):
            self._content_box.remove(c)

    def _render_result(self, result: ReportResult) -> None:
        self._clear_content()
        self._copy_btn.set_sensitive(True)
        self._refresh_btn.set_sensitive(True)

        t = Gtk.Label(label=result.title)
        t.add_css_class("reports-report-title")
        t.set_xalign(0.0)
        self._content_box.append(t)

        if result.subtitle:
            sub = Gtk.Label(label=result.subtitle)
            sub.add_css_class("reports-subtitle")
            sub.set_xalign(0.0)
            self._content_box.append(sub)

        if result.error:
            err = Gtk.Label(label="Error: " + result.error)
            err.add_css_class("health-crit")
            err.set_xalign(0.0)
            err.set_wrap(True)
            self._content_box.append(err)
            return

        self._title_lbl.set_label(result.title)

        for sec in result.sections:
            self._content_box.append(
                Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            )
            self._render_section(sec)

        adj = self._content_scroll.get_vadjustment()
        adj.set_value(0)

    def _render_section(self, sec: ReportSection) -> None:
        # Section heading
        hdr = Gtk.Label(label=sec.heading)
        hdr.add_css_class("reports-section-heading")
        hdr.set_xalign(0.0)
        self._content_box.append(hdr)

        if sec.prose:
            p = Gtk.Label(label=sec.prose)
            p.add_css_class("doc-para")
            p.set_wrap(True)
            p.set_xalign(0.0)
            p.set_hexpand(True)
            self._content_box.append(p)
            return

        if not sec.rows:
            return

        # A placeholder box occupies the fixed position in _content_box.
        # Sorting swaps the grid inside the placeholder rather than touching
        # the parent, which avoids GTK4 Box's append-to-end limitation.
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        placeholder.set_hexpand(True)

        # Per-section sort state in a mutable dict so the closure can update it.
        sort_state = {"col": 0, "asc": True}

        def _rebuild_grid(rows):
            old = placeholder.get_first_child()
            if old:
                placeholder.remove(old)
            placeholder.append(self._build_table_grid(sec.columns, rows))

        # Sort bar -- only shown for tables with 2+ columns
        if sec.columns and len(sec.columns) >= 2:
            sort_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            sort_bar.set_margin_bottom(4)
            sort_lbl = Gtk.Label(label="Sort:")
            sort_lbl.add_css_class("data-key")
            sort_bar.append(sort_lbl)

            # _make_handler wraps col_idx in a proper closure (avoids late-binding).
            def _make_handler(col_idx):
                def _handler(_btn):
                    if sort_state["col"] == col_idx:
                        sort_state["asc"] = not sort_state["asc"]
                    else:
                        sort_state["col"] = col_idx
                        sort_state["asc"] = True

                    def _sort_key(row):
                        val = row.cells[col_idx] if col_idx < len(row.cells) else ""
                        clean = (val.replace(",", "")
                                    .replace("B", "e9")
                                    .replace("M", "e6")
                                    .replace("k", "e3"))
                        try:
                            return (0, float(clean))
                        except ValueError:
                            return (1, val.lower())

                    _rebuild_grid(
                        sorted(sec.rows, key=_sort_key,
                               reverse=not sort_state["asc"])
                    )
                return _handler

            for col_idx, col_name in enumerate(sec.columns):
                btn = Gtk.Button(label=col_name)
                btn.add_css_class("reports-sort-btn")
                btn.connect("clicked", _make_handler(col_idx))
                sort_bar.append(btn)

            self._content_box.append(sort_bar)

        # Render initial (unsorted) data into the placeholder then place it.
        _rebuild_grid(sec.rows)
        self._content_box.append(placeholder)

        if sec.note:
            note = Gtk.Label(label=sec.note)
            note.add_css_class("data-key")
            note.set_xalign(0.0)
            note.set_margin_top(4)
            self._content_box.append(note)

    def _build_table_grid(self, columns: list[str], rows) -> Gtk.ScrolledWindow:
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        sw.set_hexpand(True)

        grid = Gtk.Grid()
        grid.add_css_class("doc-table")
        grid.set_column_spacing(16)
        grid.set_row_spacing(2)
        grid.set_hexpand(True)

        for ci, col in enumerate(columns):
            lbl = Gtk.Label(label=col)
            lbl.add_css_class("doc-table-header")
            lbl.set_xalign(0.0)
            lbl.set_hexpand(ci == 0)
            grid.attach(lbl, ci, 0, 1, 1)

        for ri, row in enumerate(rows, 1):
            for ci, cell in enumerate(row.cells):
                lbl = Gtk.Label(label=cell)
                lbl.add_css_class("doc-table-cell")
                lbl.set_xalign(0.0 if ci == 0 else 1.0)
                lbl.set_selectable(True)
                lbl.set_hexpand(ci == 0)
                grid.attach(lbl, ci, ri, 1, 1)

        sw.set_child(grid)
        return sw

    # ---- Copy TSV ------------------------------------------------------------

    def _copy_tsv(self) -> None:
        if not self._current_key or self._current_key not in self._result_cache:
            return
        result = self._result_cache[self._current_key]
        lines  = [result.title, result.subtitle, ""]
        for sec in result.sections:
            lines.append(sec.heading)
            if sec.columns:
                lines.append("\t".join(sec.columns))
            for row in sec.rows:
                lines.append("\t".join(row.cells))
            lines.append("")
        clipboard = self.get_display().get_clipboard()
        clipboard.set("\n".join(lines))

    def _on_key(self, ctrl, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

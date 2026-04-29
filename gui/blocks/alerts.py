"""
gui/blocks/alerts.py — Alerts block: last 5 alert events with fade-out.

Reads from the alerts component's alert_queue via core.plugin_call().
Fade: opacity 1.0 → 0.4 over seconds 60–90; permanent 0.4 after 90s.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget


class AlertsBlock(BlockWidget):
    BLOCK_TITLE = "Alerts"
    BLOCK_CSS   = "alerts-block"

    # Number of alert rows to show
    MAX_ROWS = 5

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        scroll_body = self._make_scroll_body(body)

        # Pre-build MAX_ROWS label rows; show/hide and update in refresh()
        self._alert_rows: list[Gtk.Label] = []
        for _ in range(self.MAX_ROWS):
            lbl = Gtk.Label(label="")
            lbl.set_xalign(0.0)
            lbl.set_hexpand(True)
            lbl.add_css_class("alert-entry")
            lbl.set_visible(False)
            scroll_body.append(lbl)
            self._alert_rows.append(lbl)

        # Clear button — pinned below the scrolled alert rows
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.add_css_class("alerts-clear-btn")
        clear_btn.set_halign(Gtk.Align.END)
        clear_btn.set_margin_top(4)
        clear_btn.set_margin_end(12)
        clear_btn.connect("clicked", self._on_clear)
        body.append(clear_btn)

    def _on_clear(self, _btn) -> None:
        self.core.plugin_call("alerts", "clear_alerts")

    def refresh(self) -> None:
        # Pull current alerts from the alerts component via CoreAPI
        alerts = self.core.plugin_call("alerts", "get_alerts") or []

        for i, lbl in enumerate(self._alert_rows):
            if i < len(alerts):
                alert   = alerts[i]
                opacity = self.core.plugin_call("alerts", "opacity_for", alert) or 1.0
                text    = f"{alert['emoji']}  {alert['text']}"
                lbl.set_label(text)
                lbl.set_opacity(opacity)
                lbl.set_visible(True)
            else:
                lbl.set_label("")
                lbl.set_visible(False)

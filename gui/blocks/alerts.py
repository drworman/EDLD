"""
gui/blocks/alerts.py — Alerts block: last 5 alert events with fade-out.

Reads from the alerts component's alert_queue via core.plugin_call().
Fade: opacity 1.0 → 0.4 over seconds 60–90; permanent 0.4 after 90s.

The block's footer carries the session-management surface (status indicator,
enabled toggle, End Session button) when the session-management plugin is
loaded.  The former standalone Session Management block has been folded in here
so the controls live alongside the alerts they tend to be reacting to.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
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

        # Session-management footer surface — populated on an idle callback
        # because the footer doesn't exist during build() (block_base creates it
        # after build() returns).  Same deferred pattern Commander uses for its
        # home-location search row.
        self._ksw_status_lbl: Gtk.Label  | None = None
        self._ksw_toggle:     Gtk.Switch | None = None
        self._ksw_end_btn:    Gtk.Button | None = None
        GLib.idle_add(self._build_ksw_footer)

    def _on_clear(self, _btn) -> None:
        self.core.plugin_call("alerts", "clear_alerts")

    # ── Session-management footer ──────────────────────────────────────────────

    def _build_ksw_footer(self) -> bool:
        """Idle callback: drop the session-management controls into the
        footer if the session-management plugin is loaded.  Returns False so
        GLib only calls us once."""
        ft = self.footer()
        if ft is None:
            return False
        plugin = self.core._plugins.get("ksw")
        if plugin is None:
            # No session-management plugin → no footer controls.  Footer keeps
            # only the resize handle on the right.
            return False

        # "Status: ✓" / "Status: ✗" — green check when ready, red cross
        # when not.  Uses pango markup so we get colour without needing
        # bespoke CSS classes.
        self._ksw_status_lbl = Gtk.Label()
        self._ksw_status_lbl.set_use_markup(True)
        self._ksw_status_lbl.set_valign(Gtk.Align.CENTER)
        self._ksw_status_lbl.set_margin_start(4)
        self._ksw_status_lbl.set_margin_end(8)
        self._ksw_status_lbl.add_css_class("data-key")

        # "Enabled" label + toggle switch.  Always interactive — the
        # session-flush path independently checks readiness, so flipping
        # this when not ready is a safe no-op rather than a hazard.
        enabled_lbl = Gtk.Label(label="Enabled")
        enabled_lbl.set_valign(Gtk.Align.CENTER)
        enabled_lbl.set_margin_end(4)
        enabled_lbl.add_css_class("data-key")

        self._ksw_toggle = Gtk.Switch()
        self._ksw_toggle.set_valign(Gtk.Align.CENTER)
        self._ksw_toggle.set_active(bool(getattr(plugin, "_session_enabled", True)))
        self._ksw_toggle.connect("state-set", self._on_ksw_toggle)

        # End Session button — gated on readiness since pressing it ends
        # the session, which only does anything meaningful when the host
        # is ready.
        self._ksw_end_btn = Gtk.Button(label="End Session")
        self._ksw_end_btn.set_valign(Gtk.Align.CENTER)
        self._ksw_end_btn.add_css_class("cmdr-footer-btn")
        self._ksw_end_btn.set_margin_start(8)
        self._ksw_end_btn.connect("clicked", self._on_ksw_end_session)

        # Prepend pushes items to the LEFT of the footer (the spacer +
        # resize handle stay on the right).  Reverse order so the visible
        # left-to-right order is: Status | Enabled [switch] | End Session
        ft.prepend(self._ksw_end_btn)
        ft.prepend(self._ksw_toggle)
        ft.prepend(enabled_lbl)
        ft.prepend(self._ksw_status_lbl)

        self._refresh_ksw_footer()
        return False

    def _refresh_ksw_footer(self) -> None:
        """Refresh status indicator + button sensitivity from plugin state.
        Called from refresh() (block-level repaint) and once at footer build."""
        plugin = self.core._plugins.get("ksw")
        if plugin is None or self._ksw_status_lbl is None:
            return
        ready = bool(self.core.plugin_call("ksw", "check_ready"))
        if ready:
            self._ksw_status_lbl.set_markup(
                'Status: <span foreground="#3fcf7f">✓</span>'
            )
            self._ksw_status_lbl.set_tooltip_text("Session management ready")
        else:
            self._ksw_status_lbl.set_markup(
                'Status: <span foreground="#cf3f3f">✗</span>'
            )
            self._ksw_status_lbl.set_tooltip_text(
                "Session management not ready"
            )
        # End Session button stays disabled when not ready (pressing it
        # does nothing useful otherwise).
        if self._ksw_end_btn is not None:
            self._ksw_end_btn.set_sensitive(ready)
        # Toggle visual sync only if it diverges — guards against clobbering
        # the user's last interactive choice.  Block our own state-set
        # handler while we sync so we don't loop.
        if self._ksw_toggle is not None:
            desired = bool(getattr(plugin, "_session_enabled", True))
            if self._ksw_toggle.get_active() != desired:
                self._ksw_toggle.handler_block_by_func(self._on_ksw_toggle)
                try:
                    self._ksw_toggle.set_active(desired)
                finally:
                    self._ksw_toggle.handler_unblock_by_func(self._on_ksw_toggle)

    def _on_ksw_toggle(self, _sw: Gtk.Switch, state: bool) -> bool:
        plugin = self.core._plugins.get("ksw")
        if plugin is not None:
            plugin._session_enabled = bool(state)
        # Return False so GTK runs the default handler (state ← active).
        return False

    def _on_ksw_end_session(self, _btn: Gtk.Button) -> None:
        self.core.plugin_call("ksw", "flush_session", "Manual Termination")

    # ── Refresh ───────────────────────────────────────────────────────────────

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

        # Keep the session-management footer state in sync with the plugin.
        self._refresh_ksw_footer()

"""gui/blocks/alerts.py — Recent alerts block (Qt)."""

from __future__ import annotations

from gui.block_base import GuiBlock, TextRow

_MAX_ROWS = 5


class AlertsBlock(GuiBlock):
    BLOCK_TITLE = "ALERTS"

    def _build_body(self, layout) -> None:
        self._rows: list[TextRow] = []
        for _ in range(_MAX_ROWS):
            row = self.text("", "", wrap=False)
            self._rows.append(row)
            layout.addWidget(row)
        layout.addStretch(1)

    def refresh_data(self) -> None:
        alerts = self.core.plugin_call("alerts", "get_alerts") or []
        for i, lbl in enumerate(self._rows):
            if i < len(alerts):
                a = alerts[i]
                opacity = self.core.plugin_call("alerts", "opacity_for", a) or 1.0
                text = f"{a.get('emoji', '')}  {a.get('text', '')}"
                # The TUI dims an ageing alert through its own opacity handling;
                # Qt has no equivalent on a stylesheet label, so the same
                # threshold switches the row to the dim role instead.
                lbl.set_text(text)
                lbl.setProperty("role", "dim" if opacity < 0.7 else "val")
            else:
                lbl.set_text("")
                lbl.setProperty("role", "val")
            style = lbl.style()
            style.unpolish(lbl)
            style.polish(lbl)

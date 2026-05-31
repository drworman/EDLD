"""tui/blocks/alerts.py — Recent alerts block."""
from __future__ import annotations
from textual.app        import ComposeResult
from textual.widgets    import Label
from textual.containers import Vertical
from tui.block_base     import TuiBlock

_MAX_ROWS = 5


class AlertsBlock(TuiBlock):
    BLOCK_TITLE = "ALERTS"

    def _compose_body(self) -> ComposeResult:
        with Vertical():
            for i in range(_MAX_ROWS):
                yield Label("", id=f"alert-{i}", classes="alert-entry")

    def refresh_data(self) -> None:
        alerts = self.core.plugin_call("alerts", "get_alerts") or []
        for i in range(_MAX_ROWS):
            try:
                lbl = self.query_one(f"#alert-{i}", Label)
            except Exception:
                continue
            if i < len(alerts):
                a       = alerts[i]
                opacity = self.core.plugin_call("alerts", "opacity_for", a) or 1.0
                text    = f"{a.get('emoji', '')}  {a.get('text', '')}"
                lbl.update(f"[dim]{text}[/dim]" if opacity < 0.7 else text)
            else:
                lbl.update("")

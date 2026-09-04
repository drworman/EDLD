"""
tui/blocks/session.py — Session window (Textual).

Current-session activity, split out of the Career block's Summary tab into
a window of its own so the session view and the career view each get full
height instead of sharing one tab.

Content comes from ``core.summary_model.session_sections()`` — the same
model the Career block's Summary tab renders at lifetime scope.  The two
windows therefore show the same sections, in the same order, with the same
meaning; only the scope differs.  Anything added to the model appears in
both.

Because this window no longer shares space with the wealth breakdown, it
renders each activity provider's full tab rows rather than the condensed
summary rows the Career block used to inline — notable bodies, habitable
zones, in-progress bio scans, per-commodity trade profit, limpet
efficiency, per-system merits.

Reset with Ctrl+R, which routes to session_stats.on_new_session(0).
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label
from textual.containers import VerticalScroll

from tui.block_base     import TuiBlock, KVRow, SecHdr
from core.summary_model import session_sections


class SessionBlock(TuiBlock):
    BLOCK_TITLE = "SESSION"

    def _compose_body(self) -> ComposeResult:
        yield VerticalScroll(id="session-body")

    def refresh_data(self) -> None:
        try:
            scroll = self.query_one("#session-body", VerticalScroll)
        except Exception:
            return

        try:
            sections = session_sections(self.core)
        except Exception:
            sections = []

        widgets: list = []
        for section in sections:
            widgets.append(SecHdr(section["title"]))
            for row in section["rows"]:
                if row["kind"] == "sub":
                    widgets.append(Label(row["label"], classes="dim"))
                    continue
                value = row["value"]
                if row.get("rate"):
                    value = f"{value}  {row['rate']}"
                widgets.append(KVRow(row["label"], value))

        scroll.remove_children()
        if not widgets:
            scroll.mount(Label("No session activity yet", classes="dim"))
            return
        scroll.mount(*widgets)

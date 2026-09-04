"""
gui/blocks/session.py — Session window (Qt).

Current-session activity, rendered from ``core.summary_model.session_sections()``
— the same model the Career block's Summary tab renders at lifetime scope, and
the same one the Textual Session window uses.  Three renderers, one model: a
section added to the model appears in all of them without any of them changing.

Reset with Ctrl+R, which routes to ``session_stats.on_new_session(0)``.
"""

from __future__ import annotations

from gui.block_base import GuiBlock
from core.summary_model import session_sections


class SessionBlock(GuiBlock):
    BLOCK_TITLE = "SESSION"

    def _build_body(self, layout) -> None:
        self._scroll = self.scroll()
        layout.addWidget(self._scroll, 1)

    def refresh_data(self) -> None:
        try:
            sections = session_sections(self.core)
        except Exception:
            sections = []

        rows: list = []
        for section in sections:
            rows.append(self.hdr(section["title"]))
            for row in section["rows"]:
                if row["kind"] == "sub":
                    rows.append(self.text(row["label"], "dim"))
                    continue
                value = row["value"]
                if row.get("rate"):
                    value = f"{value}  {row['rate']}"
                rows.append(self.kv(row["label"], value))

        if not rows:
            rows = [self.text("No session activity yet", "dim")]
        self._scroll.set_rows(rows)

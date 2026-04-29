"""tui/blocks/session_stats.py — Session statistics block."""
from __future__ import annotations
from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane
from textual.containers import VerticalScroll
from tui.block_base     import TuiBlock, KVRow, SecHdr

_ALL_TABS = [
    ("Summary",  "ss-tab-summary"),
    ("Combat",   "ss-tab-combat"),
    ("Exobio",   "ss-tab-exobiology"),
    ("Explore",  "ss-tab-exploration"),
    ("Income",   "ss-tab-income"),
    ("Mine",     "ss-tab-mining"),
    ("Mission",  "ss-tab-missions"),
    ("Odyssey",  "ss-tab-odyssey"),
    ("PPlay",    "ss-tab-powerplay"),
    ("Trade",    "ss-tab-trade"),
]

_PROVIDER_TO_PANE: dict[str, str] = {
    "Combat":      "ss-tab-combat",
    "Exobiology":  "ss-tab-exobiology",
    "Exploration": "ss-tab-exploration",
    "Income":      "ss-tab-income",
    "Mining":      "ss-tab-mining",
    "Missions":    "ss-tab-missions",
    "Odyssey":     "ss-tab-odyssey",
    "PowerPlay":   "ss-tab-powerplay",
    "Trade":       "ss-tab-trade",
}


class SessionStatsBlock(TuiBlock):
    BLOCK_TITLE = "SESSION STATS"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="ss-tabs"):
            for title, pane_id in _ALL_TABS:
                with TabPane(title, id=pane_id):
                    yield VerticalScroll(id=f"{pane_id}-scroll")

    def refresh_data(self) -> None:
        core      = self.core
        providers = getattr(core, "session_providers", [])
        plugin    = core._plugins.get("session_stats")
        dur_s     = plugin.session_duration_seconds() if plugin else 0.0

        # ── Summary: SecHdr per active provider + all its rows ────────────────
        summary: list = []
        if dur_s > 0:
            summary.append(KVRow("Duration", self.fmt_duration(dur_s)))
        for p in providers:
            if not hasattr(p, "get_summary_rows") or not p.has_activity():
                continue
            title = getattr(p, "ACTIVITY_TAB_TITLE", "")
            rows  = self._build_kv_rows(p.get_summary_rows())
            if not rows:
                continue
            if title:
                summary.append(SecHdr(title))
            summary.extend(rows)
        if not summary:
            summary.append(Label("[dim]No session data[/dim]", classes="dim"))
        self._repopulate("ss-tab-summary", summary)

        # ── Per-provider detail tabs ──────────────────────────────────────────
        active: set[str] = set()
        for p in providers:
            if not hasattr(p, "get_tab_rows") or not p.has_activity():
                continue
            title   = getattr(p, "ACTIVITY_TAB_TITLE", "")
            pane_id = _PROVIDER_TO_PANE.get(title)
            if not pane_id:
                continue
            active.add(title)
            self._repopulate(pane_id, self._build_kv_rows(p.get_tab_rows()))

        for title, pane_id in _PROVIDER_TO_PANE.items():
            if title not in active:
                self._repopulate(pane_id, [])

    def _repopulate(self, pane_id: str, rows: list) -> None:
        try:
            scroll = self.query_one(f"#{pane_id}-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        scroll.mount(*(rows or [Label("[dim]—[/dim]", classes="dim")]))

    def _build_kv_rows(self, raw_rows: list) -> list:
        out: list = []
        for row in raw_rows:
            lbl  = row.get("label", "")
            val  = row.get("value", "—")
            rate = row.get("rate")
            if lbl.startswith("─"):
                continue
            out.append(KVRow(lbl, f"{val}  [dim]{rate}[/dim]" if rate else val))
        return out

"""
tui/search_modal.py — Generic search-and-select modal for the EDLD TUI.

Used for:
  - Commander block: Set Home location (system or station)
  - Cargo block:     Set Target market (station)

Usage:
    async def on_result(value: dict | None) -> None: ...
    screen = SearchModal(
        title       = "Set Home Location",
        placeholder = "System or station name…",
        search_fn   = spansh_plugin.search_home,
        result_label= lambda r: f"{r['name']}  ({r.get('system','')})",
        callback    = on_result,
    )
    self.app.push_screen(screen)
"""
from __future__ import annotations
import threading
from typing import Callable

from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import ModalScreen
from textual.widgets    import Label, Button, Input
from textual.containers import Vertical, VerticalScroll


class SearchModal(ModalScreen):
    """Search-and-select modal.  Dismiss with Escape or a result click."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(
        self,
        title:        str,
        placeholder:  str,
        search_fn:    Callable[[str], list],
        result_label: Callable[[dict], str],
        callback:     Callable[[dict | None], None],
        **kw,
    ) -> None:
        super().__init__(**kw)
        self._title        = title
        self._placeholder  = placeholder
        self._search_fn    = search_fn
        self._result_label = result_label
        self._callback     = callback
        self._results:     list[dict] = []
        self._timer        = None
        self._searching    = False

    def compose(self) -> ComposeResult:
        with Vertical(id="search-outer"):
            yield Label(f" {self._title} ", id="search-title", classes="block-title")
            yield Label(
                "[dim]Type at least 3 characters then wait for results.[/dim]",
                id="search-hint",
                classes="dim",
            )
            yield Input(placeholder=self._placeholder, id="search-input")
            yield Label("", id="search-status", classes="dim")
            with VerticalScroll(id="search-results"):
                yield Label("[dim]No results yet.[/dim]", id="search-placeholder")

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.strip()
        if self._timer is not None:
            self._timer.cancel()
        if len(query) < 3:
            self._set_status("")
            self._clear_results("[dim]Type at least 3 characters.[/dim]")
            return
        self._set_status("[dim]Searching…[/dim]")
        self._timer = threading.Timer(0.4, self._do_search, args=(query,))
        self._timer.daemon = True
        self._timer.start()

    def _do_search(self, query: str) -> None:
        try:
            results = self._search_fn(query)
        except Exception as exc:
            results = []
            self.app.call_from_thread(
                self._set_status, f"[red]Search error: {exc}[/red]"
            )
        self._results = results
        self.app.call_from_thread(self._show_results, results)

    def _show_results(self, results: list[dict]) -> None:
        try:
            scroll = self.query_one("#search-results", VerticalScroll)
            scroll.remove_children()
        except Exception:
            return
        if not results:
            self._set_status("[dim]No results.[/dim]")
            scroll.mount(Label("[dim]No results found.[/dim]", classes="dim"))
            return
        self._set_status(f"[dim]{len(results)} result(s) — click to select[/dim]")
        for i, r in enumerate(results):
            lbl = self._result_label(r)
            scroll.mount(Button(lbl, id=f"result-{i}", classes="search-result-btn"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = str(event.button.id or "")
        if not bid.startswith("result-"):
            return
        idx = int(bid[7:])
        if 0 <= idx < len(self._results):
            chosen = self._results[idx]
            self._callback(chosen)
        self.dismiss()

    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#search-status", Label).update(text)
        except Exception:
            pass

    def _clear_results(self, msg: str = "") -> None:
        try:
            scroll = self.query_one("#search-results", VerticalScroll)
            scroll.remove_children()
            if msg:
                scroll.mount(Label(msg, classes="dim"))
        except Exception:
            pass

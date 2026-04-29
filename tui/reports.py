"""
tui/reports.py — Statistical reports screen for the EDLD TUI.

Wraps core/reports.py (REPORT_REGISTRY) in a full-screen ModalScreen with:
  - Left sidebar: clickable report names
  - Right panel: scrollable rendered report content
  - Background thread for journal scanning (uses app.call_from_thread
    which is the safe path from worker threads to the Textual event loop)
  - Press Escape or r to dismiss
"""
from __future__ import annotations
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import ModalScreen
from textual.widgets    import Label, Button
from textual.containers import Horizontal, Vertical, VerticalScroll

from core.reports import REPORT_REGISTRY, ReportResult, ReportSection

if TYPE_CHECKING:
    from core.core_api import CoreAPI


class ReportsScreen(ModalScreen):
    """Full-screen reports viewer.  Press r or Escape to close."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("r",      "dismiss", "Close"),
    ]

    def __init__(self, core: "CoreAPI", **kw) -> None:
        super().__init__(**kw)
        self._core        = core
        self._current_key: str | None = None
        self._loading     = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="reports-outer"):
            with Vertical(id="reports-sidebar"):
                yield Label(" REPORTS ", classes="block-title")
                for key, display, _ in REPORT_REGISTRY:
                    yield Button(display, id=f"rpt-{key}",
                                 classes="reports-sidebar-btn")
            with Vertical(id="reports-content"):
                yield Label(" Select a report ", id="reports-title",
                            classes="block-title")
                with VerticalScroll(id="reports-scroll"):
                    yield Label(
                        "[dim]Select a report from the sidebar.[/dim]",
                        id="reports-body",
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = str(event.button.id or "")
        if not bid.startswith("rpt-"):
            return
        key = bid[4:]
        if self._loading or key == self._current_key:
            return

        # Highlight the active sidebar button
        for k, _, _ in REPORT_REGISTRY:
            try:
                btn = self.query_one(f"#rpt-{k}", Button)
                if k == key:
                    btn.add_class("-active")
                else:
                    btn.remove_class("-active")
            except Exception:
                pass

        self._current_key = key
        display = next((d for k2, d, _ in REPORT_REGISTRY if k2 == key), key)
        self._set_title(f" {display} — Loading… ")
        self._set_body("[dim]Scanning journals…[/dim]")
        self._loading = True

        threading.Thread(
            target=self._run_report,
            args=(key,),
            daemon=True,
            name=f"rpt-{key}",
        ).start()

    # ── Background worker ──────────────────────────────────────────────────────

    def _run_report(self, key: str) -> None:
        """Thread body.  Always ends with a call_from_thread so the UI updates."""
        result: ReportResult | None = None
        try:
            fn = next((f for k, _, f in REPORT_REGISTRY if k == key), None)
            if fn is None:
                result = ReportResult(title="Error", subtitle="",
                                      error=f"Unknown report key: {key!r}")
            else:
                journal_dir = Path(self._core.journal_dir)
                result = fn(journal_dir)
        except BaseException as exc:          # catch everything, including OOM
            result = ReportResult(title="Error", subtitle="", error=str(exc))
        finally:
            # Always schedule the UI update on the main loop, even on failure.
            # Use self.app.call_from_thread — the only safe path from a raw
            # thread to the Textual event loop regardless of screen type.
            try:
                self.app.call_from_thread(self._deliver_result, key,
                                          result or ReportResult(
                                              title="Error", subtitle="",
                                              error="Report produced no result"))
            except BaseException:
                pass  # app may have exited; nothing useful to do

    def _deliver_result(self, key: str, result: ReportResult) -> None:
        """Called on the main event-loop thread via call_from_thread."""
        self._loading = False
        try:
            display = next((d for k, d, _ in REPORT_REGISTRY if k == key), key)
            if result.error:
                self._set_title(f" {display} ")
                self._set_body(f"[red]Error:[/red]\n{result.error}")
                return
            title_text = f" {display} "
            if result.subtitle:
                title_text += f"[dim] — {result.subtitle}[/dim]"
            self._set_title(title_text)
            self._set_body(self._render_result(result))
        except BaseException as exc:
            self._set_body(f"[red]Render error:[/red] {exc}")

    # ── Rendering ──────────────────────────────────────────────────────────────

    _IS_NUMERIC = re.compile(r"^[\d,\.%+\-\s]+$")

    def _render_result(self, result: ReportResult) -> str:
        parts: list[str] = []
        for sec in result.sections:
            if sec.heading:
                parts.append(f"[bold]{sec.heading.upper()}[/bold]")
            if sec.prose:
                parts.append(sec.prose)
            if sec.columns and sec.rows:
                # Dynamic column widths
                widths = [len(c) for c in sec.columns]
                for row in sec.rows:
                    for i, cell in enumerate(row.cells):
                        if i < len(widths):
                            widths[i] = max(widths[i], len(str(cell)))
                # Header
                hdr = "  ".join(
                    f"[dim]{sec.columns[i]:<{widths[i]}}[/dim]"
                    for i in range(len(sec.columns))
                )
                parts.append(hdr)
                sep = "  ".join("─" * widths[i] for i in range(len(sec.columns)))
                parts.append(f"[dim]{sep}[/dim]")
                # Rows
                for row in sec.rows:
                    cells_fmt = []
                    for i, cell in enumerate(row.cells):
                        cell = str(cell)
                        w    = widths[i] if i < len(widths) else 0
                        # Right-align numeric columns (all but the first)
                        if i > 0 and self._IS_NUMERIC.match(cell.strip()):
                            cells_fmt.append(f"{cell:>{w}}")
                        else:
                            cells_fmt.append(f"{cell:<{w}}")
                    parts.append("  ".join(cells_fmt))
            if sec.note:
                parts.append(f"[dim]{sec.note}[/dim]")
            parts.append("")  # blank line between sections
        return "\n".join(parts).rstrip() or "[dim]No data for this report.[/dim]"

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_title(self, text: str) -> None:
        try:
            self.query_one("#reports-title", Label).update(text)
        except Exception:
            pass

    def _set_body(self, text: str) -> None:
        try:
            self.query_one("#reports-body", Label).update(text)
        except Exception:
            pass

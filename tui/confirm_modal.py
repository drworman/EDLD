"""
tui/confirm_modal.py — Minimal yes/no confirmation modal for the EDLD TUI.

Used to guard destructive actions (e.g. a manual session termination) behind an
explicit confirmation so a stray keypress cannot trigger them.

Usage:
    def on_result(ok: bool | None) -> None:
        if ok:
            ...  # user confirmed
    self.app.push_screen(
        ConfirmModal("Terminate game session?", "This quits the game now."),
        on_result,
    )

The screen is dismissed with True (confirmed) or False (cancelled); the result
is delivered to the push_screen callback.  The "No" button is focused on open,
so Enter cancels by default.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.binding    import Binding
from textual.screen     import ModalScreen
from textual.widgets    import Label, Button
from textual.containers import Vertical, Horizontal


class ConfirmModal(ModalScreen):
    """A small yes/no confirmation dialog.  Returns True (Yes) or False (No)."""

    BINDINGS = [
        Binding("y",      "confirm", "Yes"),
        Binding("n",      "cancel",  "No"),
        Binding("escape", "cancel",  "Cancel"),
    ]

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal #confirm-box {
        width: 64;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        border: round $error;
        background: $surface;
    }
    ConfirmModal #confirm-title {
        width: 100%;
        text-style: bold;
        color: $error;
        content-align: center middle;
        padding-bottom: 1;
    }
    ConfirmModal #confirm-msg {
        width: 100%;
        padding-bottom: 1;
    }
    ConfirmModal #confirm-row {
        width: 100%;
        height: auto;
        align: center middle;
    }
    ConfirmModal #confirm-row Button {
        margin: 0 1;
    }
    """

    def __init__(self, title: str, message: str = "", **kw) -> None:
        super().__init__(**kw)
        self._title   = title
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self._title, id="confirm-title")
            if self._message:
                yield Label(self._message, id="confirm-msg")
            with Horizontal(id="confirm-row"):
                yield Button("Yes  (y)", id="confirm-yes", variant="error")
                yield Button("No  (n)",  id="confirm-no",  variant="primary")

    def on_mount(self) -> None:
        # Focus "No" by default so an accidental Enter cancels rather than confirms.
        try:
            self.query_one("#confirm-no", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(str(event.button.id) == "confirm-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

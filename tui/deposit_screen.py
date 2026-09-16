"""
tui/deposit_screen.py — Add or edit the surface deposit you are parked on.

One screen for both, because the commander does not know which they are doing
until EDLD has looked at where they are standing. ``form_for_here()`` answers
that and supplies the contents; this only draws them.

The fields come from ``core.deposit_form.FIELDS`` rather than being listed
here, so this screen and the GUI dialog cannot drift apart on what a deposit
has.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from core.deposit_form import FIELDS


class DepositScreen(ModalScreen):
    """A small form over the dashboard, dismissed with Escape."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, core, plugin) -> None:
        super().__init__()
        self._core = core
        self._plugin = plugin
        self._form, self._heading = plugin.form_for_here()

    def compose(self) -> ComposeResult:
        with Vertical(classes="pref-dialog", id="deposit-dialog"):
            yield Label("SURFACE DEPOSIT", classes="pref-title")
            yield Label(self._heading, id="deposit-heading", classes="pref-note")

            for field in FIELDS:
                current = str(self._form.get(field.key, "") or "")
                with Horizontal(classes="pref-row"):
                    yield Label(field.label, classes="key")
                    if field.kind == "choice":
                        yield Select([(c, c) for c in field.choices],
                                     value=current or None,
                                     id=f"dep-{field.key}",
                                     classes="pref-choice", allow_blank=True)
                    elif field.kind == "bool":
                        yield Select([("No", ""), ("Yes", "true")],
                                     value=current or "",
                                     id=f"dep-{field.key}",
                                     classes="pref-choice", allow_blank=False)
                    else:
                        yield Input(value=current, placeholder=field.hint,
                                    id=f"dep-{field.key}", classes="pref-input")

            yield Label("", id="deposit-result", classes="pref-note")
            with Horizontal(classes="pref-buttons"):
                yield Button("Save", id="dep-save", variant="primary")
                yield Button("Cancel", id="dep-cancel")

    def _values(self) -> dict:
        out: dict = {}
        for field in FIELDS:
            try:
                widget = self.query_one(f"#dep-{field.key}")
            except Exception:
                continue
            value = getattr(widget, "value", "")
            out[field.key] = "" if value is None else str(value)
        return out

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dep-cancel":
            self.dismiss()
            return
        if event.button.id != "dep-save":
            return
        result = self._plugin.submit_form(self._values())
        # Stay open on a rejection so the commander can correct the field
        # rather than retype the whole form; close on success so a keybind and
        # two keystrokes is the whole interaction.
        if result.startswith(("recorded", "updated")):
            self.dismiss()
        else:
            self.query_one("#deposit-result", Label).update(result)

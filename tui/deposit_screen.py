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
from textual.widgets import Button, Input, Label, Select, TextArea

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
        with Vertical(id="deposit-dialog"):
            yield Label("SURFACE DEPOSIT", classes="pref-title")
            yield Label(self._heading, id="deposit-heading", classes="pref-note")

            for field in FIELDS:
                current = str(self._form.get(field.key, "") or "")
                if field.kind == "note":
                    with Horizontal(classes="pref-row dep-note-row"):
                        yield Label(field.label, classes="key")
                        yield self._note_area(field, current)
                    continue
                with Horizontal(classes="pref-row"):
                    yield Label(field.label, classes="key")
                    if field.kind == "choice":
                        # The value is omitted entirely when there is nothing
                        # to select, rather than passed as None or BLANK.
                        #
                        # Textual validates a Select's value on mount, not on
                        # construction, so a None here raised
                        # InvalidSelectValueError the moment the screen was
                        # pushed — and an unhandled exception in a mount
                        # handler takes the whole app down. That is why this
                        # presented as EDLD vanishing on a keypress rather than
                        # as one broken field. Every field is blank on a new
                        # deposit, so it was certain to happen the first time
                        # anyone added one.
                        #
                        # The blank sentinel has moved between Textual releases
                        # — it is Select.NULL in some and Select.BLANK in
                        # others, and in at least one version BLANK is a plain
                        # False that the validator then rejects. Leaving the
                        # argument off uses whichever default that release
                        # considers blank, across the range requirements.txt
                        # allows.
                        kwargs = {"id": f"dep-{field.key}",
                                  "classes": "pref-choice",
                                  "allow_blank": True}
                        # Matched case-insensitively against the options, and
                        # dropped if it matches none. A stored value that is
                        # not an option crashes the same way None did, and one
                        # can reach the store: deposits imported from a shared
                        # sheet are written as the sheet spells them, so
                        # another commander hand-editing a cell to "high" or
                        # "Very High" would take this window down on whoever
                        # opened it next.
                        chosen = next((c for c in field.choices
                                       if c.lower() == current.lower()), None)
                        if chosen:
                            kwargs["value"] = chosen
                        yield Select([(c, c) for c in field.choices], **kwargs)
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

    @staticmethod
    def _note_area(field, current: str) -> TextArea:
        """A few lines of wrapping text, whatever Textual release is installed.

        TextArea's constructor has grown keywords across the releases
        requirements.txt allows — soft wrap, line numbers and tab behaviour
        all arrived as arguments after it did, and line numbers defaulted on
        before they defaulted off. Each is set as an attribute where it exists
        rather than passed where it might not be accepted, so an older Textual
        gets a plainer box instead of a TypeError when Ctrl+D is pressed.
        """
        area = TextArea(current, id=f"dep-{field.key}", classes="dep-note")
        for attr, value in (("soft_wrap", True),
                            ("show_line_numbers", False),
                            # Tab moves on to Save, as from every other field.
                            ("tab_behavior", "focus")):
            if hasattr(area, attr):
                try:
                    setattr(area, attr, value)
                except Exception:
                    pass
        return area

    def _values(self) -> dict:
        out: dict = {}
        for field in FIELDS:
            try:
                widget = self.query_one(f"#dep-{field.key}")
            except Exception:
                continue
            if isinstance(widget, TextArea):
                out[field.key] = widget.text
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

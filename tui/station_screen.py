"""
tui/station_screen.py — the Radio tab's Add Station form (Textual).

Name, stream address, and where to keep it: globally in ``[Radio]``, or in
the profile loaded now.  Global is preselected, and the profile choice is
disabled when no profile is loaded.  Validation, the Id and the write to
config.toml are ``RadioController.add_station``'s, shared with the desktop
dialog; this only draws the form and shows what it says.
"""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet

from core.radio import RadioError


class AddStationScreen(ModalScreen):
    """Dismissed with the new station's Id, or None when cancelled."""

    BINDINGS = [("escape", "cancel", "Close")]

    def __init__(self, controller) -> None:
        super().__init__()
        self._ctl = controller

    def compose(self) -> ComposeResult:
        global_label, profile_label = self._ctl.scope_labels()
        with Vertical(id="station-dialog"):
            yield Label("ADD RADIO STATION", classes="pref-title")
            with Horizontal(classes="pref-row"):
                yield Label("Name", classes="key")
                yield Input(placeholder="Lave Radio", id="station-name",
                            classes="pref-input")
            with Horizontal(classes="pref-row"):
                yield Label("Stream address", classes="key")
                yield Input(placeholder="https://host:8000/stream",
                            id="station-url", classes="pref-input")
            with Horizontal(classes="pref-row"):
                yield Label("Save to", classes="key")
                with RadioSet(id="station-scope"):
                    yield RadioButton(global_label, value=True, id="scope-global")
                    yield RadioButton(profile_label, id="scope-profile",
                                      disabled=self._ctl.profile_name() is None)
            yield Label("MP3, Ogg Vorbis or FLAC streams; .m3u and .pls work too.",
                        classes="pref-note")
            yield Label("", id="station-result", classes="pref-note")
            with Horizontal(classes="pref-buttons"):
                yield Button("Add", id="station-add", variant="primary")
                yield Button("Cancel", id="station-cancel")

    def on_mount(self) -> None:
        self.query_one("#station-name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "station-cancel":
            self.dismiss(None)
        elif event.button.id == "station-add":
            self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        name = self.query_one("#station-name", Input).value
        url = self.query_one("#station-url", Input).value
        to_profile = self.query_one("#scope-profile", RadioButton).value
        try:
            station = self._ctl.add_station(name, url, to_profile=to_profile)
        except RadioError as exc:
            # Plain text: the message may quote a name or "[Radio]".
            self.query_one("#station-result", Label).update(Text(str(exc)))
            return
        self.dismiss(station.id)

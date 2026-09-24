"""
gui/station_dialog.py — the Radio tab's Add Station form (Qt).

Name, stream address, and where to keep it: globally in ``[Radio]``, or in
the profile loaded now.  Global is preselected, and the profile choice is
disabled when no profile is loaded.  Validation, the Id and the write to
config.toml are ``RadioController.add_station``'s, shared with the terminal
form; this only draws the form and shows what it says.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QRadioButton, QVBoxLayout, QWidget,
)

from core.radio import RadioError


class AddStationDialog(QDialog):
    """exec() returns Accepted once the station is written; ``station_id``
    then holds its Id."""

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._ctl = controller
        self.station_id: str | None = None
        self.setWindowTitle("Add Radio Station")
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Lave Radio")
        form.addRow("Name", self._name)

        self._url = QLineEdit()
        self._url.setPlaceholderText("https://host:8000/stream")
        form.addRow("Stream address", self._url)

        global_label, profile_label = controller.scope_labels()
        scope = QWidget()
        sl = QVBoxLayout(scope)
        sl.setContentsMargins(0, 0, 0, 0)
        self._global = QRadioButton(global_label)
        self._profile = QRadioButton(profile_label)
        self._global.setChecked(True)
        self._profile.setEnabled(controller.profile_name() is not None)
        self._scope = QButtonGroup(self)
        self._scope.addButton(self._global)
        self._scope.addButton(self._profile)
        sl.addWidget(self._global)
        sl.addWidget(self._profile)
        form.addRow("Save to", scope)

        note = QLabel("MP3, Ogg Vorbis or FLAC streams; .m3u and .pls work too.")
        note.setProperty("role", "dim")
        lay.addWidget(note)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setTextFormat(Qt.PlainText)      # names may hold < or [
        self._result.setProperty("role", "dim")
        lay.addWidget(self._result)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Add")
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._name.setFocus()

    def set_fields(self, name: str, url: str, to_profile: bool = False) -> None:
        """Fill the form; used by the tests."""
        self._name.setText(name)
        self._url.setText(url)
        (self._profile if to_profile else self._global).setChecked(True)

    def error(self) -> str:
        return self._result.text()

    def submit(self) -> None:
        try:
            station = self._ctl.add_station(self._name.text(), self._url.text(),
                                            to_profile=self._profile.isChecked())
        except RadioError as exc:
            self._result.setText(str(exc))
            return
        self.station_id = station.id
        self.accept()

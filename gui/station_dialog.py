"""
gui/station_dialog.py — the Radio tab's Add and Edit Station forms (Qt).

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
        self._result.setText("")
        try:
            station = self._ctl.add_station(self._name.text(), self._url.text(),
                                            to_profile=self._profile.isChecked())
        except RadioError as exc:
            self._result.setText(str(exc))
            return
        self.station_id = station.id
        self.accept()


class EditStationDialog(QDialog):
    """Change the selected station's name and address.

    exec() returns Accepted once the change is written.  Where it is written
    is not a choice here: it goes to the layer the station already lives in,
    which the form states so the commander knows which file section changed.
    Validation and the write are ``RadioController.edit_station``'s, shared
    with the terminal form.
    """

    def __init__(self, controller, station_id: str, parent=None) -> None:
        super().__init__(parent)
        self._ctl = controller
        self._sid = station_id
        info = controller.edit_info(station_id)
        self.setWindowTitle("Edit Radio Station")
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self._name = QLineEdit(info["name"])
        form.addRow("Name", self._name)
        self._url = QLineEdit(info["url"])
        form.addRow("Stream address", self._url)
        where = QLabel(info["saved_to"])
        where.setTextFormat(Qt.PlainText)            # "[Radio]" is not markup
        form.addRow("Saved to", where)

        note = QLabel("MP3, Ogg Vorbis or FLAC streams; .m3u and .pls work too.")
        note.setProperty("role", "dim")
        lay.addWidget(note)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setTextFormat(Qt.PlainText)
        self._result.setProperty("role", "dim")
        lay.addWidget(self._result)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save")
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._name.setFocus()
        self._name.selectAll()

    def set_fields(self, name: str, url: str) -> None:
        """Fill the form; used by the tests."""
        self._name.setText(name)
        self._url.setText(url)

    def error(self) -> str:
        return self._result.text()

    def submit(self) -> None:
        self._result.setText("")
        try:
            self._ctl.edit_station(self._sid, self._name.text(), self._url.text())
        except RadioError as exc:
            self._result.setText(str(exc))
            return
        self.accept()

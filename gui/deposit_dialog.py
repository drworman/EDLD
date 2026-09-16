"""
gui/deposit_dialog.py — Add or edit the surface deposit you are parked on.

One dialog for both, for the reason the TUI screen has one: the commander does
not know which they are doing until EDLD has looked at where they are standing.

Fields come from ``core.deposit_form.FIELDS`` so this and the TUI screen cannot
drift apart on what a deposit has.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QLineEdit, QVBoxLayout)

from core.deposit_form import FIELDS


class DepositDialog(QDialog):
    def __init__(self, plugin, parent=None) -> None:
        super().__init__(parent)
        self._plugin = plugin
        form_values, heading = plugin.form_for_here()

        self.setWindowTitle("Surface Deposit")
        lay = QVBoxLayout(self)

        self._heading = QLabel(heading)
        self._heading.setWordWrap(True)
        self._heading.setProperty("role", "dim")
        lay.addWidget(self._heading)

        form = QFormLayout()
        lay.addLayout(form)
        self._widgets: dict = {}
        for field in FIELDS:
            current = str(form_values.get(field.key, "") or "")
            if field.kind == "choice":
                box = QComboBox()
                box.addItem("", "")
                for choice in field.choices:
                    box.addItem(choice, choice)
                box.setCurrentIndex(max(0, box.findData(current)))
                widget = box
            elif field.kind == "bool":
                box = QComboBox()
                box.addItem("No", "")
                box.addItem("Yes", "true")
                box.setCurrentIndex(1 if current else 0)
                widget = box
            else:
                widget = QLineEdit(current)
                if field.hint:
                    widget.setPlaceholderText(field.hint)
            self._widgets[field.key] = widget
            form.addRow(field.label, widget)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setProperty("role", "dim")
        lay.addWidget(self._result)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _values(self) -> dict:
        out: dict = {}
        for key, widget in self._widgets.items():
            if isinstance(widget, QComboBox):
                out[key] = widget.currentData() or ""
            else:
                out[key] = widget.text()
        return out

    def _save(self) -> None:
        result = self._plugin.submit_form(self._values())
        # Stay open on a rejection so the offending field can be corrected
        # rather than the whole form retyped.
        if result.startswith(("recorded", "updated")):
            self.accept()
        else:
            self._result.setText(result)

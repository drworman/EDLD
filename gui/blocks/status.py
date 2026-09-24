"""
gui/blocks/status.py — Crew / Alerts window (Qt).

Two readouts that are almost never busy at the same time, so they share one
window rather than each holding a slot of their own.

A second tab holds the radio.  An alert that needs a tab change to see is an
alert you miss, so any new alert brings the Crew / Alerts tab back to the
front; the radio carries on playing.  The radio itself lives in core/radio.py
and is shared with the terminal dashboard — this file only draws it.
"""
from __future__ import annotations
from datetime import datetime, timezone
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)
from core.radio import AlertWatcher, RadioController, RadioError
from core.ui_helpers import fmt_crew_active
from gui.block_base import GuiBlock, TextRow, _fmt_credits, _health_cls
from gui.markup import to_html


#: Alert rows kept on screen.  Sized so a burst during combat does not push
#: the crew readout out of the window.
#: Crew combat ranks, indexed by the journal's rank number.
PP_RANK_NAMES = [
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]

_MAX_ROWS = 5


class StatusBlock(GuiBlock):
    BLOCK_TITLE = "CREW / ALERTS"

    def _build_body(self, outer) -> None:
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        crew_page = QWidget()
        layout = QVBoxLayout(crew_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._build_crew(layout)
        self._tabs.addTab(crew_page, "Crew / Alerts")

        self._radio = RadioPanel(self)
        self._tabs.addTab(self._radio, "Radio")

        outer.addWidget(self._tabs, 1)
        self._alert_watch = AlertWatcher()

    def _build_crew(self, layout) -> None:

        # Name row: crew identity left, SLF type right.
        name_row = QWidget()
        nl = QHBoxLayout(name_row)
        nl.setContentsMargins(6, 0, 6, 0)
        nl.setSpacing(8)
        self._name_lbl = QLabel()
        self._name_lbl.setTextFormat(Qt.RichText)
        self._name_lbl.setProperty("role", "hdrkey")
        # Expanding rather than the default Preferred: the stretch factor alone
        # only distributes *surplus* space, so in a narrow column the name
        # label stops growing and the type label drifts left until the two sit
        # against each other. Expanding keeps the name filling the row and the
        # designation pinned to the right edge at any width.
        self._name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._type_lbl = QLabel()
        self._type_lbl.setTextFormat(Qt.RichText)
        self._type_lbl.setProperty("role", "dim")
        self._type_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._type_lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        nl.addWidget(self._name_lbl, 1)
        nl.addStretch(0)
        nl.addWidget(self._type_lbl, 0)
        layout.addWidget(name_row)

        self._rank_lbl = self.text("", "dim", wrap=False)
        layout.addWidget(self._rank_lbl)

        self._kv_slf    = self.kv("SLF")
        self._kv_hired  = self.kv("Hired")
        self._kv_active = self.kv("Active")
        self._kv_paid   = self.kv("Paid")
        for w in (self._kv_slf, self._kv_hired, self._kv_active, self._kv_paid):
            layout.addWidget(w)
        layout.addStretch(1)

        # The two halves share a window, so they need a visible seam.
        # Without one, an alert reads as another crew row.
        layout.addWidget(self.hdr("Alerts"))
        layout.addWidget(self.rule())

        self._rows: list[TextRow] = []
        for _ in range(_MAX_ROWS):
            row = self.text("", "", wrap=False)
            self._rows.append(row)
            layout.addWidget(row)
        layout.addStretch(1)

    def refresh_data(self) -> None:
        self._refresh_crew()
        self._refresh_alerts()

    def _refresh_crew(self) -> None:
        s = self.state
        has_crew = bool(s.crew_name) and s.crew_active

        if not has_crew:
            self._name_lbl.setText(to_html("No NPC crew", self.palette_map))
            self._type_lbl.setText("")
            self._rank_lbl.set_text("")
            for w in (self._kv_slf, self._kv_hired, self._kv_active, self._kv_paid):
                w.set_value("—")
            self._kv_slf.setVisible(True)
            return

        # ── Header: CREW: <n> (left)   <model> (<variant>) (right) ────────
        # Model and variant are one designation and are shown together, on the
        # right, matching the terminal dashboard.
        slf_full = (s.slf_type or "").strip()
        if "(" in slf_full and slf_full.endswith(")"):
            paren       = slf_full.index("(")
            slf_base    = slf_full[:paren].strip()
            slf_variant = slf_full[paren + 1:-1].strip()
        else:
            slf_base    = slf_full
            slf_variant = ""

        if slf_base and slf_variant:
            slf_label = f"{slf_base} ({slf_variant})"
        else:
            slf_label = slf_base or slf_variant

        crew_label = f"CREW: {s.crew_name or 'NPC'}"
        if s.cmdr_in_slf:
            crew_label += "  [IN FIGHTER]"
        self._name_lbl.setText(to_html(crew_label, self.palette_map))
        self._type_lbl.setText(to_html(slf_label, self.palette_map))

        rank_str = ""
        if s.crew_rank is not None and 0 <= s.crew_rank < len(PP_RANK_NAMES):
            rank_str = f"Combat Rank: {PP_RANK_NAMES[s.crew_rank]}"
        self._rank_lbl.set_text(rank_str)

        # ── SLF status ────────────────────────────────────────────────────────
        has_bay = s.has_fighter_bay
        self._kv_slf.setVisible(bool(has_bay))
        if has_bay:
            all_spent = (
                s.slf_stock_total > 0
                and s.slf_destroyed_count >= s.slf_stock_total
                and not s.slf_docked and not s.slf_deployed
            )
            if s.cmdr_in_slf:
                hull_str = f"{s.slf_hull}%" if s.slf_hull is not None else "—"
                self._kv_slf.set_value(f"CMDR Aboard  |  Hull {hull_str}", "val health-good")
            elif s.slf_docked:
                self._kv_slf.set_value("SLF Docked", "val health-good")
            elif s.slf_deployed:
                hull_str = f"Hull {s.slf_hull}%" if s.slf_hull is not None else "Hull —"
                cls = f"val {_health_cls(s.slf_hull)}" if s.slf_hull is not None else "val health-good"
                self._kv_slf.set_value(hull_str, cls)
            elif all_spent:
                self._kv_slf.set_value("All Spent", "val health-crit")
            else:
                self._kv_slf.set_value("Destroyed", "val health-crit")

        # ── Context ───────────────────────────────────────────────────────────
        self._kv_hired.set_value(
            s.crew_hire_time.strftime("%d %b %Y") if s.crew_hire_time else "Unknown")
        if s.crew_hire_time:
            delta = datetime.now(timezone.utc) - s.crew_hire_time
            self._kv_active.set_value(fmt_crew_active(delta))
        else:
            self._kv_active.set_value("—")

        if s.crew_total_paid and s.crew_total_paid > 0:
            prefix = "" if s.crew_paid_complete else "≥ "
            self._kv_paid.set_value(f"{prefix}{_fmt_credits(s.crew_total_paid)}")
        else:
            self._kv_paid.set_value("—")

    def _refresh_alerts(self) -> None:
        alerts = self.core.plugin_call("alerts", "get_alerts") or []
        if self._alert_watch.new_since_last(alerts):
            self._tabs.setCurrentIndex(0)
        for i, lbl in enumerate(self._rows):
            if i < len(alerts):
                a = alerts[i]
                opacity = self.core.plugin_call("alerts", "opacity_for", a) or 1.0
                text = f"{a.get('emoji', '')}  {a.get('text', '')}"
                # The TUI dims an ageing alert through its own opacity handling;
                # Qt has no equivalent on a stylesheet label, so the same
                # threshold switches the row to the dim role instead.
                lbl.set_text(text)
                lbl.setProperty("role", "dim" if opacity < 0.7 else "val")
            else:
                lbl.set_text("")
                lbl.setProperty("role", "val")
            style = lbl.style()
            style.unpolish(lbl)
            style.polish(lbl)


# ── Radio tab ─────────────────────────────────────────────────────────────────

class RadioPanel(QWidget):
    """Station list, readout and transport controls.

    Polls the shared player twice a second from a QTimer rather than being
    called back from its threads, so no widget is ever touched off the GUI
    thread.  Same controller, same labels and same controls as the terminal
    tab.
    """

    POLL_MS = 500

    def __init__(self, block: GuiBlock) -> None:
        super().__init__()
        self._block = block
        self._ctl = RadioController(block.core)
        self._shown_options: list[tuple[str, str]] = []
        self._shown_problems: list[str] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(0)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(6, 0, 6, 4)
        self._combo = QComboBox()
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.currentIndexChanged.connect(self._on_station_changed)
        rl.addWidget(self._combo, 1)
        self._add_btn = self._button("+", self._open_add)
        self._del_btn = self._button("−", self._open_delete)
        self._add_btn.setToolTip("Add a station")
        self._del_btn.setToolTip("Delete the selected station")
        rl.addWidget(self._add_btn, 0)
        rl.addWidget(self._del_btn, 0)
        layout.addWidget(row)

        self._kv_status = block.kv("Status")
        self._kv_onair  = block.kv("On air")
        self._kv_now    = block.kv("Now")
        self._kv_volume = block.kv("Volume")
        for w in (self._kv_status, self._kv_onair, self._kv_now, self._kv_volume):
            layout.addWidget(w)

        self._problems_host = QWidget()
        self._problems_layout = QVBoxLayout(self._problems_host)
        self._problems_layout.setContentsMargins(0, 4, 0, 0)
        self._problems_layout.setSpacing(0)
        layout.addWidget(self._problems_host)
        layout.addStretch(1)

        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(6, 2, 6, 2)
        fl.setSpacing(8)
        self._play_btn = self._button("▶ Play", self._ctl.toggle_play)
        self._down_btn = self._button("Vol −",  self._ctl.volume_down)
        self._up_btn   = self._button("Vol +",  self._ctl.volume_up)
        self._mute_btn = self._button("Mute",   self._ctl.toggle_mute)
        for b in (self._play_btn, self._down_btn, self._up_btn, self._mute_btn):
            fl.addWidget(b, 0)
        fl.addStretch(1)
        layout.addWidget(footer)

        self._sync_options()
        self._redraw()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self.POLL_MS)

    def _button(self, text: str, action) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("role", "link")
        b.clicked.connect(lambda _=False, a=action: (a(), self._redraw()))
        return b

    # ── Adding and deleting ──────────────────────────────────────────────────

    def _open_add(self) -> None:
        from gui.station_dialog import AddStationDialog
        dlg = AddStationDialog(self._ctl, parent=self)
        if dlg.exec() == AddStationDialog.Accepted:
            self._sync_options()
            self._redraw()

    def _ask(self, title: str, message: str) -> bool:
        """Delete confirmation.  Cancel is the default, so Enter keeps it."""
        box = QMessageBox(self)
        box.setWindowTitle("Delete station")
        box.setIcon(QMessageBox.Warning)
        box.setTextFormat(Qt.PlainText)
        box.setText(title)
        box.setInformativeText(message)
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        box.button(QMessageBox.Ok).setText("Delete")
        box.setDefaultButton(QMessageBox.Cancel)
        return box.exec() == QMessageBox.Ok

    def _error(self, message: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Radio")
        box.setIcon(QMessageBox.Warning)
        box.setTextFormat(Qt.PlainText)
        box.setText(message)
        box.exec()

    def _open_delete(self) -> None:
        sid = self._ctl.selected
        if not sid:
            return
        try:
            title, message = self._ctl.delete_prompt(sid)
        except RadioError as exc:
            self._error(str(exc))
            return
        if not self._ask(title, message):
            return
        try:
            self._ctl.delete_station(sid)
        except RadioError as exc:
            self._error(str(exc))
        self._sync_options()
        self._redraw()

    def _poll(self) -> None:
        if self._ctl.reload():
            self._sync_options()
        self._redraw()

    def _sync_options(self) -> None:
        options = self._ctl.options()
        self._combo.blockSignals(True)
        try:
            if options != self._shown_options:
                self._shown_options = options
                self._combo.clear()
                for label, sid in options:
                    self._combo.addItem(label, sid)
                if not options:
                    self._combo.setPlaceholderText("No stations")
            idx = self._combo.findData(self._ctl.selected)
            if idx >= 0 and idx != self._combo.currentIndex():
                self._combo.setCurrentIndex(idx)
        finally:
            self._combo.blockSignals(False)

    def _on_station_changed(self, index: int) -> None:
        sid = self._combo.itemData(index)
        if isinstance(sid, str):
            self._ctl.select(sid)
            self._redraw()

    def _redraw(self) -> None:
        v = self._ctl.view()
        tone = f"val {v['status_tone']}".strip()
        self._kv_status.set_value(v["status"], tone)
        self._kv_onair.set_value(v["on_air"])
        self._kv_now.set_value(v["now"])
        self._kv_volume.set_value(v["volume"])
        self._del_btn.setEnabled(v["can_delete"])
        self._play_btn.setText(v["play_label"])
        self._play_btn.setEnabled(v["can_play"])
        self._mute_btn.setText(v["mute_label"])
        if v["problems"] != self._shown_problems:
            self._shown_problems = v["problems"]
            while self._problems_layout.count():
                item = self._problems_layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            if v["problems"]:
                self._problems_layout.addWidget(self._block.hdr("Config"))
                for p in v["problems"]:
                    self._problems_layout.addWidget(self._block.text(p, "dim"))

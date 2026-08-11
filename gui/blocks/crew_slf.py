"""gui/blocks/crew_slf.py — NPC Crew and SLF status block (Qt)."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from gui.block_base import GuiBlock, _health_cls, _fmt_credits
from gui.markup import to_html

# ── Inline helpers (no UI-framework dependency) ───────────────────────────────

def hull_css(pct: int) -> str:
    if pct > 75:  return "health-good"
    if pct >= 25: return "health-warn"
    return "health-crit"


PP_RANK_NAMES = [
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]


def fmt_crew_active(delta) -> str:
    total_days = int(delta.total_seconds() // 86400)
    if total_days < 1:
        return "<1d"
    years,  rem_days = divmod(total_days, 365)
    months, days     = divmod(rem_days, 30)
    parts = []
    if years:  parts.append(f"{years}y")
    if months: parts.append(f"{months}mo")
    if days and len(parts) < 2: parts.append(f"{days}d")
    return " ".join(parts) or "<1d"


class CrewSlfBlock(GuiBlock):
    BLOCK_TITLE = "CREW / SLF"

    def _build_body(self, layout) -> None:
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

    def refresh_data(self) -> None:
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

"""
gui/blocks/crew_slf.py — NPC Crew and SLF status block.

Mirrors _build_crew_panel / _refresh_crew from the original edld_gui.py exactly.
Hidden when no active crew.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Pango
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget
from gui.helpers    import hull_css, fmt_crew_active, PP_RANK_NAMES
from datetime       import datetime, timezone


class CrewSlfBlock(BlockWidget):
    BLOCK_TITLE = "CREW"
    BLOCK_CSS   = "crew-block"

    def build(self, parent: Gtk.Box) -> None:
        # ── Two-line header (mirrors CommanderBlock) ──────────────────────────
        hdr_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        # Line 1: crew name (left) + SLF type (right)
        hdr_line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._crew_header_lbl = Gtk.Label(label="CREW")
        self._crew_header_lbl.set_xalign(0.0)
        self._crew_header_lbl.set_hexpand(True)
        hdr_line1.append(self._crew_header_lbl)
        self._crew_slf_type_hdr = Gtk.Label(label="")
        self._crew_slf_type_hdr.set_xalign(1.0)
        hdr_line1.append(self._crew_slf_type_hdr)
        hdr_outer.append(hdr_line1)

        # Line 2: rank (left) + SLF variant (right, e.g. "Gelid G")
        hdr_line2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._hdr_line2 = hdr_line2
        self._crew_rank_hdr = Gtk.Label(label="")
        self._crew_rank_hdr.set_xalign(0.0)
        self._crew_rank_hdr.set_hexpand(True)
        self._crew_rank_hdr.add_css_class("section-header")
        hdr_line2.append(self._crew_rank_hdr)
        self._crew_slf_variant_hdr = Gtk.Label(label="")
        self._crew_slf_variant_hdr.set_xalign(1.0)
        self._crew_slf_variant_hdr.set_visible(False)
        self._crew_slf_variant_hdr.add_css_class("section-header")
        hdr_line2.append(self._crew_slf_variant_hdr)
        hdr_outer.append(hdr_line2)

        body = self._build_section(parent, title_widget=hdr_outer)
        scroll_body = self._make_scroll_body(body)

        # ── Single shared grid so all labels align ───────────────────────────
        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(2)
        grid.set_margin_top(2)
        scroll_body.append(grid)

        _gr = 0

        def _kv(key_text):
            nonlocal _gr
            k = self.make_label(key_text, css_class="data-key")
            k.set_xalign(0.0)
            grid.attach(k, 0, _gr, 1, 1)
            v = self.make_label("—", css_class="data-value")
            v.set_xalign(1.0)
            v.set_hexpand(True)
            grid.attach(v, 1, _gr, 1, 1)
            _gr += 1
            return k, v

        # ── SLF vitals ───────────────────────────────────────────────────────
        self._crew_slf_key, self._crew_slf_status = _kv("SLF")
        self._crew_slf_row = self._crew_slf_key   # keep ref for visibility toggle

        # ── Separator ────────────────────────────────────────────────────────
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class("vitals-sep")
        grid.attach(sep, 0, _gr, 2, 1)
        _gr += 1

        # ── Context rows ─────────────────────────────────────────────────────
        _, self._crew_hired_lbl  = _kv("Hired")
        _, self._crew_active_lbl = _kv("Active")
        _, self._crew_paid_lbl   = _kv("Paid")

        # Hidden by default until crew is active
        self.set_visible(False)

    def refresh(self) -> None:
        s         = self.state
        has_crew  = bool(s.crew_name) and s.crew_active
        self.set_visible(has_crew)
        if not has_crew:
            return

        # ── Header ────────────────────────────────────────────────────────────
        if s.cmdr_in_slf:
            self._crew_header_lbl.set_label(
                f"CREW: {s.crew_name or 'NPC'}  [Flying {s.pilot_ship or 'Ship'}]"
            )
        else:
            self._crew_header_lbl.set_label(f"CREW: {s.crew_name or 'NPC'}")
        # Split "GU-97 (Gelid G)" -> type="GU-97", variant="Gelid G"
        slf_full = s.slf_type or ""
        if "(" in slf_full and slf_full.endswith(")"):
            paren = slf_full.index("(")
            slf_base    = slf_full[:paren].strip()
            slf_variant = slf_full[paren + 1:-1].strip()
        else:
            slf_base    = slf_full
            slf_variant = ""
        self._crew_slf_type_hdr.set_label(slf_base)
        self._crew_slf_variant_hdr.set_label(slf_variant)

        # ── Rank — shown in header line 2 ────────────────────────────────────
        if s.crew_rank is not None and 0 <= s.crew_rank < len(PP_RANK_NAMES):
            rank_str = f"Combat Rank: {PP_RANK_NAMES[s.crew_rank]}"
        else:
            rank_str = ""
        self._crew_rank_hdr.set_label(rank_str)
        # Keep the rank label visible even when empty — it's the hexpand spacer
        # that pushes the variant label to the right. Hiding it collapses the space.
        self._crew_rank_hdr.set_visible(True)
        self._crew_slf_variant_hdr.set_visible(bool(slf_variant))

        # ── Hired ─────────────────────────────────────────────────────────────
        self._crew_hired_lbl.set_label(
            s.crew_hire_time.strftime("%d %b %Y") if s.crew_hire_time else "Unknown"
        )

        # ── Active duration ───────────────────────────────────────────────────
        if s.crew_hire_time:
            self._crew_active_lbl.set_label(
                fmt_crew_active(datetime.now(timezone.utc) - s.crew_hire_time)
            )
        else:
            self._crew_active_lbl.set_label("—")

        # ── Total paid ────────────────────────────────────────────────────────
        if s.crew_total_paid is not None and s.crew_total_paid > 0:
            prefix = "" if s.crew_paid_complete else "≥ "
            self._crew_paid_lbl.set_label(
                f"{prefix}{self.fmt_credits(s.crew_total_paid)}"
            )
        else:
            self._crew_paid_lbl.set_label("—")

        # ── SLF status (hidden when no bay fitted) ────────────────────────────
        has_bay = s.has_fighter_bay
        self._crew_slf_key.set_visible(has_bay)
        self._crew_slf_status.set_visible(has_bay)
        if not has_bay:
            return

        for cls in ("health-good", "health-warn", "health-crit"):
            self._crew_slf_status.remove_css_class(cls)

        all_spent = (
            s.slf_stock_total > 0
            and s.slf_destroyed_count >= s.slf_stock_total
            and not s.slf_docked
            and not s.slf_deployed
        )

        if s.cmdr_in_slf:
            hull_str = f"{s.slf_hull}%" if s.slf_hull is not None else "—"
            self._crew_slf_status.set_label(f"CMDR Aboard  |  Hull {hull_str}")
            self._crew_slf_status.add_css_class(
                hull_css(s.slf_hull) if s.slf_hull is not None else "health-good"
            )
        elif s.slf_docked:
            self._crew_slf_status.set_label("SLF Docked")
            self._crew_slf_status.add_css_class("health-good")
        elif s.slf_deployed:
            hull_str = f"Hull {s.slf_hull}%" if s.slf_hull is not None else "Hull —"
            self._crew_slf_status.set_label(hull_str)
            self._crew_slf_status.add_css_class(
                hull_css(s.slf_hull) if s.slf_hull is not None else "health-good"
            )
        elif all_spent:
            self._crew_slf_status.set_label("All Spent")
            self._crew_slf_status.add_css_class("health-crit")
        else:
            self._crew_slf_status.set_label("Destroyed")
            self._crew_slf_status.add_css_class("health-crit")

"""
gui/blocks/exploration.py — Exploration window (GTK4).

Shows the system the commander is currently in: the honk / scan / map state,
each body's current and max-if-mapped cartographic value, high-value-mappable
highlights, bodies carrying biological signals, and system totals.  Location
awareness comes from the explo_sync component (current system + commander); the
per-body data is built by core.explo_view from the shared body database.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Pango
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget
from core.explo_view import build_system_view

# Compact display codes for common body classes.
_TYPE_ABBR = {
    "earthlike body": "ELW", "water world": "WW", "ammonia world": "AW",
    "high metal content body": "HMC", "metal rich body": "MR",
    "rocky body": "Rocky", "rocky ice body": "RkIce", "icy body": "Icy",
    "sudarsky class i gas giant": "GGc1", "sudarsky class ii gas giant": "GGc2",
    "sudarsky class iii gas giant": "GGc3", "sudarsky class iv gas giant": "GGc4",
    "sudarsky class v gas giant": "GGc5",
    "gas giant with water based life": "GGWL",
    "gas giant with ammonia based life": "GGAL",
    "water giant": "WG", "helium rich gas giant": "HeGG",
}


def _abbr(body: dict) -> str:
    if body["is_star"]:
        return f"★{body['type']}" if body["type"] else "★"
    t = (body["type"] or "").lower()
    return _TYPE_ABBR.get(t, (body["type"] or "?")[:5])


class ExplorationBlock(BlockWidget):
    BLOCK_TITLE = "EXPLORATION"
    BLOCK_CSS   = "exploration-block"

    def build(self, parent: Gtk.Box) -> None:
        # ── Header: title + system name, then state markers + totals ──────────
        hdr = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        title = Gtk.Label(label="EXPLORATION")
        title.set_xalign(0.0)
        title.set_hexpand(True)
        line1.append(title)
        self._system_lbl = Gtk.Label(label="—")
        self._system_lbl.set_xalign(1.0)
        self._system_lbl.add_css_class("section-header")
        line1.append(self._system_lbl)
        hdr.append(line1)

        line2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._state_lbl = Gtk.Label(label="")
        self._state_lbl.set_xalign(0.0)
        self._state_lbl.set_hexpand(True)
        self._state_lbl.add_css_class("section-header")
        line2.append(self._state_lbl)
        self._totals_lbl = Gtk.Label(label="")
        self._totals_lbl.set_xalign(1.0)
        self._totals_lbl.add_css_class("section-header")
        line2.append(self._totals_lbl)
        hdr.append(line2)

        body = self._build_section(parent, title_widget=hdr)
        scroll_body = self._make_scroll_body(body)

        # Placeholder shown when no system data is available yet.
        self._placeholder = self.make_label(
            "No system data yet — honk (discovery scan) to populate.",
            css_class="data-key",
        )
        self._placeholder.set_xalign(0.0)
        self._placeholder.set_wrap(True)
        scroll_body.append(self._placeholder)

        # Dynamic per-body list.  Rebuilt each refresh.
        self._body_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self._body_box.set_margin_top(2)
        scroll_body.append(self._body_box)
        self._body_rows: list[Gtk.Widget] = []

    # ── Data ──────────────────────────────────────────────────────────────────

    def _sync(self):
        return self.core._plugins.get("explo_sync")

    def refresh(self) -> None:
        view = None
        sync = self._sync()
        if sync is not None:
            try:
                addr = sync.current_system_address()
                cid  = sync.current_commander_id()
                view = build_system_view(addr, cid)
            except Exception:
                view = None
        self._render(view)

    def _render(self, view) -> None:
        # Clear the previous body rows (sweep all children — robust regardless
        # of how many rows the prior render produced).
        child = self._body_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._body_box.remove(child)
            child = nxt

        if not view:
            self._system_lbl.set_label("—")
            self._state_lbl.set_label("")
            self._totals_lbl.set_label("")
            self._placeholder.set_visible(True)
            return

        self._placeholder.set_visible(False)
        sysd = view["system"]
        tot  = view["totals"]

        self._system_lbl.set_label(sysd["name"] or "—")

        flags = []
        flags.append("honked" if sysd["honked"] else "·")
        if sysd["fully_scanned"]:
            flags.append("scanned")
        if sysd["fully_mapped"]:
            flags.append("mapped")
        self._state_lbl.set_label(
            f"{tot['scanned']}/{sysd['body_count'] or tot['bodies']} bodies"
            + (f"  ·  {tot['high_value']} worth mapping" if tot["high_value"] else "")
            + (f"  ·  {tot['bio_bodies']} bio" if tot["bio_bodies"] else "")
            + (f"  ·  {tot['first_discovery']} undiscovered" if tot.get("first_discovery") else "")
            + (f"  ·  {tot['first_footfall']} footfall" if tot.get("first_footfall") else "")
        )
        self._totals_lbl.set_label(
            f"{self.fmt_credits(tot['value_now'])} / {self.fmt_credits(tot['value_max'])}"
        )

        for b in view["bodies"]:
            self._body_box.append(self._make_row(b))

    def _make_row(self, b: dict) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        name = self.make_label(b["short"] or b["name"], css_class="data-key")
        name.set_xalign(0.0)
        name.set_width_chars(8)
        row.append(name)

        kind = self.make_label(_abbr(b), css_class="data-key")
        kind.set_xalign(0.0)
        kind.set_width_chars(6)
        row.append(kind)

        markers = []
        if b["high_value"]:
            markers.append("★")
        if b["terraformable"]:
            markers.append("T")
        if b["bio_signals"]:
            markers.append(f"◆{b['bio_signals']}")
        if b["mapped"]:
            markers.append("✓")
        if b.get("first_discovery"):
            markers.append("FD")
        if b.get("first_footfall"):
            markers.append("FF")
        mk = self.make_label(" ".join(markers), css_class="data-key")
        mk.set_xalign(0.0)
        mk.set_hexpand(True)
        row.append(mk)

        # Value: current, plus the mapping target when worth showing.
        if not b["is_star"] and not b["mapped"] and b["mapping_gain"] > 0:
            vtxt = f"{self.fmt_credits(b['value_now'])} → {self.fmt_credits(b['value_max'])}"
        else:
            vtxt = self.fmt_credits(b["value_now"])
        val = self.make_label(vtxt, css_class="data-value")
        val.set_xalign(1.0)
        row.append(val)

        if b["high_value"]:
            row.add_css_class("explo-high-value")
        if b["mapped"]:
            row.add_css_class("explo-mapped")
        return row

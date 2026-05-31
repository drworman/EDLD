"""
gui/blocks/exobiology.py — Exobiology window (GTK4).

For the system the commander is currently in, shows each body's biological
signal count and sampling progress, the genera the game has revealed (with
value-range hints for ones not yet sampled), and each sampled species with its
stage, value, and minimum clonal distance.  Location comes from explo_sync; the
per-body data is built by core.exobio_view.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget
from core.exobio_view import build_exobio_view


def _range(g: dict) -> str:
    lo, hi = g.get("value_min", 0), g.get("value_max", 0)
    if not hi:
        return ""
    if lo == hi:
        return _fmt(lo)
    return f"{_fmt(lo)}–{_fmt(hi)}"


def _fmt(n: int) -> str:
    if not n:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


class ExobiologyBlock(BlockWidget):
    BLOCK_TITLE = "EXOBIOLOGY"
    BLOCK_CSS   = "exobiology-block"

    def build(self, parent: Gtk.Box) -> None:
        hdr = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        line1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        title = Gtk.Label(label="EXOBIOLOGY")
        title.set_xalign(0.0)
        title.set_hexpand(True)
        line1.append(title)
        self._system_lbl = Gtk.Label(label="—")
        self._system_lbl.set_xalign(1.0)
        self._system_lbl.add_css_class("section-header")
        line1.append(self._system_lbl)
        hdr.append(line1)

        line2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._totals_lbl = Gtk.Label(label="")
        self._totals_lbl.set_xalign(0.0)
        self._totals_lbl.set_hexpand(True)
        self._totals_lbl.add_css_class("section-header")
        line2.append(self._totals_lbl)
        self._value_lbl = Gtk.Label(label="")
        self._value_lbl.set_xalign(1.0)
        self._value_lbl.add_css_class("section-header")
        line2.append(self._value_lbl)
        hdr.append(line2)

        body = self._build_section(parent, title_widget=hdr)
        scroll_body = self._make_scroll_body(body)

        self._placeholder = self.make_label(
            "No biology here yet — surface-scan a body with signals.",
            css_class="data-key",
        )
        self._placeholder.set_xalign(0.0)
        self._placeholder.set_wrap(True)
        scroll_body.append(self._placeholder)

        self._body_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self._body_box.set_margin_top(2)
        scroll_body.append(self._body_box)
        self._rows: list[Gtk.Widget] = []

    def _sync(self):
        return self.core._plugins.get("explo_sync")

    def _position(self):
        st = getattr(self.core, "state", None)
        if st is None:
            return None
        return {
            "lat": getattr(st, "surface_latitude", None),
            "lon": getattr(st, "surface_longitude", None),
            "radius": getattr(st, "planet_radius", None),
            "heading": getattr(st, "surface_heading", None),
            "on_foot": getattr(st, "on_foot", False),
            "body": getattr(st, "current_body_name", "") or "",
        }

    def refresh(self) -> None:
        view = None
        sync = self._sync()
        if sync is not None:
            try:
                view = build_exobio_view(
                    sync.current_system_address(), sync.current_commander_id(),
                    position=self._position(),
                )
            except Exception:
                view = None
        self._render(view)

    def _render(self, view) -> None:
        child = self._body_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._body_box.remove(child)
            child = nxt

        if not view or not view["bodies"]:
            self._system_lbl.set_label(view["system"]["name"] if view else "—")
            self._totals_lbl.set_label("")
            self._value_lbl.set_label("")
            self._placeholder.set_visible(True)
            return

        self._placeholder.set_visible(False)
        tot = view["totals"]
        self._system_lbl.set_label(view["system"]["name"] or "—")
        self._totals_lbl.set_label(
            f"{tot['bodies_with_bio']} bodies · {tot['total_signals']} signals · "
            f"{tot['analysed']} analysed"
        )
        vparts = []
        if tot["value_logged"]:
            vparts.append(self.fmt_credits(tot["value_logged"]))
        if tot.get("potential_value_max"):
            vparts.append(f"~{_fmt(tot['potential_value_min'])}–{_fmt(tot['potential_value_max'])}")
        self._value_lbl.set_label("  ·  ".join(vparts))

        for b in view["bodies"]:
            self._body_box.append(self._body_header(b))
            vline = self._value_line(b)
            if vline is not None:
                self._body_box.append(vline)
            sampled_genera = {f["genus"] for f in b["flora"]}
            for f in b["flora"]:
                self._body_box.append(self._flora_row(f))
                if f.get("aid"):
                    self._body_box.append(self._aid_row(f["aid"]))
            # Predicted genera before a surface scan, confirmed ones after.
            genera = b["predicted_genera"] if b["predicting"] else b["genera"]
            for g in genera:
                if g["genus"] not in sampled_genera:
                    self._body_box.append(self._genus_row(g))

    def _value_line(self, b: dict):
        if not b["bio_signals"] or (b["value_min"] <= 0 and b["value_max"] <= 0):
            return None
        txt = f"  est. {_fmt(b['value_min'])}–{_fmt(b['value_max'])}"
        if b.get("value_max_possible", 0) > b["value_max"]:
            txt += f" (↑{_fmt(b['value_max_possible'])})"
        if b["first_footfall"]:
            txt += f"  ✦ first footfall ×{b['first_footfall_mult']}"
        lbl = self.make_label(txt, css_class="data-value")
        lbl.set_xalign(0.0)
        if b["first_footfall"]:
            lbl.add_css_class("exobio-first-footfall")
        return lbl

    def _body_header(self, b: dict) -> Gtk.Widget:
        done = "✓" if b["complete"] else f"{b['analysed']}/{b['bio_signals']}"
        prefix = "▸ " if b.get("current") else ""
        lbl = self.make_label(
            f"{prefix}{b['short'] or b['name']}  ·  {b['bio_signals']} bio  ·  {done}",
            css_class="section-header",
        )
        lbl.set_xalign(0.0)
        lbl.set_margin_top(2)
        if b.get("current"):
            lbl.add_css_class("exobio-current-body")
        return lbl

    @staticmethod
    def _arrow(rel: float) -> str:
        return "↑↗→↘↓↙←↖"[int(((rel % 360) + 22.5) // 45) % 8]

    def _aid_row(self, aid: dict) -> Gtk.Widget:
        # Direction to the nearest prior sample, relative to the way we're facing.
        cue = ""
        if aid.get("heading") is not None and aid.get("bearing") is not None:
            cue = self._arrow(aid["bearing"] - aid["heading"]) + " "
        status = "clear ✓" if aid["ok"] else "too close — move away"
        row = self.make_label(
            f"      {cue}{aid['distance']} m to last sample · need ≥{aid['clonal']} m · {status}",
            css_class="data-value",
        )
        row.set_xalign(0.0)
        row.add_css_class("exobio-aid-ok" if aid["ok"] else "exobio-aid-warn")
        return row

    def _flora_row(self, f: dict) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name = self.make_label(f"  {f['name']}", css_class="data-key")
        name.set_xalign(0.0)
        name.set_hexpand(True)
        row.append(name)
        stage = self.make_label(
            "✓" if f["logged"] else f"{f['stage']}/3", css_class="data-key"
        )
        stage.set_xalign(1.0)
        stage.set_width_chars(4)
        row.append(stage)
        extra = "" if f["logged"] else f"  ≥{f['clonal']}m"
        val = self.make_label(_fmt(f["value"]) + extra, css_class="data-value")
        val.set_xalign(1.0)
        row.append(val)
        if not f["logged"]:
            row.add_css_class("exobio-in-progress")
        return row

    def _genus_row(self, g: dict) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = f"  {g['genus']}" + ("  (conditional)" if g.get("gated") else "")
        name = self.make_label(label, css_class="data-key")
        name.set_xalign(0.0)
        name.set_hexpand(True)
        row.append(name)
        rng = self.make_label(_range(g), css_class="data-value")
        rng.set_xalign(1.0)
        row.append(rng)
        row.add_css_class("exobio-unsampled")
        return row

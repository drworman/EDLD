"""tui/blocks/exploration.py — Exploration + Exobiology window (Textual TUI).

Shows the system the commander is currently in: honk / scan / map state, each
body's current and max-if-mapped cartographic value, high-value-mappable
highlights, and system totals — and, indented beneath any body carrying
biological signals, that body's exobiology detail.

The two used to be separate windows, which meant every body with bio signals
was listed twice: once for its cartographic value and again for its flora.
Nesting the biology under the body it belongs to removes the duplication and
keeps a body's full story in one place.

Location comes from the explo_sync component, cartographic data from
core.explo_view and biological data from core.exobio_view.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label
from textual.containers import VerticalScroll

from tui.block_base    import TuiBlock, KVRow
from tui.block_base    import SecHdr
from core.explo_view   import build_system_view
from core.exobio_view  import build_exobio_view
from core.ui_helpers   import explo_fault

_TYPE_ABBR = {
    "earthlike body": "ELW", "water world": "WW", "ammonia world": "AW",
    "high metal content body": "HMC", "metal rich body": "MR",
    "rocky body": "Rocky", "rocky ice body": "RkIce", "icy body": "Icy",
    "sudarsky class i gas giant": "GGc1", "sudarsky class ii gas giant": "GGc2",
    "sudarsky class iii gas giant": "GGc3", "sudarsky class iv gas giant": "GGc4",
    "sudarsky class v gas giant": "GGc5",
}


def _abbr(b: dict) -> str:
    if b["is_star"]:
        return f"*{b['type']}" if b["type"] else "*"
    return _TYPE_ABBR.get((b["type"] or "").lower(), (b["type"] or "?")[:5])


def _markers(b: dict) -> str:
    m = []
    if b["high_value"]:
        m.append("★")
    if b["terraformable"]:
        m.append("T")
    if b["bio_signals"]:
        m.append(f"◆{b['bio_signals']}")
    if b["mapped"]:
        m.append("✓")
    if b.get("first_discovery"):
        m.append("FD")
    if b.get("first_footfall"):
        m.append("FF")
    return " ".join(m)


def _fmt(n: int) -> str:
    if not n:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _range(g: dict) -> str:
    lo, hi = g.get("value_min", 0), g.get("value_max", 0)
    if not hi:
        return ""
    return _fmt(lo) if lo == hi else f"{_fmt(lo)}–{_fmt(hi)}"


def _arrow(rel: float) -> str:
    return "↑↗→↘↓↙←↖"[int(((rel % 360) + 22.5) // 45) % 8]



class ExplorationBlock(TuiBlock):
    BLOCK_TITLE = "EXPLORATION"

    def _compose_body(self) -> ComposeResult:
        yield Label("—", id="explo-system", classes="section-hdr")
        yield Label("", id="explo-summary", classes="dim")
        yield VerticalScroll(id="explo-bodies")

    def _position(self) -> dict | None:
        """Surface position, used for the exobiology clonal-distance aid."""
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

    def refresh_data(self) -> None:
        view = None
        bio_view = None
        err  = None
        sync = self.core._plugins.get("explo_sync")
        if sync is not None:
            try:
                view = build_system_view(
                    sync.current_system_address(), sync.current_commander_id()
                )
            except Exception as e:
                view = None
                err  = e
            # Biology is best-effort: a fault here must not blank the
            # cartographic view, which is the more commonly useful half.
            try:
                bio_view = build_exobio_view(
                    sync.current_system_address(), sync.current_commander_id(),
                    position=self._position(),
                )
            except Exception:
                bio_view = None

        # Index the biology by body so it can be nested under its own entry.
        bio_by_body: dict = {}
        for b in ((bio_view or {}).get("bodies") or []):
            for key in (b.get("name"), b.get("short")):
                if key:
                    bio_by_body[str(key)] = b

        try:
            sys_lbl = self.query_one("#explo-system", Label)
            sum_lbl = self.query_one("#explo-summary", Label)
            scroll  = self.query_one("#explo-bodies", VerticalScroll)
        except Exception:
            return

        scroll.remove_children()

        if not view:
            fault = explo_fault(self.core, err)
            sys_lbl.update("—")
            sum_lbl.update(fault or "No system data yet — honk to populate.")
            return

        sysd, tot = view["system"], view["totals"]
        sys_lbl.update(sysd["name"] or "—")

        bits = [f"{tot['scanned']}/{sysd['body_count'] or tot['bodies']} bodies"]
        if tot["high_value"]:
            bits.append(f"{tot['high_value']} worth mapping")
        if tot["bio_bodies"]:
            bits.append(f"{tot['bio_bodies']} bio")
        bio_tot = (bio_view or {}).get("totals") or {}
        if bio_tot.get("total_signals"):
            bits.append(f"{bio_tot.get('analysed', 0)}/{bio_tot['total_signals']} sampled")
        if tot.get("first_discovery"):
            bits.append(f"{tot['first_discovery']} undiscovered")
        if tot.get("first_footfall"):
            bits.append(f"{tot['first_footfall']} footfall")
        bits.append(f"{self.fmt_credits(tot['value_now'])} / {self.fmt_credits(tot['value_max'])}")
        sum_lbl.update("  ·  ".join(bits))

        rows = []
        for b in view["bodies"]:
            key = f"{(b['short'] or b['name']):<8} {_abbr(b):<6} {_markers(b)}"
            if not b["is_star"] and not b["mapped"] and b["mapping_gain"] > 0:
                val = f"{self.fmt_credits(b['value_now'])} → {self.fmt_credits(b['value_max'])}"
            else:
                val = self.fmt_credits(b["value_now"])
            cls = "val highlight" if b["high_value"] else ("val dim" if b["mapped"] else "val")
            rows.append(KVRow(key, val, val_classes=cls))

            bio = bio_by_body.get(str(b.get("name"))) or bio_by_body.get(str(b.get("short")))
            if bio:
                rows.extend(self._bio_rows(bio))
        if rows:
            scroll.mount(*rows)

    def _bio_rows(self, b: dict) -> list:
        """Exobiology detail for one body, indented under its exploration row.

        Same content the Exobiology window rendered, minus its own body
        header — the body is already named by the row above.
        """
        rows: list = []
        done = "✓" if b["complete"] else f"{b['analysed']}/{b['bio_signals']}"
        focus = "▸ " if b.get("current") else ""
        rows.append(SecHdr(f"  {focus}{b['bio_signals']} bio · {done}"))

        if b["bio_signals"] and (b["value_min"] or b["value_max"]):
            vtxt = f"est. {_fmt(b['value_min'])}–{_fmt(b['value_max'])}"
            if b.get("value_max_possible", 0) > b["value_max"]:
                vtxt += f" (↑{_fmt(b['value_max_possible'])})"
            ff = f"  [b]✦ first footfall ×{b['first_footfall_mult']}[/b]" if b["first_footfall"] else ""
            rows.append(Label(f"    {vtxt}{ff}"))

        sampled_genera = {f["genus"] for f in b["flora"]}
        for f in b["flora"]:
            stage = "✓" if f["logged"] else f"{f['stage']}/3"
            extra = "" if f["logged"] else f"  ≥{f['clonal']}m"
            cls = "val" if f["logged"] else "val highlight"
            rows.append(KVRow(f"    {f['name']}  {stage}",
                              _fmt(f["value"]) + extra, val_classes=cls))
            aid = f.get("aid")
            if aid:
                cue = ""
                if aid.get("heading") is not None and aid.get("bearing") is not None:
                    cue = _arrow(aid["bearing"] - aid["heading"]) + " "
                status = "[green]clear ✓[/green]" if aid["ok"] else "[b]too close — move away[/b]"
                rows.append(Label(
                    f"        {cue}{aid['distance']} m to last · ≥{aid['clonal']} m · {status}"
                ))

        genera = b["predicted_genera"] if b["predicting"] else b["genera"]
        for g in genera:
            if g["genus"] not in sampled_genera:
                label = f"    {g['genus']}" + ("  (cond.)" if g.get("gated") else "")
                rows.append(KVRow(label, _range(g), val_classes="val dim"))
        return rows

"""tui/blocks/exobiology.py — Exobiology window (Textual TUI).

For the current system, shows each body's biological signal count and sampling
progress, sampled species (stage, value, clonal distance), and value-range hints
for revealed-but-unsampled genera.  Location from explo_sync; data from
core.exobio_view.  Renders the Exobiology view.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label
from textual.containers import VerticalScroll

from tui.block_base   import TuiBlock, KVRow, SecHdr
from core.exobio_view import build_exobio_view


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


class ExobiologyBlock(TuiBlock):
    BLOCK_TITLE = "EXOBIOLOGY"

    def _compose_body(self) -> ComposeResult:
        yield Label("—", id="exobio-system", classes="section-hdr")
        yield Label("", id="exobio-summary", classes="dim")
        yield VerticalScroll(id="exobio-bodies")

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

    def refresh_data(self) -> None:
        view = None
        sync = self.core._plugins.get("explo_sync")
        if sync is not None:
            try:
                view = build_exobio_view(
                    sync.current_system_address(), sync.current_commander_id(),
                    position=self._position(),
                )
            except Exception:
                view = None

        try:
            sys_lbl = self.query_one("#exobio-system", Label)
            sum_lbl = self.query_one("#exobio-summary", Label)
            scroll  = self.query_one("#exobio-bodies", VerticalScroll)
        except Exception:
            return

        scroll.remove_children()

        if not view or not view["bodies"]:
            sys_lbl.update(view["system"]["name"] if view else "—")
            sum_lbl.update("[dim]No biology here yet — surface-scan a body with signals.[/dim]")
            return

        tot = view["totals"]
        sys_lbl.update(view["system"]["name"] or "—")
        bits = [f"{tot['bodies_with_bio']} bodies", f"{tot['total_signals']} signals",
                f"{tot['analysed']} analysed"]
        if tot["value_logged"]:
            bits.append(self.fmt_credits(tot["value_logged"]))
        if tot.get("potential_value_max"):
            bits.append(f"~{_fmt(tot['potential_value_min'])}–{_fmt(tot['potential_value_max'])}")
        sum_lbl.update("  ·  ".join(bits))

        rows: list = []
        for b in view["bodies"]:
            done = "✓" if b["complete"] else f"{b['analysed']}/{b['bio_signals']}"
            focus = "▸ " if b.get("current") else ""
            rows.append(SecHdr(f"{focus}{b['short'] or b['name']} · {b['bio_signals']} bio · {done}"))
            if b["bio_signals"] and (b["value_min"] or b["value_max"]):
                vtxt = f"est. {_fmt(b['value_min'])}–{_fmt(b['value_max'])}"
                if b.get("value_max_possible", 0) > b["value_max"]:
                    vtxt += f" (↑{_fmt(b['value_max_possible'])})"
                ff = f"  [b]✦ first footfall ×{b['first_footfall_mult']}[/b]" if b["first_footfall"] else ""
                rows.append(Label(f"  [dim]{vtxt}[/dim]{ff}"))
            sampled_genera = {f["genus"] for f in b["flora"]}
            for f in b["flora"]:
                stage = "✓" if f["logged"] else f"{f['stage']}/3"
                extra = "" if f["logged"] else f"  ≥{f['clonal']}m"
                cls = "val" if f["logged"] else "val highlight"
                rows.append(KVRow(f"  {f['name']}  {stage}", _fmt(f["value"]) + extra, val_classes=cls))
                aid = f.get("aid")
                if aid:
                    cue = ""
                    if aid.get("heading") is not None and aid.get("bearing") is not None:
                        cue = _arrow(aid["bearing"] - aid["heading"]) + " "
                    status = "[green]clear ✓[/green]" if aid["ok"] else "[b]too close — move away[/b]"
                    rows.append(Label(
                        f"      {cue}{aid['distance']} m to last · ≥{aid['clonal']} m · {status}"
                    ))
            # Predicted genera before a surface scan, confirmed ones after.
            genera = b["predicted_genera"] if b["predicting"] else b["genera"]
            for g in genera:
                if g["genus"] not in sampled_genera:
                    label = f"  {g['genus']}" + ("  (cond.)" if g.get("gated") else "")
                    rows.append(KVRow(label, _range(g), val_classes="val dim"))
        if rows:
            scroll.mount(*rows)

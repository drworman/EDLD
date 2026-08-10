"""tui/blocks/exploration.py — Exploration window (Textual TUI).

Shows the system the commander is currently in: honk / scan / map state, each
body's current and max-if-mapped cartographic value, high-value-mappable
highlights, bodies with biological signals, and system totals.  Location comes
from the explo_sync component; per-body data from core.explo_view.  Mirrors the
Exploration block.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label
from textual.containers import VerticalScroll

from tui.block_base    import TuiBlock, KVRow
from core.explo_view   import build_system_view

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


class ExplorationBlock(TuiBlock):
    BLOCK_TITLE = "EXPLORATION"

    def _compose_body(self) -> ComposeResult:
        yield Label("—", id="explo-system", classes="section-hdr")
        yield Label("", id="explo-summary", classes="dim")
        yield VerticalScroll(id="explo-bodies")

    def refresh_data(self) -> None:
        view = None
        sync = self.core._plugins.get("explo_sync")
        if sync is not None:
            try:
                view = build_system_view(
                    sync.current_system_address(), sync.current_commander_id()
                )
            except Exception:
                view = None

        try:
            sys_lbl = self.query_one("#explo-system", Label)
            sum_lbl = self.query_one("#explo-summary", Label)
            scroll  = self.query_one("#explo-bodies", VerticalScroll)
        except Exception:
            return

        scroll.remove_children()

        if not view:
            sys_lbl.update("—")
            sum_lbl.update("No system data yet — honk to populate.")
            return

        sysd, tot = view["system"], view["totals"]
        sys_lbl.update(sysd["name"] or "—")

        bits = [f"{tot['scanned']}/{sysd['body_count'] or tot['bodies']} bodies"]
        if tot["high_value"]:
            bits.append(f"{tot['high_value']} worth mapping")
        if tot["bio_bodies"]:
            bits.append(f"{tot['bio_bodies']} bio")
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
        if rows:
            scroll.mount(*rows)

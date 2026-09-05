"""
tui/blocks/ship_health.py — Ship Health window (Textual).

Built for neutron hopping, where the question before every leg is simply
"does anything need repairing before I carry on?".

Layout, top to bottom:

    Header      ship name and ident, then the hull type
    Hull        integrity percentage
    Shields     up / down / recharging
    Fuel        percentage, with an endurance estimate when burn rate is known
    ─────────
    MODULES     header, with a count of anything below full health
                every fitted module, sorted by power priority ascending,
                then by health ascending within each priority group

The secondary sort is the point: whatever most needs an AFM unit pointed at
it floats to the top of its power group, so a damaged module cannot hide in
the middle of a thirty-row list.

Priority is displayed 1-based to match the in-game power distribution panel;
the journal reports it 0-based and core/summary data keeps the raw value.

Hull, shields and fuel are read from ``state`` where the commander and alerts
components maintain them, so this window never becomes a second source of
truth for any of them.  Per-module health comes from the ship_health
component.

These three used to be duplicated in the Commander window as well.  They now
live here only: this is the window you look at to answer "is the ship all
right", and the ship's identity heads it for the same reason.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label
from textual.containers import VerticalScroll

from tui.block_base     import TuiBlock, KVRow, HRule, SecHdr, _health_cls
from core.state         import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD


def _fmt_health(fraction: float) -> str:
    """Render a 0.0–1.0 health fraction.

    Wear accumulates slowly, so a module at 99.2% would round to a flat
    "99%" and look identical to one at 98.6%.  One decimal place is kept
    below full health to keep that difference visible; a genuinely pristine
    module shows a clean "100%".
    """
    pct = max(0.0, min(1.0, fraction)) * 100
    if pct >= 99.95:
        return "100%"
    return f"{pct:.1f}%"


class ShipHealthBlock(TuiBlock):
    BLOCK_TITLE = "SHIP HEALTH"

    def compose(self) -> ComposeResult:
        # Two header rows carrying the ship's identity, moved here from the
        # Commander header: the vessel belongs with its own condition
        # readout, and Commander's header is now purely about the commander.
        yield Label("", id="sh-hdr1", classes="block-title")
        yield Label("", id="sh-hdr2", classes="block-title")
        yield from self._compose_body()

    def _compose_body(self) -> ComposeResult:
        yield KVRow("Hull",    id="sh-hull")
        yield KVRow("Shields", id="sh-shields")
        yield KVRow("Fuel",    id="sh-fuel")
        yield HRule()
        yield SecHdr("Modules", id="sh-modules-hdr")
        yield VerticalScroll(id="sh-modules")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        state  = self.core.state
        plugin = self.core._plugins.get("ship_health")

        self._refresh_header(state)
        self._refresh_hull(state)
        self._refresh_shields(state)
        self._refresh_fuel(state)
        self._refresh_modules(state, plugin)

    # ── Header ────────────────────────────────────────────────────────────────

    def _refresh_header(self, state) -> None:
        """Ship name / ident on the first row, hull type on the second.

        Rendered without parentheses: the type gets its own row rather than
        being bracketed onto the end of the name, which is how it read when
        this lived in the Commander header.
        """
        name  = (getattr(state, "ship_name", "")  or "").upper()
        ident = (getattr(state, "ship_ident", "") or "").upper()
        stype = (getattr(state, "pilot_ship", "") or "").upper()

        hdr1 = " - ".join(p for p in (name, ident) if p) or "SHIP HEALTH"
        self._set_label("sh-hdr1", hdr1)
        self._set_label("sh-hdr2", stype)

    def _set_label(self, node_id: str, text: str) -> None:
        try:
            label = self.query_one(f"#{node_id}", Label)
            label.update(text)
            label.display = bool(text)
        except Exception:
            pass

    # ── Fuel ──────────────────────────────────────────────────────────────────

    def _refresh_fuel(self, state) -> None:
        """Main-tank percentage, with endurance when the burn rate is known."""
        current = getattr(state, "fuel_current", None)
        tank    = getattr(state, "fuel_tank_size", None)
        if current is None or not tank or tank <= 0:
            self._set("sh-fuel", "—", "val dim")
            return

        text = f"{current / tank * 100:.0f}%"
        burn = getattr(state, "fuel_burn_rate", None)
        if burn and burn > 0:
            secs = (current / burn) * 3600
            hours, mins = int(secs // 3600), int((secs % 3600) // 60)
            text += f"  (~{hours}h {mins}m)" if hours else f"  (~{mins}m)"

        if current < tank * FUEL_CRIT_THRESHOLD:
            cls = "val health-crit"
        elif current < tank * FUEL_WARN_THRESHOLD:
            cls = "val health-warn"
        else:
            cls = "val health-good"
        self._set("sh-fuel", text, cls)

    # ── Hull ──────────────────────────────────────────────────────────────────

    def _refresh_hull(self, state) -> None:
        # ship_hull_exact carries full precision from Loadout/HullDamage;
        # ship_hull is the rounded integer the commander component keeps.
        exact = getattr(state, "ship_hull_exact", None)
        if exact is not None:
            text = _fmt_health(exact)
            pct  = int(exact * 100)
        else:
            pct = getattr(state, "ship_hull", None)
            if pct is None:
                self._set("sh-hull", "—", "val dim")
                return
            text = f"{pct}%"
        self._set("sh-hull", text, f"val {_health_cls(pct)}")

    # ── Shields ───────────────────────────────────────────────────────────────

    def _refresh_shields(self, state) -> None:
        up         = getattr(state, "ship_shields", None)
        recharging = getattr(state, "ship_shields_recharging", False)
        if up is None:
            self._set("sh-shields", "—", "val dim")
        elif up:
            self._set("sh-shields", "Up", "val health-good")
        elif recharging:
            self._set("sh-shields", "Recharging", "val health-warn")
        else:
            self._set("sh-shields", "Down", "val health-crit")

    # ── Modules ───────────────────────────────────────────────────────────────

    def _refresh_modules(self, state, plugin) -> None:
        try:
            scroll = self.query_one("#sh-modules", VerticalScroll)
        except Exception:
            return

        if plugin is not None:
            modules = plugin.modules_sorted()
        else:
            # Component unavailable — sort here so the window still works.
            modules = sorted(
                list(getattr(state, "ship_modules", []) or []),
                key=lambda m: (int(m.get("priority", 0) or 0),
                               float(m.get("health", 1.0) or 0.0),
                               m.get("name_display", "")),
            )

        self._update_header(modules)

        scroll.remove_children()
        if not modules:
            scroll.mount(Label("No loadout data yet — dock or jump to populate.",
                               classes="dim"))
            return

        rows: list = []
        for m in modules:
            health   = float(m.get("health", 1.0) or 0.0)
            pct      = int(health * 100)
            # Journal priority is 0-based; the in-game panel labels the same
            # group one higher.
            priority = int(m.get("priority", 0) or 0) + 1
            name     = m.get("name_display") or m.get("slot") or "—"
            powered  = m.get("on", True)

            key = f"{priority}  {name}"
            if not powered:
                key += " (off)"

            cls = f"val {_health_cls(pct)}" if health < 1.0 else "val dim"
            rows.append(KVRow(key, _fmt_health(health), val_classes=cls))
        scroll.mount(*rows)

    def _update_header(self, modules: list) -> None:
        """Put the count needing attention in the Modules header itself."""
        damaged = sum(1 for m in modules
                      if float(m.get("health", 1.0) or 0.0) < 1.0)
        if damaged:
            text = f"MODULES — {damaged} damaged"
        elif modules:
            text = f"MODULES — {len(modules)} all nominal"
        else:
            text = "MODULES"
        try:
            self.query_one("#sh-modules-hdr", SecHdr).update(text)
        except Exception:
            pass

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set(self, row_id: str, text: str, classes: str = "val") -> None:
        try:
            self.query_one(f"#{row_id}", KVRow).set_value(text, classes)
        except Exception:
            pass

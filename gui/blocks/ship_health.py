"""
gui/blocks/ship_health.py — Ship Health window (Qt).

Built for neutron hopping, where the question before every leg is simply
"does anything need repairing before I carry on?".

Layout, top to bottom:

    Hull        integrity percentage
    Shields     up / down / recharging
    ─────────
    MODULES     header, with a count of anything below full health
                every fitted module, sorted by power priority ascending,
                then by health ascending within each priority group

The secondary sort is the point: whatever most needs an AFM unit pointed at
it floats to the top of its power group, so a damaged module cannot hide in
the middle of a thirty-row list.

Priority is displayed 1-based to match the in-game power distribution panel;
the journal reports it 0-based and core/summary data keeps the raw value.

Hull and shields are read from ``state`` where the commander and alerts
components maintain them, so this window never becomes a second source of
truth for either figure.  Per-module health comes from the ship_health
component.
"""

from __future__ import annotations

from gui.block_base import GuiBlock, _health_cls


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


class ShipHealthBlock(GuiBlock):
    BLOCK_TITLE = "SHIP HEALTH"

    def _build_body(self, layout) -> None:
        self._hull = self.kv("Hull")
        self._shields = self.kv("Shields")
        self._modules_hdr = self.hdr("Modules")
        self._scroll = self.scroll()

        layout.addWidget(self._hull)
        layout.addWidget(self._shields)
        layout.addWidget(self.rule())
        layout.addWidget(self._modules_hdr)
        layout.addWidget(self._scroll, 1)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        state = self.core.state
        plugin = self.core._plugins.get("ship_health")

        self._refresh_hull(state)
        self._refresh_shields(state)
        self._refresh_modules(state, plugin)

    # ── Hull ──────────────────────────────────────────────────────────────────

    def _refresh_hull(self, state) -> None:
        # ship_hull_exact carries full precision from Loadout/HullDamage;
        # ship_hull is the rounded integer the commander component keeps.
        exact = getattr(state, "ship_hull_exact", None)
        if exact is not None:
            text = _fmt_health(exact)
            pct = int(exact * 100)
        else:
            pct = getattr(state, "ship_hull", None)
            if pct is None:
                self._hull.set_value("—", "val dim")
                return
            text = f"{pct}%"
        self._hull.set_value(text, f"val {_health_cls(pct)}")

    # ── Shields ───────────────────────────────────────────────────────────────

    def _refresh_shields(self, state) -> None:
        up = getattr(state, "ship_shields", None)
        recharging = getattr(state, "ship_shields_recharging", False)
        if up is None:
            self._shields.set_value("—", "val dim")
        elif up:
            self._shields.set_value("Up", "val health-good")
        elif recharging:
            self._shields.set_value("Recharging", "val health-warn")
        else:
            self._shields.set_value("Down", "val health-crit")

    # ── Modules ───────────────────────────────────────────────────────────────

    def _refresh_modules(self, state, plugin) -> None:
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

        if not modules:
            self._scroll.set_rows([
                self.text("No loadout data yet — dock or jump to populate.", "dim")
            ])
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
            rows.append(self.kv(key, _fmt_health(health), cls))
        self._scroll.set_rows(rows)

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
        self._modules_hdr.set_title(text)

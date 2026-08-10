"""
components/ship_health.py — Per-module health and power priority tracking.

Feeds the Ship Health window.  The intended user is a neutron hopper who
needs to know, at a glance and without opening the in-game right panel,
what wants repairing before the next set of jumps.

Why this component exists
-------------------------
Nothing else in EDLD carries per-module health.  ``ModulesInfo.json``
carries ``Priority`` but no ``Health`` at all, and the Assets component
parses ``Loadout`` for value and engineering rather than condition.  The
``Loadout`` event is the only source that carries both fields together, so
this component takes ``Loadout`` as its baseline and then applies the
incremental repair and damage events on top of it.

State published on MonitorState
-------------------------------
    ship_modules       list  — [{slot, name_internal, name_display,
                                 priority, on, health}]
                               health is 0.0–1.0; priority is the raw
                               journal value (0-based)
    ship_hull_exact    float — hull integrity 0.0–1.0, full precision

``state.ship_hull`` (int percent) and ``state.ship_shields`` stay owned by
the commander and alerts components; the Ship Health window reads those for
its hull and shield rows so there is one source of truth per figure.

Priority numbering
------------------
The journal reports ``Priority`` 0-based while the in-game power
distribution panel labels the same groups 1–5.  The raw value is stored
here and the display layer adds one, so what the window shows matches what
the game shows.

Cosmetic modules
----------------
Paint jobs, decals, nameplates, ship kits, engine and weapon colours, and
voice packs all report ``Priority: 1`` and ``Health: 1.0`` forever.  Left
in, they would pad the priority-1 group with a dozen rows that can never
need repair, so they are filtered out at parse time.
"""

import json
from pathlib import Path

from core.plugin_loader import BasePlugin
from data.modules import normalise_module_name


# Slot prefixes that are purely cosmetic — never damaged, never actionable.
_COSMETIC_PREFIXES = (
    "paintjob", "decal", "shipname", "shipid", "shipkit",
    "weaponcolour", "enginecolour", "vesselvoice", "bobble",
    "stringlights", "nameplate",
)

# How many journal files to search backwards for a baseline Loadout.
_SCAN_JOURNALS = 6


def _is_cosmetic(slot: str, item: str) -> bool:
    s = (slot or "").lower()
    if s.startswith(_COSMETIC_PREFIXES):
        return True
    i = (item or "").lower()
    return i.startswith(("paintjob_", "decal_", "nameplate_",
                         "weaponcustomisation_", "enginecustomisation_",
                         "voicepack_", "bobble_", "string_lights"))


def _clean_module_token(token: str) -> str:
    """Normalise a journal module token to a bare internal name.

    Repair and AfmuRepairs events name modules as ``$int_engine_size7_..._name;``
    while Loadout uses the bare ``int_engine_size7_...``.  Strip the wrapper
    so the two can be matched.
    """
    t = (token or "").strip()
    if t.startswith("$"):
        t = t[1:]
    if t.endswith(";"):
        t = t[:-1]
    if t.endswith("_name"):
        t = t[:-5]
    return t.lower()


class ShipHealthPlugin(BasePlugin):
    PLUGIN_NAME    = "ship_health"
    PLUGIN_DISPLAY = "Ship Health"
    PLUGIN_DESCRIPTION = (
        "Tracks hull, shields, and per-module health and power priority for "
        "the Ship Health window."
    )
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        # Baseline — carries both Health and Priority for every module.
        "Loadout",
        # Incremental condition changes.
        "HullDamage",
        "AfmuRepairs",
        "Repair",
        "RepairAll",
        "RebootRepair",
        # Full resets.
        "Died",
        "Resurrect",
        "SelfDestruct",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        s = core.state
        if not hasattr(s, "ship_modules"):
            s.ship_modules = []
        if not hasattr(s, "ship_hull_exact"):
            s.ship_hull_exact = None

        # Restore the last known loadout so the window has content before the
        # first Loadout of the session fires, then try for something fresher
        # from the journals on disk.
        self._restore()
        self._bootstrap_from_journals()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _restore(self) -> None:
        try:
            data = self.storage.read_json() or {}
            mods = data.get("modules")
            if isinstance(mods, list) and mods:
                self.core.state.ship_modules = mods
            hull = data.get("hull_exact")
            if isinstance(hull, (int, float)):
                self.core.state.ship_hull_exact = float(hull)
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            self.storage.write_json({
                "modules":    self.core.state.ship_modules,
                "hull_exact": self.core.state.ship_hull_exact,
            })
        except Exception:
            pass

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    def _bootstrap_from_journals(self) -> None:
        """Seed from the most recent Loadout found on disk.

        Reads newest-first and stops at the first Loadout, so the cost is a
        single partial file read in the common case.
        """
        try:
            jdir = Path(self.core.journal_dir)
            journals = sorted(jdir.glob("Journal*.log"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            return

        for path in journals[:_SCAN_JOURNALS]:
            try:
                lines = path.read_text(encoding="utf-8",
                                       errors="replace").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                if '"Loadout"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("event") == "Loadout":
                    self._apply_loadout(ev)
                    return

    # ── Event handling ────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event")

        match ev:
            case "Loadout":
                self._apply_loadout(event)

            case "HullDamage":
                # Ship hull only — SRV and fighter damage arrive on the same
                # event and are not what this window reports.
                if event.get("PlayerPilot") and not event.get("Fighter"):
                    if getattr(state, "vessel_mode", "ship") != "srv":
                        state.ship_hull_exact = float(event.get("Health") or 0.0)
                        self._changed()

            case "AfmuRepairs":
                target = _clean_module_token(event.get("Module", ""))
                health = event.get("Health")
                if target and health is not None:
                    self._set_health(target, float(health))
                    self._changed()

            case "Repair":
                self._apply_repair(event, state)

            case "RepairAll":
                self._repair_everything(state)

            case "RebootRepair":
                # Reboot & repair restores malfunctioning modules to a partial
                # state the event does not quantify.  The following Loadout
                # carries the true figures, so only nudge zeroed modules off
                # the floor and let Loadout correct them.
                slots = {s.lower() for s in (event.get("Modules") or [])}
                if slots:
                    for m in state.ship_modules:
                        if m.get("slot", "").lower() in slots and m.get("health", 1.0) <= 0.0:
                            m["health"] = 0.01
                    self._changed()

            case "Died" | "SelfDestruct":
                # The rebuy delivers a pristine hull; hold that until the next
                # Loadout confirms it.
                self._repair_everything(state)

            case "Resurrect":
                self._repair_everything(state)

    # ── Mutators ──────────────────────────────────────────────────────────────

    def _apply_loadout(self, event: dict) -> None:
        state = self.core.state
        modules = []
        for m in event.get("Modules") or []:
            slot = m.get("Slot", "")
            item = m.get("Item", "")
            if not slot or not item or _is_cosmetic(slot, item):
                continue
            modules.append({
                "slot":          slot,
                "name_internal": item,
                "name_display":  normalise_module_name(item),
                "priority":      int(m.get("Priority", 0) or 0),
                "on":            bool(m.get("On", True)),
                "health":        float(m.get("Health", 1.0) or 0.0),
            })
        state.ship_modules = modules

        hull = event.get("HullHealth")
        if hull is not None:
            state.ship_hull_exact = float(hull)
        self._changed()

    def _apply_repair(self, event: dict, state) -> None:
        """Apply a station Repair event.

        ``Items`` mixes bare keywords with module tokens: ``"Hull"`` for hull
        integrity, ``"Wear"`` for a whole-ship integrity repair, ``"All"`` for
        everything, and ``$module_name;`` tokens for individual modules.
        """
        items = event.get("Items") or []
        if isinstance(items, str):
            items = [items]

        for raw in items:
            token = (raw or "").strip()
            low   = token.lower()
            if low in ("hull", "all", "wear", "paint"):
                if low in ("hull", "all"):
                    state.ship_hull_exact = 1.0
                if low in ("all", "wear"):
                    for m in state.ship_modules:
                        m["health"] = 1.0
                continue
            self._set_health(_clean_module_token(token), 1.0)
        self._changed()

    def _repair_everything(self, state) -> None:
        for m in state.ship_modules:
            m["health"] = 1.0
        state.ship_hull_exact = 1.0
        self._changed()

    def _set_health(self, internal_name: str, health: float) -> None:
        """Set health on every module matching an internal name.

        Matching is by internal name rather than slot because the repair
        events do not name a slot.  A ship carrying two identical modules —
        twin AFM units, for instance — has both set, which is what the game
        does anyway when repairing by module type at a station.
        """
        if not internal_name:
            return
        for m in self.core.state.ship_modules:
            if m.get("name_internal", "").lower() == internal_name:
                m["health"] = max(0.0, min(1.0, health))

    # ── Notification ──────────────────────────────────────────────────────────

    def _changed(self) -> None:
        self._persist()
        gq = self.core.gui_queue
        if gq:
            gq.put(("ship_health_update", None))

    # ── Query API ─────────────────────────────────────────────────────────────

    def modules_sorted(self) -> list[dict]:
        """Modules ordered for display: priority ascending, then health
        ascending so whatever most needs repairing sits at the top of its
        power group."""
        mods = list(getattr(self.core.state, "ship_modules", []) or [])
        return sorted(
            mods,
            key=lambda m: (int(m.get("priority", 0) or 0),
                           float(m.get("health", 1.0) or 0.0),
                           m.get("name_display", "")),
        )

    def damaged_count(self, threshold: float = 1.0) -> int:
        """How many fitted modules sit below ``threshold`` health."""
        return sum(
            1 for m in getattr(self.core.state, "ship_modules", []) or []
            if float(m.get("health", 1.0) or 0.0) < threshold
        )

    def worst_health(self) -> float | None:
        """Lowest module health on the ship, or None when nothing is known."""
        mods = getattr(self.core.state, "ship_modules", []) or []
        if not mods:
            return None
        return min(float(m.get("health", 1.0) or 0.0) for m in mods)

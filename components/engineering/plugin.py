"""
components/engineering/plugin.py — Combined engineering materials inventory.

Tracks all seven engineering material categories across both the Horizons
and Odyssey systems:

  Horizons (ship-based engineering)
    Raw          — geological elements (Carbon, Vanadium, Polonium …)
    Manufactured — salvaged tech components (Heat Conductors, Polymer Capacitors …)
    Encoded      — scanned data (Modified Consumer Firmware …)

  Odyssey (on-foot engineering)
    Components   — physical parts found at settlements and on bodies
    Items        — crafted or looted objects
    Consumables  — single-use items (medkits, energy cells …)
    Data         — mission and intel data packages

Horizons materials are sourced entirely from journal events.
Odyssey materials are sourced from the ShipLocker journal event and
ShipLocker.json (read on startup for an immediate display).

State stored on MonitorState (all added via hasattr guard in on_load):
    materials_raw          dict  — {name_lower: {"count": int, "name_local": str}}
    materials_manufactured dict
    materials_encoded      dict
    engineering_locker     dict  — {
                                     "components":  {name_lower: {"count": int, "name_local": str}},
                                     "items":       { … },
                                     "consumables": { … },
                                     "data":        { … },
                                   }

GUI block: engineering  (replaces the former 'materials' block)
"""

import json
from pathlib import Path

from core.plugin_loader import BasePlugin


class EngineeringPlugin(BasePlugin):
    PLUGIN_NAME        = "engineering"
    PLUGIN_DISPLAY     = "Engineering"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = "Engineering materials — Horizons Raw/Manufactured/Encoded and Odyssey ShipLocker inventory."

    SUBSCRIBED_EVENTS = [
        # Horizons materials
        "Materials",            # Full snapshot — always authoritative
        "MaterialCollected",    # Picked up one item
        "MaterialDiscarded",    # Discarded one or more
        "MaterialTrade",        # Traded at a material trader
        "EngineerCraft",        # Consumed materials for a blueprint
        "TechnologyBroker",     # Consumed materials for a tech unlock
        "Synthesis",            # Consumed materials for synthesis
        # Odyssey ShipLocker
        "ShipLocker",
        "BackpackChange", "BuyMicroResources", "SellMicroResources",           # Full snapshot of on-foot inventory
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=50)

        s = core.state
        if not hasattr(s, "materials_raw"):          s.materials_raw          = {}
        if not hasattr(s, "materials_manufactured"): s.materials_manufactured = {}
        if not hasattr(s, "materials_encoded"):      s.materials_encoded      = {}
        if not hasattr(s, "engineering_locker"):
            s.engineering_locker = {
                "components":  {},
                "items":       {},
                "consumables": {},
                "data":        {},
            }

        # Bootstrap Backpack.json for immediate Odyssey backpack display
        _bootstrap_backpack(s, core.journal_dir)
        # Read ShipLocker.json for immediate locker display on startup
        self._read_shiplocker_json(core)

        # Deferred startup refresh — fires after the GTK main loop is running
        import threading
        threading.Timer(3.0, self._startup_refresh).start()

    def _startup_refresh(self) -> None:
        gq = self.core.gui_queue if self.core else None
        if gq:
            gq.put(("plugin_refresh", "engineering"))

    def _read_shiplocker_json(self, core) -> None:
        """Read ShipLocker.json on startup for an immediate locker snapshot."""
        try:
            path = Path(core.journal_dir) / "ShipLocker.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                core.state.engineering_locker = _parse_shiplocker(data)
        except Exception:
            pass

    def on_event(self, event: dict, state) -> None:
        core = self.core
        gq   = core.gui_queue
        ev   = event.get("event")

        match ev:

            case "Materials":
                state.materials_raw          = _parse_horizons_list(event.get("Raw", []))
                state.materials_manufactured = _parse_horizons_list(event.get("Manufactured", []))
                state.materials_encoded      = _parse_horizons_list(event.get("Encoded", []))
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "MaterialCollected":
                cat    = event.get("Category", "").lower()
                key    = event.get("Name", "").lower()
                count  = int(event.get("Count", 1))
                bucket = _horizons_bucket(state, cat)
                if bucket is not None and key:
                    entry = bucket.setdefault(key, {
                        "count":      0,
                        "name_local": event.get("Name_Localised") or _fmt_name(key),
                    })
                    entry["count"] += count
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "MaterialDiscarded":
                cat    = event.get("Category", "").lower()
                key    = event.get("Name", "").lower()
                count  = int(event.get("Count", 1))
                bucket = _horizons_bucket(state, cat)
                if bucket is not None and key and key in bucket:
                    bucket[key]["count"] -= count
                    if bucket[key]["count"] <= 0:
                        del bucket[key]
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "MaterialTrade":
                paid = event.get("Paid", {})
                recv = event.get("Received", {})
                for side, delta in [(paid, -1), (recv, 1)]:
                    cat    = side.get("Category", "").lower()
                    key    = side.get("Name", "").lower()
                    count  = int(side.get("Count", 1)) * delta
                    bucket = _horizons_bucket(state, cat)
                    if bucket is not None and key:
                        if count < 0:
                            if key in bucket:
                                bucket[key]["count"] += count
                                if bucket[key]["count"] <= 0:
                                    del bucket[key]
                        else:
                            entry = bucket.setdefault(key, {
                                "count":      0,
                                "name_local": side.get("Name_Localised") or _fmt_name(key),
                            })
                            entry["count"] += count
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "EngineerCraft" | "TechnologyBroker" | "Synthesis":
                key_ingr = "Ingredients" if ev != "Synthesis" else "Materials"
                for item in event.get(key_ingr, []):
                    cat    = item.get("Category", "").lower()
                    key    = item.get("Name", "").lower()
                    count  = int(item.get("Count", 1))
                    bucket = _horizons_bucket(state, cat)
                    if bucket is None:
                        for b in (state.materials_raw,
                                  state.materials_manufactured,
                                  state.materials_encoded):
                            if key in b:
                                bucket = b
                                break
                    if bucket is not None and key and key in bucket:
                        bucket[key]["count"] -= count
                        if bucket[key]["count"] <= 0:
                            del bucket[key]
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "ShipLocker":
                state.engineering_locker = _parse_shiplocker(event)
                if gq: gq.put(("plugin_refresh", "engineering"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_horizons_list(items: list) -> dict:
    """Parse a Horizons material list from a journal event into a name→data dict."""
    result = {}
    for item in items:
        key = item.get("Name", "").lower()
        if not key:
            continue
        result[key] = {
            "count":      int(item.get("Count", 0)),
            "name_local": item.get("Name_Localised") or _fmt_name(key),
        }
    return result


def _parse_shiplocker(data: dict) -> dict:
    """Parse a ShipLocker event or ShipLocker.json into the engineering_locker
    structure: dict of group name → {name_lower: {"count": int, "name_local": str}}.

    The structure deliberately mirrors the Horizons materials format so that
    the block's _refresh_section() can handle all seven tabs identically.
    """
    result: dict[str, dict] = {}
    for group in ("Components", "Items", "Consumables", "Data"):
        bucket: dict = {}
        for item in data.get(group, []):
            count = int(item.get("Count", 0))
            if count <= 0:
                continue
            key  = item.get("Name", "").lower()
            disp = item.get("Name_Localised") or _fmt_name(key)
            bucket[key] = {"count": count, "name_local": disp}
        result[group.lower()] = bucket
    return result


def _horizons_bucket(state, category: str):
    """Return the correct Horizons materials dict for a category string."""
    if "raw" in category:          return state.materials_raw
    if "manufactured" in category: return state.materials_manufactured
    if "encoded" in category:      return state.materials_encoded
    return None


def _fmt_name(key: str) -> str:
    return key.replace("_", " ").title()


# ── Backpack JSON helpers ─────────────────────────────────────────────────────

def _bootstrap_backpack(state, journal_dir) -> None:
    """Bootstrap Odyssey backpack micro-resources from Backpack.json on startup."""
    if not hasattr(state, "engineering_backpack"):
        state.engineering_backpack = {}
    data = _read_backpack_json(journal_dir)
    if data:
        state.engineering_backpack = data


def _read_backpack_json(journal_dir) -> dict | None:
    """Read Backpack.json and return {category: [{name, name_local, count}]} or None."""
    if journal_dir is None:
        return None
    import json as _json
    from pathlib import Path as _Path
    import builtins as _bi
    path = _Path(journal_dir) / "Backpack.json"
    try:
        data = _json.load(_bi.open(path, encoding="utf-8"))
    except Exception:
        return None
    result = {}
    for cat in ("Items", "Components", "Consumables", "Data"):
        items = data.get(cat, [])
        if items:
            result[cat.lower()] = [
                {
                    "name":       i.get("Name", ""),
                    "name_local": i.get("Name_Localised") or i.get("Name", ""),
                    "count":      int(i.get("Count", 0)),
                }
                for i in items
            ]
    return result or None



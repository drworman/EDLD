"""
components/cargo.py — Ship cargo inventory tracking.

Tracks the current cargo hold: capacity, used slots, and per-item breakdown
enriched with market data (sell price, galactic average, category) from
Market.json and CAPI /market.

Cargo.json strategy
-------------------
The game writes Cargo.json on every hold change. It is always the ship's cargo
(never SRV or Fighter), so we read it on every "Cargo" journal event rather than
parsing the event Inventory array directly — which suffers from per-vessel events
firing in sequence and overwriting the ship's snapshot.

State written to MonitorState:
    cargo_capacity      int   — maximum hold tonnage (from Loadout)
    cargo_items         dict  — {key: {count, stolen, name_local}}
    cargo_market_info   dict  — full market data from Market.json / CAPI:
                                {
                                  "station_name": str,
                                  "star_system":  str,
                                  "commodities":  {
                                    key: {
                                      name_local, category, category_local,
                                      sell_price, mean_price
                                    }
                                  }
                                }

Dashboard block: cargo
"""

import json
from pathlib import Path

from core.plugin_loader import BasePlugin

_CANON_RE = __import__('re').compile(r'^\$(.+)_name;$')


def _canonicalise_key(raw: str) -> str:
    """Normalise a commodity key to plain lowercase.

    Both Market.json and some journal events use the $commodity_name;
    localisation wrapper. Strip it so keys always match.
    """
    s = (raw or "").strip().lower()
    m = _CANON_RE.match(s)
    return m.group(1) if m else s


class CargoPlugin(BasePlugin):
    PLUGIN_NAME    = "cargo"
    PLUGIN_DISPLAY = "Cargo"
    PLUGIN_DESCRIPTION = "Live ship hold inventory with market price comparison via Spansh."
    PLUGIN_VERSION = "2.0.0"

    SUBSCRIBED_EVENTS = [
        "Cargo",            # Full inventory snapshot (or count-only signal)
        "CargoTransfer",    # Ship ↔ carrier transfer — apply deltas immediately
        "CollectCargo",     # Scooped/picked up
        "EjectCargo",       # Dropped
        "MarketBuy",        # Bought commodity
        "MarketSell",       # Sold commodity
        "MiningRefined",    # Refined ore into hold
        "CargoDepot",       # Wing mission cargo
        "Loadout",          # Hold capacity
        "LoadGame",         # Session start
        "Died",             # Ship destroyed
        "Market",           # Market.json updated (player opened market UI)
        "Docked",           # Market.json written when player docks
        "Location",         # Market.json written on session start at station
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=45)
        s = core.state
        if not hasattr(s, "cargo_capacity"):   s.cargo_capacity   = 0
        if not hasattr(s, "cargo_items"):      s.cargo_items      = {}
        # Legacy field kept for compat — block now reads cargo_market_info instead
        if not hasattr(s, "cargo_mean_prices"):s.cargo_mean_prices = {}
        if not hasattr(s, "cargo_market_info"):s.cargo_market_info = {}

        # Restore persisted galactic-average prices accumulated from all previous
        # market visits. These survive restarts and FC visits (which wipe the local
        # Market.json). New prices are MERGED in, never replaced wholesale.
        saved_prices = self.storage.read_json("data.json") or {}
        if isinstance(saved_prices, dict):
            s.cargo_mean_prices = saved_prices

        # Bootstrap current-market data — CAPI first, then Market.json.
        # Merge new prices into the persisted set so visiting an FC (which has a
        # single-item Market.json) doesn't erase prices from previous stations.
        capi_mkt = getattr(s, "capi_market", None)
        if capi_mkt and capi_mkt.get("commodities"):
            s.cargo_market_info = _build_market_info_from_capi(capi_mkt)
            new_prices = {
                k: v["mean_price"]
                for k, v in capi_mkt["commodities"].items()
                if v.get("mean_price")
            }
            s.cargo_mean_prices.update(new_prices)
        else:
            info = _read_market_json(core.journal_dir)
            if info:
                s.cargo_market_info = info
                new_prices = {
                    k: v["mean_price"]
                    for k, v in info.get("commodities", {}).items()
                    if v.get("mean_price")
                }
                s.cargo_mean_prices.update(new_prices)

        if s.cargo_mean_prices:
            self._save_mean_prices(s.cargo_mean_prices)

        # Watch Market.json for changes not triggered by a journal event
        # (e.g. selecting a comparison market from the galaxy/system map).
        import threading as _thr
        _thr.Thread(
            target=self._watch_market_json,
            daemon=True,
            name="cargo-market-watch",
        ).start()

        # Bootstrap cargo from Cargo.json
        items = _read_cargo_json(core.journal_dir)
        if items is not None:
            s.cargo_items = items

    def _watch_market_json(self) -> None:
        """Poll Market.json for mtime changes.

        The game writes Market.json silently (no journal event) when the
        player selects a comparison market from the galaxy or system map.
        Poll every 2 seconds; on change, re-read and refresh cargo block.
        """
        import time as _time
        from pathlib import Path as _Path
        market_path = _Path(self.core.journal_dir) / "Market.json"
        last_mtime  = 0.0
        while True:
            try:
                if market_path.is_file():
                    mtime = market_path.stat().st_mtime
                    if mtime != last_mtime:
                        last_mtime = mtime
                        info = _read_market_json(self.core.journal_dir)
                        if info:
                            state = self.core.state
                            state.cargo_market_info = info
                            new_prices = {
                                k: v["mean_price"]
                                for k, v in info.get("commodities", {}).items()
                                if v.get("mean_price")
                            }
                            if new_prices:
                                state.cargo_mean_prices.update(new_prices)
                                self._save_mean_prices(state.cargo_mean_prices)
                            gq = self.core.gui_queue
                            if gq:
                                gq.put(("plugin_refresh", "cargo"))
            except Exception:
                pass
            _time.sleep(2.0)

    def on_event(self, event: dict, state) -> None:
        core = self.core
        gq   = core.gui_queue
        ev   = event.get("event")

        match ev:

            case "Loadout":
                cap = event.get("CargoCapacity", 0)
                if cap:
                    state.cargo_capacity = int(cap)
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "Cargo":
                # The game fires Cargo in two forms:
                #   Full:  {"Count": N, "Inventory": [...]}  — authoritative snapshot
                #   Count: {"Count": N}                      — count-only signal after
                #          CargoTransfer or ColonisationContribution; Inventory omitted
                #
                # For Count:0 with no Inventory the hold is definitively empty.
                # For Count:N with no Inventory we read Cargo.json — by the time
                # this event fires the file is current (CargoTransfer precedes it).
                inventory = event.get("Inventory")
                count     = event.get("Count", -1)
                if inventory is not None:
                    # Full snapshot — parse directly, no file race possible
                    result = {}
                    for item in inventory:
                        key = _canonicalise_key(item.get("Name", ""))
                        if not key:
                            continue
                        n = int(item.get("Count", 0))
                        if n <= 0:
                            continue
                        result[key] = {
                            "count":      n,
                            "stolen":     bool(item.get("Stolen", False)),
                            "name_local": item.get("Name_Localised") or _fmt_name(key),
                        }
                    state.cargo_items = result
                elif count == 0:
                    # Count-only event with zero — hold is empty
                    state.cargo_items = {}
                else:
                    # Count-only event with N > 0 — read Cargo.json (will be current)
                    items = _read_cargo_json(core.journal_dir)
                    if items is not None:
                        state.cargo_items = items
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "CargoTransfer":
                # Fired when cargo moves between ship and fleet carrier.
                # Apply each transfer as a delta so the hold stays accurate
                # without waiting for the follow-up Cargo event.
                for t in event.get("Transfers", []):
                    key       = _canonicalise_key(t.get("Type", ""))
                    n         = int(t.get("Count", 0))
                    direction = t.get("Direction", "")
                    if not key or n <= 0:
                        continue
                    if direction == "toship":
                        entry = state.cargo_items.setdefault(key, {
                            "count": 0, "stolen": False,
                            "name_local": t.get("Type_Localised") or _fmt_name(key),
                        })
                        entry["count"] += n
                    elif direction == "tocarrier":
                        if key in state.cargo_items:
                            state.cargo_items[key]["count"] -= n
                            if state.cargo_items[key]["count"] <= 0:
                                del state.cargo_items[key]
                # Purge any zero-count stragglers
                state.cargo_items = {k: v for k, v in state.cargo_items.items()
                                     if v.get("count", 0) > 0}
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "CollectCargo":
                key = _canonicalise_key(event.get("Type", ""))
                if key:
                    entry = state.cargo_items.setdefault(key, {
                        "count": 0, "stolen": bool(event.get("Stolen", False)),
                        "name_local": event.get("Type_Localised") or _fmt_name(key),
                    })
                    entry["count"] += 1
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "EjectCargo":
                key = _canonicalise_key(event.get("Type", ""))
                count = int(event.get("Count", 1))
                if key and key in state.cargo_items:
                    state.cargo_items[key]["count"] -= count
                    if state.cargo_items[key]["count"] <= 0:
                        del state.cargo_items[key]
                # Purge any other zero-count entries left by edge cases
                state.cargo_items = {k: v for k, v in state.cargo_items.items()
                                     if v.get("count", 0) > 0}
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "MarketBuy":
                key   = _canonicalise_key(event.get("Type", ""))
                count = int(event.get("Count", 1))
                if key:
                    entry = state.cargo_items.setdefault(key, {
                        "count": 0, "stolen": False,
                        "name_local": event.get("Type_Localised") or _fmt_name(key),
                    })
                    entry["count"] += count
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "MarketSell":
                key   = _canonicalise_key(event.get("Type", ""))
                count = int(event.get("Count", 1))
                if key and key in state.cargo_items:
                    state.cargo_items[key]["count"] -= count
                    if state.cargo_items[key]["count"] <= 0:
                        del state.cargo_items[key]
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "MiningRefined":
                key = _canonicalise_key(event.get("Type", ""))
                if key:
                    entry = state.cargo_items.setdefault(key, {
                        "count": 0, "stolen": False,
                        "name_local": event.get("Type_Localised") or _fmt_name(key),
                    })
                    entry["count"] += 1
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "CargoDepot":
                items = _read_cargo_json(core.journal_dir)
                if items is not None:
                    state.cargo_items = items
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "Died":
                state.cargo_items = {}
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "Market":
                info = _read_market_json(core.journal_dir)
                if info:
                    state.cargo_market_info = info
                    new_prices = {
                        k: v["mean_price"]
                        for k, v in info.get("commodities", {}).items()
                        if v.get("mean_price")
                    }
                    if new_prices:
                        state.cargo_mean_prices.update(new_prices)
                        self._save_mean_prices(state.cargo_mean_prices)
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "Docked" | "Location":
                # Market.json is (re)written when the player docks or loads
                # at a station. Re-read it so prices/station update immediately
                # even if the player never opens the commodities screen.
                info = _read_market_json(core.journal_dir)
                if info:
                    state.cargo_market_info = info
                    new_prices = {
                        k: v["mean_price"]
                        for k, v in info.get("commodities", {}).items()
                        if v.get("mean_price")
                    }
                    if new_prices:
                        state.cargo_mean_prices.update(new_prices)
                        self._save_mean_prices(state.cargo_mean_prices)
                if gq: gq.put(("plugin_refresh", "cargo"))

            case "LoadGame":
                state.cargo_items = {}
                if gq: gq.put(("plugin_refresh", "cargo"))


    def _save_mean_prices(self, prices: dict) -> None:
        """Persist accumulated galactic-average prices to plugin storage."""
        try:
            self.storage.write_json(prices, "data.json")
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_market_json(journal_dir) -> dict | None:
    """Read Market.json and return a cargo_market_info dict or None.

    Returns None for Fleet Carrier markets — FC Market.json only contains
    public trade orders (often zero items) with MeanPrice=0, which is
    useless for galactic-average price lookups on ship cargo.
    """
    if journal_dir is None:
        return None
    path = Path(journal_dir) / "Market.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    # FC markets have no useful galactic average prices — skip them entirely
    if data.get("StationType") == "FleetCarrier":
        return None

    commodities = {}
    for item in data.get("Items", []):
        key = _canonicalise_key(item.get("Name", ""))
        if not key:
            continue
        cat_raw   = item.get("Category", "")
        cat_local = item.get("Category_Localised", "")
        if not cat_local:
            # Strip $..._name; wrapper from category key
            m = _CANON_RE.match(cat_raw.lower())
            cat_local = m.group(1).replace("_", " ").title() if m else cat_raw.title()
        commodities[key] = {
            "name_local":   item.get("Name_Localised", "") or _fmt_name(key),
            "category":     cat_raw,
            "category_local": cat_local,
            "sell_price":   int(item.get("SellPrice", 0)),
            "mean_price":   int(item.get("MeanPrice", 0)),
        }

    return {
        "station_name": data.get("StationName", ""),
        "star_system":  data.get("StarSystem", ""),
        "commodities":  commodities,
    }


def _build_market_info_from_capi(capi_mkt: dict) -> dict:
    """Convert state.capi_market into cargo_market_info format."""
    commodities = {}
    for key, c in capi_mkt.get("commodities", {}).items():
        cat = c.get("category", "")
        commodities[key] = {
            "name_local":     c.get("name_local", "") or _fmt_name(key),
            "category":       cat,
            "category_local": cat.replace("_", " ").title() if cat else "",
            "sell_price":     int(c.get("sell_price", 0)),
            "mean_price":     int(c.get("mean_price", 0)),
        }
    return {
        "station_name": capi_mkt.get("station_name", ""),
        "star_system":  capi_mkt.get("star_system", ""),
        "commodities":  commodities,
    }


def _read_cargo_json(journal_dir) -> dict | None:
    """Read Cargo.json and return cargo_items dict or None."""
    if journal_dir is None:
        return None
    path = Path(journal_dir) / "Cargo.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    result = {}
    for item in data.get("Inventory", []):
        key = _canonicalise_key(item.get("Name", ""))
        if not key:
            continue
        result[key] = {
            "count":      int(item.get("Count", 1)),
            "stolen":     bool(item.get("Stolen", False)),
            "name_local": item.get("Name_Localised") or _fmt_name(key),
        }
    return result


def _fmt_name(key: str) -> str:
    return key.replace("_", " ").title()



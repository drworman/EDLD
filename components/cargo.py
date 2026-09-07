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
        #: Vessel named by the most recent Cargo event — "Ship" or "SRV".
        self._cargo_vessel = "Ship"
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

        # The ship's hold and capacity are only reported by Loadout and by
        # Ship cargo events, and Elite opens a new journal on every launch.
        # Resume a save while already in an SRV and the new journal contains
        # neither — only SRV events — so both have to be recovered.
        #
        # The hold comes from what was last seen, because its true contents
        # are often the result of transfers rather than any single Cargo
        # event: the last Ship cargo event in the previous journal can say
        # empty while sixty tonnes were moved aboard afterwards.
        self._saved_cargo: dict = {}
        saved = self.storage.read_json("cargo.json") or {}
        if isinstance(saved, dict):
            self._saved_cargo = saved
            if not int(getattr(s, "cargo_capacity", 0) or 0):
                s.cargo_capacity = int(saved.get("capacity", 0) or 0)
            if not (getattr(s, "cargo_items", None) or {}):
                items = saved.get("items")
                if isinstance(items, dict):
                    s.cargo_items = items

        # Capacity still falls back to the journals, which is the one place it
        # is reported outright.
        self._bootstrap_from_journals()

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

    def _bootstrap_from_journals(self) -> None:
        """Seed ship capacity and hold from the most recent journals on disk.

        Reads newest-first and stops once both are known, so the usual cost is
        one partial file read.  Only Ship cargo is taken: an SRV manifest here
        would be the wrong hold entirely.
        """
        state = self.core.state
        need_cap   = not int(getattr(state, "cargo_capacity", 0) or 0)
        need_items = not (getattr(state, "cargo_items", None) or {})
        if not (need_cap or need_items):
            return

        try:
            jdir = Path(self.core.journal_dir)
            journals = sorted(jdir.glob("Journal*.log"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            return

        for path in journals[:8]:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            for line in reversed(lines):
                if '"event"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                name = ev.get("event")

                if need_cap and name == "Loadout":
                    cap = ev.get("CargoCapacity")
                    if cap is not None:
                        state.cargo_capacity = int(cap)
                        need_cap = False

                elif (need_items and name == "Cargo"
                        and str(ev.get("Vessel", "Ship")) == "Ship"):
                    inv = ev.get("Inventory")
                    if isinstance(inv, list):
                        state.cargo_items = {
                            k: v for k, v in
                            (_cargo_entry(i) for i in inv) if k
                        }
                        need_items = False

                if not (need_cap or need_items):
                    return

    def on_event(self, event, state, *args, **kwargs):
        """Dispatch, then persist the ship's hold if it changed.

        Wrapped rather than saved inside each branch because several return
        early, and a hold that is only sometimes persisted is worse than one
        that never is.
        """
        result = self._on_event(event, state, *args, **kwargs)
        try:
            snapshot = {
                "capacity": int(getattr(state, "cargo_capacity", 0) or 0),
                "items":    getattr(state, "cargo_items", None) or {},
            }
            if snapshot != self._saved_cargo:
                self._saved_cargo = json.loads(json.dumps(snapshot))
                self.storage.write_json(self._saved_cargo, "cargo.json")
        except Exception:
            pass
        return result

    def _on_event(self, event: dict, state) -> None:
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
                # Cargo also fires for the SRV, and those events name only a
                # count — never an Inventory.  Untangled, an SRV event with
                # Count > 0 sent the ship's hold off to re-read Cargo.json,
                # and an SRV Count:0 emptied the ship's hold outright.
                self._cargo_vessel = str(event.get("Vessel", "Ship"))
                if self._cargo_vessel == "SRV":
                    state.srv_cargo_count = max(int(event.get("Count", 0) or 0), 0)
                    # These events usually carry only a count, but the first
                    # after a load carries the manifest — keep it when it is
                    # there so the SRV's hold can be listed rather than just
                    # totalled.
                    inv = event.get("Inventory")
                    if isinstance(inv, list):
                        state.srv_cargo_items = {
                            k: v for k, v in
                            (_cargo_entry(i) for i in inv) if k
                        }
                    elif state.srv_cargo_count == 0:
                        state.srv_cargo_items = {}
                    else:
                        # Count-only: Cargo.json is the SRV's while the
                        # commander is aboard, so it carries the manifest the
                        # event omits.  Without this the listing froze at
                        # whatever the last event with an Inventory said.
                        srv_items = _read_cargo_json(core.journal_dir, "SRV")
                        if srv_items is not None:
                            state.srv_cargo_items = srv_items
                    if gq: gq.put(("cargo_update", None))
                    return

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
                # Refined ore lands in whatever the commander is flying.  An
                # SRV with a refinery fills its own hold and reports it through
                # count-only SRV Cargo events, so crediting the ship here
                # counts the ore twice: once on refine, and again when
                # CargoTransfer moves it across.
                #
                # vessel_mode alone is not enough to tell.  LoadGame resets it
                # to "ship", and resuming a save while already in an SRV emits
                # no LaunchSRV to correct it — so after a reload every refine
                # was credited to the ship again.  Which hold the game last
                # reported on is the reliable signal, since the SRV's own
                # Cargo events keep arriving while it is being filled.
                if self._in_srv(state):
                    return

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
                # Resuming does not empty the hold, and no Ship cargo event
                # necessarily follows: resume straight into an SRV and only
                # SRV events arrive, so clearing here lost the ship's cargo
                # for the rest of the session with nothing to restore it.
                items = _read_cargo_json(core.journal_dir, "Ship")
                if items is not None:
                    state.cargo_items = items
                if gq: gq.put(("plugin_refresh", "cargo"))


    def _in_srv(self, state) -> bool:
        """True when refined ore is going into the SRV rather than the ship.

        Two independent signals, because either can be stale on its own: the
        vessel the game last reported cargo for, and the commander's tracked
        vessel mode.
        """
        if getattr(self, "_cargo_vessel", "Ship") == "SRV":
            return True
        return str(getattr(state, "vessel_mode", "")).lower() == "srv"

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


def _cargo_entry(item: dict) -> tuple:
    """(key, record) for one Cargo inventory entry; ("", None) if unusable."""
    key = _canonicalise_key(item.get("Name", ""))
    if not key:
        return "", None
    return key, {
        "count":      int(item.get("Count", 1)),
        "stolen":     bool(item.get("Stolen", False)),
        "name_local": item.get("Name_Localised") or _fmt_name(key),
    }


def _read_cargo_json(journal_dir, vessel: str = "Ship") -> dict | None:
    """Read Cargo.json, but only when it describes ``vessel``.

    The file is rewritten for whichever hold last changed, so while the
    commander is in an SRV it holds the *SRV's* manifest.  Reading it blindly
    put SRV ore in the ship's hold.  Returns None when the file describes a
    different vessel, so the caller leaves its own hold alone.
    """
    if journal_dir is None:
        return None
    path = Path(journal_dir) / "Cargo.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if str(data.get("Vessel", "Ship")) != vessel:
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



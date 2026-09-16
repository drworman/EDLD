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
import os as _os
from pathlib import Path

from core.commodity_ledger import CommodityLedger, canonical_name
from core.plugin_loader import BasePlugin
from core.sell_table import (is_carrier, render_html, render_markdown,
                             sell_table)

_CANON_RE = __import__('re').compile(r'^\$(.+)_name;$')


def _canonicalise_key(raw: str) -> str:
    """Normalise a commodity key to plain lowercase.

    Both Market.json and some journal events use the $commodity_name;
    localisation wrapper. Strip it so keys always match.

    Delegates to core.commodity_ledger so the plugin and the commodity
    catalogue cannot disagree about what counts as the same commodity.
    """
    return canonical_name(raw)


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

        # Running catalogue of every commodity ever seen in Market.json, with
        # its galactic average re-recorded whenever that price drifts.  Unlike
        # cargo_mean_prices (a name→price map the manifest prices against) this
        # is a durable record carrying each commodity's identity as well, and
        # it accepts Fleet Carrier markets, which _read_market_json rejects.
        #
        # Set up defensively: a component that raises in on_load does not
        # load, and losing the whole Cargo window over a side record would be
        # a poor trade.  The failure is logged rather than swallowed, and
        # _update_commodity_ledger() is a no-op while _ledger is None.
        self._ledger = None
        self._ledger_mtime = 0.0
        self._ledger_lock = __import__("threading").Lock()
        try:
            # The ledger is a galactic average, not a commander's opinion of
            # one, so it lives in the shared data directory rather than under
            # commanders/<fid>/.  Any per-commander copies are consolidated on
            # the first start after the move; see core/data_migrate.py.
            from core.data_migrate import migrate_to_shared, shared_ledger_path
            from core.state import EDLD_DATA_DIR, shared_data_dir
            migrate_to_shared(EDLD_DATA_DIR, shared_data_dir(),
                              log=self._ledger_log)
            self._ledger = CommodityLedger(
                shared_ledger_path(),
                log=self._ledger_log,
            )
            loaded = self._ledger.load()
            if loaded:
                self._ledger_log(f"commodity ledger loaded — {loaded} commodities")
        except Exception as exc:
            self._ledger = None
            self._ledger_log(f"commodity ledger unavailable: {exc}")
        self._update_commodity_ledger()

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
                self._poll_cargo_json()
                if market_path.is_file():
                    mtime = market_path.stat().st_mtime
                    if mtime != last_mtime:
                        last_mtime = mtime
                        # Catalogue first: it takes every market, including
                        # the Fleet Carrier ones _read_market_json discards.
                        self._update_commodity_ledger()
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
        """Recover ship capacity and hold from the journals on disk.

        The hold cannot be taken from a single event.  Ship cargo events are
        often count-only — the newest one in a real capture read "71" with no
        inventory — and the true contents are frequently the product of
        transfers made afterwards.  Picking one event found an older, emptied
        snapshot and reported nothing aboard.

        So the recent journals are replayed forward instead: the last cargo
        event that carried an inventory is the baseline, and everything that
        moved cargo after it is applied.

        Sales and jettisons were once assumed to need no special handling, on
        the grounds that they emit their own cargo event which resets the
        baseline.  They do emit one, but in a real capture it carries no
        Inventory — selling 120 t of Tritium produced ``Count: 127`` and
        selling the remaining Low Temperature Diamonds produced ``Count: 0``,
        both without a manifest.  Neither reset anything, so both cargoes
        stayed in the hold across every restart, and a later transfer of
        Thortveitite was added on top of goods that had been sold hours
        earlier.  The panel read 326 t of a 1024 t hold when 79 t were aboard.

        Hence the market and jettison events are replayed too, and a Ship
        cargo event reading ``Count: 0`` empties the hold whether or not it
        names a manifest — that is the one count-only form whose contents are
        not in doubt.
        """
        state = self.core.state
        try:
            jdir = Path(self.core.journal_dir)
        # Ordered by filename, not mtime.  Elite's journal names are ISO
        # timestamps and sort chronologically on their own; mtimes do not
        # survive a file sync between machines, and in a real capture the four
        # newest by mtime were four months older than the newest by name.  The
        # replay then ran over ancient journals and reported their hold — or,
        # once an empty result was allowed to stand, no hold at all.
        # find_latest_journal() has always picked by name; this now agrees.
            journals = sorted(jdir.glob("Journal*.log"))[-4:]
        except Exception:
            return

        capacity = 0
        items: dict | None = None

        for path in journals:
            try:
                lines = path.read_text(encoding="utf-8",
                                       errors="replace").splitlines()
            except OSError:
                continue

            for line in lines:
                if '"event"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                name = ev.get("event")

                if name == "Loadout":
                    cap = ev.get("CargoCapacity")
                    if cap is not None:
                        capacity = int(cap)

                elif name == "Cargo" and str(ev.get("Vessel", "Ship")) == "Ship":
                    inv = ev.get("Inventory")
                    if isinstance(inv, list):
                        items = {k: v for k, v in
                                 (_cargo_entry(i) for i in inv) if k}
                    elif int(ev.get("Count", -1) or 0) == 0:
                        # Count-only, but zero: the hold is empty and there is
                        # nothing a manifest could add.  Every other count-only
                        # form is ignored, since the journal does not say what
                        # the count is made of.
                        items = {}

                elif name in ("MarketBuy", "MarketSell",
                              "EjectCargo") and items is not None:
                    key = _canonicalise_key(ev.get("Type", ""))
                    count = int(ev.get("Count", 0) or 0)
                    if key and count:
                        if name == "MarketBuy":
                            entry = items.setdefault(key, {
                                "count": 0, "stolen": False,
                                "name_local": ev.get("Type_Localised")
                                              or _fmt_name(key),
                            })
                            entry["count"] += count
                        else:
                            entry = items.get(key)
                            if entry:
                                entry["count"] -= count
                                if entry["count"] <= 0:
                                    items.pop(key, None)

                elif name == "CargoTransfer" and items is not None:
                    for tr in ev.get("Transfers") or []:
                        key = _canonicalise_key(tr.get("Type", ""))
                        count = int(tr.get("Count", 0) or 0)
                        if not key or not count:
                            continue
                        if str(tr.get("Direction", "")) == "toship":
                            entry = items.setdefault(key, {
                                "count": 0, "stolen": False,
                                "name_local": tr.get("Type_Localised")
                                              or _fmt_name(key),
                            })
                            entry["count"] += count
                        else:
                            entry = items.get(key)
                            if entry:
                                entry["count"] -= count
                                if entry["count"] <= 0:
                                    items.pop(key, None)

        # ── The SRV's hold ────────────────────────────────────────────────
        # The replay above rebuilds the ship's hold, and on_load applies
        # Cargo.json over it when that file describes the Ship.  Nothing did
        # either for the SRV: its hold is never listed in a journal event —
        # those carry a count and nothing else — so the only record of what is
        # in it is Cargo.json, and only while the commander is aboard.
        #
        # A mining session is left in the SRV.  On the next launch the SRV
        # manifest read empty with ore aboard and Cargo.json saying so, and
        # stayed empty until the next refined chunk landed.
        #
        # Applied strictly by vessel: reading this file without checking is
        # what once put SRV ore in the ship's hold.
        snap = _read_cargo_snapshot(jdir)
        if snap and snap["vessel"] == "SRV":
            state.srv_cargo_items = snap["items"]
            state.srv_cargo_count = snap["count"]

        # The journals win over the persisted copy: they are the record the
        # game itself wrote, and a stale save — or one written during a
        # session when the hold was not yet known — would otherwise stick.
        # Persistence remains the fallback for whatever the journals on disk
        # no longer reach.
        if capacity:
            state.cargo_capacity = capacity
        if items is not None:
            # Tested against None, not truthiness: an empty hold is a result
            # the replay reached, and letting it fall through to the persisted
            # copy is how a sold-out hold kept its old contents.
            state.cargo_items = items

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
                self._update_commodity_ledger()
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
                self._update_commodity_ledger()
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

    # ── Commodity catalogue ───────────────────────────────────────────────────

    @staticmethod
    def _ledger_log(msg: str) -> None:
        """Route ledger diagnostics to the debug log rather than dropping them.

        The catalogue is a side record — a failure here must not disturb the
        dashboard — but it must not vanish either, which is how the costly
        bugs in this codebase have always hidden.
        """
        try:
            from core import debug as _dbg
            _dbg.info(f"  [cargo] {msg}")
        except Exception:
            pass

    def _update_commodity_ledger(self) -> None:
        """Fold the current Market.json into the commodity catalogue.

        Guarded on Market.json's mtime, so the several callers that fire on
        one market write — the file watcher and the Market/Docked/Location
        events, which all describe the same write — do the work once.
        """
        ledger = getattr(self, "_ledger", None)
        if ledger is None:
            return
        try:
            with self._ledger_lock:
                path = Path(self.core.journal_dir) / "Market.json"
                if not path.is_file():
                    return
                mtime = path.stat().st_mtime
                if mtime == self._ledger_mtime:
                    return
                self._ledger_mtime = mtime
                items = _read_market_items(self.core.journal_dir)
                if not items:
                    return
                added, drifted = ledger.apply(items)
                carrier = _market_is_carrier(self.core.journal_dir)
            if added or drifted:
                self._ledger_log(
                    f"commodity ledger: {added} new, {drifted} price(s) drifted"
                )
            # The sell table ignores carriers outright: docking at one leaves
            # the files describing whatever was quoting before, which is what
            # the panel goes on showing too.
            if not carrier:
                self._write_sell_files()
        except Exception as exc:
            self._ledger_log(f"commodity ledger update failed: {exc}")

    def _poll_cargo_json(self) -> None:
        """Follow Cargo.json the way the market watcher follows Market.json.

        Cargo.json is a live file: the game rewrites it whenever the hold
        changes, for whichever vessel changed.  EDLD read it once at startup
        and thereafter only when a journal event said to — so the manifest was
        only ever as fresh as the journal.

        Journals lag.  They are buffered, they rotate, and a directory that is
        synced, rotated, or rewritten underneath the game leaves the file on
        disk frozen while the game carries on writing elsewhere.  In a real
        capture the newest journal stood still for five hours — last event a
        return to the main menu — while Cargo.json tracked 620 t of ore
        through the hold.  EDLD showed an empty ship the whole time, because
        nothing ever told it to look.

        Applied strictly by vessel, as everywhere else that touches this file:
        reading it without checking which hold it describes is what once put
        SRV ore in the ship's.
        """
        try:
            path = Path(self.core.journal_dir) / "Cargo.json"
            if not path.is_file():
                return
            mtime = path.stat().st_mtime
            if mtime == getattr(self, "_cargo_json_mtime", None):
                return
            self._cargo_json_mtime = mtime

            snap = _read_cargo_snapshot(self.core.journal_dir)
            if not snap:
                return
            state = self.core.state
            if snap["vessel"] == "SRV":
                if (snap["items"] != state.srv_cargo_items
                        or snap["count"] != state.srv_cargo_count):
                    state.srv_cargo_items = snap["items"]
                    state.srv_cargo_count = snap["count"]
                else:
                    return
            elif snap["vessel"] == "Ship":
                if snap["items"] == state.cargo_items:
                    return
                state.cargo_items = snap["items"]
            else:
                return

            gq = getattr(self.core, "gui_queue", None)
            if gq:
                gq.put(("cargo_update", None))
        except Exception as exc:
            self._ledger_log(f"Cargo.json poll failed: {exc}")

    def sell_table(self) -> dict:
        """The current sell table, for the TUI and GUI popups.

        Built on demand rather than cached, so the popup reflects the market
        underfoot at the moment it is opened even if no Market.json has been
        written since the last one.
        """
        ledger = getattr(self, "_ledger", None)
        rows = ledger.rows() if ledger is not None else {}
        return sell_table(self.core.state, rows)

    def _write_sell_files(self) -> None:
        """Write the sell table beside the catalogue, as Markdown and HTML."""
        ledger = getattr(self, "_ledger", None)
        if ledger is None:
            return
        table = sell_table(self.core.state, ledger.rows())
        for suffix, render in (("commodities.md",   render_markdown),
                               ("commodities.html", render_html)):
            path = self.storage.file_path(suffix)
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(render(table))
                _os.replace(tmp, path)
            except OSError as exc:
                self._ledger_log(f"sell table write failed at {path}: {exc}")
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    # ── overlay ───────────────────────────────────────────────────────────────
    #
    # The cargo component owns the hold, so it owns the overlay panel about the
    # hold.  Nothing in core/overlay_panels.py knows what a limpet is or when a
    # hold is worth showing; returning None below is this component's own
    # relevance test and is the whole of what `auto` mode consults.

    OVERLAY_PANELS = ("cargo",)

    def overlay_panel(self, panel_id: str, ctx):
        """How full am I — the one cargo number worth covering the game for.

        In an SRV both holds are reported. The SRV's own hold is what fills
        while mining and the mothership's is what the run is actually limited
        by, and a commander who can see only one of them is the one who drives
        back to a full ship.
        """
        if panel_id != "cargo":
            return None
        from core.overlay_panels import Panel

        s = self.core.state if hasattr(self, "core") else None
        s = s or getattr(self, "_state", None)
        if s is None:
            return None

        ship_used = sum(int(i.get("count", 0) or 0)
                        for i in (getattr(s, "cargo_items", {}) or {}).values())
        ship_cap = int(getattr(s, "cargo_capacity", 0) or 0)
        rows: list[tuple[str, str]] = []

        if bool(getattr(ctx, "in_srv", False)):
            srv_used = int(getattr(s, "srv_cargo_count", 0) or 0)
            # The journal never reports a surface vehicle's capacity, so it
            # comes from the same table the dashboard uses rather than from a
            # state field that does not exist — which is why this read "SRV 4"
            # while the dashboard three feet away read "4/72".
            from data.ships import srv_cargo_capacity
            srv_cap = int(srv_cargo_capacity(getattr(s, "srv_type", "")) or 0)
            rows.append(("SRV", f"{srv_used}/{srv_cap}" if srv_cap else str(srv_used)))
            if ship_cap:
                rows.append(("Ship", f"{ship_used}/{ship_cap}"))
        elif ship_cap:
            rows.append(("Hold", f"{ship_used}/{ship_cap}"))

        if not rows:
            # No capacity known and nothing aboard — a panel reading 0/0 is
            # noise, not information.
            return None
        return Panel(id="cargo", title="CARGO", rows=rows)



# ── Helpers ───────────────────────────────────────────────────────────────────

def _market_is_carrier(journal_dir) -> bool:
    """True when the market currently on disk belongs to a carrier.

    Read from the file rather than from cargo_market_info, which never
    records a carrier at all and so cannot tell "docked at a carrier" apart
    from "docked at the station this still describes".
    """
    if journal_dir is None:
        return False
    path = Path(journal_dir) / "Market.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    return is_carrier(data.get("StationType", ""))


def _read_market_items(journal_dir) -> list | None:
    """Read Market.json and return its raw ``Items`` list, or None.

    Deliberately unlike _read_market_json, which drops Fleet Carrier markets
    because their MeanPrice of 0 is useless for pricing the manifest.  The
    commodity catalogue wants the commodities regardless of what the market
    says they are worth, and handles the zeros itself.
    """
    if journal_dir is None:
        return None
    path = Path(journal_dir) / "Market.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    items = data.get("Items")
    return items if isinstance(items, list) else None


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

    # Carrier markets have no useful galactic average prices — skip them
    # entirely.  Matched on substring rather than the exact "FleetCarrier"
    # string so a squadron carrier is caught by the same rule; both are
    # player-run and mobile, and neither is a market worth pricing against.
    if is_carrier(data.get("StationType", "")):
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


def _read_cargo_snapshot(journal_dir) -> dict | None:
    """Cargo.json as it stands: which vessel it describes, and what is in it.

    Unlike _read_cargo_json this does not filter — the caller needs to know
    *which* hold the file is describing in order to apply it to the right one.
    """
    if journal_dir is None:
        return None
    try:
        with open(Path(journal_dir) / "Cargo.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    items = {}
    for item in data.get("Inventory") or []:
        key = _canonicalise_key(item.get("Name", ""))
        if not key:
            continue
        items[key] = {
            "count":      int(item.get("Count", 1)),
            "stolen":     bool(item.get("Stolen", False)),
            "name_local": item.get("Name_Localised") or _fmt_name(key),
        }
    return {
        "vessel":    str(data.get("Vessel", "Ship")),
        "count":     max(int(data.get("Count", 0) or 0), 0),
        "timestamp": str(data.get("timestamp", "")),
        "items":     items,
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



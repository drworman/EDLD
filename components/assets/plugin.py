"""
components/assets/plugin.py — Commander assets inventory.

Tracks four asset categories sourced from the journal:

  Wallet    — credit balance (Status.json, live)
  Ships     — current ship (Loadout event) + stored ships (StoredShips event)
  Modules   — modules stored away from any ship (StoredModules event)

Startup strategy
----------------
On load the plugin:
  1. Restores the last-known ship/module lists from plugin storage (data.json).
  2. Scans the last SCAN_JOURNALS journal files (newest first) for the most
     recent StoredShips and StoredModules events, overwriting storage if found.
  3. Falls back to empty lists if neither source has data.

This means the fleet list is always populated from the most recent journal data
found on disk, not just events seen in the current session.

Note: Odyssey ShipLocker inventory is in builtins/engineering/plugin.py.

State stored on MonitorState (added via hasattr guard in on_load):
    assets_balance         float   — current credit balance
    assets_current_ship    dict    — {_key, type, type_display, name, ident,
                                      system, value, hull}
    assets_stored_ships    list    — [{_key, type, type_display, name, ident,
                                        system, value, hot}]
    assets_stored_modules  list    — [{_key, name_internal, name_display,
                                        slot, system, mass, value, hot}]

CAPI note: when FDev CAPI is integrated, stored ships and modules will come
from /profile.  The state schema is forward-compatible.
"""


import json
import threading
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.state import normalise_ship_name
from data.modules import (
    MODULE_CLASS_MAP  as _CLASS_MAP,
    MODULE_TYPES      as _MODULE_TYPES,
    MODULE_MOUNT_MAP  as _MOUNT_MAP,
    MODULE_SIZE_MAP   as _SIZE_MAP,
    ARMOUR_GRADES     as _ARMOUR_GRADES_MAP,
    normalise_module_name,
)

# How many journal files to scan backwards for StoredShips/StoredModules
SCAN_JOURNALS = 10


# ── Legacy inline stubs replaced by data.modules imports above ───────────────
# The dict literals that used to live here have moved to data/modules.py.
# The _ARMOUR_GRADES name is kept below as a local alias for the inline
# per-event parsing block that uses it.
_ARMOUR_GRADES = _ARMOUR_GRADES_MAP


class AssetsPlugin(BasePlugin):
    PLUGIN_NAME        = "assets"
    PLUGIN_DISPLAY     = "Assets"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = "Commander assets — wallet, ships, and stored modules."

    SUBSCRIBED_EVENTS = [
        # Balance
        "Statistics",
        "Commander",
        # Ships
        "Loadout",
        "ModulesInfo",
        "StoredShips",
        "ShipyardSwap",
        # Modules (move between ship and storage)
        "StoredModules",
        "ModuleRetrieve",
        "ModuleStore",
        "ModuleBuy",
        "ModuleSell",
        "ModuleSwap",
        # Fleet carrier
        "CarrierStats",
        "CarrierJump",
        "CarrierFinance",
        "FCMaterials",
        "CarrierDecommission",   # carrier sold/decommissioned
        # Ships sold/transferred
        "ShipyardSell",
        # Session boundaries
        "LoadGame",
    ]


    def on_load(self, core) -> None:
        super().on_load(core)
        s = core.state
        if not hasattr(s, "assets_balance"):        s.assets_balance        = None
        if not hasattr(s, "assets_total_wealth"):   s.assets_total_wealth   = None
        if not hasattr(s, "assets_current_ship"):   s.assets_current_ship   = None
        if not hasattr(s, "assets_stored_ships"):   s.assets_stored_ships   = []
        if not hasattr(s, "assets_stored_modules"): s.assets_stored_modules = []
        if not hasattr(s, "assets_carrier"):        s.assets_carrier        = None
        if not hasattr(s, "assets_fc_materials"):   s.assets_fc_materials   = None
        # Bootstrap carrier materials from FCMaterials.json if present
        _bootstrap_fc_materials(s, core.journal_dir)
        # Bootstrap fitted module summary from ModulesInfo.json
        _bootstrap_modules_info(s, core.journal_dir)
        self._shiptype_cache: dict[str, str] = {}
        # Per-ShipID loadout cache — persisted to storage, same approach as Inara
        self._ship_loadout_cache: dict = {}

        # ── Step 1: build ShipType→localised name cache from Shipyard.json ────
        # Must happen before any parsing in the background scan thread.
        self._read_shipyard_json()

        # ── Step 2: restore last-known fleet from plugin storage ──────────────
        self._restore_from_storage()

        # ── Step 2b: load persisted CAPI profile (synchronous, no delay) ─────
        # CAPI writes capi_profile.json after every poll. Reading it here gives
        # immediate complete fleet data before the scan thread or CAPI re-poll.
        self._load_capi_profile_from_disk()

        # ── Step 3: scan recent journals for StoredShips/StoredModules ────────
        # Also scans Shipyard journal events to extend the name cache with
        # ships from any station the player has ever visited.
        threading.Thread(target=self._scan_and_refresh, daemon=True,
                         name="assets-scan").start()

        # ── Step 4: read Status.json for initial balance ──────────────────────
        self._read_status_json()

    def _read_shipyard_json(self) -> None:
        """Prime the ShipType→localised name cache from Shipyard.json.

        Shipyard.json is written by the game whenever the player accesses a
        shipyard.  It contains ``ShipType`` and ``ShipType_Localised`` for
        every ship in the price list, giving us authoritative display names
        for newer ships (e.g. ``smallcombat01_nx`` → ``Kestrel Mk II``) that
        may not yet be in our static map.  We cache them in
        ``self._shiptype_cache`` so ``_parse_stored_ships`` and the Loadout
        handler can look them up.
        """
        try:
            path = Path(self.core.journal_dir) / "Shipyard.json"
            if not path.exists():
                return
            data = path.read_text(encoding="utf-8").strip()
            # Shipyard.json is a single multi-line JSON object.
            # Try whole-file parse first; fall back to line-by-line for
            # any journal-format variants (one JSON object per line).
            import json as _json
            def _index_entries(obj):
                for entry in obj.get("PriceList", []):
                    st  = entry.get("ShipType", "").lower()
                    loc = entry.get("ShipType_Localised", "")
                    if st and loc:
                        self._shiptype_cache[st] = loc
            try:
                _index_entries(_json.loads(data))
            except ValueError:
                for raw_line in data.splitlines():
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        _index_entries(_json.loads(raw_line))
                    except ValueError:
                        pass
        except Exception:
            pass

    def _localised_ship_name(self, ship_type: str) -> str:
        """Return the best display name for a ShipType internal string."""
        # 1. Shipyard.json cache (authoritative, covers newest ships)
        key = ship_type.lower()
        if key in self._shiptype_cache:
            return self._shiptype_cache[key]
        # 2. Static map
        from core.state import normalise_ship_name
        name = normalise_ship_name(ship_type)
        if name:
            return name
        # 3. Fallback: clean up underscores + title-case
        return ship_type.replace("_", " ").strip().title()

    def _load_capi_profile_from_disk(self) -> None:
        """Read persisted CAPI data from disk and populate fleet + carrier state.

        CAPI writes capi_profile.json and capi_fleetcarrier.json after every poll.
        Reading them here gives the complete fleet with loadouts on startup with
        zero delay — no journal scanning, no 10-second CAPI re-poll wait.
        Falls back gracefully when files don't exist (CAPI disabled / first run).
        """
        # ── Profile → current ship + stored fleet ─────────────────────────
        try:
            profile_data = self.storage.read_sibling_json("core", "capi_profile.json")
            if profile_data:
                state = self.core.state
                ship_raw  = profile_data.get("ship")  or {}
                ships_raw = profile_data.get("ships") or {}

                if ship_raw:
                    ship_type   = ship_raw.get("name", "")
                    ship_type_l = (ship_raw.get("nameLocalized")
                                   or normalise_ship_name(ship_type)
                                   or ship_type)
                    health_obj  = ship_raw.get("health", {})
                    value_obj   = ship_raw.get("value",  {})
                    hf = float(health_obj.get("hull", 1000000))
                    hull_pct = round(hf / 10000) if hf > 1.0 else round(hf * 100)
                    state.assets_current_ship = {
                        "_key":         "current",
                        "current":      True,
                        "ship_id":      ship_raw.get("id"),
                        "type":         ship_type,
                        "type_display": ship_type_l,
                        "name":         ship_raw.get("shipName",  ""),
                        "ident":        ship_raw.get("shipIdent", ""),
                        "system":       (ship_raw.get("starsystem") or {}).get("name", "—"),
                        "value":        value_obj.get("hull", 0),
                        "hull":         hull_pct,
                        "rebuy":        value_obj.get("free", 0),
                        "loadout":      _build_loadout_from_capi_modules(
                                            ship_raw.get("modules") or {}),
                        "capi":         True,
                    }

                current_id = (state.assets_current_ship or {}).get("ship_id")
                stored = []
                for sid_str, sv in ships_raw.items():
                    try:    sid = int(sid_str)
                    except: sid = sid_str
                    if sid == current_id:
                        continue
                    val  = sv.get("value") or {}
                    svh  = sv.get("health") or {}
                    svhf = float(svh.get("hull", 1000000))
                    loc  = sv.get("starsystem") or {}
                    stored.append({
                        "_key":         f"ship_{sid}",
                        "ship_id":      sid,
                        "current":      False,
                        "type":         sv.get("name", ""),
                        "type_display": (sv.get("nameLocalized")
                                             or normalise_ship_name(sv.get("name", ""))
                                             or sv.get("name", "")),
                        "name":         sv.get("shipName",  ""),
                        "ident":        sv.get("shipIdent", ""),
                        "system":       loc.get("name", "—") if isinstance(loc, dict) else "—",
                        "value":        val.get("hull", 0),
                        "rebuy":        val.get("free", 0),
                        "hull":         round(svhf / 10000) if svhf > 1.0 else round(svhf * 100),
                        "hot":          False,
                        "loadout":      _build_loadout_from_capi_modules(
                                            sv.get("modules") or {}),
                        "capi":         True,
                    })
                if stored:
                    state.assets_stored_ships = stored

                # Commander balance + squadron from CAPI profile
                cmdr = profile_data.get("commander") or {}
                bal = cmdr.get("credits")
                if bal is not None:
                    state.assets_balance = float(bal)
                _cmdr_sq = (profile_data.get("commander") or {}).get("squadron") or {}
                sq = profile_data.get("squadron") or _cmdr_sq
                if sq:
                    state.pilot_squadron_name = sq.get("name", "")
                    state.pilot_squadron_tag = (
                        sq.get("tag") or sq.get("Tag") or sq.get("TAG") or
                        sq.get("shortName") or sq.get("ShortName") or
                        sq.get("shortname") or sq.get("short_name") or ""
                    )
                    state.pilot_squadron_rank = (
                        sq.get("rank") or sq.get("Rank") or
                        sq.get("rankName") or sq.get("currentRankName") or ""
                    )

                else:
                    state.pilot_squadron_name = ""
                    state.pilot_squadron_tag  = ""
                    state.pilot_squadron_rank = ""
                gq = self.core.gui_queue if self.core else None
                if gq:
                    try: gq.put_nowait(("plugin_refresh", "commander"))
                    except Exception: pass

                # NOTE: CAPI launchBays reports wrong fighter type — not used.
        except Exception:
            pass

        # ── Fleet carrier ─────────────────────────────────────────────────
        try:
            fc_data = self.storage.read_sibling_json("core", "capi_fleetcarrier.json")
            if fc_data:
                from components.assets.plugin import AssetsPlugin as _AP
                # Reuse the existing carrier parser
                carrier = self._parse_carrier_stats_from_capi(fc_data)
                if carrier:
                    self.core.state.assets_carrier = carrier
        except Exception:
            pass

    def _parse_carrier_stats_from_capi(self, fc: dict) -> dict | None:
        """Parse capi_fleetcarrier.json into the assets_carrier state dict."""
        try:
            name_obj  = fc.get("name") or {}
            callsign  = name_obj.get("callsign", "")
            vanity_hex = name_obj.get("filteredVanityName", "")
            # vanityName is hex-encoded ASCII
            try:
                vanity = bytes.fromhex(vanity_hex).decode("ascii").strip()
            except Exception:
                vanity = ""
            cap   = fc.get("capacity") or {}
            fin   = fc.get("finance")  or {}
            mkt   = fc.get("market")   or {}
            svcs  = mkt.get("services") or {}
            space = cap
            services: dict = {}
            for svc, status in svcs.items():
                services[svc] = status
            return {
                "callsign":     callsign,
                "name":         vanity,
                "system":       fc.get("currentStarSystem", "—"),
                "state":        fc.get("state", ""),
                "theme":        "",
                "balance":      int(fin.get("bankBalance", 0)),
                "fuel":         int(fc.get("fuel", 0)),
                "debt":         0,
                "cargo_used":   int(cap.get("cargoNotForSale", 0)),
                "ship_packs":   int(cap.get("shipPacks", 0)),
                "module_packs": int(cap.get("modulePacks", 0)),
                "micro_total":  int(cap.get("microresourceCapacityTotal", 0)),
                "micro_free":   int(cap.get("microresourceCapacityFree", 0)),
                "micro_used":   int(cap.get("microresourceCapacityUsed", 0)),
                "services":     services,
                "carrier_type": "FleetCarrier",  # CAPI does not expose type; assume FC
            }
        except Exception:
            return None

    def _restore_from_storage(self) -> None:
        """Load last-persisted module list from plugin storage.

        Ships are always rebuilt from journal scan on startup — we do not
        restore the ship list from storage because previous sessions may have
        persisted CAPI-sourced data that includes non-owned ships.
        StoredModules is safe to restore since it only changes when the player
        opens outfitting.
        """
        try:
            saved = self.storage.read_json("data.json") or {}
            s = self.core.state
            modules = saved.get("stored_modules")
            if isinstance(modules, list):
                s.assets_stored_modules = modules
            lc = saved.get("ship_loadout_cache")
            if isinstance(lc, dict):
                self._ship_loadout_cache = {
                    int(k): v for k, v in lc.items()
                    if str(k).lstrip("-").isdigit()
                }
        except Exception:
            pass

    def _scan_and_refresh(self) -> None:
        """Rebuild fleet state on startup.

        Roster authority
        ----------------
        CAPI /profile ships{} is the authoritative owned-ship list — Frontier
        maintains it server-side and it only includes ships you actually own.
        When CAPI has polled, we build the roster exclusively from those ShipIDs.

        When CAPI has NOT polled (disabled or not yet authenticated), we fall
        back to journal data: the most recent StoredShips event for stored ships
        plus the most recent Loadout for the current ship.  We do NOT scan
        multiple journal files for Loadout events, because that picks up ships
        you've since sold.

        Additional journal passes collect StoredModules and CarrierStats.
        """
        try:
            journal_dir = Path(self.core.journal_dir)
            journals    = sorted(journal_dir.glob("Journal*.log"), reverse=True)
            state       = self.core.state

            # ── Phase 0a: load persisted CAPI fleet ─────────────────────
            # CAPI writes capi/fleet.json after every profile poll.
            # Loading it here gives immediate fleet + full loadouts on startup.
            try:
                # If _load_capi_profile_from_disk already ran, fleet is populated.
                # Skip — nothing to do here.
                pass
            except Exception:
                pass

            # ── Phase 0b: build Shipyard/Shipyard-event name cache ───────
            for jpath in journals[:SCAN_JOURNALS]:
                try:
                    lines = jpath.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in lines:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("event") == "Shipyard":
                        for entry in ev.get("PriceList", []):
                            st  = entry.get("ShipType", "").lower()
                            loc = entry.get("ShipType_Localised", "")
                            if st and loc:
                                self._shiptype_cache[st] = loc

            # ── Phase 1: determine authoritative ShipID set ───────────────────
            # CAPI /profile ships{} is the definitive owned-fleet source.
            # Fall back to the most recent StoredShips journal event when CAPI
            # hasn't polled (disabled / unauthenticated).
            # capi_raw is empty at startup (CAPI polls 10s later).
            # Read capi_profile.json directly so we have the validated
            # roster immediately — same file _load_capi_profile_from_disk used.
            capi_raw = getattr(state, "capi_raw", {})
            capi_ships_raw = (capi_raw.get("profile") or {}).get("ships") or {}
            _capi_profile_data: dict = {}
            if not capi_ships_raw:
                try:
                    _capi_profile_data = self.storage.read_sibling_json("core", "capi_profile.json")
                    capi_ships_raw = (_capi_profile_data.get("ships") or {})
                except Exception:
                    pass
            capi_owned_ids: set = set()
            if capi_ships_raw:
                for sid_str in capi_ships_raw:
                    try:    capi_owned_ids.add(int(sid_str))
                    except: capi_owned_ids.add(sid_str)

            # Include the ship that was CURRENT at the time of the last CAPI poll.
            # It lives in profile["ship"]["id"], not in ships{}.  After the player
            # swaps ships before the next poll, the formerly-current ship moves to
            # stored but CAPI still shows it as current — so it's absent from ships{}
            # and would be dropped from the roster.
            if not _capi_profile_data:
                try:
                    _capi_profile_data = self.storage.read_sibling_json("core", "capi_profile.json")
                except Exception:
                    pass
            _capi_current_sid = (_capi_profile_data.get("ship") or {}).get("id")
            if _capi_current_sid is not None:
                try:    capi_owned_ids.add(int(_capi_current_sid))
                except: capi_owned_ids.add(_capi_current_sid)

            # Supplement with ships from the most recent StoredShips journal event.
            # CAPI may lag by minutes to hours; StoredShips is written in real time.
            if capi_owned_ids:
                for _jpath in journals[:SCAN_JOURNALS]:
                    _found_ss = False
                    try:
                        for _line in reversed(_jpath.read_text(encoding="utf-8").splitlines()):
                            try:
                                _sev = json.loads(_line)
                            except ValueError:
                                continue
                            if _sev.get("event") == "StoredShips":
                                for _sect in ("ShipsHere", "ShipsRemote"):
                                    for _s in _sev.get(_sect, []):
                                        _sid = _s.get("ShipID")
                                        if _sid is not None:
                                            try:    capi_owned_ids.add(int(_sid))
                                            except: capi_owned_ids.add(_sid)
                                _found_ss = True
                                break
                    except OSError:
                        continue
                    if _found_ss:
                        break

            # ── Phase 2: most recent Loadout → current ship identity ──────────
            current_ship: dict | None = None
            current_sid = None
            for jpath in journals[:SCAN_JOURNALS]:
                if current_ship is not None:
                    break
                try:
                    lines = jpath.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in reversed(lines):
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("event") == "Loadout":
                        sid = ev.get("ShipID")
                        ship_type   = ev.get("Ship", "")
                        ship_type_l = (ev.get("Ship_Localised")
                                       or self._localised_ship_name(ship_type))
                        if ship_type_l and ship_type:
                            self._shiptype_cache[ship_type.lower()] = ship_type_l
                        current_sid = sid
                        # Parse loadout from this event for immediate use
                        _p2_lo = []
                        for _m in (ev.get("Modules") or []):
                            _sl = _m.get("Slot", ""); _it = _m.get("Item", "")
                            if not _sl or not _it: continue
                            _er = _m.get("Engineering") or {}
                            _eng = {}
                            if _er.get("BlueprintName"):
                                _eng = {"BlueprintName": _er["BlueprintName"],
                                        "Level": int(_er.get("Level",0)),
                                        "Quality": float(_er.get("Quality",0)),
                                        "ExperimentalEffect": _er.get("ExperimentalEffect",""),
                                        "Modifiers": _er.get("Modifiers") or []}
                            _p2_lo.append({"slot": _sl, "name_internal": _it,
                                            "name_display": normalise_module_name(_it),
                                            "on": bool(_m.get("On",True)),
                                            "priority": int(_m.get("Priority",0)),
                                            "value": int(_m.get("Value",0)),
                                            "engineering": _eng})
                        current_ship = {
                            "_key":         "current",
                            "ship_id":      sid,
                            "current":      True,
                            "type":         ship_type,
                            "type_display": ship_type_l,
                            "name":         ev.get("ShipName", ""),
                            "ident":        ev.get("ShipIdent", ""),
                            "system":       getattr(state, "pilot_system", None) or "—",
                            "value":        ev.get("HullValue", 0),
                            "rebuy":        ev.get("Rebuy", 0),
                            "hull":         100,
                            "hot":          False,
                            "loadout":      _p2_lo,
                        }
                        break

            if current_ship is not None:
                state.assets_current_ship = current_ship

            # ── Phase 2b: populate loadout cache from journal history ─────────
            # Scan all Loadout events (newest-first, one per ShipID) and cache
            # the fitted modules. Skips ships already in cache.
            # This is the same data Inara accumulates over time.
            # Scan ALL journals (uncapped) — ships not boarded recently need
            # their Loadout event found wherever it appears in history.
            # Ships already in the persistent cache are skipped immediately.
            # Only look for loadouts for ships we know we currently own.
            # capi_owned_ids is the validated roster from Frontier's servers.
            # If CAPI is unavailable, scan for any ShipID (fallback behaviour).
            _target_sids = (capi_owned_ids | ({int(current_sid)} if current_sid else set()))\
                           if capi_owned_ids else None
            # seen_sids: already have loadout for these — skip
            seen_sids: set = set(self._ship_loadout_cache.keys())
            for jpath in journals:
                try:
                    lines = jpath.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in reversed(lines):
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("event") != "Loadout":
                        continue
                    ev_sid = ev.get("ShipID")
                    if ev_sid is None:
                        continue
                    ev_sid_i = int(ev_sid)
                    if ev_sid_i in seen_sids:
                        continue  # already have loadout for this ship
                    if _target_sids is not None and ev_sid_i not in _target_sids:
                        continue  # not in our validated roster — skip
                    seen_sids.add(ev_sid_i)
                    _mods = ev.get("Modules") or []
                    _lo = []
                    for _m in _mods:
                        _slot = _m.get("Slot", "")
                        _item = _m.get("Item", "")
                        if not _slot or not _item:
                            continue
                        _er = _m.get("Engineering") or {}
                        _eng = {}
                        if _er.get("BlueprintName"):
                            _eng = {
                                "BlueprintName":      _er["BlueprintName"],
                                "Level":              int(_er.get("Level", 0)),
                                "Quality":            float(_er.get("Quality", 0)),
                                "ExperimentalEffect": _er.get("ExperimentalEffect", ""),
                                "Modifiers":          _er.get("Modifiers") or [],
                            }
                        _lo.append({
                            "slot":          _slot,
                            "name_internal": _item,
                            "name_display":  normalise_module_name(_item),
                            "on":            bool(_m.get("On", True)),
                            "priority":      int(_m.get("Priority", 0)),
                            "value":         int(_m.get("Value", 0)),
                            "engineering":   _eng,
                        })
                    if _lo:
                        self._ship_loadout_cache[ev_sid_i] = _lo
            # Prune cache of sold/disposed ships (CAPI is authoritative roster)
            if capi_owned_ids:
                # Add current ship to the valid set
                valid_ids = capi_owned_ids | ({int(current_sid)} if current_sid else set())
                orphans = [k for k in self._ship_loadout_cache if k not in valid_ids]
                for k in orphans:
                    del self._ship_loadout_cache[k]
            else:
                # CAPI unavailable: prune against the most recent StoredShips event.
                # Prevents sold ships from accumulating in the persistent cache.
                stored_ids: set = set()
                if current_sid is not None:
                    stored_ids.add(int(current_sid) if isinstance(current_sid, int)
                                   else current_sid)
                for jpath in journals[:SCAN_JOURNALS]:
                    found = False
                    try:
                        for line in reversed(jpath.read_text(encoding="utf-8").splitlines()):
                            try:
                                ev = json.loads(line)
                            except ValueError:
                                continue
                            if ev.get("event") == "StoredShips":
                                for section in ("ShipsHere", "ShipsRemote"):
                                    for s in ev.get(section, []):
                                        sid = s.get("ShipID")
                                        if sid is not None:
                                            try:    stored_ids.add(int(sid))
                                            except: stored_ids.add(sid)
                                found = True
                                break
                    except OSError:
                        continue
                    if found:
                        break
                if stored_ids:
                    orphans = [k for k in self._ship_loadout_cache
                               if k not in stored_ids]
                    for k in orphans:
                        del self._ship_loadout_cache[k]
            # Persist any newly-discovered loadouts (and pruning)
            self._save_to_storage()

            # ── Phase 3: build stored fleet ───────────────────────────────────
            # Source A: CAPI ships{} — authoritative set, enriched by journal.
            # Source B (fallback): most recent StoredShips journal event.
            loadout_by_id: dict = {}

            if capi_owned_ids:
                # Build complete ships from CAPI — includes fitted loadout.
                for sid_str, sv in capi_ships_raw.items():
                    try:    sid = int(sid_str)
                    except: sid = sid_str
                    if sid == current_sid:
                        continue
                    ship_type = sv.get("name", "")
                    disp = sv.get("nameLocalized") or self._localised_ship_name(ship_type)
                    loc  = sv.get("starsystem") or {}
                    sys_n = loc.get("name", "—") if isinstance(loc, dict) else "—"
                    val  = sv.get("value") or {}
                    sv_h = sv.get("health") or {}
                    sv_hr = float(sv_h.get("hull", 1000000))
                    hull_pct = round(sv_hr / 10000) if sv_hr > 1.0 else round(sv_hr * 100)
                    sv_loadout = []
                    for sl, sm in (sv.get("modules") or {}).items():
                        mi = sm.get("name", "")
                        disp_m = sm.get("nameLocalized") or normalise_module_name(mi)
                        eng_raw = sm.get("engineering") or {}
                        eng = {}
                        if eng_raw.get("BlueprintName"):
                            eng = {
                                "BlueprintName": eng_raw["BlueprintName"],
                                "Level":         int(eng_raw.get("Level", 0)),
                                "ExperimentalEffect": eng_raw.get("ExperimentalEffect", ""),
                                "Modifiers":     eng_raw.get("Modifiers") or [],
                            }
                        sv_loadout.append({
                            "slot": sl, "name_internal": mi, "name_display": disp_m,
                            "on": bool(sm.get("on", True)),
                            "priority": int(sm.get("priority", 0)),
                            "value": int(sm.get("value", 0)),
                            "engineering": eng,
                        })
                    loadout_by_id[sid] = {
                        "_key":         f"ship_{sid}",
                        "ship_id":      sid,
                        "current":      False,
                        "type":         ship_type,
                        "type_display": disp,
                        "name":         sv.get("shipName",  ""),
                        "ident":        sv.get("shipIdent", ""),
                        "system":       sys_n,
                        "value":        val.get("hull", 0),
                        "rebuy":        val.get("free", 0),
                        "hull":         hull_pct,
                        "hot":          False,
                        "loadout":      sv_loadout,
                    }

                # Ships in capi_owned_ids that have no entry in capi_ships_raw
                # (e.g. the ship that was current at CAPI poll time and has since
                # been swapped out, or ships added from StoredShips journal scan)
                # need to be built from journal StoredShips data.
                _jonly = capi_owned_ids - {int(k) for k in capi_ships_raw} - (
                    {int(current_sid)} if current_sid is not None else set()
                )
                if _jonly:
                    for _jp2 in journals[:SCAN_JOURNALS]:
                        if not _jonly:
                            break
                        try:
                            _jp2_lines = _jp2.read_text(encoding="utf-8").splitlines()
                        except OSError:
                            continue
                        for _line2 in reversed(_jp2_lines):
                            if not _jonly:
                                break
                            try:
                                _ev2 = json.loads(_line2)
                            except ValueError:
                                continue
                            if _ev2.get("event") == "StoredShips":
                                for _sect2 in ("ShipsHere", "ShipsRemote"):
                                    for _s2 in _ev2.get(_sect2, []):
                                        _sid2 = _s2.get("ShipID")
                                        if _sid2 is None:
                                            continue
                                        try:    _sid2_i = int(_sid2)
                                        except: _sid2_i = _sid2
                                        if _sid2_i in _jonly:
                                            _st2 = _s2.get("ShipType", "")
                                            _disp2 = (_s2.get("ShipType_Localised")
                                                      or self._localised_ship_name(_st2))
                                            loadout_by_id[_sid2_i] = {
                                                "_key":         f"ship_{_sid2_i}",
                                                "ship_id":      _sid2_i,
                                                "current":      False,
                                                "type":         _st2,
                                                "type_display": _disp2,
                                                "name":         _s2.get("Name", ""),
                                                "ident":        _s2.get("Ident", ""),
                                                "system":       _s2.get("StarSystem", "—"),
                                                "value":        _s2.get("Value", 0),
                                                "hot":          _s2.get("Hot", False),
                                                "loadout":      self._ship_loadout_cache.get(
                                                                    _sid2_i, []),
                                            }
                                            _jonly.discard(_sid2_i)
                # Fallback: most recent StoredShips event only
                for jpath in journals[:SCAN_JOURNALS]:
                    if loadout_by_id:
                        break
                    try:
                        lines = jpath.read_text(encoding="utf-8").splitlines()
                    except OSError:
                        continue
                    for line in reversed(lines):
                        try:
                            ev = json.loads(line)
                        except ValueError:
                            continue
                        if ev.get("event") == "StoredShips":
                            for section in ("ShipsHere", "ShipsRemote"):
                                for s in ev.get(section, []):
                                    sid = s.get("ShipID")
                                    if sid is None or sid == current_sid:
                                        continue
                                    ship_type = s.get("ShipType", "")
                                    disp = (s.get("ShipType_Localised")
                                            or self._localised_ship_name(ship_type))
                                    loadout_by_id[sid] = {
                                        "_key":         f"ship_{sid}",
                                        "ship_id":      sid,
                                        "current":      False,
                                        "type":         ship_type,
                                        "type_display": disp,
                                        "name":         s.get("Name", ""),
                                        "ident":        s.get("Ident", ""),
                                        "system":       s.get("StarSystem", "—"),
                                        "value":        s.get("Value", 0),
                                        "hot":          s.get("Hot", False),
                                        "loadout":      self._ship_loadout_cache.get(int(sid) if isinstance(sid, int) else sid, []),
                                    }
                            break   # stop after first StoredShips event

            # ── Phase 4: enrich stored ships from journal StoredShips ─────────
            # (Adds location/hot when CAPI was the roster source)
            for jpath in journals[:SCAN_JOURNALS]:
                found_stored = False
                try:
                    lines = jpath.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in reversed(lines):
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    name = ev.get("event")
                    if name == "StoredShips":
                        for section in ("ShipsHere", "ShipsRemote"):
                            for s in ev.get(section, []):
                                sid = s.get("ShipID")
                                if sid in loadout_by_id:
                                    if loadout_by_id[sid]["system"] == "—":
                                        loadout_by_id[sid]["system"] = s.get("StarSystem", "—")
                                    loadout_by_id[sid]["hot"] = s.get("Hot", False)
                                    if not loadout_by_id[sid].get("ident"):
                                        loadout_by_id[sid]["ident"] = s.get("Ident", "")
                                    # Apply cached loadout if not already present
                                    if not loadout_by_id[sid].get("loadout"):
                                        _cached = self._ship_loadout_cache.get(
                                            int(sid) if isinstance(sid, int) else sid, [])
                                        if _cached:
                                            loadout_by_id[sid]["loadout"] = _cached
                        found_stored = True
                        break
                if found_stored:
                    break

            # ── Phase 5: StoredModules + CarrierStats ─────────────────────────
            # StoredModules only fires when the player opens outfitting —
            # this could be in any journal, not just recent ones.
            found_modules = False
            found_carrier = False
            for jpath in journals:  # scan all — StoredModules may be old
                if found_modules and found_carrier:
                    break
                try:
                    lines = jpath.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in reversed(lines):
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    name = ev.get("event")
                    if not found_modules and name == "StoredModules":
                        state.assets_stored_modules = self._parse_stored_modules(ev)
                        found_modules = True
                    elif not found_carrier and name == "CarrierStats":
                        state.assets_carrier = self._parse_carrier_stats(ev)
                        found_carrier = True

            # Commit: prefer the CAPI-loaded roster (set by _load_capi_profile_from_disk).
            # If it exists, apply loadout cache + journal location/hot to those ships.
            # Only replace roster entirely if it is still empty.
            existing = state.assets_stored_ships
            if existing:
                # Patch existing CAPI-sourced ships with loadout + journal data
                for ship in existing:
                    sid = ship.get("ship_id")
                    if sid is None:
                        continue
                    sid_i = int(sid) if isinstance(sid, int) else sid
                    # Sanitise type_display — if it looks like an unprocessed
                    # internal name (contains "_" with no spaces, e.g. "type9_military")
                    # refresh it through the localisation pipeline.  This corrects
                    # any stale values written by an older version of the code.
                    td = ship.get("type_display", "")
                    # Re-localise if type_display looks like an unprocessed internal name.
                    # Catches two patterns CAPI can produce:
                    #   "Type9_Military"  — has underscore, no spaces (existing check)
                    #   "Smallnx01"       — no underscore, no spaces, mixed-case (new)
                    # We attempt re-localisation whenever there are no spaces AND the
                    # display value differs from what _localised_ship_name would produce.
                    if td and " " not in td.strip():
                        refreshed = self._localised_ship_name(ship.get("type", ""))
                        if refreshed and refreshed != td:
                            ship["type_display"] = refreshed
                    # Apply loadout from cache if ship has none
                    if not ship.get("loadout"):
                        ship["loadout"] = self._ship_loadout_cache.get(sid_i, [])
                    # Apply location/hot from journal scan if available
                    journal_ship = loadout_by_id.get(sid_i)
                    if journal_ship:
                        if ship.get("system", "—") == "—" and journal_ship.get("system", "—") != "—":
                            ship["system"] = journal_ship["system"]
                        if journal_ship.get("hot"):
                            ship["hot"] = True
                        if not ship.get("ident") and journal_ship.get("ident"):
                            ship["ident"] = journal_ship["ident"]
            else:
                # No CAPI data — use journal-sourced roster
                state.assets_stored_ships = list(loadout_by_id.values())

            # Sanitise current ship type_display with the same logic applied to
            # stored ships above.  Catches cases where _load_capi_profile_from_disk
            # or a stale capi_profile.json left a raw internal name (e.g.
            # "Type9_Military") in assets_current_ship before _build_roster ran.
            _cur = state.assets_current_ship
            if _cur:
                _td = _cur.get("type_display", "")
                if _td and " " not in _td.strip():
                    _refreshed = self._localised_ship_name(_cur.get("type", ""))
                    if _refreshed and _refreshed != _td:
                        _cur["type_display"] = _refreshed

            self._save_to_storage()
        except Exception:
            pass

        gq = self.core.gui_queue if self.core else None
        if gq:
            gq.put(("plugin_refresh", "assets"))

    def _parse_stored_ships(self, event: dict) -> list:
        ships = []
        for section in ("ShipsHere", "ShipsRemote"):
            for s in event.get(section, []):
                ship_type = s.get("ShipType", "")
                disp = (s.get("ShipType_Localised")
                        or self._localised_ship_name(ship_type))
                name   = s.get("Name", "")
                ident  = s.get("Ident", "")
                key    = f"{s.get('ShipID', '')}_{ship_type}"
                ships.append({
                    "_key":         key,
                    "ship_id":      s.get("ShipID"),    # used to dedupe vs current ship
                    "current":      False,
                    "type":         ship_type,
                    "type_display": disp,
                    "name":         name,
                    "ident":        ident,
                    "system":       s.get("StarSystem", "—"),
                    "value":        s.get("Value", 0),
                    "hot":          s.get("Hot", False),
                })
        return ships

    def _parse_stored_modules(self, event: dict) -> list:
        mods = []
        for i, m in enumerate(event.get("Items", [])):
            internal = m.get("Name", "")
            # normalise_module_name produces "8A Shield Generator" (with size/class).
            # Name_Localised only gives "Shield Generator" (no size/class).
            # Prefer the normalised name; fall back to localised if normaliser
            # produces a raw title-case string (unrecognised module type).
            _norm = normalise_module_name(internal)
            _loc  = m.get("Name_Localised", "")
            # If normaliser produced a recognised name (contains digit or known word),
            # use it. Otherwise fall back to localised name.
            import re as _re2
            _has_class = bool(_re2.match(r"^\d+[A-E] ", _norm))
            disp = _norm if _has_class else (_loc or _norm)
            system = m.get("StarSystem", "—")
            key    = f"{i}_{internal}_{system}"
            # StoredModules journal uses flat EngineerModifications/Level/Quality fields
            # (NOT a nested "Engineering" dict like Loadout uses)
            eng = {}
            bp = m.get("EngineerModifications", "")
            if bp:
                eng["BlueprintName"] = bp
                lv = m.get("Level")
                if lv is not None: eng["Level"] = int(lv)
                qu = m.get("Quality")
                if qu is not None: eng["Quality"] = round(float(qu), 2)
            mods.append({
                "_key":         key,
                "name_internal":internal,
                "name_display": disp,
                "slot":         m.get("Slot", "") or internal,
                "storage_slot": m.get("StorageSlot", 0),
                "system":       system,
                "mass":         m.get("Mass", 0.0),
                "value":        m.get("BuyPrice", m.get("Value", 0)),
                "hot":          m.get("Hot", False),
                "engineering":  eng,
            })
        return mods

    def _parse_carrier_stats(self, event: dict) -> dict:
        """Extract display-relevant fields from a CarrierStats journal event."""
        fin   = event.get("Finance", {})
        space = event.get("SpaceUsage", {})

        # Services: journal gives a list of {"Name": ..., "Active": bool}
        raw_svcs = event.get("Services", [])
        services = {}
        if isinstance(raw_svcs, list):
            for svc in raw_svcs:
                k = svc.get("Name", "")
                if k:
                    services[k] = "ok" if svc.get("Active", False) else "unavailable"

        total_cap = space.get("TotalCapacity", 0)
        free_sp   = space.get("FreeSpace", 0)

        return {
            # Identity
            "callsign":      event.get("Callsign", "—"),
            "name":          event.get("Name", "—"),
            "system":        event.get("CurrentStarSystem", "—"),
            # Fuel
            "fuel":          event.get("FuelLevel", 0),   # 0–1000 tritium
            # Operational state (not in journal — CAPI fills this)
            "carrier_state": "—",
            # Access
            "docking":       event.get("DockingAccess",   "—"),
            "notorious":     event.get("AllowNotorious",  False),
            # Finance
            "balance":       fin.get("CarrierBalance",    0),
            "reserve":       fin.get("ReserveBalance",    0),
            "available":     fin.get("AvailableBalance",  0),
            "reserve_pct":   fin.get("ReservePercent",    0),
            "tax_refuel":    fin.get("TaxRate_Refuel",    0),
            "tax_repair":    fin.get("TaxRate_Repair",    0),
            "tax_rearm":     fin.get("TaxRate_Rearm",     0),
            "tax_pioneer":   fin.get("TaxRate_Pioneer",   0),
            # Cargo
            "cargo_total":   total_cap,
            "cargo_used":    total_cap - free_sp,
            "cargo_free":    free_sp,
            # Pack storage
            "ship_packs":    space.get("ShipPacks",       0),
            "module_packs":  space.get("ModulePacks",     0),
            # Micro-resources
            "micro_total":   space.get("MicroresourceCapacityTotal", 0),
            "micro_free":    space.get("MicroresourceCapacityFree",  0),
            "micro_used":    space.get("MicroresourceCapacityUsed",  0),
            # Services
            "services":      services,
            # Carrier type — determines decommission value
            "carrier_type":  event.get("CarrierType", "FleetCarrier"),
        }

    def _save_to_storage(self) -> None:
        """Persist module list and per-ship loadout cache to plugin storage."""
        try:
            s = self.core.state
            self.storage.write_json({
                "stored_modules":     getattr(s, "assets_stored_modules", []),
                "ship_loadout_cache": {str(k): v for k, v in self._ship_loadout_cache.items()},
            }, "data.json")
        except Exception:
            pass

    def _read_status_json(self) -> None:
        """Read Balance from Status.json on startup."""
        try:
            path = Path(self.core.journal_dir) / "Status.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                bal = data.get("Balance")
                if bal is not None:
                    self.core.state.assets_balance = float(bal)
        except Exception:
            pass


    def on_event(self, event: dict, state) -> None:
        core = self.core
        gq   = core.gui_queue
        ev   = event.get("event")

        match ev:

            case "LoadGame":
                # LoadGame contains Balance
                bal = event.get("Credits")
                if bal is not None:
                    state.assets_balance = float(bal)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "Commander":
                # Some versions carry balance here too
                bal = event.get("Credits")
                if bal is not None:
                    state.assets_balance = float(bal)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "Statistics":
                # Bank_Account.Current_Wealth is TOTAL wealth — liquid credits +
                # value of all ships + modules + carrier balance.  It must NOT be
                # used as the liquid credit balance.  We store it separately so the
                # wallet tab can display it as "Net Worth" for context.
                bank = event.get("Bank_Account", {})
                total = bank.get("Current_Wealth")
                if total is not None:
                    state.assets_total_wealth = float(total)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "Loadout":
                ship_type   = event.get("Ship", "")
                ship_type_l = (event.get("Ship_Localised")
                               or self._localised_ship_name(ship_type)
                               or ship_type)
                # If localised name still looks like an internal string (no spaces),
                # force it through the static map.
                if ship_type_l and " " not in ship_type_l.strip():
                    _fixed = self._localised_ship_name(ship_type)
                    if _fixed:
                        ship_type_l = _fixed
                # Also prime the name cache from this event's localised name
                if ship_type_l and ship_type:
                    self._shiptype_cache[ship_type.lower()] = ship_type_l
                # Parse fitted modules with engineering for popover display
                _raw_mods = event.get("Modules") or []
                _loadout  = []
                for _m in _raw_mods:
                    _slot = _m.get("Slot", "")
                    _item = _m.get("Item", "")
                    if not _slot or not _item:
                        continue
                    _eng_raw = _m.get("Engineering") or {}
                    _eng = {}
                    if _eng_raw.get("BlueprintName"):
                        _eng["BlueprintName"] = _eng_raw["BlueprintName"]
                        _eng["Level"]         = int(_eng_raw.get("Level", 0))
                        _eng["Quality"]       = float(_eng_raw.get("Quality", 0))
                        if _eng_raw.get("ExperimentalEffect"):
                            _eng["ExperimentalEffect"] = _eng_raw["ExperimentalEffect"]
                        _eng["Modifiers"] = _eng_raw.get("Modifiers") or []
                    _loadout.append({
                        "slot":          _slot,
                        "name_internal": _item,
                        "name_display":  normalise_module_name(_item),
                        "on":            bool(_m.get("On", True)),
                        "priority":      int(_m.get("Priority", 0)),
                        "value":         int(_m.get("Value", 0)),
                        "engineering":   _eng,
                    })
                # Before replacing current ship, apply its cached loadout
                # to its entry in stored_ships (it's about to become stored).
                _prev_id = (state.assets_current_ship or {}).get("ship_id")
                _new_sid = event.get("ShipID")
                if _prev_id is not None and _prev_id != _new_sid:
                    _prev_lo = self._ship_loadout_cache.get(int(_prev_id), [])
                    for _s in getattr(state, "assets_stored_ships", []):
                        if _s.get("ship_id") == _prev_id:
                            _s["loadout"] = _prev_lo
                            break
                state.assets_current_ship = {
                    "_key":         "current",
                    "current":      True,
                    "ship_id":      _new_sid,
                    "type":         ship_type,
                    "type_display": ship_type_l,
                    "name":         event.get("ShipName", ""),
                    "ident":        event.get("ShipIdent", ""),
                    "system":       getattr(state, "pilot_system", None) or "—",
                    "value":        event.get("HullValue", 0) + event.get("ModulesValue", 0),
                    "rebuy":        event.get("Rebuy", 0),
                    "hull":         100,
                    "loadout":      _loadout,
                }
                # Cache this loadout by ShipID — persists across sessions
                if _new_sid is not None and _loadout:
                    self._ship_loadout_cache[int(_new_sid)] = _loadout
                    self._save_to_storage()
                if gq: gq.put(("plugin_refresh", "assets"))

            case "StoredShips":
                # StoredShips lists every ship in every storage location
                # (ShipsHere + ShipsRemote) — it is authoritative and complete.
                # Replace the stored list entirely rather than merging, so that
                # ships the player has sold or transferred are removed immediately
                # without waiting for a CAPI poll.
                #
                # The one entry StoredShips never includes is the player's active
                # ship (it's boarded, not stored).  Preserve that from the existing
                # list if it's there, so state always holds the complete fleet.
                incoming = {
                    d["ship_id"]: d
                    for d in self._parse_stored_ships(event)
                    if d.get("ship_id") is not None
                }
                current_id = (getattr(state, "assets_current_ship", None) or {}).get("ship_id")
                existing   = {
                    d["ship_id"]: d
                    for d in getattr(state, "assets_stored_ships", [])
                    if d.get("ship_id") is not None
                }
                # Build the new list: authoritative incoming + current ship entry
                # (if present in existing and not already in incoming).
                result = dict(incoming)
                if current_id is not None and current_id not in result and current_id in existing:
                    result[current_id] = existing[current_id]
                state.assets_stored_ships = list(result.values())
                self._save_to_storage()
                if gq: gq.put(("plugin_refresh", "assets"))

            case "StoredModules":
                state.assets_stored_modules = self._parse_stored_modules(event)
                self._save_to_storage()
                if gq: gq.put(("plugin_refresh", "assets"))

            case "ShipyardSwap" | "ModuleRetrieve" | "ModuleStore" | "ModuleBuy" | "ModuleSell" | "ModuleSwap":
                # No direct state change — StoredModules / Loadout follow immediately.
                # Refresh the tab titles so Ships(N) / Modules(N) counts stay current.
                if gq: gq.put(("plugin_refresh", "assets"))

            case "ShipyardSell":
                # Remove the sold ship from the loadout cache immediately so it
                # doesn't reappear at the next roster refresh.
                sell_id = event.get("SellShipID")
                if sell_id is not None:
                    try:    sell_id_i = int(sell_id)
                    except: sell_id_i = sell_id
                    self._ship_loadout_cache.pop(sell_id_i, None)
                    # Remove from in-memory stored fleet
                    state.assets_stored_ships = [
                        s for s in getattr(state, "assets_stored_ships", [])
                        if s.get("ship_id") not in (sell_id, sell_id_i)
                    ]
                    # Remove from persisted capi_profile.json so the ship
                    # does not reappear on the next restart before a fresh
                    # CAPI poll overwrites the file.
                    try:
                        profile = self.storage.read_sibling_json("core", "capi_profile.json")
                        if profile:
                            ships = profile.get("ships") or {}
                            for key in list(ships.keys()):
                                try:
                                    if int(key) in (sell_id, sell_id_i):
                                        del ships[key]
                                except (ValueError, TypeError):
                                    if key in (str(sell_id), str(sell_id_i)):
                                        del ships[key]
                            profile["ships"] = ships
                            self.storage.write_sibling_json("core", "capi_profile.json", profile)
                    except Exception:
                        pass
                    self._save_to_storage()
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierStats":
                state.assets_carrier = self._parse_carrier_stats(event)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "FCMaterials":
                # Fired when the player opens the FC commodity screen.
                # Mirrors the FCMaterials.json bootstrap format exactly.
                items = event.get("Items", [])
                if isinstance(items, list):
                    state.assets_fc_materials = [
                        {
                            "name":       i.get("Name", ""),
                            "name_local": i.get("Name_Localised") or i.get("Name", ""),
                            "price":      int(i.get("Price",    0)),
                            "stock":      int(i.get("Stock",    0)),
                            "demand":     int(i.get("Demand",   0)),
                            "buy_order":  bool(i.get("BuyOrder", False)),
                        }
                        for i in items if i.get("Name")
                    ]
                    if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierDecommission":
                # Carrier has been sold/decommissioned — clear all carrier state.
                state.assets_carrier = None
                self._save_to_storage()
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierJump":
                if state.assets_carrier is not None:
                    state.assets_carrier["system"] = event.get("SystemName", "—")
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierFinance":
                if state.assets_carrier is not None:
                    fin = event.get("Finance", {})
                    if fin.get("CarrierBalance")  is not None: state.assets_carrier["balance"]     = fin["CarrierBalance"]
                    if fin.get("ReserveBalance")  is not None: state.assets_carrier["reserve"]     = fin["ReserveBalance"]
                    if fin.get("AvailableBalance") is not None: state.assets_carrier["available"]  = fin["AvailableBalance"]
                    if fin.get("ReservePercent")  is not None: state.assets_carrier["reserve_pct"] = fin["ReservePercent"]
                if gq: gq.put(("plugin_refresh", "assets"))


# ── Helpers ───────────────────────────────────────────────────────────────────



# ── FCMaterials JSON helpers ───────────────────────────────────────────────────

def _bootstrap_fc_materials(state, journal_dir) -> None:
    """Bootstrap fleet carrier materials from FCMaterials.json on startup."""
    if journal_dir is None:
        return
    import json as _json
    from pathlib import Path as _Path
    import builtins as _bi
    path = _Path(journal_dir) / "FCMaterials.json"
    try:
        data = _json.load(_bi.open(path, encoding="utf-8"))
    except Exception:
        return
    items = data.get("Items", [])
    if isinstance(items, list) and items:
        state.assets_fc_materials = [
            {
                "name":      i.get("Name", ""),
                "name_local": i.get("Name_Localised") or i.get("Name", ""),
                "price":     int(i.get("Price",  0)),
                "stock":     int(i.get("Stock",  0)),
                "demand":    int(i.get("Demand", 0)),
                "buy_order": bool(i.get("BuyOrder", False)),
            }
            for i in items if i.get("Name")
        ]

# ── ModulesInfo JSON helpers ───────────────────────────────────────────────────

def _bootstrap_modules_info(state, journal_dir) -> None:
    """Bootstrap lightweight fitted module list from ModulesInfo.json on startup.
    Only used before CAPI poll and Loadout event arrive; superseded by capi_loadout.
    """
    if journal_dir is None:
        return
    import json as _json
    from pathlib import Path as _Path
    import builtins as _bi
    path = _Path(journal_dir) / "ModulesInfo.json"
    try:
        data = _json.load(_bi.open(path, encoding="utf-8"))
    except Exception:
        return
    modules = data.get("Modules", [])
    if isinstance(modules, list) and modules:
        # Store as {slot: {name, power, priority}} for quick access
        fitted = {}
        for m in modules:
            slot = m.get("Slot", "")
            if slot:
                fitted[slot] = {
                    "name":     m.get("Item", ""),
                    "power":    float(m.get("Power", 0.0)),
                    "priority": int(m.get("Priority", 0)),
                }
        if fitted and not getattr(state, "capi_loadout", None):
            state.capi_loadout = fitted

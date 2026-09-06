"""
components/assets.py — Commander assets inventory.

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
from datetime import datetime, timezone
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


def _build_loadout_from_capi_modules(modules: dict) -> list[dict]:
    """Turn a CAPI ``modules`` mapping into the loadout shape used elsewhere.

    Referenced by the CAPI stored-ships and shipyard paths since before this
    release but never defined, so populating a stored ship's loadout from CAPI
    raised NameError.  The journal path already builds the same records; this
    matches that shape so both feed the Ships tab identically.

    CAPI keys slots by name and wraps each module in a ``module`` object; a
    slot with no item is skipped rather than rendered as an empty row.
    """
    out: list[dict] = []
    for slot, entry in (modules or {}).items():
        if not isinstance(entry, dict):
            continue
        mod = entry.get("module") or entry
        item = str(mod.get("name", "") or "")
        if not item:
            continue

        eng = {}
        engineer = mod.get("engineer") or mod.get("modifiers") or {}
        if isinstance(engineer, dict) and engineer.get("blueprintName"):
            eng = {
                "BlueprintName": engineer.get("blueprintName", ""),
                "Level":         int(engineer.get("level", 0) or 0),
                "Quality":       float(engineer.get("quality", 0) or 0),
                "ExperimentalEffect": engineer.get("experimentalEffect", ""),
                "Modifiers":     engineer.get("modifiers") or [],
            }

        out.append({
            "slot":          str(slot),
            "name_internal": item,
            "name_display":  normalise_module_name(item),
            "on":            bool(mod.get("on", True)),
            "priority":      int(mod.get("priority", 0) or 0),
            "value":         int(mod.get("value", 0) or 0),
            "engineering":   eng,
        })
    return out


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
        # Jump lifecycle.  CarrierLocation is how a jump completing is seen
        # when the commander is not aboard; CarrierJump is the aboard case.
        "CarrierJumpRequest",
        "CarrierJumpCancelled",
        "CarrierLocation",
        "CarrierFinance",
        "FCMaterials",
        "CarrierDecommission",   # carrier sold/decommissioned
        # Ships sold/transferred
        "ShipyardSell",
        # Session boundaries
        "LoadGame",
    ]


    def on_load(self, core) -> None:
        #: CarrierID (as str) -> pending jump, see the carrier
        #: jump lifecycle section below.
        self._pending_jumps: dict[str, dict] = {}
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
        """Parse capi_fleetcarrier.json into the assets_carrier state dict.

        Key names must match ``_parse_carrier_stats`` (journal CarrierStats)
        and the CAPI ingest in ``core/data.py``, because whichever source
        fires last wins and the display reads one set of names.  They used to
        diverge — this parser emitted ``state`` where the others emit
        ``carrier_state``, and omitted docking, balances and cargo free space
        entirely — so a CAPI-sourced carrier rendered with fields missing that
        a journal-sourced one had.
        """
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
            tax   = fin.get("service_taxation") or {}

            def _i(v) -> int:
                try:
                    return int(v or 0)
                except (TypeError, ValueError):
                    return 0

            used = (_i(cap.get("cargoForSale")) +
                    _i(cap.get("cargoNotForSale")) +
                    _i(cap.get("cargoSpaceReserved")))
            free = _i(cap.get("freeSpace"))
            balance = _i(fin.get("bankBalance"))
            reserve = _i(fin.get("bankReservedBalance"))

            return {
                "callsign":      callsign,
                "name":          vanity or callsign,
                "system":        fc.get("currentStarSystem", "—"),
                "theme":         fc.get("theme", "—"),
                "carrier_state": fc.get("state", "—"),
                "docking":       fc.get("dockingAccess") or "—",
                "notorious":     bool(fc.get("notoriousAccess", False)),
                "balance":       balance,
                "reserve":       reserve,
                "available":     max(balance - reserve, 0),
                "maintenance":     _i(fin.get("maintenance")),
                "maintenance_wtd": _i(fin.get("maintenanceToDate")),
                "tax_refuel":    tax.get("refuel", 0),
                "tax_repair":    tax.get("repair", 0),
                "tax_rearm":     tax.get("rearm", 0),
                "tax_pioneer":   tax.get("pioneersupplies", 0),
                "fuel":          _i(fc.get("fuel")),
                "debt":          0,
                "cargo_used":    used,
                "cargo_free":    free,
                "cargo_total":   (used + free) or 25_000,
                "cargo_crew":    _i(cap.get("crew")),
                "ship_packs":    _i(cap.get("shipPacks")),
                "module_packs":  _i(cap.get("modulePacks")),
                "micro_total":   _i(cap.get("microresourceCapacityTotal")),
                "micro_free":    _i(cap.get("microresourceCapacityFree")),
                "micro_used":    _i(cap.get("microresourceCapacityUsed")),
                "services":      dict(svcs),
                # CAPI does not expose carrier type; a squadron carrier is
                # rare enough that assuming a fleet carrier is the safer
                # default, and the journal corrects it when CarrierStats fires.
                "carrier_type":  "FleetCarrier",
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

    # ── Carrier jump lifecycle ────────────────────────────────────────────────
    #
    # A scheduled jump locks the carrier down for roughly fifteen minutes:
    # nobody can dock, and anyone aboard is going wherever it goes.  That is
    # worth a notification whether or not the commander is watching the
    # carrier's own panel, so all three transitions go out through the alerts
    # component, which puts them in the Alerts window and emits them to the
    # terminal and Discord at their configured level.
    #
    # The events themselves are thin.  CarrierJumpRequest names the
    # destination and departure time but not the carrier; CarrierJumpCancelled
    # names neither; and completion arrives as CarrierLocation when the
    # commander is elsewhere or CarrierJump when aboard — and when aboard,
    # both fire, about a minute apart.  So the pending jump is tracked here
    # and cleared by whichever completion event lands first.

    #: Journal spelling → readable carrier kind.
    _CARRIER_KIND = {
        "FleetCarrier":    "Fleet carrier",
        "SquadronCarrier": "Squadron carrier",
    }

    def _carrier_by_id(self, carrier_id, state) -> dict | None:
        """Find the fleet or squadron carrier matching an id, or None."""
        if carrier_id is None:
            return None
        for carrier in (getattr(state, "assets_carrier", None),
                        getattr(state, "assets_squadron_carrier", None)):
            if carrier and str(carrier.get("carrier_id", "")) == str(carrier_id):
                return carrier
        return None

    def _carrier_label(self, carrier_id, state, carrier_type: str = "") -> str:
        """"NAME (IDENT)" for a carrier, falling back as data allows.

        A jump can be scheduled before CarrierStats has been seen this
        session, so this degrades to the kind of carrier rather than
        rendering an empty name.
        """
        carrier = self._carrier_by_id(carrier_id, state)
        if carrier:
            name = str(carrier.get("name") or "").strip()
            ident = str(carrier.get("callsign") or "").strip()
            if name and ident:
                return f"{name} ({ident})"
            if name or ident:
                return name or ident
        return self._CARRIER_KIND.get(str(carrier_type), "Carrier")

    @staticmethod
    def _fmt_countdown(seconds: float) -> str:
        """Render a departure countdown as "15m 49s" / "1h 12m"."""
        seconds = max(int(seconds), 0)
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    def _departure_in(self, event: dict) -> tuple[str, str]:
        """Return (countdown text, departure clock time) for a jump request.

        Journal timestamps are UTC.  Printing that clock time raw made the
        figure meaningless to anyone not running on UTC — it read as neither
        their wall clock nor a duration.  The clock time now follows the same
        ``UseUTC`` setting as every other time EDLD prints, and is labelled so
        it cannot be mistaken for part of the countdown.
        """
        departure = str(event.get("DepartureTime") or "")
        stamp = str(event.get("timestamp") or "")
        if not departure:
            return "", ""
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        try:
            dep_dt = datetime.strptime(departure, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            return "", ""
        try:
            now_dt = datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            now_dt = None

        countdown = (self._fmt_countdown((dep_dt - now_dt).total_seconds())
                     if now_dt else "")

        use_utc = bool((getattr(self.core, "app_settings", None) or {}).get("UseUTC"))
        local = dep_dt if use_utc else dep_dt.astimezone()
        return countdown, local.strftime("%H:%M") + (" UTC" if use_utc else "")

    def _alerts(self):
        return self.core._plugins.get("alerts")

    def _notify_carrier(self, level_key: str, emoji: str, text: str) -> None:
        """Route a carrier notification through the alerts component.

        Falls back to a direct emit if alerts is disabled, so turning that
        component off silences the Alerts window rather than the notification.
        """
        alerts = self._alerts()
        if alerts is not None:
            try:
                alerts.push_external(emoji, text, loglevel=level_key,
                                     sigil="*  CARR")
                return
            except Exception:
                pass
        try:
            self.core.emitter.emit(
                msg_term=text, msg_discord=f"**{text}**", emoji=emoji,
                sigil="*  CARR",
                loglevel=int(self.core.notify_levels.get(level_key, 3)),
            )
        except Exception:
            pass

    def _schedule_carrier_jump(self, event: dict, state) -> None:
        carrier_id = event.get("CarrierID")
        destination = str(event.get("SystemName") or "—")
        body = str(event.get("Body") or "")
        countdown, clock = self._departure_in(event)

        self._pending_jumps[str(carrier_id)] = {
            "system": destination,
            "body": body,
            "departure": event.get("DepartureTime", ""),
            "carrier_type": event.get("CarrierType", ""),
        }

        # Replaying history at startup must not fire notifications for jumps
        # that resolved long ago; the pending entry above is still recorded so
        # a jump scheduled before launch still reports its arrival.
        if getattr(state, "in_preload", False):
            return

        label = self._carrier_label(carrier_id, state, event.get("CarrierType", ""))
        where = f"{destination} ({body})" if body else destination
        when = f" in {countdown}" if countdown else ""
        at = f" (departs {clock})" if clock else ""
        self._notify_carrier(
            "CarrierJumpScheduled", "🛰️",
            f"{label} JUMP SCHEDULED to {where}{when}{at}")

    def _cancel_carrier_jump(self, event: dict, state) -> None:
        carrier_id = event.get("CarrierID")
        pending = self._pending_jumps.pop(str(carrier_id), None)

        if getattr(state, "in_preload", False):
            return

        label = self._carrier_label(carrier_id, state, event.get("CarrierType", ""))
        destination = (pending or {}).get("system") or ""
        where = f" to {destination}" if destination else ""
        self._notify_carrier(
            "CarrierJumpCancelled", "🛑",
            f"{label} JUMP CANCELLED{where}")

    def _complete_carrier_jump(self, carrier_id, arrived: str, state,
                               event: dict) -> None:
        """Report an arrival, but only for the jump that was actually pending.

        CarrierLocation is a periodic status event as much as an arrival one —
        in a real journal it outnumbers jumps roughly two to one — so simply
        taking the next one after a request reports the wrong system whenever
        a status update lands before departure.  An arrival therefore has to
        name the destination that was requested.

        The departure-time check covers the other case: a jump to a body in
        the system the carrier is already in, where the destination matches
        before it has gone anywhere.

        When the commander is aboard, both CarrierLocation and CarrierJump
        fire for the same arrival about a minute apart.  Popping the pending
        entry makes this fire exactly once per scheduled jump.
        """
        key = str(carrier_id)
        pending = self._pending_jumps.get(key)
        if pending is None:
            return

        destination = str(pending.get("system") or "")
        if destination and arrived and arrived != "—":
            if arrived.strip().casefold() != destination.strip().casefold():
                return          # a status update from somewhere else

        if not self._past_departure(pending, event):
            return              # still counting down

        self._pending_jumps.pop(key, None)
        if getattr(state, "in_preload", False):
            return

        label = self._carrier_label(carrier_id, state,
                                    pending.get("carrier_type", ""))
        final = arrived if arrived and arrived != "—" else destination or "—"
        self._notify_carrier(
            "CarrierJumpComplete", "✅",
            f"{label} JUMP COMPLETE — arrived at {final}")

    @staticmethod
    def _past_departure(pending: dict, event: dict) -> bool:
        """Has the scheduled departure time passed?

        Missing or unparseable timestamps resolve to True: a carrier that has
        reported arriving at its destination has arrived, and refusing to say
        so because a clock could not be read would be the worse failure.
        """
        departure = str(pending.get("departure") or "")
        stamp = str(event.get("timestamp") or "")
        if not departure or not stamp:
            return True
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        try:
            return datetime.strptime(stamp, fmt) >= datetime.strptime(departure, fmt)
        except ValueError:
            return True

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
            "carrier_id":    event.get("CarrierID"),
            "callsign":      event.get("Callsign", "—"),
            "name":          event.get("Name", "—"),
            "theme":         event.get("Theme", "—"),
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
                # CarrierType distinguishes a personal fleet carrier from a
                # squadron one.  They were previously written to the same
                # field, so whichever event arrived last won and the other
                # carrier vanished from the display.
                parsed = self._parse_carrier_stats(event)
                if parsed and "Squadron" in str(parsed.get("carrier_type", "")):
                    state.assets_squadron_carrier = parsed
                else:
                    state.assets_carrier = parsed
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
                # CarrierID tells us which one; without it, clear the fleet
                # carrier, which is the one a lone commander will have.
                cid = event.get("CarrierID")
                squadron = state.assets_squadron_carrier or {}
                if cid and str(squadron.get("carrier_id", "")) == str(cid):
                    state.assets_squadron_carrier = None
                    self._save_to_storage()
                    if gq: gq.put(("plugin_refresh", "assets"))
                    return
                state.assets_carrier = None
                self._save_to_storage()
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierJump":
                # The arrival event, fired only when the commander is aboard.
                # It names the system in StarSystem, not SystemName — reading
                # the wrong key had been blanking the carrier's system to "—"
                # on every jump the commander rode along with.
                arrived = (event.get("StarSystem")
                           or event.get("SystemName") or "—")
                if state.assets_carrier is not None:
                    state.assets_carrier["system"] = arrived
                # CarrierJump identifies the carrier by MarketID.
                self._complete_carrier_jump(
                    event.get("MarketID"), arrived, state, event)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierJumpRequest":
                self._schedule_carrier_jump(event, state)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierJumpCancelled":
                # Carries only CarrierType and CarrierID — nothing about where
                # the carrier was headed — so the pending jump recorded at
                # request time is the only source for that.
                self._cancel_carrier_jump(event, state)
                if gq: gq.put(("plugin_refresh", "assets"))

            case "CarrierLocation":
                # Fires periodically as a status event, not only after a jump,
                # so it is only treated as an arrival when a jump is actually
                # pending for that carrier.
                cid = event.get("CarrierID")
                arrived = event.get("StarSystem") or "—"
                carrier = self._carrier_by_id(cid, state)
                if carrier is not None and arrived != "—":
                    carrier["system"] = arrived
                self._complete_carrier_jump(cid, arrived, state, event)
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

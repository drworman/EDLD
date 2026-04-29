"""
components/inara/plugin.py — Inara API uploader for EDLD.

Posts commander activity to the Inara API (https://inara.cz/inapi/v1/).

What is posted
--------------
Travel       — FSD jumps, dockings
Status       — credits, ranks (pilot, engineer, power), reputation
Missions     — accepted, completed, failed, abandoned
Ship         — current ship identity and full loadout
Materials    — Horizons materials snapshot (from Materials journal event)

What is NOT posted (yet — pending CAPI integration)
----------------------------------------------------
Fleet (stored ships)       — StoredShips is stale; CAPI /profile is authoritative
Combat log (kills, bonds)  — high-frequency; Inara does not require real-time
Market transactions        — covered by EDDN for the galaxy-wide dataset

Config [Inara] in config.toml
------------------------------
    Enabled        = false          # opt-in
    ApiKey         = ""             # personal API key from inara.cz settings
    CommanderName  = ""             # in-game name only — do not include "CMDR"

Rate limits
-----------
Inara enforces 2 requests per minute per API key across all apps.  We batch
all events between session transitions and flush on FSDJump / Docked / LoadGame.
The sender thread enforces a minimum 30-second gap between requests.

Whitelisting
------------
App name registered with Inara: EDLD
"""

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.state import EDLD_DATA_DIR, VERSION

# ── Constants ─────────────────────────────────────────────────────────────────

PLUGIN_VERSION  = "1.0.0"
INARA_API_URL   = "https://inara.cz/inapi/v1/"
APP_NAME        = "EDLD"
APP_VERSION     = VERSION
HTTP_TIMEOUT_S  = 20
SEND_INTERVAL_S = 30        # 2 requests/minute hard limit from Inara
STARTUP_DELAY_S = 8         # wait before first send so preload finishes
BATCH_MAX       = 100       # events per request (Inara has no documented per-batch limit)
def _queue_file() -> Path:
    return cmdr_data_dir() / "inara_queue.jsonl"

# Journal Rank keys → Inara rankName strings
_RANK_KEYS = {
    "Combat":       "combat",
    "Trade":        "trade",
    "Explore":      "explore",
    "Soldier":      "soldier",
    "Exobiologist": "exobiologist",
    "CQC":          "cqc",
    "Federation":   "federation",
    "Empire":       "empire",
}

CFG_DEFAULTS = {
    "Enabled":       False,
    "ApiKey":        "",
    "CommanderName": "",
}


# ── Sender thread ─────────────────────────────────────────────────────────────

class _Sender(threading.Thread):
    """
    Background thread — batches Inara API events and POSTs them.

    Call push(event_dict) to enqueue an individual Inara event.
    Call flush() to force an immediate send of the accumulated batch.
    Call stop() for clean shutdown.
    """

    def __init__(self, cmdr_name: str, api_key: str, queue_file) -> None:
        super().__init__(daemon=True, name="inara-sender")
        self._cmdr       = cmdr_name
        self._key        = api_key
        self._queue_file = queue_file
        self._q          = queue.Queue()
        self._stop_evt   = threading.Event()
        self._last_send  = 0.0

    def push(self, inara_event: dict) -> None:
        self._q.put(inara_event)

    def flush(self) -> None:
        self._q.put(_FLUSH_SENTINEL)

    def stop(self) -> None:
        self._stop_evt.set()
        self._q.put(None)

    def run(self) -> None:
        time.sleep(STARTUP_DELAY_S)
        self._drain_disk()

        batch: list[dict] = []

        while not self._stop_evt.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                if batch and (time.monotonic() - self._last_send >= SEND_INTERVAL_S):
                    self._send_batch(batch)
                    batch = []
                continue

            if item is None:
                if batch:
                    self._send_batch(batch)
                return

            if item is _FLUSH_SENTINEL:
                if batch:
                    self._send_batch(batch)
                    batch = []
                continue

            batch.append(item)
            if len(batch) >= BATCH_MAX:
                self._send_batch(batch)
                batch = []

        if batch:
            self._send_batch(batch)

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _send_batch(self, events: list[dict]) -> None:
        """POST a batch of Inara events.  Persist to disk on failure."""
        gap = SEND_INTERVAL_S - (time.monotonic() - self._last_send)
        if gap > 0:
            time.sleep(gap)

        payload = {
            "header": {
                "appName":        APP_NAME,
                "appVersion":     APP_VERSION,
                "isDeveloped":    False,
                "APIkey":         self._key,
                "commanderName":  self._cmdr,
            },
            "events": events,
        }

        try:
            raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            req = urllib.request.Request(
                INARA_API_URL,
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent":   f"{APP_NAME}/{APP_VERSION}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                self._last_send = time.monotonic()
                body = resp.read().decode("utf-8")
                result = json.loads(body) if body.strip() else {}
                header_status = result.get("header", {}).get("eventStatus", 200)
                if header_status not in (200, 204):
                    msg = result.get("header", {}).get("eventStatusText", "")
                    print(f"  [Inara] API header error {header_status}: {msg}")
                    # 400 = bad request — no point retrying
                    if header_status != 400:
                        self._persist(events)

        except urllib.error.HTTPError as e:
            print(f"  [Inara] HTTP {e.code} — queuing {len(events)} event(s) to disk")
            if e.code != 400:
                self._persist(events)
        except Exception as exc:
            print(f"  [Inara] Send error ({type(exc).__name__}: {exc}) — queuing to disk")
            self._persist(events)

    # ── Disk queue ────────────────────────────────────────────────────────────

    def _persist(self, events: list[dict]) -> None:
        try:
            self._queue_file.parent.mkdir(parents=True, exist_ok=True)
            import builtins as _bi
            with _bi.open(self._queue_file, "a", encoding="utf-8") as f:
                for ev in events:
                    f.write(json.dumps({"queued_at": time.time(), "msg": ev}) + "\n")
        except Exception as e:
            print(f"  [Inara] Failed to persist events to disk: {e}")

    def _drain_disk(self) -> None:
        if not self._queue_file.exists():
            return
        try:
            import builtins as _bi
            lines = _bi.open(self._queue_file, encoding="utf-8").read().splitlines()
        except Exception:
            return
        if not lines:
            return

        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line)["msg"])
            except Exception:
                pass

        if events:
            print(f"  [Inara] Replaying {len(events)} queued event(s) from disk...")
            for i in range(0, len(events), BATCH_MAX):
                self._send_batch(events[i:i + BATCH_MAX])
                if i + BATCH_MAX < len(events):
                    time.sleep(SEND_INTERVAL_S)

        try:
            self._queue_file.unlink(missing_ok=True)
        except Exception:
            pass


_FLUSH_SENTINEL = object()


# ── Plugin ────────────────────────────────────────────────────────────────────

class InaraPlugin(BasePlugin):

    PLUGIN_NAME        = "inara"
    PLUGIN_DISPLAY     = "Inara Uploader"
    PLUGIN_VERSION     = PLUGIN_VERSION
    PLUGIN_DESCRIPTION = "Posts commander activity to inara.cz."
    PLUGIN_DEFAULT_ENABLED = False

    SUBSCRIBED_EVENTS = [
        # Session
        "LoadGame", "Commander",
        # Location / travel
        "Location", "FSDJump", "CarrierJump", "Docked",
        # Ranks and reputation
        "Rank", "Progress", "Reputation", "EngineerProgress",
        # Powerplay
        "Powerplay", "PowerplayJoin", "PowerplayLeave",
        "PowerplayDefect", "PowerplayRank", "PowerplayMerits",
        # Credits
        "Statistics",
        # Missions
        "MissionAccepted", "MissionCompleted",
        "MissionFailed", "MissionAbandoned",
        # Ship — identity, loadout, fleet
        "Loadout", "ShipyardSwap", "ShipyardBuy", "ShipyardSell",
        "StoredShips", "SetUserShipName",
        # Materials
        "Materials",
        # Cargo snapshot
        "Cargo",
        # Micro-resources (Odyssey ship locker)
        "ShipLockerMaterials",
        # Exobiology
        "SellOrganicData",
        # Combat death
        "Died",
        # Community goals
        "CommunityGoalJoin", "CommunityGoalReward",
        # Multicrew
        "MulticrewJoin", "MulticrewEnd",
    ]

    def on_load(self, core) -> None:
        self.core          = core
        self._enabled      = False
        self._sender: _Sender | None = None

        # Internal tracking — maintained independently from MonitorState
        # so we never accidentally send stale data.
        self._cmdr_name:    str = ""
        self._ship_type:    str = ""
        self._ship_id:      int | None = None
        self._system_name:  str | None = None
        self._star_pos:     list | None = None
        # Rank snapshot — accumulated from Rank + Progress events
        # so we can send a combined array to Inara on LoadGame
        self._rank_values:    dict[str, int]   = {}   # key → rankValue
        self._rank_progress:  dict[str, float] = {}   # key → fraction 0-1
        self._micro_items:    list[dict]        = []   # last ShipLockerMaterials snapshot
        self._last_loadout:   dict | None       = None  # dedup: only send changed loadouts

        cfg = core.load_setting("Inara", CFG_DEFAULTS, warn=False)

        if not bool(core.cfg.app_settings.get("PrimaryInstance", True)):
            print("  [Inara] Uploads suppressed (PrimaryInstance = false)")
            return
        if not cfg["Enabled"]:
            return
        if not cfg["ApiKey"] or not cfg["CommanderName"]:
            print(
                "  [Inara] Disabled — ApiKey and CommanderName must both be "
                "set in config.toml under [Inara]"
            )
            return

        self._enabled     = True
        # Strip "CMDR " prefix if the user included it — a common mistake
        raw_name          = cfg["CommanderName"].strip()
        self._cmdr_name   = raw_name[5:].strip() if raw_name.upper().startswith("CMDR ") else raw_name
        self._sender      = _Sender(self._cmdr_name, cfg["ApiKey"], self.storage.path / "queue.jsonl")
        self._sender.start()

        self._load_note = f"uploading as CMDR {self._cmdr_name}"

    def on_unload(self) -> None:
        if self._sender:
            self._sender.stop()
            self._sender.join(timeout=5)

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event", "")
        ts = event.get("timestamp", "")

        # Always maintain internal tracking regardless of enabled state
        self._track(ev, event)

        if not self._enabled or self._sender is None:
            return

        # ── Beta guard — never send beta data to Inara ────────────────────────
        game_version = getattr(state, "_game_version", "") or ""
        if "beta" in game_version.lower() or game_version.startswith("3."):
            return

        match ev:

            case "LoadGame":
                credits = event.get("Credits")
                if credits is not None and credits >= 0:
                    self._push(ts, "setCommanderCredits", {
                        "commanderCredits": int(credits),
                    })
                # Flush current rank snapshot
                if self._rank_values:
                    self._push_ranks(ts)
                self._sender.flush()

            case "Rank":
                for journal_key, inara_key in _RANK_KEYS.items():
                    if journal_key in event:
                        self._rank_values[inara_key] = int(event[journal_key])

            case "Progress":
                for journal_key, inara_key in _RANK_KEYS.items():
                    if journal_key in event:
                        self._rank_progress[inara_key] = event[journal_key] / 100.0

            case "Statistics":
                # Bank_Account.Current_Wealth is total wealth (liquid + ship/module
                # values + carrier balance), NOT liquid credits.  Report it only as
                # commanderAssets.  Liquid commanderCredits come from LoadGame.Credits
                # or a post-CAPI-poll update (assets_balance), never from Statistics.
                bank   = event.get("Bank_Account", {})
                assets = bank.get("Assets_Total") or bank.get("Current_Wealth")
                if assets is not None and assets >= 0:
                    self._push(ts, "setCommanderCredits",
                               {"commanderAssets": int(assets)})

            case "Reputation":
                # Post major faction reputations
                reps = []
                for faction_key, inara_name in [
                    ("Federation", "Federation"),
                    ("Empire",     "Empire"),
                    ("Alliance",   "Alliance"),
                    ("Independent","Independent"),
                ]:
                    val = event.get(faction_key)
                    if val is not None:
                        reps.append({
                            "factionName":       inara_name,
                            "reputationValue":   val / 100.0,
                        })
                if reps:
                    self._push(ts, "setCommanderReputationMajorFaction", reps)

            case "EngineerProgress":
                engineers = event.get("Engineers", [])
                if engineers:
                    eng_data = []
                    for eng in engineers:
                        name   = eng.get("Engineer")
                        stage  = eng.get("Progress")       # "Known"/"Invited"/"Unlocked"/etc.
                        rank_v = eng.get("Rank")
                        if name and stage:
                            entry: dict = {
                                "engineerName": name,
                                "rankStage":    stage,
                            }
                            if rank_v is not None:
                                entry["rankValue"] = int(rank_v)
                            eng_data.append(entry)
                    if eng_data:
                        self._push(ts, "setCommanderRankEngineer", eng_data)

            case "Powerplay" | "PowerplayJoin":
                power  = event.get("Power")
                rank_v = event.get("Rank", 1)
                merits = event.get("Merits") or event.get("TotalMerits")
                if power:
                    data: dict = {
                        "powerName": power,
                        "rankValue": int(rank_v),
                    }
                    if merits is not None:
                        data["meritsValue"] = int(merits)
                    self._push(ts, "setCommanderRankPower", data)

            case "PowerplayLeave":
                # Signal end of pledge — send rank 0
                power = getattr(state, "pp_power", None)
                if power:
                    self._push(ts, "setCommanderRankPower", {
                        "powerName": power,
                        "rankValue": 0,
                    })

            case "PowerplayRank":
                rank_v = event.get("Rank")
                power  = getattr(state, "pp_power", None)
                merits = getattr(state, "pp_merits_total", None)
                if power and rank_v is not None:
                    data = {"powerName": power, "rankValue": int(rank_v)}
                    if merits is not None:
                        data["meritsValue"] = int(merits)
                    self._push(ts, "setCommanderRankPower", data)

            case "PowerplayMerits":
                power  = event.get("Power") or getattr(state, "pp_power", None)
                rank_v = getattr(state, "pp_rank", None)
                merits = event.get("TotalMerits")
                if power and merits is not None:
                    data = {"powerName": power, "meritsValue": int(merits)}
                    if rank_v is not None:
                        data["rankValue"] = int(rank_v)
                    self._push(ts, "setCommanderRankPower", data)

            case "FSDJump" | "CarrierJump":
                data: dict = {
                    "starsystemName": event.get("StarSystem", ""),
                }
                if self._star_pos:
                    data["starsystemCoords"] = self._star_pos
                jump_dist = event.get("JumpDist")
                if jump_dist is not None:
                    data["jumpDistance"] = round(float(jump_dist), 2)
                if self._ship_type:
                    data["shipType"] = self._ship_type
                if self._ship_id is not None:
                    data["shipGameID"] = self._ship_id
                self._push(ts, "addCommanderTravelFSDJump", data)
                self._push_ranks(ts)
                self._sender.flush()

            case "Docked":
                data = {
                    "starsystemName": event.get("StarSystem", ""),
                    "stationName":    event.get("StationName", ""),
                }
                market_id = event.get("MarketID")
                if market_id is not None:
                    data["marketID"] = int(market_id)
                if self._ship_type:
                    data["shipType"] = self._ship_type
                if self._ship_id is not None:
                    data["shipGameID"] = self._ship_id
                self._push(ts, "addCommanderTravelDock", data)
                self._sender.flush()

            case "MissionAccepted":
                mission_id = event.get("MissionID")
                name       = event.get("Name", "")
                faction    = event.get("Faction", "")
                expires    = event.get("Expiry", "")
                if mission_id is not None:
                    data = {
                        "missionGameID": int(mission_id),
                        "missionName":   name,
                    }
                    if faction:
                        data["minorfactionName"] = faction
                    if expires:
                        data["missionExpiry"] = expires
                    self._push(ts, "addCommanderMission", data)

            case "MissionCompleted":
                mission_id = event.get("MissionID")
                reward     = event.get("Reward", 0)
                if mission_id is not None:
                    self._push(ts, "setCommanderMissionCompleted", {
                        "missionGameID": int(mission_id),
                        "rewardCredits": int(reward),
                    })

            case "MissionFailed":
                mission_id = event.get("MissionID")
                if mission_id is not None:
                    self._push(ts, "setCommanderMissionFailed", {
                        "missionGameID": int(mission_id),
                    })

            case "MissionAbandoned":
                mission_id = event.get("MissionID")
                if mission_id is not None:
                    self._push(ts, "setCommanderMissionAbandoned", {
                        "missionGameID": int(mission_id),
                    })

            case "Loadout":
                # Current ship identity + full stats
                ship_type = event.get("Ship", "")
                ship_id   = event.get("ShipID")
                if ship_type:
                    ship_data: dict = {
                        "shipType":      ship_type,
                        "isCurrentShip": True,
                    }
                    if ship_id is not None:
                        ship_data["shipGameID"] = int(ship_id)
                    name  = event.get("ShipName")
                    ident = event.get("ShipIdent")
                    if name:  ship_data["shipName"]  = name
                    if ident: ship_data["shipIdent"] = ident
                    hull_val  = event.get("HullValue")
                    mods_val  = event.get("ModulesValue")
                    rebuy     = event.get("Rebuy")
                    fuel_cap  = (event.get("FuelCapacity") or {}).get("Main")
                    cargo_cap = event.get("CargoCapacity")
                    max_jump  = event.get("MaxJumpRange")
                    if hull_val  is not None: ship_data["shipHullValue"]    = int(hull_val)
                    if mods_val  is not None: ship_data["shipModulesValue"] = int(mods_val)
                    if rebuy     is not None: ship_data["shipRebuyCost"]    = int(rebuy)
                    if fuel_cap  is not None: ship_data["fuelCapacity"]     = round(float(fuel_cap), 2)
                    if cargo_cap is not None: ship_data["cargoCapacity"]    = int(cargo_cap)
                    if max_jump  is not None: ship_data["maxJumpRange"]     = round(float(max_jump), 2)
                    self._push(ts, "setCommanderShip", ship_data)

                # Full loadout — use Inara camelCase field names (not journal PascalCase)
                modules = event.get("Modules", [])
                if modules and ship_type:
                    loadout_modules = []
                    for mod in modules:
                        slot = mod.get("Slot", "")
                        item = mod.get("Item", "")
                        if not slot or not item:
                            continue
                        # Inara API field names (verified against EDMC implementation)
                        entry: dict = {
                            "slotName":     slot,
                            "itemName":     item,
                            "isOn":         bool(mod.get("On", True)),
                            "itemPriority": int(mod.get("Priority", 0)),
                            "itemHealth":   round(float(mod.get("Health", 1.0)), 4),
                        }
                        value  = mod.get("Value")
                        ammo_c = mod.get("AmmoInClip")
                        ammo_h = mod.get("AmmoInHopper")
                        hot    = mod.get("Hot")
                        if value  is not None: entry["itemValue"]     = int(value)
                        if ammo_c is not None: entry["itemAmmoClip"]  = int(ammo_c)
                        if ammo_h is not None: entry["itemAmmoHopper"]= int(ammo_h)
                        if hot    is not None: entry["isHot"]         = bool(hot)
                        # Engineering — camelCase keys per Inara API spec
                        eng = mod.get("Engineering")
                        if eng and eng.get("BlueprintName"):
                            bp: dict = {
                                "blueprintName":    eng["BlueprintName"],
                                "blueprintLevel":   int(eng.get("Level", 0)),
                                "blueprintQuality": round(float(eng.get("Quality", 0)), 2),
                            }
                            if eng.get("ExperimentalEffect"):
                                bp["experimentalEffect"] = eng["ExperimentalEffect"]
                            modifiers = eng.get("Modifiers") or []
                            bp["modifiers"] = []
                            for mod_entry in modifiers:
                                m: dict = {"name": mod_entry.get("Label", "")}
                                if "OriginalValue" in mod_entry:
                                    m["value"]         = mod_entry["Value"]
                                    m["originalValue"] = mod_entry["OriginalValue"]
                                    m["lessIsGood"]    = int(mod_entry.get("LessIsGood", 0))
                                elif "ValueStr" in mod_entry:
                                    m["value"] = mod_entry["ValueStr"]
                                elif "Value" in mod_entry:
                                    m["value"] = mod_entry["Value"]
                                bp["modifiers"].append(m)
                            entry["engineering"] = bp
                        loadout_modules.append(entry)

                    loadout_data: dict = {
                        "shipType":    ship_type,
                        "shipLoadout": loadout_modules,
                    }
                    if ship_id is not None:
                        loadout_data["shipGameID"] = int(ship_id)
                    # Deduplicate: only send if loadout changed
                    if loadout_data != self._last_loadout:
                        self._last_loadout = loadout_data
                        self._push(ts, "setCommanderShipLoadout", loadout_data)

            case "Materials":
                # Full materials snapshot — post as setCommanderInventoryMaterials
                all_materials = []
                for category, journal_key in [
                    ("raw",          "Raw"),
                    ("manufactured", "Manufactured"),
                    ("encoded",      "Encoded"),
                ]:
                    for item in event.get(journal_key, []):
                        all_materials.append({
                            "itemName":     item.get("Name", ""),
                            "itemCount":    int(item.get("Count", 0)),
                            "itemCategory": category,
                        })
                if all_materials:
                    self._push(ts, "setCommanderInventoryMaterials", all_materials)

            case "ShipLockerMaterials":
                items = []
                for category, key in [("data", "Data"), ("goods", "Goods"), ("assets", "Assets")]:
                    for item in event.get(key, []):
                        name = item.get("Name", "")
                        if name:
                            items.append({
                                "itemName":     name,
                                "itemCount":    int(item.get("Count", 0)),
                                "itemCategory": category,
                            })
                self._micro_items = items
                if items:
                    self._push(ts, "setCommanderInventoryMicroResources", items)

            case "Cargo":
                cargo = self._read_cargo_json()
                if cargo:
                    self._push(ts, "setCommanderInventoryCargo", cargo)

            case "ShipyardBuy":
                # Do NOT send setCommanderShip here — the Loadout event that follows
                # will send both setCommanderShip and setCommanderShipLoadout together.
                # Clear dedup cache so the next Loadout is always sent.
                self._last_loadout = None

            case "ShipyardSell":
                ship_type = event.get("ShipType", "")
                ship_id   = event.get("SellShipID")
                if ship_type:
                    d = {"shipType": ship_type}
                    if ship_id is not None:
                        d["shipGameID"] = int(ship_id)
                    self._push(ts, "setCommanderShipDestroyed", d)

            case "StoredShips":
                def _push_stored(ship, in_garage: bool) -> None:
                    stype = ship.get("ShipType", "")
                    if not stype:
                        return
                    d: dict = {"shipType": stype, "isCurrentShip": False, "shipInGarage": in_garage}
                    sid = ship.get("ShipID")
                    if sid is not None: d["shipGameID"] = int(sid)
                    sname  = ship.get("Name")
                    sident = ship.get("Ident")
                    if sname:  d["shipName"]  = sname
                    if sident: d["shipIdent"] = sident
                    val = ship.get("Value")
                    if val is not None: d["shipHullValue"] = int(val)
                    hot = ship.get("Hot")
                    if hot is not None: d["shipIsHot"] = bool(hot)
                    if in_garage:
                        loc = ship.get("StarSystem")
                        sta = ship.get("StationName")
                        if loc: d["shipStarSystem"] = loc
                        if sta: d["shipStation"]    = sta
                        in_t = ship.get("InTransit")
                        if in_t is not None: d["shipInTransit"] = bool(in_t)
                    self._push(ts, "setCommanderShip", d)
                for ship in event.get("ShipsHere", []):
                    _push_stored(ship, False)
                for ship in event.get("ShipsRemote", []):
                    _push_stored(ship, True)

            case "ShipyardSwap":
                # Wait for subsequent Loadout event
                self._last_loadout = None

            case "SetUserShipName":
                ship_type = event.get("Ship", "")
                if ship_type:
                    d: dict = {"shipType": ship_type, "isCurrentShip": True}
                    sid = event.get("ShipID")
                    if sid is not None:
                        d["shipGameID"] = int(sid)
                    name  = event.get("UserShipName")
                    ident = event.get("UserShipId")
                    if name:  d["shipName"]  = name
                    if ident: d["shipIdent"] = ident
                    self._push(ts, "setCommanderShip", d)

            case "Died":
                killer_ship = event.get("KillerShip", "")
                d: dict = {}
                if killer_ship:
                    d["killerShipType"] = killer_ship
                    d["isPlayerKill"]   = bool(event.get("KillerRank") is not None)
                self._push(ts, "addCommanderCombatDeath", d)

            case "SellOrganicData":
                bio_data = event.get("BioData", [])
                organisms = []
                for entry in bio_data:
                    species = entry.get("Species_Localised") or entry.get("Species", "")
                    genus   = entry.get("Genus_Localised")   or entry.get("Genus", "")
                    value   = int(entry.get("Value", 0))
                    bonus   = int(entry.get("Bonus", 0))
                    if species:
                        organisms.append({
                            "speciesName": species,
                            "genusName":   genus,
                            "reward":      value + bonus,
                        })
                if organisms:
                    self._push(ts, "addCommanderExobiology", organisms)

            case "CommunityGoalJoin":
                cgid = event.get("CGID")
                if cgid is not None:
                    self._push(ts, "addCommanderCommunityGoalProgress", {
                        "communitygoalGameID": int(cgid),
                        "communitygoalName":   event.get("Name", ""),
                        "starsystemName":      event.get("SystemName", ""),
                        "stationName":         event.get("MarketName", ""),
                        "percentileBand":      0,
                        "contribution":        0,
                    })

            case "CommunityGoalReward":
                cgid   = event.get("CGID")
                reward = event.get("Reward", 0)
                if cgid is not None:
                    self._push(ts, "addCommanderCommunityGoalProgress", {
                        "communitygoalGameID": int(cgid),
                        "communitygoalName":   event.get("Name", ""),
                        "contribution":        int(reward),
                        "isCompleted":         True,
                    })

            case "MulticrewJoin":
                self._push(ts, "addCommanderFleetActivity", {
                    "activityType":  "multicrew",
                    "isJoining":     True,
                    "shipType":      event.get("ShipType", ""),
                    "commanderName": event.get("CaptainName", ""),
                })

            case "MulticrewEnd":
                self._push(ts, "addCommanderFleetActivity", {
                    "activityType":   "multicrew",
                    "isJoining":      False,
                    "timeInSession":  int(event.get("Timespan", 0)),
                })

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _read_cargo_json(self) -> list[dict]:
        """Read Cargo.json and return Inara-formatted cargo list."""
        from pathlib import Path as _Path
        import json as _json, builtins as _bi
        jdir = getattr(self.core, "journal_dir", None)
        if jdir is None:
            return []
        path = _Path(jdir) / "Cargo.json"
        try:
            data = _json.load(_bi.open(path, encoding="utf-8"))
        except Exception:
            return []
        result = []
        for item in data.get("Inventory", []):
            name = item.get("Name", "")
            if name:
                result.append({
                    "itemName":   name,
                    "itemCount":  int(item.get("Count", 1)),
                    "itemStolen": bool(item.get("Stolen", False)),
                })
        return result

    def _track(self, ev: str, event: dict) -> None:
        """Maintain internal ship/location state from raw journal events."""
        if ev == "Commander":
            name = event.get("Name")
            if name:
                self._cmdr_name = name

        elif ev in ("FSDJump", "CarrierJump", "Location"):
            self._system_name = event.get("StarSystem") or self._system_name
            pos = event.get("StarPos")
            if pos:
                self._star_pos = pos

        elif ev == "Loadout":
            ship_type = event.get("Ship")
            ship_id   = event.get("ShipID")
            if ship_type:
                self._ship_type = ship_type
            if ship_id is not None:
                self._ship_id = int(ship_id)

        elif ev in ("ShipyardSwap", "ShipyardBuy"):
            ship_type = event.get("ShipType")
            ship_id   = event.get("ShipID") or event.get("NewShipID")
            if ship_type:
                self._ship_type = ship_type
            if ship_id is not None:
                self._ship_id = int(ship_id)

    def push_credits(self, credits: int) -> None:
        """Push an authoritative liquid credit balance to Inara.
        Called by the CAPI plugin after a successful /profile poll.
        Uses current time as the event timestamp.
        """
        import time
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._push(ts, "setCommanderCredits", {"commanderCredits": int(credits)})

    def _push(self, timestamp: str, event_name: str, event_data) -> None:
        """Enqueue a single Inara API event."""
        if self._sender:
            self._sender.push({
                "eventName":      event_name,
                "eventTimestamp": timestamp,
                "eventData":      event_data,
            })

    def _push_ranks(self, timestamp: str) -> None:
        """Send the accumulated rank snapshot as a combined setCommanderRankPilot."""
        if not self._rank_values:
            return
        ranks = []
        for key, value in self._rank_values.items():
            entry: dict = {"rankName": key, "rankValue": value}
            progress = self._rank_progress.get(key)
            if progress is not None:
                entry["rankProgress"] = round(progress, 4)
            ranks.append(entry)
        self._push(timestamp, "setCommanderRankPilot", ranks)

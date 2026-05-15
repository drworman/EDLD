"""
components/inara.py — Inara API uploader for EDLD.

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

The commander name is sourced from journal data (state.pilot_name, populated
by the commander plugin from the Commander/LoadGame events), so there is no
CommanderName setting to keep in sync.  The API key must match the
commander on Inara's end; mismatches surface as auth errors at send time.

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
from core import debug as _dbg
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
}


# ── Sender thread ─────────────────────────────────────────────────────────────

class _Sender(threading.Thread):
    """
    Background thread — batches Inara API events and POSTs them.

    Call push(event_dict) to enqueue an individual Inara event.
    Call flush() to force an immediate send of the accumulated batch.
    Call stop() for clean shutdown.
    """

    def __init__(self, cmdr_provider, api_key: str, queue_file) -> None:
        super().__init__(daemon=True, name="inara-sender")
        # cmdr_provider: callable returning the current commander name as a
        # string.  Resolved at send time rather than baked in at __init__ so
        # the plugin doesn't need a config value — it reads from
        # state.pilot_name once the journal Commander event arrives.  When
        # the provider returns an empty string (pilot_name not yet known),
        # _send_batch persists the queue and skips the request.
        self._cmdr_provider = cmdr_provider
        self._key           = api_key
        self._queue_file    = queue_file
        self._q             = queue.Queue()
        self._stop_evt      = threading.Event()
        self._last_send     = 0.0

    def push(self, inara_event: dict) -> None:
        self._q.put(inara_event)

    def flush(self) -> None:
        self._q.put(_FLUSH_SENTINEL)

    def stop(self) -> None:
        self._stop_evt.set()
        self._q.put(None)

    def run(self) -> None:
        _dbg.info(f"  [Inara] sender thread entering main loop "
                  f"(queue file: {self._queue_file})")
        time.sleep(STARTUP_DELAY_S)
        self._drain_disk()

        batch: list[dict] = []
        push_count = 0   # total events pushed; logged periodically as a heartbeat
        last_heartbeat = time.monotonic()

        while not self._stop_evt.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                if batch and (time.monotonic() - self._last_send >= SEND_INTERVAL_S):
                    self._send_batch(batch)
                    batch = []
                # Heartbeat once a minute — confirms the sender is alive and
                # surfaces "queue is empty, no events arriving" cases.
                if time.monotonic() - last_heartbeat >= 60:
                    _dbg.log(f"  [Inara] sender heartbeat: "
                             f"pushed {push_count} events since start, "
                             f"batch={len(batch)}, last_send={self._last_send:.0f}")
                    last_heartbeat = time.monotonic()
                continue
            push_count += 1

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

        # Resolve commander name at send time.  Source is journal data via
        # state.pilot_name — config no longer carries it.  When pilot_name
        # is not yet known (Commander/LoadGame haven't arrived) Inara would
        # reject with a generic auth error; persist and retry later instead.
        try:
            cmdr = (self._cmdr_provider() or "").strip()
        except Exception:
            cmdr = ""
        if not cmdr:
            _dbg.info(
                f"  [Inara] Deferring send — commander name not yet known "
                f"(journal Commander/LoadGame missing); "
                f"persisting {len(events)} event(s) to disk."
            )
            self._persist(events)
            return

        payload = {
            "header": {
                "appName":        APP_NAME,
                "appVersion":     APP_VERSION,
                "isDeveloped":    False,
                "APIkey":         self._key,
                "commanderName":  cmdr,
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
            _dbg.log(f"  [Inara] POST {len(events)} event(s) for "
                     f"commander={cmdr!r}")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                self._last_send = time.monotonic()
                body = resp.read().decode("utf-8")
                result = json.loads(body) if body.strip() else {}
                header_status = result.get("header", {}).get("eventStatus", 200)
                if header_status in (200, 204):
                    _dbg.log(f"  [Inara] batch accepted (HTTP {resp.status}, "
                             f"header_status={header_status}, "
                             f"{len(events)} event(s))")
                else:
                    msg = result.get("header", {}).get("eventStatusText", "")
                    _dbg.info(f"  [Inara] API header error {header_status}: {msg}")
                    # 400 = bad request — no point retrying
                    if header_status != 400:
                        self._persist(events)

        except urllib.error.HTTPError as e:
            _dbg.info(f"  [Inara] HTTP {e.code} — queuing {len(events)} event(s) to disk")
            if e.code != 400:
                self._persist(events)
        except Exception as exc:
            _dbg.info(f"  [Inara] Send error ({type(exc).__name__}: {exc}) — queuing to disk")
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
            _dbg.info(f"  [Inara] Failed to persist events to disk: {e}")

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
            _dbg.info(f"  [Inara] Replaying {len(events)} queued event(s) from disk...")
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
    # Loads by default, matching the other integration plugins (eddn,
    # edsm, edastro).  Whether the plugin actually *runs* is decided by
    # the user's config — see the cfg["Enabled"] check in on_load.  The
    # plugin_states.json menu toggle is a second-level override on top.
    PLUGIN_DEFAULT_ENABLED = True

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
        # Total wealth
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

        # Wealth tracking — replicates Inara's journal-import behavior.
        # Statistics events provide Bank_Account.Current_Wealth which is FDev's
        # all-up wealth (credits + ships + modules + carrier purchase + carrier
        # services + carrier bank balance).  Inara holds the non-credits
        # portion of that figure constant between Statistics events and adjusts
        # only by credit deltas.  We replicate that: cache the most recent
        # Current_Wealth and the credits balance at that moment, then on every
        # subsequent commanderCredits push compute commanderAssets via
        # carry-forward = _last_wealth + (current_credits - _last_wealth_credits).
        # Skipping the bundled assets push (when we have no Statistics anchor
        # yet) creates the 5.7B "no marker" entries we previously saw — Inara
        # falls back to its own internal rollup which excludes carrier.
        self._last_wealth:         int | None = None
        self._last_wealth_credits: int | None = None
        self._last_credits:        int | None = None

        # Fleet reconciliation state (Changes 3+4)
        # ── _seen_ship_ids:  numeric ShipIDs we've sent setCommanderShip for at
        #    any point.  Persisted to data.json so cross-run sells/transfers
        #    we missed can still be reconciled against the next CAPI poll.
        # ── _reconciled:     one-shot flag.  Reconcile fires on the first event
        #    after CAPI's /profile poll has populated state.capi_raw, then
        #    never again until next process start.
        self._seen_ship_ids:   set[int] = set()
        self._reconciled:      bool     = False
        try:
            saved = self.storage.read_json("data.json") or {}
            for x in saved.get("seen_ship_ids", []):
                try:
                    self._seen_ship_ids.add(int(x))
                except (TypeError, ValueError):
                    continue
        except Exception:
            pass

        cfg = core.load_setting("Inara", CFG_DEFAULTS, warn=False)

        if not bool(core.cfg.app_settings.get("PrimaryInstance", True)):
            _dbg.info("  [Inara] Uploads suppressed (PrimaryInstance = false)")
            return
        if not cfg["Enabled"]:
            return
        if not cfg["ApiKey"]:
            _dbg.info(
                "  [Inara] Disabled — ApiKey must be set in config.toml "
                "under [Inara] (commander name is sourced from journal)"
            )
            return

        self._enabled = True
        # Commander name comes from journal data via state.pilot_name —
        # the commander plugin populates it on the Commander/LoadGame events.
        # The sender resolves it at send time, persisting events if pilot_name
        # is empty (e.g. before journal preload finishes).
        cmdr_provider = lambda: (getattr(core.state, "pilot_name", None) or "")
        self._sender  = _Sender(
            cmdr_provider, cfg["ApiKey"], self.storage.file_path("queue.jsonl"),
        )
        self._sender.start()

        # Read path — periodic getCommunityGoals fetch.  Hourly cadence
        # comfortably fits within Inara's 2-req/min limit alongside the
        # upload sender.  The reader is a separate thread, not gated on
        # _Sender, so it won't be delayed by upload bursts.  Initial fetch
        # happens 30 s after on_load so journal preload has settled.
        if not hasattr(core.state, "inara_community_goals"):
            core.state.inara_community_goals = []
            core.state.inara_community_goals_ts = 0.0
        self._cg_stop_evt = threading.Event()
        self._cg_thread = threading.Thread(
            target=self._cg_reader_loop,
            daemon=True,
            name="inara-cg-reader",
        )
        self._cg_thread.start()

        # _cmdr_name will populate once the Commander/LoadGame journal events
        # arrive (handled below in the event dispatch).  Until then the load
        # note reflects "pending"; after pilot_name lands, sends start flowing.
        self._load_note = "enabled (commander pending journal preload)"

    def on_unload(self) -> None:
        # Persist tracked ship IDs so a cross-run sell can be reconciled
        # against the next CAPI poll.  Best-effort — never block shutdown.
        try:
            self._save_seen()
        except Exception:
            pass
        if hasattr(self, "_cg_stop_evt"):
            self._cg_stop_evt.set()
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

        # ── Fleet reconciliation (one-shot, on first CAPI-ready event) ────────
        # Cheap fast-path: if we've already reconciled, this is a single bool
        # check.  Otherwise tries to reconcile; the method itself bails out
        # quickly when CAPI data isn't ready yet.
        if not self._reconciled:
            try:
                self._reconcile_fleet(state, ts)
            except Exception as e:
                # Never let reconciliation errors break event processing.
                _dbg.info(f"  [Inara] fleet reconcile error: {e}")
                self._reconciled = True  # don't retry indefinitely on a broken state

        match ev:

            case "LoadGame":
                credits = event.get("Credits")
                if credits is not None and credits >= 0:
                    self._last_credits = int(credits)
                    payload: dict = {"commanderCredits": int(credits)}
                    # Bundle commanderAssets via carry-forward when we have
                    # a Statistics anchor.  Without bundling, Inara falls
                    # back to its internal rollup (no carrier), creating
                    # the 5.7B fallback entries we don't want.
                    wealth = self._wealth_for_credits(int(credits))
                    if wealth is not None:
                        payload["commanderAssets"] = int(wealth)
                    self._push(ts, "setCommanderCredits", payload)
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

            # Total wealth snapshot.  Bank_Account.Current_Wealth is FDev's
            # canonical all-up wealth and matches what Inara's journal-import
            # path attaches to entries imported directly.  Push it unmodified
            # as commanderAssets, then cache the snapshot (wealth + credits at
            # this moment) so subsequent commanderCredits pushes can carry
            # forward via _wealth_for_credits.
            case "Statistics":
                bank   = event.get("Bank_Account", {})
                wealth = bank.get("Current_Wealth")
                if wealth is not None and wealth >= 0:
                    self._push(ts, "setCommanderCredits",
                               {"commanderAssets": int(wealth)})
                    self._last_wealth = int(wealth)
                    # Anchor the carry-forward computation on the credit
                    # balance current at this moment.  Statistics doesn't
                    # carry credits itself; use the most recently observed
                    # value (typically a LoadGame from seconds earlier).
                    if self._last_credits is not None:
                        self._last_wealth_credits = self._last_credits

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
                    self._push_ship(ts, ship_data)

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
                # Mirror the deletion in our seen set so reconcile won't
                # ever try to re-emit destroy for an already-sold ship.
                if ship_id is not None:
                    try:
                        self._seen_ship_ids.discard(int(ship_id))
                        self._save_seen()
                    except (TypeError, ValueError):
                        pass

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
                    # Change 2: StoredShips carries hull only — augment with
                    # CAPI's modules value so Inara doesn't keep an inflated
                    # stale figure from a pre-strip Loadout.
                    capi_mods = self._capi_modules_value(state, sid)
                    if capi_mods is not None:
                        d["shipModulesValue"] = capi_mods
                    hot = ship.get("Hot")
                    if hot is not None: d["shipIsHot"] = bool(hot)
                    if in_garage:
                        loc = ship.get("StarSystem")
                        sta = ship.get("StationName")
                        if loc: d["shipStarSystem"] = loc
                        if sta: d["shipStation"]    = sta
                        in_t = ship.get("InTransit")
                        if in_t is not None: d["shipInTransit"] = bool(in_t)
                    self._push_ship(ts, d)
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
                    self._push_ship(ts, d)

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

    # ── Read path: Community Goals ────────────────────────────────────────────

    # How often the reader thread polls Inara for the current CG list.
    # CG state changes slowly (hourly tier updates at most); 60 min keeps
    # us well under Inara's 2-req/min limit.
    _CG_REFRESH_INTERVAL_S = 60 * 60
    _CG_INITIAL_DELAY_S    = 30

    def _cg_reader_loop(self) -> None:
        """Background thread: periodically pull getCommunityGoals from Inara
        and publish the result on state.inara_community_goals.  Failures are
        logged but never raise — the upload pipeline must keep working."""
        # Wait briefly so journal preload settles before our first HTTP call.
        if self._cg_stop_evt.wait(self._CG_INITIAL_DELAY_S):
            return
        while not self._cg_stop_evt.is_set():
            try:
                self._fetch_community_goals()
            except Exception as exc:
                _dbg.info(f"  [Inara] CG fetch error ({type(exc).__name__}: {exc})")
            if self._cg_stop_evt.wait(self._CG_REFRESH_INTERVAL_S):
                return

    def _fetch_community_goals(self) -> None:
        """One-shot fetch of getCommunityGoals.  Stores the result list on
        state.inara_community_goals (oldest discoverable structure: each
        entry has goalName, goalSystem, goalStation, contributors,
        currentTotal, top tier rewards, etc — the exact fields are what
        Inara returns and we pass through unmodified)."""
        import time
        # Commander name comes from journal data via state.pilot_name.  If
        # not yet populated, skip this cycle — the next interval will retry.
        cmdr = (getattr(self.core.state, "pilot_name", None) or "").strip()
        if not cmdr:
            return
        ts_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = {
            "header": {
                "appName":        APP_NAME,
                "appVersion":     APP_VERSION,
                "isDeveloped":    False,
                "APIkey":         self._sender._key if self._sender else "",
                "commanderName":  cmdr,
            },
            "events": [
                {
                    "eventName":      "getCommunityGoalsRecent",
                    "eventTimestamp": ts_iso,
                    "eventData":      {},
                },
            ],
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
                body = resp.read().decode("utf-8")
        except Exception as exc:
            _dbg.info(f"  [Inara] CG fetch HTTP error ({type(exc).__name__}: {exc})")
            return

        try:
            result = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError as exc:
            _dbg.info(f"  [Inara] CG fetch — unparseable response ({exc})")
            return

        header_status = result.get("header", {}).get("eventStatus", 200)
        if header_status not in (200, 204):
            msg = result.get("header", {}).get("eventStatusText", "")
            _dbg.info(f"  [Inara] CG fetch header error {header_status}: {msg}")
            return

        # The response events array mirrors the request.  Find the
        # getCommunityGoals reply by position (we only sent one event).
        events = result.get("events") or []
        if not events:
            return
        ev = events[0]
        ev_status = ev.get("eventStatus", 200)
        if ev_status not in (200, 204):
            _dbg.info(
                f"  [Inara] getCommunityGoals returned status {ev_status}: "
                f"{ev.get('eventStatusText','')}"
            )
            return
        cgs = ev.get("eventData") or []
        if not isinstance(cgs, list):
            return
        # Publish on state.  Other plugins / UI blocks can consume.
        import time as _t
        self.core.state.inara_community_goals    = cgs
        self.core.state.inara_community_goals_ts = _t.time()
        _dbg.info(f"  [Inara] Community Goals refreshed: {len(cgs)} active")

    def get_community_goals(self) -> list:
        """Public accessor — returns the most recent CG list (may be empty
        if fetch hasn't completed yet).  Callable via
        core.plugin_call('inara', 'get_community_goals')."""
        return list(getattr(self.core.state, "inara_community_goals", []) or [])

    def push_credits(self, credits: int) -> None:
        """Push an authoritative liquid credit balance to Inara.
        Called by the CAPI plugin after a successful /profile poll.
        Uses current time as the event timestamp.

        Bundles commanderAssets via carry-forward when a Statistics anchor
        exists, so this push doesn't create the 5.7B fallback entries that
        Inara generates when given commanderCredits without an accompanying
        commanderAssets value.
        """
        import time
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._last_credits = int(credits)
        payload: dict = {"commanderCredits": int(credits)}
        wealth = self._wealth_for_credits(int(credits))
        if wealth is not None:
            payload["commanderAssets"] = int(wealth)
        self._push(ts, "setCommanderCredits", payload)

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

    # ── Fleet reconciliation (Changes 3+4) ────────────────────────────────────

    def _push_ship(self, ts: str, ship_data: dict) -> None:
        """setCommanderShip wrapper that records the ship ID for reconciliation.

        Every code path that sends setCommanderShip should go through this so
        we have a complete record of ships Inara has been told about.  The
        record persists across runs in data.json.
        """
        self._push(ts, "setCommanderShip", ship_data)
        sid = ship_data.get("shipGameID")
        if sid is None:
            return
        try:
            sid_int = int(sid)
        except (TypeError, ValueError):
            return
        if sid_int in self._seen_ship_ids:
            return
        self._seen_ship_ids.add(sid_int)
        self._save_seen()

    def _save_seen(self) -> None:
        """Persist _seen_ship_ids to data.json.  Best-effort."""
        try:
            self.storage.write_json(
                {"seen_ship_ids": sorted(self._seen_ship_ids)},
                "data.json",
            )
        except Exception:
            pass

    def _reconcile_fleet(self, state, ts: str) -> None:
        """One-shot fleet reconciliation against the authoritative CAPI roster.

        Runs once per process, on the first event after a successful CAPI
        /profile poll has populated state.capi_raw["profile"].  Three effects:

          1. Ships in _seen_ship_ids that are no longer in CAPI get a
             setCommanderShipDestroyed — these are sells/transfers we missed
             while EDLD was offline (or, on first run, will be empty).
          2. Every ship currently in CAPI is re-emitted via setCommanderShip
             with hull + modules values from CAPI, so stored ships' values
             in Inara match reality even if their last journal Loadout is
             ancient.
          3. Every ship currently in CAPI also gets a setCommanderShipLoadout
             built from CAPI's per-ship modules dict — gives Inara correct
             per-module engineering data for stored ships, which otherwise
             only get loadout uploads when swapped to in-game.

        Skipped while state.in_preload is True so historical bootstrap doesn't
        trigger a flush.
        """
        if self._reconciled:
            return
        if not self._enabled or self._sender is None:
            return
        if getattr(state, "in_preload", False):
            return

        capi_profile = (getattr(state, "capi_raw", {}) or {}).get("profile") or {}
        capi_ships   = capi_profile.get("ships") or {}
        if not capi_ships:
            return  # CAPI not yet populated — try again next event

        # Build the set of ShipIDs CAPI considers currently owned.
        capi_ids: set[int] = set()
        for sid_key in capi_ships.keys():
            try:
                capi_ids.add(int(sid_key))
            except (TypeError, ValueError):
                continue

        # 1) Phantom cleanup — ships we've reported to Inara that no longer exist.
        stale = self._seen_ship_ids - capi_ids
        for sid in sorted(stale):
            self._push(ts, "setCommanderShipDestroyed", {"shipGameID": int(sid)})
            self._seen_ship_ids.discard(sid)

        # 2) Refresh values for every currently-owned ship.
        current_ship_id = (capi_profile.get("ship") or {}).get("id")
        try:
            current_ship_id = int(current_ship_id) if current_ship_id is not None else None
        except (TypeError, ValueError):
            current_ship_id = None

        for sid_key, ship in capi_ships.items():
            try:
                sid = int(sid_key)
            except (TypeError, ValueError):
                continue
            stype = (ship.get("name") or "").lower()
            if not stype:
                continue
            d: dict = {
                "shipType":      stype,
                "shipGameID":    sid,
                "isCurrentShip": (sid == current_ship_id),
                "shipInGarage":  (sid != current_ship_id),
            }
            if ship.get("shipName"):
                d["shipName"]  = ship["shipName"]
            if ship.get("shipID"):  # alphanumeric ident, e.g. "URS-10"
                d["shipIdent"] = ship["shipID"]

            val = ship.get("value") or {}
            hull_val = val.get("hull")
            mod_val  = val.get("modules")
            # Only set values when CAPI has meaningful data.  CAPI sometimes
            # reports 0 for stored ships; sending 0 would clobber a good
            # value from a prior journal Loadout.
            if isinstance(hull_val, (int, float)) and hull_val > 0:
                d["shipHullValue"] = int(hull_val)
            if isinstance(mod_val, (int, float)) and mod_val > 0:
                d["shipModulesValue"] = int(mod_val)

            # Location for stored ships, when CAPI has it.
            if sid != current_ship_id:
                ss = ship.get("starsystem") or {}
                if isinstance(ss, dict) and ss.get("name"):
                    d["shipStarSystem"] = ss["name"]
                st = ship.get("station") or {}
                if isinstance(st, dict) and st.get("name"):
                    d["shipStation"] = st["name"]

            self._push_ship(ts, d)

            # Change 5: emit setCommanderShipLoadout from CAPI per-ship modules.
            # The active ship's loadout is already kept fresh by the journal
            # Loadout handler — but stored ships only get loadout uploads here
            # (or never, before this change).  CAPI's ships[<id>].modules dict
            # carries the same data as a journal Loadout, just with different
            # key casing; _capi_loadout_for_ship translates.
            loadout = self._capi_loadout_for_ship(ship, stype, sid)
            if loadout is not None:
                self._push(ts, "setCommanderShipLoadout", loadout)

        # Make sure every current ship is in the seen set, even ones we
        # may not have touched (defensive).
        self._seen_ship_ids |= capi_ids
        self._save_seen()
        self._reconciled = True

    def _capi_loadout_for_ship(self, ship: dict, ship_type: str,
                               ship_id: int | None) -> dict | None:
        """Translate a CAPI per-ship loadout dict into Inara's
        setCommanderShipLoadout payload.  Returns None when CAPI doesn't
        carry usable module data for this ship.

        CAPI schema (per ship):
            modules: { "<slotName>": {
                name, on, priority, value, health, hot,
                engineering: { BlueprintName, Level, Quality,
                               ExperimentalEffect, Modifiers: [...] }
            }, ... }

        Inara setCommanderShipLoadout schema:
            shipType, shipGameID, shipLoadout: [
                { slotName, itemName, isOn, itemPriority, itemHealth,
                  itemValue?, isHot?, engineering?: {
                      blueprintName, blueprintLevel, blueprintQuality,
                      experimentalEffect?, modifiers: [
                          { name, value?, originalValue?, lessIsGood? }
                      ]
                  } }, ...
            ]
        """
        if not ship_type:
            return None
        capi_modules = ship.get("modules") or {}
        if not isinstance(capi_modules, dict) or not capi_modules:
            return None

        loadout_modules: list[dict] = []
        for slot_name, mod in capi_modules.items():
            if not isinstance(mod, dict):
                continue
            item = mod.get("name", "")
            if not slot_name or not item:
                continue
            entry: dict = {
                "slotName":     slot_name,
                "itemName":     item,
                "isOn":         bool(mod.get("on", True)),
                "itemPriority": int(mod.get("priority", 0)),
            }
            # itemHealth: CAPI stores as 0–1000000 sometimes, 0–1 elsewhere.
            # Mirror the assets plugin's defensive handling.
            health = mod.get("health")
            if isinstance(health, (int, float)):
                hv = float(health)
                if hv > 1.0:
                    hv = hv / 1000000.0 if hv > 100 else hv / 100.0
                entry["itemHealth"] = round(max(0.0, min(1.0, hv)), 4)
            value = mod.get("value")
            if isinstance(value, (int, float)) and value > 0:
                entry["itemValue"] = int(value)
            hot = mod.get("hot")
            if hot is not None:
                entry["isHot"] = bool(hot)

            eng = mod.get("engineering")
            if isinstance(eng, dict) and eng.get("BlueprintName"):
                bp: dict = {
                    "blueprintName":  eng["BlueprintName"],
                    "blueprintLevel": int(eng.get("Level", 0)),
                    "blueprintQuality": round(float(eng.get("Quality", 0)), 2),
                }
                if eng.get("ExperimentalEffect"):
                    bp["experimentalEffect"] = eng["ExperimentalEffect"]
                bp["modifiers"] = []
                for m_in in (eng.get("Modifiers") or []):
                    if not isinstance(m_in, dict):
                        continue
                    m_out: dict = {"name": m_in.get("Label", "")}
                    # Preserve the same numeric/string discrimination the
                    # journal Loadout handler uses, so Inara sees consistent
                    # data regardless of which path emitted it.
                    if "OriginalValue" in m_in:
                        m_out["value"]         = m_in.get("Value")
                        m_out["originalValue"] = m_in["OriginalValue"]
                        m_out["lessIsGood"]    = int(m_in.get("LessIsGood", 0))
                    elif "ValueStr" in m_in:
                        m_out["value"] = m_in["ValueStr"]
                    elif "Value" in m_in:
                        m_out["value"] = m_in["Value"]
                    bp["modifiers"].append(m_out)
                entry["engineering"] = bp
            loadout_modules.append(entry)

        if not loadout_modules:
            return None
        out: dict = {"shipType": ship_type, "shipLoadout": loadout_modules}
        if ship_id is not None:
            out["shipGameID"] = int(ship_id)
        return out

    def _wealth_for_credits(self, current_credits: int) -> int | None:
        """Carry-forward commanderAssets value for a given credits balance.

        Replicates Inara's journal-import behavior: hold the non-credits
        portion of the most recent Statistics.Bank_Account.Current_Wealth
        constant, and adjust by the credit delta since that snapshot.

        Returns None until we've seen at least one Statistics event AND have
        a credits anchor for it — in that state the caller should push
        commanderCredits without commanderAssets, accepting that Inara may
        show a fallback rollup until the next Statistics arrives.
        """
        if self._last_wealth is None or self._last_wealth_credits is None:
            return None
        return self._last_wealth + (int(current_credits) - self._last_wealth_credits)

    def _capi_modules_value(self, state, ship_id: int | None) -> int | None:
        """Look up the CAPI-reported modules value for a given ship ID.

        Used by the StoredShips handler (Change 2) — StoredShips events
        carry only the hull value, so without this lookup Inara would keep
        a stale shipModulesValue from before the ship was de-fitted.
        Returns None when CAPI data is missing or zero.
        """
        if ship_id is None:
            return None
        capi_profile = (getattr(state, "capi_raw", {}) or {}).get("profile") or {}
        capi_ships   = capi_profile.get("ships") or {}
        ship         = capi_ships.get(str(ship_id)) or capi_ships.get(int(ship_id)) or {}
        mod_val      = (ship.get("value") or {}).get("modules")
        if isinstance(mod_val, (int, float)) and mod_val > 0:
            return int(mod_val)
        return None


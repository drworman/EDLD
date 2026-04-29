"""
components/edsm/plugin.py — EDSM journal uploader for EDLD.

Uploads journal events to the EDSM API (https://www.edsm.net/api-journal-v1).

Config [EDSM]:
    Enabled        = false          # opt-in
    CommanderName  = ""             # your EDSM commander name
    ApiKey         = ""             # your EDSM API key (from EDSM settings)

EDSM notes:
  - Live galaxy only; beta/legacy data is suppressed.
  - Rate limit: ~1 request per 10 s (360/hr).  We batch events and flush
    on session transitions to stay well within this.
  - A discard list is fetched at startup; events EDSM doesn't want are dropped.
  - Transient state fields (_systemAddress, _systemName, etc.) are injected
    into each event so EDSM can link entries to the galaxy map.
"""

import gzip
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

PLUGIN_VERSION     = "1.0.0"
EDSM_JOURNAL_URL   = "https://www.edsm.net/api-journal-v1"
EDSM_DISCARD_URL   = "https://www.edsm.net/api-journal-v1/discard"
SOFTWARE_NAME      = "EDLD"
SOFTWARE_VERSION   = VERSION
HTTP_TIMEOUT_S     = 15
SEND_INTERVAL_S    = 12      # minimum gap between POST requests (~5/min, well under 360/hr)
BATCH_MAX          = 50      # maximum events per POST
STARTUP_DELAY_S    = 10      # seconds after load before we begin uploading
def _queue_file() -> Path:
    return cmdr_data_dir() / "edsm_queue.jsonl"

# Events that are always suppressed regardless of discard list
_ALWAYS_SKIP = frozenset({
    "Fileheader",
    "continued",
    "Shutdown",
    "ShutDown",
})

# Events we subscribe to — broad set; discard list prunes at runtime
SUBSCRIBED_EVENTS = [
    "LoadGame", "Commander", "NewCommander", "ClearSavedGame",
    "Location", "FSDJump", "CarrierJump", "Docked", "Undocked",
    "SupercruiseEntry", "SupercruiseExit", "ApproachSettlement",
    "Scan", "SAAScanComplete", "SAASignalsFound", "FSSBodySignals",
    "FSSDiscoveryScan", "FSSSignalDiscovered", "NavBeaconScan",
    "BuyExplorationData", "SellExplorationData",
    "MarketBuy", "MarketSell", "BuyAmmo", "BuyDrones",
    "SellDrones", "RefuelAll", "RefuelPartial", "Repair",
    "RepairAll", "RebootRestore", "RestockVehicle", "FetchRemoteModule",
    "Missions", "MissionAccepted", "MissionCompleted", "MissionFailed",
    "MissionAbandoned", "MissionRedirected",
    "Bounty", "RedeemVoucher", "CrimeVictim", "Died",
    "Rank", "Progress", "Reputation", "Statistics", "Promotion",
    "Powerplay", "PowerplaySalary", "PowerplayDefect", "PowerplayJoin",
    "PowerplayLeave", "PowerplayVote", "PowerplayCollect",
    "EngineerProgress", "MaterialCollected", "MaterialDiscarded",
    "MaterialTrade", "MiningRefined", "ProspectedAsteroid",
    "Synthesis", "TechnologyBroker",
    "ShipyardBuy", "ShipyardSell", "ShipyardSwap", "ShipyardTransfer",
    "ModuleBuy", "ModuleSell", "ModuleSellRemote", "ModuleStore",
    "ModuleRetrieve", "ModuleSwap",
    "Loadout", "SetUserShipName",
    "StoredModules", "StoredShips",
    "CargoDepot", "CollectCargo", "EjectCargo", "SellMicroResources",
    "CrewHire", "CrewAssign", "CrewFire", "NpcCrewRank",
    "FactionKillBond", "CommitCrime", "PayFines", "PayLegacyFines",
    "PayBounties",
    "CommunityGoal", "CommunityGoalJoin", "CommunityGoalReward",
    "USSDrop", "Screenshot",
    "Touchdown", "Liftoff", "EmbarkDismembark",
    "CodexEntry",
    "ScanOrganic", "SellOrganicData",
    "SRVHandbrake",  # included so discard list can prune it
    "Music",
    "ReceiveText", "SendText",
]

CFG_DEFAULTS = {
    "Enabled":       False,
    "CommanderName": "",
    "ApiKey":        "",
}


# ── Sender thread ─────────────────────────────────────────────────────────────

class _Sender(threading.Thread):
    """
    Background thread that batches events and POSTs them to EDSM.

    Enqueue with push(event_dict).
    Call flush() to force-drain the in-process batch (e.g. on FSDJump).
    Call stop() for clean shutdown.
    """

    def __init__(self, commander_name: str, api_key: str, queue_file) -> None:
        super().__init__(daemon=True, name="edsm-sender")
        self._cmdr      = commander_name
        self._key       = api_key
        self._queue_file = queue_file
        self._q:        queue.Queue = queue.Queue()
        self._stop_evt  = threading.Event()
        self._last_send = 0.0

    def push(self, event: dict) -> None:
        self._q.put(event)

    def flush(self) -> None:
        """Signal an immediate drain of the in-process queue."""
        self._q.put(_FLUSH_SENTINEL)

    def stop(self) -> None:
        self._stop_evt.set()
        self._q.put(None)   # unblock get()

    def run(self) -> None:
        time.sleep(STARTUP_DELAY_S)

        # Drain disk queue from a previous interrupted session
        self._drain_disk()

        batch: list[dict] = []

        while not self._stop_evt.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                # Flush batch if we've accumulated something and enough time has passed
                if batch and (time.monotonic() - self._last_send >= SEND_INTERVAL_S):
                    self._send_batch(batch)
                    batch = []
                continue

            if item is None:
                # Shutdown signal
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

        # Final flush on stop
        if batch:
            self._send_batch(batch)

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _send_batch(self, events: list[dict]) -> None:
        """POST a batch of events to EDSM.  Persist to disk on failure."""
        gap = SEND_INTERVAL_S - (time.monotonic() - self._last_send)
        if gap > 0:
            time.sleep(gap)

        payload = {
            "commanderName": self._cmdr,
            "apiKey":        self._key,
            "fromSoftware":  SOFTWARE_NAME,
            "fromSoftwareVersion": SOFTWARE_VERSION,
            "message":       events,
        }
        try:
            raw     = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            encoded = gzip.compress(raw)
            req = urllib.request.Request(
                EDSM_JOURNAL_URL,
                data=encoded,
                headers={
                    "Content-Type":     "application/json",
                    "Content-Encoding": "gzip",
                    "User-Agent":       f"{SOFTWARE_NAME}/{SOFTWARE_VERSION}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                self._last_send = time.monotonic()
                if resp.status != 200:
                    self._persist(events)

        except urllib.error.HTTPError as e:
            print(f"  [EDSM] HTTP {e.code} — queuing {len(events)} event(s) to disk")
            self._persist(events)
        except Exception as exc:
            print(f"  [EDSM] Send error ({type(exc).__name__}: {exc}) — queuing to disk")
            self._persist(events)

    # ── Disk persistence ──────────────────────────────────────────────────────

    def _persist(self, events: list[dict]) -> None:
        try:
            self._queue_file.parent.mkdir(parents=True, exist_ok=True)
            import builtins as _bi
            with _bi.open(self._queue_file, "a", encoding="utf-8") as f:
                for ev in events:
                    f.write(json.dumps({"queued_at": time.time(), "msg": ev}) + "\n")
        except Exception as e:
            print(f"  [EDSM] Failed to persist events to disk queue: {e}")

    def _drain_disk(self) -> None:
        if not self._queue_file.exists():
            return
        try:
            import builtins as _bi
            with _bi.open(self._queue_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return

        if not lines:
            return

        print(f"  [EDSM] Replaying {len(lines)} queued event(s) from disk...")

        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                events.append(record["msg"])
            except Exception:
                pass

        if events:
            # Send in batches with pacing
            for i in range(0, len(events), BATCH_MAX):
                chunk = events[i:i + BATCH_MAX]
                self._send_batch(chunk)
                if i + BATCH_MAX < len(events):
                    time.sleep(SEND_INTERVAL_S)

        try:
            self._queue_file.unlink(missing_ok=True)
        except Exception:
            pass


# Sentinel object — not a dict, so it's safe to put in the same queue as events
_FLUSH_SENTINEL = object()


# ── Plugin ────────────────────────────────────────────────────────────────────

class EDSMPlugin(BasePlugin):

    PLUGIN_NAME      = "edsm"
    PLUGIN_DISPLAY   = "EDSM Uploader"
    PLUGIN_DESCRIPTION = "Syncs commander travel history to Elite Dangerous Star Map (EDSM)."
    PLUGIN_VERSION   = PLUGIN_VERSION
    SUBSCRIBED_EVENTS = SUBSCRIBED_EVENTS

    def on_load(self, core) -> None:
        self.core          = core
        self._enabled      = False
        self._sender:      _Sender | None = None
        self._discard_set: frozenset[str] = frozenset()

        # Internal location/session tracking — mirrors EDDN plugin's approach.
        # We do NOT read from MonitorState; we maintain our own copies from
        # journal events directly so transient fields injected into EDSM
        # messages are always accurate.
        self._cmdr_name:      str        = ""
        self._game_version:   str        = ""
        self._game_build:     str        = ""
        self._system_name:    str | None = None
        self._system_address: int | None = None
        self._star_pos:       list | None = None   # [x, y, z]
        self._market_id:      int | None = None
        self._station_name:   str | None = None
        self._ship_id:        int | None = None    # ShipID integer from Loadout

        cfg = core.load_setting("EDSM", CFG_DEFAULTS, warn=False)

        if not bool(core.cfg.app_settings.get("PrimaryInstance", True)):
            print("  [EDSM] Uploads suppressed (PrimaryInstance = false)")
            return
        if not cfg["Enabled"]:
            return
        if not cfg["CommanderName"] or not cfg["ApiKey"]:
            print(
                "  [EDSM] Disabled — CommanderName and ApiKey must both be set in config.toml"
            )
            return

        self._enabled = True
        self._cmdr    = cfg["CommanderName"]
        self._key     = cfg["ApiKey"]

        # Fetch discard list in a background thread so startup isn't delayed
        threading.Thread(
            target=self._fetch_discard_list,
            daemon=True,
            name="edsm-discard",
        ).start()

        self._sender = _Sender(self._cmdr, self._key, self.storage.path / "queue.jsonl")
        self._sender.start()

        print(
            f"  [EDSM] Enabled — uploading as CMDR {self._cmdr}"
        )

    def on_unload(self) -> None:
        if self._sender:
            self._sender.stop()
            self._sender.join(timeout=5)

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event", "")

        # Always track session/location state regardless of enabled status,
        # so if the plugin is later enabled mid-session the fields are ready.
        self._update_tracking(ev, event)

        if not self._enabled or self._sender is None:
            return
        if ev in _ALWAYS_SKIP:
            return
        if ev in self._discard_set:
            return

        # Inject EDSM transient state fields from our own tracking
        enriched = dict(event)
        if self._system_name:
            enriched.setdefault("_systemName", self._system_name)
        if self._system_address is not None:
            enriched.setdefault("_systemAddress", self._system_address)
        if self._star_pos is not None:
            enriched.setdefault("_systemCoordinates", self._star_pos)
        if self._market_id is not None:
            enriched.setdefault("_marketId", self._market_id)
        if self._station_name is not None:
            enriched.setdefault("_stationName", self._station_name)
        if self._ship_id is not None:
            enriched.setdefault("_shipId", self._ship_id)

        enriched.pop("_logtime", None)
        self._sender.push(enriched)

        # Flush batch on key session transitions
        if ev in ("FSDJump", "CarrierJump", "Docked", "Undocked",
                  "Location", "LoadGame"):
            self._sender.flush()

    def _update_tracking(self, ev: str, event: dict) -> None:
        """Maintain internal location/session state from raw journal events."""
        if ev == "Fileheader":
            self._game_version = event.get("gameversion", "") or ""
            self._game_build   = event.get("build", "") or ""

        elif ev == "LoadGame":
            if not self._game_version:
                self._game_version = event.get("gameversion", "") or ""
            if not self._game_build:
                self._game_build = event.get("build", "") or ""

        elif ev == "Commander":
            name = event.get("Name", "")
            if name:
                self._cmdr_name = name

        elif ev in ("FSDJump", "CarrierJump", "Location"):
            self._system_name    = event.get("StarSystem") or self._system_name
            self._system_address = event.get("SystemAddress") or self._system_address
            pos = event.get("StarPos")
            if pos:
                self._star_pos = pos
            # Clear station context when jumping
            if ev in ("FSDJump", "CarrierJump"):
                self._market_id    = None
                self._station_name = None

        elif ev == "Docked":
            self._system_name    = event.get("StarSystem") or self._system_name
            self._system_address = event.get("SystemAddress") or self._system_address
            self._market_id      = event.get("MarketID") or self._market_id
            self._station_name   = event.get("StationName") or self._station_name

        elif ev == "Undocked":
            self._station_name = None
            self._market_id    = None

        elif ev == "Loadout":
            self._ship_id = event.get("ShipID") or self._ship_id

    # ── Discard list ──────────────────────────────────────────────────────────

    def _fetch_discard_list(self) -> None:
        try:
            req = urllib.request.Request(
                EDSM_DISCARD_URL,
                headers={"User-Agent": f"{SOFTWARE_NAME}/{SOFTWARE_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, list):
                        self._discard_set = frozenset(data)
        except Exception as exc:
            print(f"  [EDSM] Could not fetch discard list ({type(exc).__name__}: {exc})")

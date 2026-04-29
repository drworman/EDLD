"""
components/edastro/plugin.py — EDAstro journal uploader for EDLD.

Uploads journal events to EDAstro (https://edastro.com).

Config [EDAstro]:
    Enabled             = false   # opt-in
    UploadCarrierEvents = false   # CarrierStatus / CarrierJumpRequest are opt-in
                                  # (may expose carrier location to third parties)

EDAstro notes:
  - Anonymous — no API key required.
  - An event-interest list is fetched at startup; only requested events are sent.
  - Fills gaps EDDN/EDSM don't cover: Odyssey organic scans, Codex, fleet carriers.
  - Rate limit: 100 requests per 15 minutes (per EDAstro API headers).
  - Live galaxy only; beta data is suppressed.
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

PLUGIN_VERSION        = "1.0.0"
EDASTRO_UPLOAD_URL    = "https://edastro.com/api/journal"
EDASTRO_INTEREST_URL  = "https://edastro.com/api/journal/interested"
SOFTWARE_NAME         = "EDLD"
SOFTWARE_VERSION      = VERSION
HTTP_TIMEOUT_S        = 30
SEND_INTERVAL_S       = 10      # ~6/min, leaves comfortable headroom under 100/15 min
BATCH_MAX             = 30
STARTUP_DELAY_S       = 12      # stagger slightly behind EDSM startup
def _queue_file() -> Path:
    return cmdr_data_dir() / "edastro_queue.jsonl"

# Carrier events that require explicit opt-in
_CARRIER_EVENTS = frozenset({
    "CarrierStatus",
    "CarrierJumpRequest",
})

# Broad subscription list — event-interest endpoint prunes at runtime
SUBSCRIBED_EVENTS = [
    "Scan", "SAAScanComplete", "SAASignalsFound", "FSSBodySignals",
    "FSSDiscoveryScan", "FSSSignalDiscovered", "NavBeaconScan",
    "CodexEntry",
    "ScanOrganic", "SellOrganicData",
    "FSDJump", "CarrierJump", "Location",
    "Docked", "Undocked",
    "MarketBuy", "MarketSell",
    "MissionAccepted", "MissionCompleted", "MissionFailed", "MissionAbandoned",
    "Bounty", "RedeemVoucher",
    "Rank", "Progress", "Promotion",
    "Powerplay", "PowerplaySalary", "PowerplayCollect",
    "EngineerProgress",
    "MaterialCollected", "MaterialTrade",
    "MiningRefined", "ProspectedAsteroid",
    "ShipyardBuy", "ShipyardSell", "ModuleBuy", "ModuleSell",
    "Loadout",
    "CommunityGoal", "CommunityGoalJoin", "CommunityGoalReward",
    "CarrierStats", "CarrierJumpCancelled",
    "CarrierStatus",        # opt-in
    "CarrierJumpRequest",   # opt-in
]

CFG_DEFAULTS = {
    "Enabled":             False,
    "UploadCarrierEvents": False,
}

# Beta / legacy detection helper (mirrors EDDN plugin approach)
_BETA_TAGS = ("beta", "alpha", "test", "legacy")


def _is_beta(gameversion: str) -> bool:
    return any(t in gameversion.lower() for t in _BETA_TAGS)


# ── Sender thread ─────────────────────────────────────────────────────────────

class _Sender(threading.Thread):

    def __init__(self, queue_file) -> None:
        super().__init__(daemon=True, name="edastro-sender")
        self._queue_file = queue_file
        self._q         = queue.Queue()
        self._stop_evt  = threading.Event()
        self._last_send = 0.0

    def push(self, event: dict) -> None:
        self._q.put(event)

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
        gap = SEND_INTERVAL_S - (time.monotonic() - self._last_send)
        if gap > 0:
            time.sleep(gap)

        try:
            raw     = json.dumps(events, separators=(",", ":")).encode("utf-8")
            encoded = gzip.compress(raw)
            req = urllib.request.Request(
                EDASTRO_UPLOAD_URL,
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
            print(f"  [EDAstro] HTTP {e.code} — queuing {len(events)} event(s) to disk")
            self._persist(events)
        except TimeoutError:
            # Transient network timeout — queue for retry, don't flood the log
            self._persist(events)
        except Exception as exc:
            print(f"  [EDAstro] Send error ({type(exc).__name__}: {exc}) — queuing to disk")
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
            print(f"  [EDAstro] Failed to persist events to disk queue: {e}")

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

        print(f"  [EDAstro] Replaying {len(lines)} queued event(s) from disk...")
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
            for i in range(0, len(events), BATCH_MAX):
                chunk = events[i:i + BATCH_MAX]
                self._send_batch(chunk)
                if i + BATCH_MAX < len(events):
                    time.sleep(SEND_INTERVAL_S)

        try:
            self._queue_file.unlink(missing_ok=True)
        except Exception:
            pass


_FLUSH_SENTINEL = object()


# ── Plugin ────────────────────────────────────────────────────────────────────

class EDAstroPlugin(BasePlugin):

    PLUGIN_NAME        = "edastro"
    PLUGIN_DISPLAY     = "EDAstro Uploader"
    PLUGIN_DESCRIPTION = "Contributes exploration and carrier data to ED Astronomer (EDAstro)."
    PLUGIN_VERSION     = PLUGIN_VERSION
    SUBSCRIBED_EVENTS  = SUBSCRIBED_EVENTS

    def on_load(self, core) -> None:
        self.core                  = core
        self._enabled              = False
        self._carrier_opt_in       = False
        self._interest_set:        frozenset[str] = frozenset(SUBSCRIBED_EVENTS)
        self._sender: _Sender | None = None
        self._gameversion          = ""

        cfg = core.load_setting("EDAstro", CFG_DEFAULTS, warn=False)

        if not bool(core.cfg.app_settings.get("PrimaryInstance", True)):
            print("  [EDAstro] Uploads suppressed (PrimaryInstance = false)")
            return
        if not cfg["Enabled"]:
            return

        self._enabled        = True
        self._carrier_opt_in = bool(cfg["UploadCarrierEvents"])

        threading.Thread(
            target=self._fetch_interest_list,
            daemon=True,
            name="edastro-interest",
        ).start()

        self._sender = _Sender(self.storage.path / "queue.jsonl")
        self._sender.start()

        carrier_note = " (carrier events: on)" if self._carrier_opt_in else ""
        self._load_note = f"enabled{carrier_note}"

    def on_unload(self) -> None:
        if self._sender:
            self._sender.stop()
            self._sender.join(timeout=5)

    def on_event(self, event: dict, state) -> None:
        if not self._enabled or self._sender is None:
            return

        event_name = event.get("event", "")

        # Beta / legacy suppression
        gv = event.get("gameversion", self._gameversion)
        if gv:
            self._gameversion = gv
        if self._gameversion and _is_beta(self._gameversion):
            return

        # Carrier events require opt-in
        if event_name in _CARRIER_EVENTS and not self._carrier_opt_in:
            return

        # Only send events EDAstro is interested in
        if event_name not in self._interest_set:
            return

        ev_clean = {k: v for k, v in event.items() if k != "_logtime"}
        self._sender.push(ev_clean)

        if event_name in ("FSDJump", "CarrierJump", "Docked", "Location"):
            self._sender.flush()

    # ── Interest list ──────────────────────────────────────────────────────────

    def _fetch_interest_list(self) -> None:
        try:
            req = urllib.request.Request(
                EDASTRO_INTEREST_URL,
                headers={"User-Agent": f"{SOFTWARE_NAME}/{SOFTWARE_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, list) and data:
                        self._interest_set = frozenset(data)
        except Exception as exc:
            print(
                f"  [EDAstro] Could not fetch interest list "
                f"({type(exc).__name__}: {exc}) — using defaults"
            )

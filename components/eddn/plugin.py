"""
components/eddn/plugin.py — EDDN (Elite Dangerous Data Network) uploader.

Subscribes to relevant journal events and forwards anonymised, schema-compliant
messages to the EDDN gateway at https://eddn.edcd.io:4430/upload/

Behaviour
---------
- Opt-in via config.toml [EDDN] Enabled = true
- Reads Market.json / Outfitting.json / Shipyard.json from the journal directory
  when Market / Outfitting / Shipyard journal events fire
- Tracks game version/build from Fileheader (preferred) and LoadGame
- Tracks location (SystemAddress, StarSystem, StarPos) from FSDJump / Location /
  CarrierJump; cross-checks before augmenting events that lack coords
- Strips all _Localised keys recursively before sending
- Batches FSSSignalDiscovered events and flushes on the next non-FSSSignalDiscovered
- Beta detection: appends /test to $schemaRef when game version contains "beta"
  (case-insensitive) or gameversion starts with "3." (legacy/beta clients)
- Deduplication: commodity/outfitting/shipyard/fcmaterials track last-sent hash
  and skip identical sends
- Retry: failed messages are queued to disk (JSON lines) and retried every
  RETRY_INTERVAL_S seconds; 400/426 responses are dropped without retry

Config (config.toml)
--------------------
[EDDN]
Enabled       = false     # master switch; must be explicitly true to upload
UploaderID    = ""        # defaults to commander name if blank
TestMode      = false     # force /test schema suffix regardless of game version

Dependencies
------------
Standard library only (urllib.request, gzip, json, hashlib, threading, queue).
No requests, no third-party libraries.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import queue
import threading
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.plugin_loader import BasePlugin
from core.state import EDLD_DATA_DIR, PROGRAM, VERSION


# ── Constants ─────────────────────────────────────────────────────────────────

EDDN_ENDPOINT    = "https://eddn.edcd.io:4430/upload/"
SOFTWARE_NAME    = PROGRAM
SOFTWARE_VERSION = VERSION

# Retry queue on disk
def _queue_file() -> Path:
    return cmdr_data_dir() / "eddn_queue.jsonl"

# How often (seconds) the sender thread wakes to process the retry queue
RETRY_INTERVAL_S = 60

# How long (seconds) to wait before retrying a failed message (minimum)
RETRY_HOLD_S     = 60

# HTTP timeout for POST
HTTP_TIMEOUT_S   = 15

# Journal-schema disallowed keys (top-level)
JOURNAL_DISALLOWED = frozenset({
    "ActiveFine", "CockpitBreach", "BoostUsed",
    "FuelLevel", "FuelUsed", "JumpDist",
    "Latitude", "Longitude", "Wanted",
    "IsNewEntry", "NewTraitsDiscovered", "Traits", "VoucherAmount",
})

# Faction keys that are personal data
FACTION_DISALLOWED = frozenset({
    "HappiestSystem", "HomeSystem", "MyReputation", "SquadronFaction",
})

# outfitting module name filter
import re as _re
MODULE_RE = _re.compile(r"^Hpt_|^Int_|Armour_", _re.IGNORECASE)
CANONICALISE_RE = _re.compile(r"^\$(.+)_name;$")


# ── Schema URLs ───────────────────────────────────────────────────────────────

def _schema(name: str, version: int, test: bool) -> str:
    suffix = "/test" if test else ""
    return f"https://eddn.edcd.io/schemas/{name}/{version}{suffix}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _filter_localised(d: Any) -> Any:
    """Recursively strip keys ending in _Localised from dicts."""
    if isinstance(d, dict):
        return {
            k: _filter_localised(v)
            for k, v in d.items()
            if not k.endswith("_Localised")
        }
    if isinstance(d, list):
        return [_filter_localised(x) for x in d]
    return d


def _canonicalise(name: str) -> str:
    """Strip $..._name; wrapper from commodity names."""
    m = CANONICALISE_RE.match(name)
    return m.group(1).lower() if m else name.lower()


def _dict_hash(d: dict) -> str:
    return hashlib.md5(
        json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# ── Sender thread ─────────────────────────────────────────────────────────────

class _Sender(threading.Thread):
    """
    Background thread that drains an in-process queue and a disk retry queue.

    The in-process queue carries (msg_dict, retry_on_fail) tuples.
    Messages where retry_on_fail=True that fail are appended to the disk queue.
    The disk queue is checked on every RETRY_INTERVAL_S wake-up.
    """

    def __init__(self, endpoint: str, queue_file: Path) -> None:
        super().__init__(daemon=True, name="eddn-sender")
        self._endpoint   = endpoint
        self._queue_file = queue_file
        self._q: queue.Queue = queue.Queue()
        self._stop_evt   = threading.Event()

    def enqueue(self, msg: dict, retry: bool = True) -> None:
        self._q.put((msg, retry))

    def stop(self) -> None:
        self._stop_evt.set()
        self._q.put(None)  # unblock

    def run(self) -> None:
        last_retry = 0.0
        while not self._stop_evt.is_set():
            # Drain in-process queue
            while True:
                try:
                    item = self._q.get(timeout=1.0)
                except queue.Empty:
                    break
                if item is None:
                    return
                msg, retry = item
                ok, permanent = self._send(msg)
                if not ok and retry and not permanent:
                    self._append_disk(msg)

            # Periodically retry disk queue
            now = time.monotonic()
            if now - last_retry >= RETRY_INTERVAL_S:
                last_retry = now
                self._drain_disk()

    def _send(self, msg: dict) -> tuple[bool, bool]:
        """
        POST msg to EDDN.

        Returns (success, permanent_failure).
        permanent=True means don't retry (400 / 426).
        """
        try:
            payload  = json.dumps(msg, separators=(",", ":")).encode("utf-8")
            encoded  = gzip.compress(payload)
            req      = urllib.request.Request(
                self._endpoint,
                data=encoded,
                headers={
                    "Content-Type":     "application/json",
                    "Content-Encoding": "gzip",
                    "User-Agent":       f"{SOFTWARE_NAME}/{SOFTWARE_VERSION}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                return (resp.status == 200, False)

        except urllib.error.HTTPError as e:
            if e.code in (400, 426):
                # Schema validation failure or outdated schema — do not retry
                try:
                    body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    body = "(unreadable)"
                print(
                    f"  [EDDN] Permanent HTTP {e.code} — dropping message: {body[:200]}"
                )
                return (False, True)
            if e.code == 413:
                print(f"  [EDDN] HTTP 413 Payload Too Large — dropping")
                return (False, True)
            print(f"  [EDDN] HTTP {e.code} — will retry")
            return (False, False)

        except Exception as exc:
            print(f"  [EDDN] Send error ({type(exc).__name__}: {exc}) — will retry")
            return (False, False)

    def _append_disk(self, msg: dict) -> None:
        try:
            self._queue_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._queue_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"queued_at": time.time(), "msg": msg}) + "\n")
        except Exception as e:
            print(f"  [EDDN] Failed to persist message to disk queue: {e}")

    def _drain_disk(self) -> None:
        if not self._queue_file.exists():
            return
        try:
            with open(self._queue_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return

        if not lines:
            return

        remaining = []
        now = time.time()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                age = now - record.get("queued_at", 0)
                if age < RETRY_HOLD_S:
                    remaining.append(line)
                    continue
                ok, permanent = self._send(record["msg"])
                if not ok and not permanent:
                    remaining.append(line)
                else:
                    time.sleep(0.4)   # pace burst drain — avoid hammering EDDN
            except Exception:
                pass  # malformed line — drop it

        try:
            if remaining:
                with open(self._queue_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(remaining) + "\n")
            else:
                self._queue_file.unlink(missing_ok=True)
        except Exception as e:
            print(f"  [EDDN] Failed to update disk queue: {e}")


# ── Plugin ────────────────────────────────────────────────────────────────────

class EDDNPlugin(BasePlugin):
    """EDDN uploader builtin."""

    PLUGIN_NAME    = "eddn"
    PLUGIN_DISPLAY = "EDDN Uploader"
    PLUGIN_DESCRIPTION = "Contributes journal data to the Elite Dangerous Data Network (EDDN)."
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = [
        # Location / jump events (journal schema + augmentation source)
        "Fileheader",
        "LoadGame",
        "Location",
        "FSDJump",
        "CarrierJump",
        # Journal schema events
        "Docked",
        "Scan",
        "SAASignalsFound",
        "ScanBaryCentre",
        # FSS / signal events
        "FSSDiscoveryScan",
        "FSSSignalDiscovered",
        "FSSAllBodiesFound",
        "FSSBodySignals",
        # Station-market events (trigger reading .json files)
        "Market",
        "Outfitting",
        "Shipyard",
        # FC materials
        "FCMaterials",
        "CarrierTradeOrder",    # buy/sell order change — re-send Market.json
        # Docking events (own schema)
        "DockingGranted",
        "DockingDenied",
        # Settlement approach (own schema)
        "ApproachSettlement",
        # Codex (own schema)
        "CodexEntry",
        # Nav beacon (own schema)
        "NavBeaconScan",
        # Nav route (own schema — reads NavRoute.json)
        "NavRoute",
        # Docking state tracking
        "Undocked",
        # Carrier identity
        "CarrierStats",
    ]

    # ── on_load ───────────────────────────────────────────────────────────────

    def on_load(self, core) -> None:
        super().on_load(core)

        # Load EDDN config section
        cfg = core.load_setting("EDDN", {
            "Enabled":    False,
            "UploaderID": "",
            "TestMode":   False,
        }, warn=False)

        self._primary     = bool(core.cfg.app_settings.get("PrimaryInstance", True))
        self._enabled     = bool(cfg.get("Enabled", False)) and self._primary
        self._uploader_id = str(cfg.get("UploaderID", "")).strip()
        self._test_mode   = bool(cfg.get("TestMode", False))

        # Runtime state — tracks what we need for augmentation / headers
        self._game_version: str  = ""
        self._game_build:   str  = ""
        self._cmdr_name:    str  = ""
        self._horizons:     bool | None = None
        self._odyssey:      bool | None = None

        # Location tracking — updated by FSDJump / Location / CarrierJump
        self._system_address: int  | None = None
        self._star_system:    str  | None = None
        self._star_pos:       list | None = None  # [x, y, z]

        # FSSSignalDiscovered batching
        self._fss_signals: list[dict] = []

        # Docking state — used to validate CarrierTradeOrder sends
        self._carrier_market_id: int | None = None   # MarketID of our own FC
        self._docked_station_id: int | None = None   # current docked MarketID

        # Dedup hashes
        self._last_commodity_hash:   str | None = None
        self._last_outfitting_hash:  str | None = None
        self._last_shipyard_hash:    str | None = None
        self._last_fcmaterials_hash: str | None = None
        self._last_market_id:        int | None = None

        if self._enabled:
            self._sender = _Sender(EDDN_ENDPOINT, self.storage.path / "queue.jsonl")
            self._sender.start()
            self._load_note = f"LIVE" if not self._test_mode else "TEST MODE"
        elif not self._primary:
            self._sender = None
            self._load_note = "suppressed (PrimaryInstance = false)"
        else:
            self._sender = None
            self._load_note = "disabled"

    def on_unload(self) -> None:
        if self._sender:
            # Flush any remaining FSSSignalDiscovered before stopping
            if self._fss_signals:
                self._flush_fss_signals(flush_event=None)
            self._sender.stop()

    # ── on_event ──────────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        if not self._enabled:
            return

        ev = event.get("event", "")

        # Always update game/cmdr tracking regardless of upload intent
        if ev == "Fileheader":
            self._game_version = event.get("gameversion", "") or ""
            self._game_build   = event.get("build", "") or ""
            return  # Fileheader itself is never uploaded

        if ev == "LoadGame":
            # Only take gameversion/build from LoadGame if Fileheader hasn't set them
            if not self._game_version:
                self._game_version = event.get("gameversion", "") or ""
            if not self._game_build:
                self._game_build = event.get("build", "") or ""
            # horizons/odyssey come from LoadGame
            if "Horizons" in event:
                self._horizons = bool(event["Horizons"])
            if "Odyssey" in event:
                self._odyssey = bool(event["Odyssey"])
            # Reset game version on new session so Fileheader for next session wins
            # (Fileheader always comes before LoadGame in a real session)
            return

        if ev == "Commander":
            name = event.get("Name", "")
            if name:
                self._cmdr_name = name
            return

        # ── Flush any pending FSSSignalDiscovered before non-FSS events ───────
        if ev != "FSSSignalDiscovered" and self._fss_signals:
            if state.in_preload:
                # Preload events are historical — silently discard accumulated
                # signals rather than attempting a flush that will likely
                # mismatch the current system and produce a spurious warning.
                self._fss_signals = []
            else:
                self._flush_fss_signals(flush_event=event)

        # ── Location tracking ─────────────────────────────────────────────────
        # Track docked status and carrier identity
        if ev == "Docked":
            self._docked_station_id = event.get("MarketID")
        elif ev == "Undocked":
            self._docked_station_id = None
        elif ev == "CarrierStats":
            # CarrierID == MarketID for fleet carriers
            self._carrier_market_id = event.get("CarrierID")
        elif ev in ("Location",) and event.get("Docked"):
            self._docked_station_id = event.get("MarketID")

        if ev in ("FSDJump", "Location", "CarrierJump"):
            self._update_location(event)

        # ── Dispatch ──────────────────────────────────────────────────────────
        is_test = self._is_test()

        match ev:
            # ── Journal schema (Docked / FSDJump / Scan / Location / SAASignalsFound / CarrierJump) ──
            case "Docked" | "FSDJump" | "Scan" | "Location" | "SAASignalsFound" | "CarrierJump":
                self._send_journal(event, is_test)

            # ── FSSDiscoveryScan ──────────────────────────────────────────────
            case "FSSDiscoveryScan":
                self._send_fssdiscoveryscan(event, is_test)

            # ── FSSSignalDiscovered (batch) ────────────────────────────────────
            case "FSSSignalDiscovered":
                self._fss_signals.append(event)

            # ── FSSAllBodiesFound ─────────────────────────────────────────────
            case "FSSAllBodiesFound":
                self._send_fssallbodiesfound(event, is_test)

            # ── FSSBodySignals ────────────────────────────────────────────────
            case "FSSBodySignals":
                self._send_fssbodysignals(event, is_test)

            # ── ScanBaryCentre ────────────────────────────────────────────────
            case "ScanBaryCentre":
                self._send_scanbarycentre(event, is_test)

            # ── NavBeaconScan ─────────────────────────────────────────────────
            case "NavBeaconScan":
                self._send_navbeaconscan(event, is_test)

            # ── CodexEntry ────────────────────────────────────────────────────
            case "CodexEntry":
                self._send_codexentry(event, is_test)

            # ── ApproachSettlement ────────────────────────────────────────────
            case "ApproachSettlement":
                self._send_approachsettlement(event, is_test)

            # ── DockingGranted / DockingDenied ────────────────────────────────
            case "DockingGranted":
                self._send_dockinggranted(event, is_test)
            case "DockingDenied":
                self._send_dockingdenied(event, is_test)

            # ── Market / Outfitting / Shipyard / FCMaterials / NavRoute ────────
            # These read from .json files that only reflect the current session.
            # Skip them during preload — the on-disk files are stale.
            case "Market" | "Outfitting" | "Shipyard" | "FCMaterials" | "NavRoute" if not state.in_preload:
                match ev:
                    case "Market":
                        self._send_market_json(event, is_test)
                    case "Outfitting":
                        self._send_outfitting_json(event, is_test)
                    case "Shipyard":
                        self._send_shipyard_json(event, is_test)
                    case "NavRoute":
                        self._send_navroute_json(event, is_test)
                    case "FCMaterials":
                        self._send_fcmaterials(event, is_test)

            # ── Fleet Carrier trade order ─────────────────────────────────────
            case "CarrierTradeOrder":
                # Trade order changed on our FC — re-send Market.json if we
                # are currently docked at our own carrier. If not docked,
                # Market.json still reflects the last station we visited and
                # would produce a MarketID mismatch.
                carrier_id = event.get("CarrierID")
                if (carrier_id and
                        self._carrier_market_id == carrier_id and
                        self._docked_station_id == carrier_id):
                    self._last_commodity_hash = None
                    self._send_market_json(
                        {"MarketID": carrier_id, "timestamp": event.get("timestamp", "")},
                        is_test,
                    )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _is_test(self) -> bool:
        """True when we should append /test to schemaRef."""
        if self._test_mode:
            return True
        gv = self._game_version.lower()
        # alpha/beta clients
        if "alpha" in gv or "beta" in gv:
            return True
        return False

    def _uploader(self) -> str:
        return self._uploader_id or self._cmdr_name or "unknown"

    def _header(self) -> dict:
        return {
            "uploaderID":      self._uploader(),
            "softwareName":    SOFTWARE_NAME,
            "softwareVersion": SOFTWARE_VERSION,
            "gameversion":     self._game_version,
            "gamebuild":       self._game_build,
        }

    def _update_location(self, event: dict) -> None:
        sa = event.get("SystemAddress")
        ss = event.get("StarSystem")
        sp = event.get("StarPos")
        if sa is not None:
            self._system_address = sa
        if ss:
            self._star_system = ss
        if sp and len(sp) == 3:
            self._star_pos = list(sp)

    def _augment_system(self, msg: dict, require_match: bool = True) -> bool:
        """
        Add StarSystem / SystemAddress / StarPos to msg if missing.

        If require_match=True, the event's SystemAddress must match our tracked
        location (cross-check against game bug / missed jump). Returns False and
        logs a warning if augmentation is unsafe.
        """
        event_sa = msg.get("SystemAddress")

        if require_match and event_sa is not None:
            if self._system_address is None or event_sa != self._system_address:
                print(
                    f"  [EDDN] SystemAddress mismatch for {msg.get('event')} "
                    f"(event={event_sa} tracked={self._system_address}) — dropping"
                )
                return False

        if "StarSystem" not in msg and msg.get("SystemName") is None and msg.get("System") is None:
            if not self._star_system:
                print(f"  [EDDN] No StarSystem available for {msg.get('event')} — dropping")
                return False
            msg["StarSystem"] = self._star_system

        if "StarPos" not in msg:
            if not self._star_pos:
                print(f"  [EDDN] No StarPos available for {msg.get('event')} — dropping")
                return False
            msg["StarPos"] = list(self._star_pos)

        if "SystemAddress" not in msg:
            if self._system_address is None:
                print(f"  [EDDN] No SystemAddress available for {msg.get('event')} — dropping")
                return False
            msg["SystemAddress"] = self._system_address

        return True

    def _add_horizons_odyssey(self, msg: dict) -> None:
        """Inject horizons / odyssey flags only when we know them."""
        if self._horizons is not None:
            msg["horizons"] = self._horizons
        if self._odyssey is not None:
            msg["odyssey"] = self._odyssey

    def _post(self, schema_ref: str, message: dict) -> None:
        """Build the envelope and hand to the sender thread."""
        envelope = {
            "$schemaRef": schema_ref,
            "header":     self._header(),
            "message":    message,
        }
        if self._sender:
            self._sender.enqueue(envelope)

    def _read_json_file(self, journal_event_name: str) -> dict | None:
        """
        Read Market.json / Outfitting.json / Shipyard.json from the journal dir.

        Returns the parsed dict, or None on any error.
        """
        journal_dir = self.core.journal_dir
        if journal_dir is None:
            return None
        path = Path(journal_dir) / f"{journal_event_name}.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"  [EDDN] Could not read {path.name}: {e}")
            return None

    # ── Journal schema ────────────────────────────────────────────────────────

    def _send_journal(self, event: dict, is_test: bool) -> None:
        """
        Send a Docked / FSDJump / Scan / Location / SAASignalsFound / CarrierJump
        on the journal/1 schema.
        """
        msg = deepcopy(event)
        msg = _filter_localised(msg)

        # Remove disallowed top-level keys
        for k in JOURNAL_DISALLOWED:
            msg.pop(k, None)

        # Remove internal EDLD annotation
        msg.pop("_logtime", None)

        # Strip personal faction data
        if "Factions" in msg:
            msg["Factions"] = [
                {k: v for k, v in f.items() if k not in FACTION_DISALLOWED}
                for f in msg["Factions"]
            ]

        ev = msg.get("event", "")

        # Augment: add StarSystem + StarPos if missing
        # FSDJump / Location / CarrierJump already have them; Scan / Docked / SAASignalsFound may not
        if "StarPos" not in msg or "StarSystem" not in msg:
            if not self._augment_system(msg, require_match=True):
                return
        else:
            # Update our location tracking from this event
            pass  # already done in on_event dispatch

        self._add_horizons_odyssey(msg)

        # SystemAddress is required
        if "SystemAddress" not in msg:
            print(f"  [EDDN] No SystemAddress in {ev} — dropping")
            return

        self._post(_schema("journal", 1, is_test), msg)

    # ── FSSDiscoveryScan ──────────────────────────────────────────────────────

    def _send_fssdiscoveryscan(self, event: dict, is_test: bool) -> None:
        msg = deepcopy(event)
        msg = _filter_localised(msg)
        msg.pop("_logtime", None)
        msg.pop("Progress", None)  # personal data

        if not self._augment_system(msg, require_match=True):
            return

        self._add_horizons_odyssey(msg)
        self._post(_schema("fssdiscoveryscan", 1, is_test), msg)

    # ── FSSSignalDiscovered (batched) ─────────────────────────────────────────

    def _flush_fss_signals(self, flush_event: dict | None) -> None:
        """
        Flush the accumulated FSSSignalDiscovered batch.

        flush_event is the triggering non-FSS event (used for system cross-check
        in the Odyssey ordering where Location/FSDJump/CarrierJump comes after).
        In the Horizons ordering the signals arrive before the jump event, so we
        use tracked state instead.
        """
        if not self._fss_signals:
            return

        if flush_event and flush_event.get("event") in ("Location", "FSDJump", "CarrierJump"):
            aug_sa   = flush_event.get("SystemAddress")
            aug_sys  = flush_event.get("StarSystem")
            aug_pos  = flush_event.get("StarPos")
        else:
            aug_sa   = self._system_address
            aug_sys  = self._star_system
            aug_pos  = self._star_pos

        if aug_sa is None or aug_sys is None or aug_pos is None:
            print("  [EDDN] FSSSignalDiscovered flush: no location data — dropping batch")
            self._fss_signals = []
            return

        if self._fss_signals[0].get("SystemAddress") != aug_sa:
            print("  [EDDN] FSSSignalDiscovered flush: first signal SystemAddress mismatch — dropping batch")
            self._fss_signals = []
            return

        is_test = self._is_test()
        signals_out = []
        for s in self._fss_signals:
            if s.get("SystemAddress") != aug_sa:
                continue
            # Drop mission USS signals
            if s.get("USSType") == "$USS_Type_MissionTarget;":
                continue
            s2 = _filter_localised(s)
            # Remove per-signal keys that aren't part of the EDDN signal object
            for k in ("event", "horizons", "odyssey", "TimeRemaining", "SystemAddress", "_logtime"):
                s2.pop(k, None)
            signals_out.append(s2)

        if not signals_out:
            self._fss_signals = []
            return

        msg: dict = {
            "event":         "FSSSignalDiscovered",
            "timestamp":     self._fss_signals[0]["timestamp"],
            "SystemAddress": aug_sa,
            "StarSystem":    aug_sys,
            "StarPos":       list(aug_pos),
            "signals":       signals_out,
        }
        self._add_horizons_odyssey(msg)
        self._post(_schema("fsssignaldiscovered", 1, is_test), msg)
        self._fss_signals = []

    # ── FSSAllBodiesFound ─────────────────────────────────────────────────────

    def _send_fssallbodiesfound(self, event: dict, is_test: bool) -> None:
        msg = deepcopy(event)
        msg = _filter_localised(msg)
        msg.pop("_logtime", None)
        if not self._augment_system(msg, require_match=True):
            return
        self._add_horizons_odyssey(msg)
        self._post(_schema("fssallbodiesfound", 1, is_test), msg)

    # ── FSSBodySignals ────────────────────────────────────────────────────────

    def _send_fssbodysignals(self, event: dict, is_test: bool) -> None:
        msg = deepcopy(event)
        msg = _filter_localised(msg)
        msg.pop("_logtime", None)
        if not self._augment_system(msg, require_match=True):
            return
        self._add_horizons_odyssey(msg)
        self._post(_schema("fssbodysignals", 1, is_test), msg)

    # ── ScanBaryCentre ────────────────────────────────────────────────────────

    def _send_scanbarycentre(self, event: dict, is_test: bool) -> None:
        msg = deepcopy(event)
        msg = _filter_localised(msg)
        msg.pop("_logtime", None)
        if not self._augment_system(msg, require_match=True):
            return
        self._add_horizons_odyssey(msg)
        self._post(_schema("scanbarycentre", 1, is_test), msg)

    # ── NavBeaconScan ─────────────────────────────────────────────────────────

    def _send_navbeaconscan(self, event: dict, is_test: bool) -> None:
        msg = deepcopy(event)
        msg = _filter_localised(msg)
        msg.pop("_logtime", None)
        if not self._augment_system(msg, require_match=True):
            return
        self._add_horizons_odyssey(msg)
        self._post(_schema("navbeaconscan", 1, is_test), msg)

    # ── CodexEntry ────────────────────────────────────────────────────────────

    def _send_codexentry(self, event: dict, is_test: bool) -> None:
        msg = deepcopy(event)
        msg = _filter_localised(msg)
        msg.pop("_logtime", None)

        # Disallowed personal fields
        for k in ("IsNewEntry", "NewTraitsDiscovered"):
            msg.pop(k, None)

        # CodexEntry uses "System" not "StarSystem" for the system name
        # Cross-check SystemAddress before augmenting StarPos
        if self._system_address is None or msg.get("SystemAddress") != self._system_address:
            print(
                f"  [EDDN] CodexEntry SystemAddress mismatch "
                f"(event={msg.get('SystemAddress')} tracked={self._system_address}) — dropping"
            )
            return

        if "StarPos" not in msg:
            if not self._star_pos:
                print("  [EDDN] CodexEntry: no StarPos available — dropping")
                return
            msg["StarPos"] = list(self._star_pos)

        # Validate only the truly required fields (schema: timestamp/event/System/StarPos/SystemAddress/EntryID)
        if not msg.get("System") or not msg.get("EntryID"):
            print("  [EDDN] CodexEntry: missing required System or EntryID — dropping")
            return

        self._add_horizons_odyssey(msg)
        self._post(_schema("codexentry", 1, is_test), msg)

    # ── ApproachSettlement ────────────────────────────────────────────────────

    def _send_approachsettlement(self, event: dict, is_test: bool) -> None:
        # Game bug workaround: ApproachSettlement can be missing Lat/Long
        if "Latitude" not in event or "Longitude" not in event:
            return

        msg = deepcopy(event)
        msg = _filter_localised(msg)
        msg.pop("_logtime", None)

        if not self._augment_system(msg, require_match=True):
            return
        self._add_horizons_odyssey(msg)
        self._post(_schema("approachsettlement", 1, is_test), msg)

    # ── DockingGranted / DockingDenied ────────────────────────────────────────

    def _send_dockinggranted(self, event: dict, is_test: bool) -> None:
        msg = deepcopy(event)
        msg = _filter_localised(msg)
        msg.pop("_logtime", None)
        self._add_horizons_odyssey(msg)
        self._post(_schema("dockinggranted", 1, is_test), msg)

    def _send_dockingdenied(self, event: dict, is_test: bool) -> None:
        msg = deepcopy(event)
        msg = _filter_localised(msg)
        msg.pop("_logtime", None)
        self._add_horizons_odyssey(msg)
        self._post(_schema("dockingdenied", 1, is_test), msg)

    # ── Market.json ───────────────────────────────────────────────────────────

    def _send_market_json(self, trigger: dict, is_test: bool) -> None:
        """
        Read Market.json and send commodity/3 schema message.
        The journal Market event is just a trigger; the actual data is in the .json file.
        """
        data = self._read_json_file("Market")
        if data is None:
            return

        # Cross-check MarketID matches trigger event
        if data.get("MarketID") != trigger.get("MarketID"):
            print("  [EDDN] Market.json MarketID mismatch — skipping")
            return

        items = data.get("Items", [])
        commodities = sorted(
            [
                {
                    "name":          _canonicalise(c["Name"]),
                    "meanPrice":     c["MeanPrice"],
                    "buyPrice":      c["BuyPrice"],
                    "stock":         c["Stock"],
                    "stockBracket":  c["StockBracket"],
                    "sellPrice":     c["SellPrice"],
                    "demand":        c["Demand"],
                    "demandBracket": c["DemandBracket"],
                }
                for c in items
                # Skip NonMarketable (e.g. limpets) and items with a legality restriction
                if "nonmarketable" not in c.get("Category", "").lower()
                and not c.get("legality", "")
            ],
            key=lambda x: x["name"],
        )

        h = _dict_hash({"commodities": commodities, "mid": data.get("MarketID")})
        if h == self._last_commodity_hash:
            return
        self._last_commodity_hash = h

        if data.get("MarketID") != self._last_market_id:
            self._last_commodity_hash = h
            self._last_outfitting_hash = None
            self._last_shipyard_hash = None
            self._last_market_id = data.get("MarketID")

        msg: dict = {
            "timestamp":   data.get("timestamp", trigger.get("timestamp", "")),
            "systemName":  data.get("StarSystem") or self._star_system or "",
            "stationName": data.get("StationName", ""),
            "marketId":    data.get("MarketID"),
            "commodities": commodities,
        }

        if data.get("StationType"):
            msg["stationType"] = data["StationType"]
        if data.get("CarrierDockingAccess"):
            msg["carrierDockingAccess"] = data["CarrierDockingAccess"]

        self._add_horizons_odyssey(msg)
        self._post(_schema("commodity", 3, is_test), msg)

    # ── Outfitting.json ───────────────────────────────────────────────────────

    def _send_outfitting_json(self, trigger: dict, is_test: bool) -> None:
        data = self._read_json_file("Outfitting")
        if data is None:
            return

        if data.get("MarketID") != trigger.get("MarketID"):
            print("  [EDDN] Outfitting.json MarketID mismatch — skipping")
            return

        items = data.get("Items", [])
        # Filter: only Hpt_/Int_/Armour_ modules; skip int_planetapproachsuite;
        # skip items with a non-null sku unless it is the Horizons planetary sku
        HORIZONS_SKU = "ELITE_HORIZONS_V_PLANETARY_LANDINGS"
        modules = sorted(
            MODULE_RE.sub(lambda m: m.group(0).capitalize(), item["Name"])
            for item in items
            if (
                MODULE_RE.search(item["Name"])
                and item["Name"].lower() != "int_planetapproachsuite"
                and (not item.get("sku") or item.get("sku") == HORIZONS_SKU)
            )
        )

        if not modules:
            return  # schema requires minItems=1

        h = _dict_hash({"modules": modules, "mid": data.get("MarketID")})
        if h == self._last_outfitting_hash:
            return
        self._last_outfitting_hash = h

        msg: dict = {
            "timestamp":   data.get("timestamp", trigger.get("timestamp", "")),
            "systemName":  data.get("StarSystem") or self._star_system or "",
            "stationName": data.get("StationName", ""),
            "marketId":    data.get("MarketID"),
            "modules":     modules,
        }
        self._add_horizons_odyssey(msg)
        self._post(_schema("outfitting", 2, is_test), msg)

    # ── Shipyard.json ─────────────────────────────────────────────────────────

    def _send_shipyard_json(self, trigger: dict, is_test: bool) -> None:
        data = self._read_json_file("Shipyard")
        if data is None:
            return

        if data.get("MarketID") != trigger.get("MarketID"):
            print("  [EDDN] Shipyard.json MarketID mismatch — skipping")
            return

        pricelist = data.get("PriceList") or []
        ships = sorted(set(ship["ShipType"] for ship in pricelist if ship.get("ShipType")))

        if not ships:
            return  # schema requires minItems=1

        h = _dict_hash({"ships": ships, "mid": data.get("MarketID")})
        if h == self._last_shipyard_hash:
            return
        self._last_shipyard_hash = h

        msg: dict = {
            "timestamp":   data.get("timestamp", trigger.get("timestamp", "")),
            "systemName":  data.get("StarSystem") or self._star_system or "",
            "stationName": data.get("StationName", ""),
            "marketId":    data.get("MarketID"),
            "ships":       ships,
        }
        self._add_horizons_odyssey(msg)
        self._post(_schema("shipyard", 2, is_test), msg)

    # ── FCMaterials ───────────────────────────────────────────────────────────

    def _send_fcmaterials(self, event: dict, is_test: bool) -> None:
        """Read FCMaterials.json and send fcmaterials_journal/1 schema message.
        The journal FCMaterials event is a trigger; authoritative data is in the file.
        Schema requires: timestamp, event, MarketID, CarrierName, CarrierID, Items.
        """
        data = self._read_json_file("FCMaterials")
        if data is None:
            return

        # Validate required fields are present
        for field in ("MarketID", "CarrierName", "CarrierID", "Items"):
            if not data.get(field) and data.get(field) != 0:
                print(f"  [EDDN] FCMaterials.json missing {field!r} — skipping")
                return

        h = _dict_hash({"items": data["Items"], "mid": data.get("MarketID")})
        if h == self._last_fcmaterials_hash:
            return
        self._last_fcmaterials_hash = h

        msg = _filter_localised(deepcopy(data))
        msg.pop("_logtime", None)

        self._add_horizons_odyssey(msg)
        self._post(_schema("fcmaterials_journal", 1, is_test), msg)

    # ── NavRoute.json ─────────────────────────────────────────────────────────

    def _send_navroute_json(self, trigger: dict, is_test: bool) -> None:
        """Read NavRoute.json and send navroute/1 schema message."""
        data = self._read_json_file("NavRoute")
        if not data:
            return
        route = data.get("Route", [])
        if not route:
            return   # empty route / NavRouteClear — nothing useful to send
        # Build EDDN-format route entries
        eddn_route = []
        for hop in route:
            entry: dict = {
                "StarSystem":    hop.get("StarSystem", ""),
                "SystemAddress": hop.get("SystemAddress", 0),
                "StarPos":       hop.get("StarPos", [0, 0, 0]),
                "StarClass":     hop.get("StarClass", ""),
            }
            eddn_route.append(entry)
        msg: dict = {
            "timestamp": data.get("timestamp", trigger.get("timestamp", "")),
            "event":     "NavRoute",
            "Route":     eddn_route,
        }
        self._add_horizons_odyssey(msg)
        self._post(_schema("navroute", 1, is_test), msg)

    # ── fcmaterials_capi (called by CAPI data layer) ──────────────────────────

    def push_fcmaterials_capi(
        self,
        market_id:  int,
        carrier_id: str,
        items:      dict,
        timestamp:  str,
    ) -> None:
        """
        Called by the CAPI data layer after a /market poll on a fleet carrier.
        Sends the bartender micro-resource orders via fcmaterials_capi/1 schema.

        items  — raw orders.onfootmicroresources dict from CAPI /market response.
        carrier_id — CAPI "name" field (the callsign, used as CarrierID).
        """
        if not self._enabled or self._sender is None:
            return
        if not items:
            return

        # Strip locName from purchases and sales per schema requirement
        def _strip_loc(obj):
            if isinstance(obj, list):
                return [{k: v for k, v in i.items() if k != "locName"}
                        for i in obj if isinstance(i, dict)]
            if isinstance(obj, dict):
                return {key: {k: v for k, v in val.items() if k != "locName"}
                        if isinstance(val, dict) else val
                        for key, val in obj.items()}
            return obj

        clean_items = {
            "purchases": _strip_loc(items.get("purchases", [])),
            "sales":     _strip_loc(items.get("sales",     [])),
        }

        is_test = self._is_test()
        msg: dict = {
            "timestamp": timestamp,
            "event":     "FCMaterials",
            "MarketID":  int(market_id),
            "CarrierID": str(carrier_id),
            "Items":     clean_items,
        }
        self._add_horizons_odyssey(msg)
        self._post(_schema("fcmaterials_capi", 1, is_test), msg)


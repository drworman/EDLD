"""
components/edsm/plugin.py — EDSM journal uploader for EDLD.

Uploads journal events to the EDSM API (https://www.edsm.net/api-journal-v1).

Subscription model — "send everything EDSM accepts":
  The plugin subscribes with the wildcard "*" and receives every journal
  event the dispatcher sees.  Filtering is then driven by:
    1. _ALWAYS_SKIP    — meta-events with no semantic content (Fileheader,
                         continued, Shutdown/ShutDown).
    2. EDSM's published discard list, fetched at startup from
       /api-journal-v1/discard.  EDSM tells us exactly which event names
       it does not want; everything else is fair game.
    3. Beta-build guard — beta/legacy game versions never POST to live EDSM.

  This means new journal events introduced by future game updates flow to
  EDSM automatically without code changes, until EDSM chooses to discard
  them.  Flight logs, mission history, suit/weapon/engineer activity,
  carrier ops, squadron events, NavRoute, Friends, Wing, Interdiction,
  Resurrect, EngineerCraft and everything else FDev emits are now covered.

Config [EDSM]:
    Enabled        = false          # opt-in
    CommanderName  = ""             # your EDSM commander name
    ApiKey         = ""             # your EDSM API key (from EDSM settings)

EDSM notes:
  - Live galaxy only; beta/legacy data is suppressed via the in-plugin
    beta-guard, not just by EDSM's server-side rejection.
  - Rate limit: ~1 request per 10 s (360/hr).  We batch events and flush
    on session transitions to stay well within this.
  - Transient state fields (_systemAddress, _systemName, _systemCoordinates,
    _marketId, _stationName, _shipId) are injected into each event so EDSM
    can link entries to the galaxy map and to your ship/station context.
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

# Events that are always suppressed regardless of discard list — these
# are meta-frames or shutdown markers that EDSM cannot meaningfully use.
_ALWAYS_SKIP = frozenset({
    "Fileheader",
    "continued",
    "Shutdown",
    "ShutDown",
})

# Wildcard subscription: receive every event the dispatcher sees.  Filtering
# is done at runtime via _ALWAYS_SKIP + EDSM's published discard list + the
# beta guard.  See the file docstring for rationale.
SUBSCRIBED_EVENTS = ["*"]

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

        # ── Diagnostic counters (thread-safe via _stats_lock) ─────────────────
        # Per-session accounting for what we sent and how EDSM responded.
        # Inspect via EDSMPlugin.get_stats() — useful when "is my data
        # reaching EDSM?" is the question and the answer needs to be more
        # specific than "I think so".
        self._stats: dict = {
            "events_sent":     0,   # POSTed (counted before HTTP attempt)
            "events_accepted": 0,   # msgnum 100 (OK)
            "events_warned":   0,   # msgnum 101-199 (accepted with notice)
            "events_rejected": 0,   # msgnum 200+ (per-event reject) or batch-level reject
            "http_failures":   0,   # HTTPError / socket / parse failures
            "by_event":        {},  # event_name -> {sent, accepted, warned, rejected}
        }
        self._stats_lock = threading.Lock()
        # Last raw EDSM response — useful for ad-hoc debugging from a console.
        self._last_response:    dict | None = None
        self._last_response_ts: float | None = None
        # Whether we've already printed the "first successful batch" confirmation.
        self._first_ok_printed: bool = False

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
            # Count outbound before the request so we record traffic even on
            # transport failures.  The accepted/warned/rejected breakdown
            # adjusts after we read the response body.
            self._record_sent(events)
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                self._last_send = time.monotonic()
                body_raw = resp.read()
                try:
                    body = json.loads(body_raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    with self._stats_lock:
                        self._stats["http_failures"] += 1
                    print(
                        f"  [EDSM] Unparseable response body "
                        f"({type(e).__name__}: {e}); queuing {len(events)} to disk"
                    )
                    self._persist(events)
                    return
                self._last_response    = body
                self._last_response_ts = time.time()
                self._inspect_response(body, events)
                if resp.status != 200:
                    # Non-200 HTTP — persist regardless of body interpretation.
                    self._persist(events)

        except urllib.error.HTTPError as e:
            with self._stats_lock:
                self._stats["http_failures"] += 1
            print(f"  [EDSM] HTTP {e.code} — queuing {len(events)} event(s) to disk")
            self._persist(events)
        except Exception as exc:
            with self._stats_lock:
                self._stats["http_failures"] += 1
            print(f"  [EDSM] Send error ({type(exc).__name__}: {exc}) — queuing to disk")
            self._persist(events)

    # ── Response inspection ───────────────────────────────────────────────────

    def _record_sent(self, events: list[dict]) -> None:
        """Bump per-event-type sent counters before HTTP attempt."""
        type_counts: dict[str, int] = {}
        for ev in events:
            t = ev.get("event", "?")
            type_counts[t] = type_counts.get(t, 0) + 1
        with self._stats_lock:
            self._stats["events_sent"] += len(events)
            for t, n in type_counts.items():
                bt = self._stats["by_event"].setdefault(
                    t, {"sent": 0, "accepted": 0, "warned": 0, "rejected": 0}
                )
                bt["sent"] += n

    def _inspect_response(self, body: dict, events: list[dict]) -> None:
        """Parse EDSM's response body and surface per-event status.

        EDSM /api-journal-v1 response shape:
            {
              "msgnum": int,        # 100 = OK; 1xx = info; 2xx = error
              "msg":    str,
              "events": [            # per-event responses, parallel to request
                  {"msgnum": int, "msg": str},
                  ...
              ]
            }

        msgnum semantics:
            100         OK, event accepted
            101-199     Accepted with notice (e.g. duplicate, stale system)
            201         Authentication failure (whole batch)
            202         Permission denied
            203         Disabled in user settings
            204         Software version too old
            300+        Server / processing errors
        """
        top_msgnum = body.get("msgnum")
        top_msg    = body.get("msg", "")

        # Top-level error → whole batch rejected
        if isinstance(top_msgnum, int) and top_msgnum >= 200:
            with self._stats_lock:
                self._stats["events_rejected"] += len(events)
                for ev in events:
                    bt = self._stats["by_event"].setdefault(
                        ev.get("event", "?"),
                        {"sent": 0, "accepted": 0, "warned": 0, "rejected": 0},
                    )
                    bt["rejected"] += 1
            # Auth-class errors deserve a bright banner.
            if top_msgnum in (201, 202, 203, 204):
                print(
                    f"  [EDSM] *** BATCH REJECTED ({top_msgnum}): {top_msg} ***  "
                    f"Check CommanderName and ApiKey in config."
                )
            else:
                print(f"  [EDSM] Batch rejected ({top_msgnum}): {top_msg}")
            return

        # First successful batch — print a one-time confirmation so the user
        # knows the upload pipeline is actually flowing.
        if not self._first_ok_printed:
            self._first_ok_printed = True
            print(
                f"  [EDSM] First batch OK — uploaded {len(events)} event(s); "
                f"response: msgnum={top_msgnum} {top_msg}"
            )

        # Per-event status array — index matches request order
        per_event = body.get("events") or []
        if not isinstance(per_event, list):
            # Top-level OK with no per-event detail → assume all accepted
            with self._stats_lock:
                self._stats["events_accepted"] += len(events)
                for ev in events:
                    bt = self._stats["by_event"].setdefault(
                        ev.get("event", "?"),
                        {"sent": 0, "accepted": 0, "warned": 0, "rejected": 0},
                    )
                    bt["accepted"] += len(events)
            return

        for i, ev_resp in enumerate(per_event):
            if not isinstance(ev_resp, dict):
                continue
            msgnum  = ev_resp.get("msgnum")
            msg     = ev_resp.get("msg", "")
            ev_name = events[i].get("event", "?") if i < len(events) else "?"

            with self._stats_lock:
                bt = self._stats["by_event"].setdefault(
                    ev_name, {"sent": 0, "accepted": 0, "warned": 0, "rejected": 0}
                )
                if not isinstance(msgnum, int):
                    self._stats["events_accepted"] += 1
                    bt["accepted"] += 1
                elif msgnum == 100:
                    self._stats["events_accepted"] += 1
                    bt["accepted"] += 1
                elif msgnum < 200:
                    self._stats["events_warned"] += 1
                    bt["warned"] += 1
                    # Print notice-level responses so the user sees why
                    # something they expected didn't quite "take".
                    print(f"  [EDSM] {ev_name} notice ({msgnum}): {msg}")
                else:
                    self._stats["events_rejected"] += 1
                    bt["rejected"] += 1
                    print(f"  [EDSM] {ev_name} REJECTED ({msgnum}): {msg}")

    def get_stats(self) -> dict:
        """Thread-safe snapshot of upload statistics."""
        with self._stats_lock:
            return {
                "events_sent":     self._stats["events_sent"],
                "events_accepted": self._stats["events_accepted"],
                "events_warned":   self._stats["events_warned"],
                "events_rejected": self._stats["events_rejected"],
                "http_failures":   self._stats["http_failures"],
                "by_event":        {k: dict(v) for k, v in self._stats["by_event"].items()},
                "last_response_at": self._last_response_ts,
                "last_response":   self._last_response,
            }

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
            # Print a closing summary so the user sees what happened over
            # the session even if no errors fired.
            try:
                stats = self._sender.get_stats()
                self._print_stats_summary(stats, label="Final")
            except Exception:
                pass
            self._sender.stop()
            self._sender.join(timeout=5)

    def get_stats(self) -> dict:
        """Public diagnostic snapshot of upload activity.

        Returns a dict with:
            events_sent / events_accepted / events_warned / events_rejected
            http_failures
            by_event: {event_name: {sent, accepted, warned, rejected}}
            last_response: last JSON response body received from EDSM
            last_response_at: unix timestamp of that response

        Callable via core.plugin_call("edsm", "get_stats").  Returns an
        empty dict if the plugin is disabled or the sender hasn't started.
        """
        if self._sender is None:
            return {}
        return self._sender.get_stats()

    def print_stats(self) -> None:
        """Print the current stats summary to stdout — handy from a REPL."""
        if self._sender is None:
            print("  [EDSM] Disabled — no stats available")
            return
        self._print_stats_summary(self._sender.get_stats(), label="Current")

    @staticmethod
    def _print_stats_summary(stats: dict, label: str = "Current") -> None:
        print(
            f"  [EDSM] {label} stats: "
            f"{stats['events_sent']} sent, "
            f"{stats['events_accepted']} accepted, "
            f"{stats['events_warned']} warned, "
            f"{stats['events_rejected']} rejected, "
            f"{stats['http_failures']} HTTP failure(s)"
        )
        by_event = stats.get("by_event") or {}
        # Show event types that have anything other than a clean accept,
        # plus the busiest accepted ones, for orientation.
        problems = [
            (n, d) for n, d in by_event.items()
            if d.get("warned") or d.get("rejected")
        ]
        if problems:
            print("  [EDSM]   Per-event issues:")
            for name, d in sorted(problems, key=lambda x: -(x[1].get("rejected", 0) + x[1].get("warned", 0))):
                print(
                    f"  [EDSM]     {name:<28} sent={d['sent']:>4}  "
                    f"accepted={d['accepted']:>4}  warned={d['warned']:>3}  rejected={d['rejected']:>3}"
                )

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event", "")

        # Always track session/location state regardless of enabled status,
        # so if the plugin is later enabled mid-session the fields are ready.
        self._update_tracking(ev, event)

        if not self._enabled or self._sender is None:
            return
        if ev in _ALWAYS_SKIP:
            self._note_filtered(ev, "always_skip")
            return
        if ev in self._discard_set:
            self._note_filtered(ev, "edsm_discard_list")
            return

        # Beta / legacy guard — EDSM only accepts live-galaxy data.  Without
        # this, EDSM would reject the batch HTTP-side and we'd waste a slot
        # in our rate budget plus persist a doomed retry to disk.  "beta" in
        # gameversion catches all FDev beta phases; "3." catches the 3.x
        # legacy/Horizons branch where EDSM no longer accepts new data.
        gv = (self._game_version or "").lower()
        if "beta" in gv or gv.startswith("3."):
            self._note_filtered(ev, f"beta_guard(gameversion={gv!r})")
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

        # Trace mode: surface every event we're about to send, so the user
        # can correlate journal activity with EDSM uploads in real time.
        # Skipped during preload to avoid drowning the console at startup.
        if getattr(self.core, "trace_mode", False) and not getattr(state, "in_preload", False):
            print(f"  [EDSM trace] queued {ev}")

        # Flush batch on key session transitions
        if ev in ("FSDJump", "CarrierJump", "Docked", "Undocked",
                  "Location", "LoadGame"):
            self._sender.flush()

    def _note_filtered(self, ev: str, reason: str) -> None:
        """Surface filter decisions when trace mode is on — answers
        'why didn't EDSM see my X event' without re-running the journal."""
        if getattr(self.core, "trace_mode", False):
            print(f"  [EDSM trace] filtered {ev}  ({reason})")

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

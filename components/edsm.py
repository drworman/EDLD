"""
components/edsm.py — EDSM journal uploader for EDLD.

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
    ApiKey         = ""             # your EDSM API key from settings page

The commander name is sourced from journal data (state.pilot_name) — no
CommanderName setting to keep in sync.  The API key must match this commander
on EDSM's side; mismatches surface as 201 rejections with a diagnostic banner.

EDSM notes:
  - Live galaxy only; beta/legacy data is suppressed via the in-plugin
    beta-guard, not just by EDSM's server-side rejection.
  - Rate limit: ~1 request per 10 s (360/hr).  We batch events and flush
    on session transitions to stay well within this.
  - Transient state fields (_systemAddress, _systemName, _systemCoordinates,
    _marketId, _stationName, _shipId) are injected into each event so EDSM
    can link entries to the galaxy map and to your ship/station context.
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

PLUGIN_VERSION     = "1.0.0"
EDSM_JOURNAL_URL   = "https://www.edsm.net/api-journal-v1"
EDSM_DISCARD_URL   = "https://www.edsm.net/api-journal-v1/discard"
# Read endpoints — anonymous for system-v1, authenticated for commander-v1.
EDSM_SYSTEM_BODIES_URL    = "https://www.edsm.net/api-system-v1/bodies"
EDSM_CMDR_POSITION_URL    = "https://www.edsm.net/api-logs-v1/get-position"
SOFTWARE_NAME      = "EDLD"
SOFTWARE_VERSION   = VERSION
HTTP_TIMEOUT_S     = 15
SEND_INTERVAL_S    = 12      # minimum gap between POST requests (~5/min, well under 360/hr)
BATCH_MAX          = 50      # maximum events per POST
STARTUP_DELAY_S    = 10      # seconds after load before we begin uploading

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

    def __init__(self, cmdr_provider, api_key: str, queue_file,
                 metadata_provider=None) -> None:
        super().__init__(daemon=True, name="edsm-sender")
        # cmdr_provider: callable returning the current commander name as a
        # string.  Resolved at send time so the plugin doesn't need a config
        # value — it reads from state.pilot_name (populated by the commander
        # plugin from journal Commander/LoadGame events).
        self._cmdr_provider = cmdr_provider
        self._key       = api_key
        self._queue_file = queue_file
        self._q:        queue.Queue = queue.Queue()
        self._stop_evt  = threading.Event()
        self._last_send = 0.0

        # Optional callable: () -> dict of version metadata to merge into
        # any drained event that lacks it.  Drained events from earlier bug
        # eras (JSON-body, gzip, missing version metadata) have no
        # gameversion/build, and EDSM 207-rejects the whole batch if any
        # event is missing them.  When this callable is set and returns
        # data with a gameversion, _drain_disk uses it to fix up old events
        # before retry.  When unset or returns no gameversion, the disk
        # queue is left intact for a later attempt.
        self._metadata_provider = metadata_provider

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

        # Resolve commander name at send time.  Source is journal data via
        # state.pilot_name — config no longer carries it.  If pilot_name
        # is empty (preload hasn't seen Commander/LoadGame yet) EDSM would
        # reject with 201 "Missing commander name"; persist and retry later.
        try:
            cmdr = (self._cmdr_provider() or "").strip()
        except Exception:
            cmdr = ""
        if not cmdr or not self._key:
            with self._stats_lock:
                self._stats["http_failures"] += 1
            print(
                f"  [EDSM] Pre-flight failed — "
                f"cmdr={cmdr!r}, key=<{len(self._key)} chars>; "
                f"persisting {len(events)} event(s) to disk."
            )
            self._persist(events)
            return

        # EDSM's /api-journal-v1 is an application/x-www-form-urlencoded
        # endpoint — NOT a JSON-body endpoint.  The "message" form field
        # carries the events as a JSON-encoded string (single event object
        # or an array of event objects).  Sending the whole body as a JSON
        # object causes EDSM to respond with msgnum 206 "Cannot decode JSON"
        # because it looks for a form field named "message" and finds none.
        #
        # Also: EDSM does NOT honor Content-Encoding: gzip on this endpoint.
        # If we gzip the body, EDSM treats the binary bytes as raw form data,
        # finds no recognizable key=value pairs, and rejects with msgnum 201
        # "Missing commander name".  EDMC (the canonical EDSM uploader) sends
        # plain form data; we do the same.
        # Resolve version metadata for both per-event injection (already
        # done in EDSMPlugin.on_event) and the top-level form fields EDSM
        # checks at the batch level.  Without fromGameVersion / fromGameBuild
        # at the form-field level (alongside commanderName / apiKey /
        # fromSoftware / fromSoftwareVersion / message), EDSM rejects the
        # entire batch with msgnum 207 "Game/Build version not found"
        # before it even examines the events.  EDMC sends these — we must too.
        md: dict = {}
        if self._metadata_provider:
            try:
                md = self._metadata_provider() or {}
            except Exception as e:
                print(f"  [EDSM] Metadata provider error: {e}")
                md = {}

        if not md.get("gameversion"):
            # No Fileheader/LoadGame seen yet this session — EDSM will reject
            # any batch we send without fromGameVersion.  Persist and bail.
            with self._stats_lock:
                self._stats["http_failures"] += 1
            print(
                f"  [EDSM] Pre-flight failed — version metadata not yet known "
                f"(Fileheader/LoadGame missing); persisting {len(events)} "
                f"event(s) to disk for later retry."
            )
            self._persist(events)
            return

        form = {
            "commanderName":       cmdr,
            "apiKey":              self._key,
            "fromSoftware":        SOFTWARE_NAME,
            "fromSoftwareVersion": SOFTWARE_VERSION,
            "fromGameVersion":     md["gameversion"],
            "fromGameBuild":       md.get("build", ""),
            "message":             json.dumps(events, separators=(",", ":")),
        }
        try:
            import urllib.parse as _up
            body = _up.urlencode(form).encode("utf-8")
            req = urllib.request.Request(
                EDSM_JOURNAL_URL,
                data=body,
                headers={
                    "Content-Type":   "application/x-www-form-urlencoded",
                    "User-Agent":     f"{SOFTWARE_NAME}/{SOFTWARE_VERSION}",
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
            # Auth-class errors deserve a bright banner.  Surface the exact
            # request-level credentials and version metadata we sent (cmdr
            # visible, key length only) so the user can compare against their
            # config — the most common causes are an ApiKey mismatch with the
            # journal-derived commander name, or missing version metadata.
            if top_msgnum in (201, 202, 203, 204, 205, 206, 207, 208):
                gv = self._metadata_provider() if self._metadata_provider else {}
                try:
                    cmdr_now = self._cmdr_provider() or ""
                except Exception:
                    cmdr_now = ""
                print(
                    f"  [EDSM] *** BATCH REJECTED ({top_msgnum}): {top_msg} ***\n"
                    f"  [EDSM]     Sent commanderName={cmdr_now!r} (journal-sourced)  "
                    f"apiKey=<{len(self._key)} chars>\n"
                    f"  [EDSM]     Sent fromGameVersion={gv.get('gameversion')!r}  "
                    f"fromGameBuild={gv.get('build')!r}\n"
                    f"  [EDSM]     Verify the [EDSM] ApiKey in config.toml matches "
                    f"this commander on https://www.edsm.net/en/settings/api"
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

        if not events:
            try:
                self._queue_file.unlink(missing_ok=True)
            except Exception:
                pass
            return

        # Re-enrich events that lack version metadata.  Old queued events
        # from previous bug eras don't have gameversion/build/etc., and
        # EDSM 207-rejects any batch containing such an event.  If we have
        # current session metadata, inject it (setdefault preserves existing
        # values where the event already had them).  If we don't yet have
        # metadata — Fileheader/LoadGame not seen this session — defer the
        # drain entirely; queue.jsonl stays intact for the next attempt.
        metadata: dict = {}
        if self._metadata_provider:
            try:
                metadata = self._metadata_provider() or {}
            except Exception as e:
                print(f"  [EDSM] Metadata provider error: {e}")

        needs_enrich = sum(1 for ev in events if "gameversion" not in ev)
        if needs_enrich and not metadata.get("gameversion"):
            print(
                f"  [EDSM] Deferring queue drain — {needs_enrich} of "
                f"{len(events)} queued event(s) lack version metadata and "
                f"Fileheader/LoadGame have not been seen yet this session."
            )
            return  # leave queue.jsonl intact; retry next session

        if needs_enrich and metadata:
            for ev in events:
                if "gameversion" not in ev:
                    for k, v in metadata.items():
                        if v is not None:
                            ev.setdefault(k, v)
            print(
                f"  [EDSM] Re-enriched {needs_enrich} drained event(s) "
                f"with current session metadata (gameversion="
                f"{metadata.get('gameversion')!r})."
            )

        print(f"  [EDSM] Replaying {len(events)} queued event(s) from disk...")

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
        # Horizons / Odyssey flags — EDSM uses these to confirm an event
        # belongs to the live galaxy.  None until we observe Fileheader or
        # LoadGame; once set, injected into every outbound event.
        self._horizons:       bool | None = None
        self._odyssey:        bool | None = None
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

        # Only ApiKey is required from config — commander name now comes from
        # journal data via state.pilot_name once preload has parsed Commander/
        # LoadGame.  Strip whitespace defensively since TOML preserves spaces.
        key_raw = cfg["ApiKey"]
        key     = key_raw.strip() if isinstance(key_raw, str) else ""

        if not key:
            print(
                "  [EDSM] Disabled — ApiKey is empty.  "
                "Check the [EDSM] section (or [<Profile>].EDSM.*) in config.toml."
            )
            return

        self._enabled = True
        self._key     = key
        # Commander name resolved at send time from state.pilot_name.  Same
        # callable goes to the sender (for the form body), the position-check
        # thread (for /get-position), and the rejection banner.
        self._cmdr_provider = lambda: (getattr(core.state, "pilot_name", None) or "")

        # Fetch discard list in a background thread so startup isn't delayed
        threading.Thread(
            target=self._fetch_discard_list,
            daemon=True,
            name="edsm-discard",
        ).start()
        # Sanity check: ask EDSM what position they have on file for us.
        # Runs slightly later so journal preload has a chance to populate
        # state.pilot_name first.
        threading.Thread(
            target=self._fetch_position_check,
            daemon=True,
            name="edsm-position",
        ).start()

        self._sender = _Sender(
            self._cmdr_provider, self._key,
            self.storage.file_path("queue.jsonl"),
            metadata_provider=self._get_metadata_snapshot,
        )
        self._sender.start()

        # Key length only — full key never goes to logs.  Commander name will
        # appear on the first batch's diagnostic line once pilot_name lands.
        from core import debug as _dbg
        _dbg.info(
            f"  [EDSM] Enabled — ApiKey=<{len(self._key)} chars>; "
            f"commander will be sourced from journal data."
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

        # Game version / build metadata.  FDev's journal only emits these on
        # Fileheader and LoadGame; every other event omits them.  EDSM
        # rejects the batch with msgnum 207 "Game/Build version not found"
        # unless each event carries the metadata.  We populate from our cache
        # of the most recent Fileheader/LoadGame.  Field names match what
        # FDev / EDMC use so EDSM can read whichever variant it expects.
        if self._game_version:
            enriched.setdefault("gameversion", self._game_version)
        if self._game_build:
            enriched.setdefault("build",     self._game_build)
            enriched.setdefault("gamebuild", self._game_build)
        if self._horizons is not None:
            enriched.setdefault("horizons",  self._horizons)
            enriched.setdefault("Horizons",  self._horizons)
        if self._odyssey is not None:
            enriched.setdefault("odyssey",   self._odyssey)
            enriched.setdefault("Odyssey",   self._odyssey)

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

        # After arriving in a new system (live, not preload), ask EDSM what
        # bodies they know about.  Helps the user gauge exploration value
        # without leaving the app.  Skipped during preload to avoid a flood
        # of HTTP calls for historical jumps.
        if ev in ("FSDJump", "CarrierJump") and not getattr(state, "in_preload", False):
            self._maybe_announce_destination_bodies()

    def _note_filtered(self, ev: str, reason: str) -> None:
        """Surface filter decisions when trace mode is on — answers
        'why didn't EDSM see my X event' without re-running the journal."""
        if getattr(self.core, "trace_mode", False):
            print(f"  [EDSM trace] filtered {ev}  ({reason})")

    def _get_metadata_snapshot(self) -> dict:
        """Snapshot of current version/galaxy fields for event enrichment.

        Called by _Sender when re-enriching drained events from disk that
        were queued before we started injecting these fields.  Returns
        only fields that are populated; absent fields are omitted so the
        caller can detect "metadata not yet known" by checking gameversion.
        """
        md: dict = {}
        if self._game_version:
            md["gameversion"] = self._game_version
        if self._game_build:
            md["build"]     = self._game_build
            md["gamebuild"] = self._game_build
        if self._horizons is not None:
            md["horizons"] = self._horizons
            md["Horizons"] = self._horizons
        if self._odyssey is not None:
            md["odyssey"]  = self._odyssey
            md["Odyssey"]  = self._odyssey
        return md

    def _update_tracking(self, ev: str, event: dict) -> None:
        """Maintain internal location/session state from raw journal events."""
        if ev == "Fileheader":
            self._game_version = event.get("gameversion", "") or ""
            self._game_build   = event.get("build", "") or ""
            # Fileheader carries Odyssey (bool); Horizons comes from LoadGame
            if "Odyssey" in event:
                self._odyssey = bool(event.get("Odyssey"))

        elif ev == "LoadGame":
            # LoadGame is authoritative — it carries gameversion + build +
            # both flags.  Always update so a mid-session game-mode change
            # (e.g. legacy ↔ live, Horizons ↔ Odyssey) is reflected.
            gv = event.get("gameversion", "") or ""
            gb = event.get("build", "")       or ""
            if gv: self._game_version = gv
            if gb: self._game_build   = gb
            if "Horizons" in event:
                self._horizons = bool(event.get("Horizons"))
            if "Odyssey" in event:
                self._odyssey = bool(event.get("Odyssey"))

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

    # ── Read endpoints ────────────────────────────────────────────────────────

    def _fetch_position_check(self) -> None:
        """One-shot sanity check at startup: what does EDSM think our last
        reported position is?  Prints a one-liner showing system + age so the
        user can confirm the link is bidirectional.  Failure is logged but
        not fatal — read failures don't affect uploads.

        Waits briefly for journal preload to populate state.pilot_name; if
        that doesn't happen within the wait window the check is skipped
        with a hint so the user knows the journal stream isn't flowing.
        """
        # Poll for pilot_name to appear.  Preload typically lands within a
        # few seconds; we wait up to 30 s before giving up.
        for _ in range(30):
            time.sleep(1.0)
            cmdr = (self._cmdr_provider() or "").strip()
            if cmdr:
                break
        else:
            print(
                "  [EDSM] Position check skipped — journal preload did not "
                "populate commander name within 30 s."
            )
            return
        try:
            import urllib.parse as _up
            url = (
                f"{EDSM_CMDR_POSITION_URL}?"
                + _up.urlencode({
                    "commanderName": cmdr,
                    "apiKey":        self._key,
                    "showId":        1,
                })
            )
            req = urllib.request.Request(
                url, headers={"User-Agent": f"{SOFTWARE_NAME}/{SOFTWARE_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                if resp.status != 200:
                    return
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            print(f"  [EDSM] Position check failed ({type(exc).__name__}: {exc})")
            return

        msgnum = body.get("msgnum")
        if isinstance(msgnum, int) and msgnum >= 200:
            print(f"  [EDSM] Position check rejected ({msgnum}): {body.get('msg','')}")
            return
        system   = body.get("system")
        date     = body.get("date")
        first    = body.get("firstDiscover")
        if system:
            extra = f" at {date}" if date else ""
            extra += " (first discoverer)" if first else ""
            print(f"  [EDSM] Last known position: {system}{extra}")
        else:
            print(f"  [EDSM] No prior position on file — uploads will establish history.")

    def fetch_system_bodies(self, system_name: str | None = None,
                            system_address: int | None = None) -> dict | None:
        """Public read: fetch the body list EDSM has for a system.

        Returns the parsed response on success, None on any failure.
        Either system_name or system_address can be supplied — the latter
        is preferred when both are available since it's unambiguous.
        Available via core.plugin_call("edsm", "fetch_system_bodies", ...).
        """
        if not system_name and not system_address:
            return None
        try:
            import urllib.parse as _up
            params: dict = {}
            if system_address is not None:
                params["systemId64"] = system_address
            elif system_name:
                params["systemName"] = system_name
            url = f"{EDSM_SYSTEM_BODIES_URL}?{_up.urlencode(params)}"
            req = urllib.request.Request(
                url, headers={"User-Agent": f"{SOFTWARE_NAME}/{SOFTWARE_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                if resp.status != 200:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def _maybe_announce_destination_bodies(self) -> None:
        """Called shortly after FSDJump: fetch EDSM's body knowledge for the
        new system, log "EDSM has N bodies known" line.  Non-blocking —
        runs on its own short-lived thread so the dispatcher doesn't stall.
        """
        sys_name = self._system_name
        sys_addr = self._system_address
        if not sys_name and sys_addr is None:
            return
        def _worker():
            data = self.fetch_system_bodies(sys_name, sys_addr)
            if not isinstance(data, dict):
                return
            n_bodies = int(data.get("bodyCount") or 0)
            known    = data.get("bodies") or []
            if n_bodies > 0 or known:
                print(
                    f"  [EDSM] {sys_name}: EDSM knows {len(known)}/{n_bodies} "
                    f"bodies"
                )
        threading.Thread(target=_worker, daemon=True,
                         name="edsm-bodies").start()

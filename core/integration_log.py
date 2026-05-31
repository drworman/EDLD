"""
core/integration_log.py — Unified logging for upload integrations.

All four EDLD integrations (EDDN, EDSM, EDAstro, Inara) share the same
fundamental shape:

    1. Maintain an in-memory + disk-backed queue of events to send.
    2. POST a batch to an HTTP endpoint.
    3. Parse the response for a top-level status, then per-event statuses
       inside an ``events[]`` array.
    4. Log everything to the file-based debug log so it survives the
       GTK4 fork-early restructure (which silently sends bare ``print()``
       to ``/dev/null`` on the child process).

This module standardises the log format across all four integrations so
the file is consistent and per-event errors get surfaced automatically.
Each function emits a single line prefixed with ``[<Tag>]`` matching the
existing pattern in the rest of the codebase.

Severity policy
---------------
- ``log()`` (verbose / routine)  — anything that happens normally and
  doesn't need to draw attention: batch POSTs, accepted responses,
  per-event notices that mean "we already have this" (EDSM 101/102,
  Inara 204).  Always written to the file but doesn't add noise to a
  user scanning for problems.
- ``info()`` (problem / decision) — anything the user genuinely needs
  to see: HTTP failures, top-level rejections, per-event hard errors
  (Inara 400+, EDSM 2xx/5xx), disk-persist decisions, sender startup.

Bodies
------
``body_dump()`` is a debug-trace helper that writes a raw response body
to the log, truncated to a sensible maximum.  Callers should gate it on
``core.trace_mode`` to avoid spamming the log under normal operation —
this module deliberately doesn't reach into ``core`` itself to keep the
dependency direction clean (every plugin imports core; core shouldn't
import plugins).
"""
from __future__ import annotations

from pathlib import Path
from typing  import Any

from core import debug as _dbg


# ── Sender lifecycle ─────────────────────────────────────────────────────────

def sender_started(tag: str, queue_file: Path | str) -> None:
    """Log the entry banner when an integration's sender thread starts.

    Critical for diagnosing "did the thread even launch?" — a NameError
    or import-time exception will kill the thread silently otherwise.
    """
    _dbg.info(f"  [{tag}] sender thread entering main loop "
              f"(queue file: {queue_file})")


def sender_stopped(tag: str, **counts: Any) -> None:
    """Log a closing summary when the sender exits cleanly."""
    bits = [f"{k}={v}" for k, v in counts.items()]
    suffix = f" — {', '.join(bits)}" if bits else ""
    _dbg.info(f"  [{tag}] sender thread exiting{suffix}")


def heartbeat(tag: str, **counts: Any) -> None:
    """Per-minute sender heartbeat.

    Surfaces 'thread alive but queue idle' vs 'queue active but nothing
    sending' patterns over the lifetime of a session.  Each integration
    picks its own keys (push_count, batch, sent, accepted, rejected,
    failures, etc) — the helper just formats them uniformly.
    """
    bits = [f"{k}={v}" for k, v in counts.items()]
    _dbg.log(f"  [{tag}] sender heartbeat: " + ", ".join(bits))


# ── Request / response logging ───────────────────────────────────────────────

def request_posted(tag: str, count: int, cmdr: str = "", **extra: Any) -> None:
    """Log the start of a batch POST.

    ``cmdr`` is the commander name for batches that carry one (Inara,
    EDSM).  Anonymous batches (EDDN, EDAstro) just pass count.  Extra
    kwargs become ``k=v`` suffixes (e.g. ``gameversion='4.3.3.0'``).
    """
    bits = [f"POST {count} event(s)"]
    if cmdr:
        bits.append(f"commander={cmdr!r}")
    for k, v in extra.items():
        bits.append(f"{k}={v!r}")
    _dbg.log(f"  [{tag}] " + ", ".join(bits))


def response_ok(tag: str, http_status: Any, count: int = 0,
                **extra: Any) -> None:
    """Log a successful batch response."""
    bits = [f"batch accepted (HTTP {http_status}"]
    for k, v in extra.items():
        bits.append(f"{k}={v!r}")
    bits.append(f"{count} event(s))")
    _dbg.log(f"  [{tag}] " + ", ".join(bits))


def response_failed(tag: str, http_status: Any, msg: str = "",
                    count: int = 0) -> None:
    """Log a top-level batch failure (HTTP error or header rejection)."""
    bit = f"batch failed (HTTP {http_status})"
    if msg:
        bit += f": {msg}"
    if count:
        bit += f" — {count} event(s) affected"
    _dbg.info(f"  [{tag}] {bit}")


# ── Per-event statuses ───────────────────────────────────────────────────────
#
# Both Inara and EDSM return per-event status codes inside the response's
# ``events[]`` array, separate from the top-level status.  Inara reports
# these in the dashboard's Errors / SoftErrors / Warnings columns.  EDSM
# uses them for 101 "already stored" / 102 "older" / 103 "duplicate"
# notices.  Surfacing each one in the log so the user can see exactly
# which event failed and why.

def event_notice(tag: str, ev_name: str, status: Any, msg: str = "") -> None:
    """Per-event informational notice — routine, not a problem.

    e.g. EDSM 101 "already stored", 102 "older than stored",
    Inara 204 "event was processed but is functionally a no-op".
    """
    suffix = f": {msg}" if msg else ""
    _dbg.log(f"  [{tag}] {ev_name} notice ({status}){suffix}")


def event_warning(tag: str, ev_name: str, status: Any, msg: str = "") -> None:
    """Per-event warning — something looks wrong but the upload continued.

    e.g. Inara 3xx soft errors, EDSM 1xx-warning sub-codes.
    """
    suffix = f": {msg}" if msg else ""
    _dbg.info(f"  [{tag}] event warning — {ev_name} ({status}){suffix}")


def event_error(tag: str, ev_name: str, status: Any, msg: str = "") -> None:
    """Per-event hard error — the event was rejected.

    e.g. Inara 400 "Missing required field",
    EDSM 200-series fatal codes.
    """
    suffix = f": {msg}" if msg else ""
    _dbg.info(f"  [{tag}] EVENT ERROR — {ev_name} status={status}{suffix}")


def parse_inara_events(tag: str, events_sent: list[dict],
                       events_response: list[dict]) -> None:
    """Walk Inara's per-event response array, logging anything non-OK.

    Inara's response shape:
        {"header": {"eventStatus": 200, ...},
         "events": [{"eventStatus": 200}, {"eventStatus": 400, ...}]}

    A 200 is OK.  A 204 means accepted-but-no-op.  Everything else is
    surfaced — 3xx as warnings, 4xx+ as errors — with the event name
    pulled from the corresponding entry in events_sent.
    """
    for idx, resp in enumerate(events_response):
        try:
            status = resp.get("eventStatus", 200)
        except AttributeError:
            continue
        if status in (200, 204):
            continue
        msg     = resp.get("eventStatusText", "") if isinstance(resp, dict) else ""
        ev_name = "?"
        if idx < len(events_sent):
            try:
                ev_name = events_sent[idx].get("eventName", "?") or "?"
            except AttributeError:
                pass
        if status >= 400:
            event_error  (tag, ev_name, status, msg)
        else:
            event_warning(tag, ev_name, status, msg)


def parse_edsm_events(tag: str, events_sent: list[dict],
                      events_response: list[dict]) -> None:
    """Walk EDSM's per-event response array, logging anything non-100.

    EDSM's response shape:
        {"msgnum": 100, "msg": "OK",
         "events": [{"msgnum": 100, "msg": "OK"},
                    {"msgnum": 102, "msg": "Message older than the stored one"}]}

    msgnum 100 is OK.  1xx are informational notices (101/102/103 etc).
    2xx and 5xx are errors.  The event name comes from the corresponding
    entry in events_sent.
    """
    for idx, resp in enumerate(events_response):
        try:
            msgnum = resp.get("msgnum", 100)
        except AttributeError:
            continue
        if msgnum == 100:
            continue
        msg     = resp.get("msg", "") if isinstance(resp, dict) else ""
        ev_name = "?"
        if idx < len(events_sent):
            try:
                ev_name = events_sent[idx].get("event", "?") or "?"
            except AttributeError:
                pass
        if 100 < msgnum < 200:
            event_notice (tag, ev_name, msgnum, msg)
        elif msgnum >= 500:
            event_error  (tag, ev_name, msgnum, msg)
        else:
            event_error  (tag, ev_name, msgnum, msg)


# ── Generic ──────────────────────────────────────────────────────────────────

def notice(tag: str, message: str) -> None:
    """User-visible single-line notice ('Uploads suppressed', etc).

    Always written prominently (debug.info), not gated on trace.
    """
    _dbg.info(f"  [{tag}] {message}")


def transient(tag: str, message: str) -> None:
    """Routine activity log line — always written, low priority."""
    _dbg.log(f"  [{tag}] {message}")


def body_dump(tag: str, body: str, *, max_chars: int = 2000) -> None:
    """Dump a raw response body to the log, truncated to max_chars.

    Useful when an integration returns something unexpected and we
    want to see the literal bytes.  Callers should gate this on
    ``core.trace_mode`` to keep the file from filling with response
    bodies under normal operation.
    """
    if body is None:
        return
    s = body if len(body) <= max_chars else (
        body[:max_chars] + f"... (truncated; {len(body)} chars total)"
    )
    _dbg.log(f"  [{tag}] raw response body:\n{s}")

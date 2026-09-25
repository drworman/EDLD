"""
core/server/protocol.py — what goes over the wire, and how it is built.

Framing
-------
UTF-8 JSON, one object per line (NDJSON), over TLS.  The same framing the
overlay renderer already uses, chosen for the same reasons: trivially parsed on
every platform, readable in a packet capture of the decrypted stream, and no
library needed on either end.  Lines longer than :data:`MAX_LINE` are refused.

Every message has a ``t`` (type).  See docs/SERVER.md for the full list.

The model
---------
A snapshot is a ``header`` plus a list of ``panels``.  The header is what the
client shows at all times — commander, squadron, ship, where they are, whether
the game is running.  A panel is a titled list of rows in the shape the
dashboards already use, ``{label, value, rate, kind}``, built from the same
UI-agnostic sources the dashboards and the overlay read:

* ``session.*`` and ``career.*`` — :mod:`core.summary_model`, exactly what the
  Session and Career tabs show
* ``commander``, ``ship``, ``cargo`` — the components' own overlay panels
* ``status`` — hull, shields, fuel
* ``alerts`` — the Alerts pane

Nothing here decides what a number means or how to format it.  That is the
components' job, and the mobile client shows what they produced, the same way
the TUI and the desktop window do.  A panel added to a component appears on the
device without anything being written twice.

Changes are sent per panel: when a panel's content differs from what was last
published it is sent again whole.  Panels are small, and whole-panel updates
mean the client never has to reconcile a partial one.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import time
from typing import Any, Callable

from core.server import PROTOCOL_VERSION

MAX_LINE = 1 << 20            # 1 MiB
_SLUG = re.compile(r"[^a-z0-9]+")


# ── Framing ───────────────────────────────────────────────────────────────────

class ProtocolError(ValueError):
    pass


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":"), ensure_ascii=False,
                       default=str) + "\n").encode("utf-8")


def decode(line: bytes) -> dict:
    if len(line) > MAX_LINE:
        raise ProtocolError("line too long")
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc
    if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
        raise ProtocolError("not a message")
    return msg


# ── Rows and panels ───────────────────────────────────────────────────────────

def slug(text: str) -> str:
    return _SLUG.sub("-", str(text).lower()).strip("-") or "section"


def _row(label: Any, value: Any, rate: Any = None, kind: str = "kv") -> dict:
    return {"label": "" if label is None else str(label),
            "value": "" if value is None else str(value),
            "rate": None if not rate else str(rate),
            "kind": kind}


def rows_from_model(rows: list) -> list[dict]:
    """Rows from core.summary_model, which are already in wire shape."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        out.append(_row(r.get("label"), r.get("value"), r.get("rate"),
                        str(r.get("kind") or "kv")))
    return out


def rows_from_overlay(rows: list) -> list[dict]:
    """Rows from an overlay Panel: ``(label, value)`` pairs.

    An empty label is a full-width line and an empty value is a heading, the
    same convention the overlay draws with.
    """
    out = []
    for pair in rows or []:
        try:
            label, value = pair
        except (TypeError, ValueError):
            continue
        if not label:
            out.append(_row("", value, kind="line"))
        elif value in (None, ""):
            out.append(_row(label, "", kind="sub"))
        else:
            out.append(_row(label, value))
    return out


def panel(pid: str, title: str, group: str, rows: list[dict],
          order: int = 100) -> dict:
    return {"id": pid, "title": title, "group": group,
            "order": order, "rows": rows}


def digest(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str)
                        .encode("utf-8")).hexdigest()


# ── Building from a running EDLD ──────────────────────────────────────────────

def _iso(dt) -> str | None:
    if isinstance(dt, _dt.datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone(_dt.timezone.utc).isoformat(timespec="seconds")
    return None


class SnapshotBuilder:
    """Builds headers and panels from CoreAPI.

    Each source is isolated: one that raises is logged once per distinct fault
    and its panels are left out, so a broken component costs the device one
    panel, not the connection.
    """

    #: How often the game-running check may run.  It can fall back to a
    #: process scan, which is not something to do every second.
    GAME_CHECK_S = 5.0

    def __init__(self, core, journal_dir=None, log: Callable[[str], None] | None = None,
                 kill_allowed: Callable[[], tuple[bool, str]] | None = None):
        self.core = core
        self.journal_dir = journal_dir
        self._log = log or (lambda m: None)
        self._kill_allowed = kill_allowed or (lambda: (False, "disabled"))
        self._faults: set[str] = set()
        self._game_running = False
        self._game_checked = 0.0
        self._alert_ts: dict[tuple, str] = {}

    def _fault(self, where: str, exc: BaseException) -> None:
        sig = f"{where}: {type(exc).__name__}: {exc}"
        if sig not in self._faults:
            self._faults.add(sig)
            self._log(f"[server] {sig}")

    # ── header ────────────────────────────────────────────────────────────────

    def game_running(self) -> bool:
        now = time.monotonic()
        if now - self._game_checked >= self.GAME_CHECK_S:
            self._game_checked = now
            try:
                from core.journal import _ed_client_running
                self._game_running = bool(_ed_client_running(self.journal_dir))
            except Exception as exc:
                self._fault("game check", exc)
        return self._game_running

    def header(self) -> dict:
        s = getattr(self.core, "state", None)
        g = lambda name, default=None: getattr(s, name, default) if s else default
        kill_ok, kill_reason = self._kill_allowed()
        return {
            "cmdr": g("pilot_name"),
            "squadron": {
                "name": g("pilot_squadron_name") or None,
                "tag": g("pilot_squadron_tag") or None,
                "rank": g("pilot_squadron_rank") or None,
            } if g("pilot_squadron_name") else None,
            "ship": {
                "name": g("ship_name"),
                "ident": g("ship_ident"),
                "type": g("pilot_ship"),
            } if (g("ship_name") or g("pilot_ship")) else None,
            "system": g("pilot_system"),
            "location": g("pilot_location"),
            "mode": g("pilot_mode"),
            "game": {
                "running": self.game_running(),
                "lastEvent": _iso(g("event_time")),
            },
            "monitorError": g("monitor_error") or None,
            "endSession": {"available": kill_ok, "reason": kill_reason or None},
        }

    # ── panels ────────────────────────────────────────────────────────────────

    def panels(self) -> list[dict]:
        out: list[dict] = []
        out += self._status_panel()
        out += self._overlay_panels()
        out += self._model_panels("session", 300)
        out += self._model_panels("career", 500)
        out += self._alerts_panel()
        return out

    def _status_panel(self) -> list[dict]:
        s = getattr(self.core, "state", None)
        if s is None:
            return []
        rows: list[dict] = []
        try:
            hull = getattr(s, "ship_hull", None)
            if hull is not None:
                rows.append(_row("Hull", f"{float(hull):.0f}%"))
            shields = getattr(s, "ship_shields", None)
            if shields is not None:
                recharging = getattr(s, "ship_shields_recharging", False)
                rows.append(_row("Shields", "Recharging" if recharging
                                 else ("Up" if shields else "Down")))
            fuel = getattr(s, "fuel_current", None)
            tank = getattr(s, "fuel_tank_size", None)
            if fuel is not None and tank:
                rows.append(_row("Fuel", f"{fuel:.1f} / {float(tank):.0f} t "
                                         f"({100 * fuel / float(tank):.0f}%)"))
        except Exception as exc:
            self._fault("status panel", exc)
            return []
        return [panel("status", "Status", "status", rows, 10)] if rows else []

    def _overlay_panels(self) -> list[dict]:
        """The components' own overlay panels that carry no scope setting.

        Activity panels are left out here — their figures arrive richer through
        the session and career models — and so is anything whose content
        depends on an overlay-only setting, which a device has no way to set.
        """
        from core.overlay_panels import context_from
        try:
            from core.surface_survey import POSITIONS
            pos = POSITIONS.latest()
        except Exception:
            pos = None
        ctx = context_from(pos, getattr(self.core, "state", None))
        out = []
        order = 20
        for comp in list(getattr(self.core, "_plugins", {}).values()):
            # "commander" is left out: the header already carries it.
            for pid in ("ship", "cargo"):
                if pid not in (getattr(comp, "OVERLAY_PANELS", ()) or ()):
                    continue
                try:
                    p = comp.overlay_panel(pid, ctx)
                except Exception as exc:
                    self._fault(f"{pid} panel", exc)
                    continue
                if p is None or p.is_empty():
                    continue
                out.append(panel(pid, p.title or pid.title(), "vessel",
                                 rows_from_overlay(p.rows), order))
                order += 1
        return out

    def _model_panels(self, scope: str, base_order: int) -> list[dict]:
        try:
            from core import summary_model
            fn = (summary_model.session_sections if scope == "session"
                  else summary_model.career_sections)
            sections = fn(self.core) or []
        except Exception as exc:
            self._fault(f"{scope} model", exc)
            return []
        out = []
        for i, sec in enumerate(sections):
            title = str(sec.get("title", "") or scope)
            out.append(panel(f"{scope}.{slug(title)}", title, scope,
                             rows_from_model(sec.get("rows", [])),
                             base_order + i))
        return out

    def _alerts_panel(self) -> list[dict]:
        alerts = getattr(self.core, "_plugins", {}).get("alerts")
        if alerts is None:
            return []
        try:
            items = alerts.get_alerts()
        except Exception as exc:
            self._fault("alerts", exc)
            return []
        # Each alert carries when it happened, not how long ago: an age would
        # change every second and resend the panel with it.  The device turns
        # the time into "4m ago" itself.
        mono_now, wall_now = time.monotonic(), time.time()
        rows = []
        for a in items:
            row = _row("", f"{a.get('emoji', '')} {a.get('text', '')}".strip(),
                       kind="line")
            mono = a.get("mono_time")
            if mono is not None:
                # Converted once per alert and remembered: recomputing it each
                # build lets clock jitter flip the rounded second, which would
                # resend the panel for nothing.
                key = (float(mono), row["value"])
                ts = self._alert_ts.get(key)
                if ts is None:
                    at = wall_now - (mono_now - float(mono))
                    ts = _dt.datetime.fromtimestamp(
                        round(at), _dt.timezone.utc).isoformat(timespec="seconds")
                    self._alert_ts[key] = ts
                row["ts"] = ts
            rows.append(row)
        if len(self._alert_ts) > 64:            # forget alerts long gone
            live = {float(a["mono_time"]) for a in items
                    if a.get("mono_time") is not None}
            self._alert_ts = {k: v for k, v in self._alert_ts.items()
                              if k[0] in live}
        return [panel("alerts", "Alerts", "status", rows, 15)] if rows else []

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class ChangeTracker:
    """Remembers what was last published and reports what changed."""

    def __init__(self):
        self.seq = 0
        self._header_digest: str | None = None
        self._panel_digests: dict[str, str] = {}
        self.header: dict = {}
        self.panels: dict[str, dict] = {}

    def update(self, header: dict, panels: list[dict]) -> dict | None:
        """Fold in a fresh build.  Returns a ``panels`` message, or None."""
        upsert, remove = [], []
        new = {p["id"]: p for p in panels}
        for pid, p in new.items():
            d = digest(p)
            if self._panel_digests.get(pid) != d:
                self._panel_digests[pid] = d
                upsert.append(p)
        for pid in list(self._panel_digests):
            if pid not in new:
                del self._panel_digests[pid]
                remove.append(pid)
        hd = digest(header)
        header_changed = hd != self._header_digest
        self._header_digest = hd
        self.header, self.panels = header, new
        if not (upsert or remove or header_changed):
            return None
        self.seq += 1
        msg = {"t": "panels", "seq": self.seq, "ts": _now_iso(),
               "upsert": upsert, "remove": remove}
        if header_changed:
            msg["header"] = header
        return msg

    def snapshot(self) -> dict:
        return {"t": "snapshot", "v": PROTOCOL_VERSION, "seq": self.seq,
                "ts": _now_iso(), "header": self.header,
                "panels": list(self.panels.values())}

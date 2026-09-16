"""
core/overlay.py — Contextual on-screen overlay: primitives and transport.

**Experimental.** Off by default, and verified only on X11 so far — there is no
Windows or macOS machine to test against, so those platforms are reasoned about
rather than confirmed.  ``--overlay-probe`` reports what any given machine can
actually do, which is what a bug report from one of them should carry.

EDLD draws its own overlay rather than talking to somebody else's. Hooking into
an existing overlay tool would mean every EDLD user first installing that tool,
which is a poor answer to "why would I run this", and the established one is
GPLv3 against EDLD's MIT.

Architecture
------------
The renderer runs in a **child process**, not a thread. Qt requires its event
loop on the main thread, and EDLD's main thread is already the TUI's, the
terminal's, or the dashboard's Qt loop depending on mode. A child gives all
three modes the same overlay, keeps a renderer crash from taking the dashboard
with it, and means the TUI does not acquire a Qt dependency at runtime.

Frames go to the child over **stdin**, newline-delimited JSON, one frame per
line. A socket was the obvious choice and is the wrong one: binding a listener
on localhost triggers a Windows Firewall prompt the first time, collides with
whatever else wanted the port, and outlives a parent that died badly. A pipe
does none of that, and the child exits on its own when the parent closes it.

The child reports back on **stdout**: one JSON line at startup saying what it
was actually able to do, then status lines. See :class:`OverlayCapabilities`.

Capabilities are measured, not assumed
--------------------------------------
Whether a translucent, click-through, always-on-top window is possible depends
on the platform, the compositor, and on Wayland the answer is simply no — an
ordinary client cannot position itself absolutely or stay above others, and the
protocol that would allow it is not something Qt exposes. Rather than shipping
a table of what ought to work, the child tries and reports, and Options shows
what came back.

Exclusive fullscreen defeats every overlay on every platform. Nothing here can
change that; the probe reports the display mode where it can determine it so
the answer is visible rather than mysterious.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

#: Config section for the overlay, read by the surface_mining component.
CFG_DEFAULTS = {
    "Enabled":     False,
    "Anchor":      "top-centre",   # top-left | top-centre | top-right | bottom-*
    # Spacing, in two layers, because there are genuinely two gaps and the
    # previous names hid one of them: OffsetY was what actually set the
    # distance from the monitor edge and was never exposed in either front
    # end, while the exposed "Padding Y" only moved text around inside a
    # fixed-size window. Asking which one moved the overlay down the screen
    # had no reachable answer.
    #
    #   Margin  — monitor edge   →  window edge   (moves the whole overlay)
    #   Pad     — window edge    →  first glyph   (breathing room in the box)
    "MarginX":     0,
    "MarginY":     40,
    "Width":       720,   # height is grown to fit the content
    "Opacity":     0.85,
    "FontFamily":  "",     # blank = whatever Qt picks; any installed family
    "ColourTheme": "elite-orange",
    "ShadowOffset":   1,      # px, 0-2; 0 disables the shadow
    "ShadowStrength": 0.85,   # 0-1, multiplied by Opacity
    "PadX":        16,
    "PadY":        8,
    "DockWidth":   260,    # width of the left/right docked windows
    "DockTop":     140,    # monitor top edge → top of a dock window
    "Scale":       1.0,
    "SpanDegrees": 90,    # width of the compass tape, in degrees of arc
    "MaxTargets":  5,     # marks drawn on the tape at once
    "Monitor":     0,
}

_ANCHORS = ("top-left", "top-centre", "top-right",
            "bottom-left", "bottom-centre", "bottom-right")

_HANDSHAKE_TIMEOUT_S = 10.0


# ── primitives ────────────────────────────────────────────────────────────────

def text(id: str, x: int, y: int, body: str, colour: str = "#cfd6e4",
         size: int = 13, weight: str = "normal") -> dict:
    """A run of text at a position inside the overlay window."""
    return {"type": "text", "id": id, "x": int(x), "y": int(y),
            "text": str(body), "colour": colour, "size": int(size),
            "weight": weight}


def tape(id: str, x: int, y: int, width: int, heading: float,
         span_deg: float, marks: list[dict]) -> dict:
    """A compass strip: the commander's heading, with bearings placed on it.

    ``marks`` are ``{"bearing": float, "label": str, "colour": str}``.  Anything
    outside the visible span is dropped by :func:`tape_positions` rather than
    clamped to the edge, because a mark pinned to the end of the tape reads as
    "it is over there" when the truth is "it is behind you".
    """
    return {"type": "tape", "id": id, "x": int(x), "y": int(y),
            "width": int(width), "heading": float(heading),
            "span": float(span_deg), "marks": list(marks)}


def relative_bearing(heading: float, bearing: float) -> float:
    """Signed degrees from the nose to a bearing, in (-180, 180]."""
    delta = (float(bearing) - float(heading) + 540.0) % 360.0 - 180.0
    return 180.0 if delta == -180.0 else delta


def tape_positions(heading: float, span_deg: float, width: int,
                   marks: list[dict]) -> list[tuple[float, dict]]:
    """Place marks along a tape, dropping those outside the visible arc.

    Returns ``(x_offset, mark)`` pairs, x measured from the tape's left edge.
    """
    if span_deg <= 0 or width <= 0:
        return []
    half = span_deg / 2.0
    out = []
    for m in marks:
        rel = relative_bearing(heading, m.get("bearing", 0.0))
        if abs(rel) > half:
            continue
        out.append(((rel + half) / span_deg * width, m))
    return out


# ── capabilities ──────────────────────────────────────────────────────────────

@dataclass
class OverlayCapabilities:
    """What the renderer was actually able to do on this machine."""
    available:       bool = False
    platform:        str  = ""     # qt platform plugin name: windows, xcb, wayland, cocoa
    translucent:     bool = False
    click_through:   bool = False
    always_on_top:   bool = False
    compositing:     bool = False
    screens:         int  = 0
    reason:          str  = ""     # populated when available is False

    @property
    def usable(self) -> bool:
        """Whether the overlay is worth showing at all.

        Click-through is not optional. An overlay that swallows mouse input
        over the game is worse than no overlay, because the failure shows up
        as the game not responding rather than as anything to do with EDLD.
        """
        return bool(self.available and self.always_on_top and self.click_through)

    def summary(self) -> str:
        if not self.available:
            return f"unavailable — {self.reason or 'unknown'}"
        missing = [n for n, v in (("always-on-top", self.always_on_top),
                                  ("click-through", self.click_through),
                                  ("translucency",  self.translucent)) if not v]
        if not missing:
            return f"ready ({self.platform}, {self.screens} screen(s))"
        return f"degraded on {self.platform} — no {', '.join(missing)}"


# ── the client ────────────────────────────────────────────────────────────────

class OverlayClient:
    """Owns the renderer child process and writes frames to it."""

    def __init__(self, config: dict | None = None, log=None,
                 spawn: Optional[Callable[[], subprocess.Popen]] = None) -> None:
        self._cfg = {**CFG_DEFAULTS, **(config or {})}
        self._log = log or (lambda _m: None)
        self._spawn = spawn or self._default_spawn
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._caps = OverlayCapabilities()
        self._last_error = ""
        #: Families registered from EDLD's fonts directory, reported by the
        #: renderer. Empty until it has started at least once.
        self.fonts: list[str] = []

    @property
    def capabilities(self) -> OverlayCapabilities:
        return self._caps

    @property
    def running(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    # ── process lifecycle ─────────────────────────────────────────────────────

    def _default_spawn(self) -> subprocess.Popen:
        """Launch the renderer.

        A frozen build re-executes itself with a flag, because there is no
        interpreter on the user's machine to run a module with. A source
        checkout runs the module directly.
        """
        if getattr(sys, "frozen", False):
            argv = [sys.executable, "--overlay-renderer"]
        else:
            argv = [sys.executable, "-m", "core.overlay_proc"]
        env = dict(os.environ)
        env["EDLD_OVERLAY_CONFIG"] = json.dumps(self._cfg)
        return subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, text=True, bufsize=1,
            cwd=str(_repo_root()),
        )

    def start(self) -> OverlayCapabilities:
        """Start the renderer and wait for its capability handshake."""
        with self._lock:
            if self.running:
                return self._caps
            try:
                self._proc = self._spawn()
            except Exception as exc:
                self._caps = OverlayCapabilities(
                    reason=f"could not start renderer: {type(exc).__name__}: {exc}")
                self._log(self._caps.reason)
                return self._caps

            self._caps = self._handshake()
            self._log(f"overlay {self._caps.summary()}")
            if not self._caps.usable:
                self._stop_locked()
            else:
                threading.Thread(target=self._drain_stdout, daemon=True,
                                 name="overlay-stdout").start()
            return self._caps

    def _handshake(self) -> OverlayCapabilities:
        """Read the child's first stdout line, or give up.

        A renderer that never answers is treated as a renderer that does not
        work. Waiting indefinitely for a process that has hung is how an
        optional feature becomes a startup that never finishes.
        """
        deadline = time.time() + _HANDSHAKE_TIMEOUT_S
        proc = self._proc
        assert proc is not None
        while time.time() < deadline:
            if proc.poll() is not None:
                err = (proc.stderr.read() or "").strip().splitlines()
                return OverlayCapabilities(
                    reason=f"renderer exited immediately: "
                           f"{err[-1][:160] if err else f'code {proc.returncode}'}")
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if data.get("event") != "capabilities":
                continue
            data.pop("event", None)
            known = {f for f in OverlayCapabilities.__dataclass_fields__}
            return OverlayCapabilities(**{k: v for k, v in data.items()
                                          if k in known})
        return OverlayCapabilities(
            reason=f"renderer did not answer within {_HANDSHAKE_TIMEOUT_S:.0f}s")

    def _drain_stdout(self) -> None:
        """Keep the child's stdout drained and report anything it says.

        Not optional housekeeping: a child whose stdout pipe fills blocks on
        write and stops rendering, which presents as an overlay that froze for
        no reason.
        """
        proc = self._proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                self._log(f"overlay: {line[:160]}")
                continue
            if data.get("event") == "fonts":
                self.fonts = list(data.get("families") or [])
                self._log(f"overlay fonts available: {', '.join(self.fonts)}")
                continue
            if data.get("event") == "shown":
                self._log(f"overlay window mapped: {data.get('elements')} "
                          f"element(s), visible={data.get('visible')}, "
                          f"geometry={data.get('geometry')}, "
                          f"screen={data.get('screen')}, "
                          f"alpha={data.get('alpha')}")
                continue
            if data.get("event") == "error":
                self._last_error = str(data.get("message", ""))
                self._log(f"overlay error: {self._last_error}")

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        proc, self._proc = self._proc, None
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ── frames ────────────────────────────────────────────────────────────────

    def send(self, elements: list[dict], window: str = "top") -> bool:
        """Draw a frame in one window. An empty list hides that window.

        Returns False when the frame did not go out, which the caller should
        treat as the overlay being gone rather than as a transient.
        """
        if not self.running:
            return False
        payload = json.dumps({"event": "frame", "window": window,
                              "elements": elements})
        with self._lock:
            proc = self._proc
            if not proc or not proc.stdin:
                return False
            try:
                proc.stdin.write(payload + "\n")
                proc.stdin.flush()
                return True
            except (BrokenPipeError, ValueError, OSError) as exc:
                self._last_error = f"renderer went away: {type(exc).__name__}"
                self._log(self._last_error)
                self._stop_locked()
                return False

    def clear(self, window: str = "top") -> bool:
        return self.send([], window)

    def status(self) -> str:
        if not self.running:
            return self._last_error or self._caps.summary()
        return self._caps.summary()


def _repo_root():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent


def client_from_config(cfg: dict, log=None) -> Optional[OverlayClient]:
    """Build a client from a config section, or None if the overlay is off."""
    if not cfg or not cfg.get("Enabled"):
        return None
    anchor = str(cfg.get("Anchor", "top-centre"))
    if anchor not in _ANCHORS:
        if log:
            log(f"overlay anchor {anchor!r} is not one of {', '.join(_ANCHORS)}; "
                f"using top-centre")
        cfg = {**cfg, "Anchor": "top-centre"}
    return OverlayClient(cfg, log=log)

"""
core/overlay_proc.py — The overlay renderer, run as a child process.

Started by :class:`core.overlay.OverlayClient`, never imported by the rest of
EDLD. Reads newline-delimited JSON frames on stdin, draws them in a frameless
translucent always-on-top click-through window, and reports on stdout.

Run directly for a look at what this machine can do::

    python -m core.overlay_proc --probe

which prints the capability line and exits without opening anything.

What the probe actually measures
--------------------------------
Four things, and each is checked rather than inferred from the platform name:

``translucent``    a per-pixel alpha window, so the overlay is text on the game
                   rather than text on a grey slab.
``click_through``  input passes to the game underneath. Not optional: an
                   overlay that eats mouse clicks over the cockpit presents as
                   the game having locked up, and the user has no reason to
                   connect that to EDLD.
``always_on_top``  the window stays above the game. Under Wayland an ordinary
                   client cannot ask for this at all, which is why that
                   platform reports unavailable instead of half-working.
``compositing``    on X11, whether a compositor is running. Without one there
                   is no alpha channel to composite into and translucency
                   degrades to a solid colour-key, which looks worse than no
                   overlay.

Exclusive fullscreen defeats all of this on every platform and cannot be probed
from outside the game. It is called out in the setup notes instead.
"""

from __future__ import annotations

import json
import os
import sys
import threading

# The parent talks to us on stdout, so anything that prints for its own reasons
# corrupts the channel. Qt and its plugins are chatty on some platforms.
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.qpa.*=false")


# The protocol owns stdout, so anything else that writes there corrupts it.
# EDLD's own import graph prints to stdout in at least one place (an optional
# dependency announcing itself), Qt platform plugins do it on some systems, and
# a stray print added later would be a protocol bug rather than a stray print.
# So the real stdout is duplicated away and kept private, and sys.stdout is
# pointed at stderr where the parent logs it as text.
_PROTOCOL_FD = os.dup(1)
os.dup2(2, 1)
_PROTOCOL = os.fdopen(_PROTOCOL_FD, "w", buffering=1)


def _emit(obj: dict) -> None:
    """Write one protocol line to the parent."""
    _PROTOCOL.write(json.dumps(obj) + "\n")
    _PROTOCOL.flush()


def _fail(reason: str) -> None:
    _emit({"event": "capabilities", "available": False, "reason": reason})
    sys.exit(0)


def _load_fonts() -> list[str]:
    """Register every font in EDLD's fonts directory with Qt.

    Elite's own faces are not system-installed and should not have to be: a
    commander drops the .ttf files in and they become selectable, without
    touching fontconfig or needing root. Registering by file also means the
    family names come from the fonts themselves rather than from a list
    hardcoded here — which matters, because the set of faces on offer is not
    something this code should claim to know.
    """
    from PySide6.QtGui import QFontDatabase

    families: list[str] = []
    dirs = []
    try:
        from core.state import EDLD_DATA_DIR
        dirs.append(EDLD_DATA_DIR / "fonts")
    except Exception:
        pass
    # Shipped fonts, then the user's. Both, because they answer different
    # questions: the repo directory is what everyone gets, the data directory
    # is where a commander drops a face we cannot redistribute.
    dirs.insert(0, _repo_fonts_dir())

    for font_dir in dirs:
        if not font_dir or not font_dir.is_dir():
            continue
        for path in sorted(font_dir.iterdir()):
            if path.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                fid = QFontDatabase.addApplicationFont(str(path))
            except Exception as exc:
                _emit({"event": "error",
                       "message": f"font load {path.name}: {exc}"})
                continue
            if fid >= 0:
                families.extend(QFontDatabase.applicationFontFamilies(fid))
    return sorted(set(families))


def _repo_fonts_dir():
    """Where fonts shipped with EDLD live, frozen or not."""
    from pathlib import Path

    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "fonts"
    return Path(__file__).resolve().parent.parent / "fonts"


def _config() -> dict:
    from core.overlay import CFG_DEFAULTS
    try:
        return {**CFG_DEFAULTS, **json.loads(os.environ.get("EDLD_OVERLAY_CONFIG", "{}"))}
    except ValueError:
        return dict(CFG_DEFAULTS)


# ── geometry ──────────────────────────────────────────────────────────────────

def anchor_position(anchor: str, screen_w: int, screen_h: int,
                    w: int, h: int, off_x: int, off_y: int) -> tuple[int, int]:
    """Top-left corner for a window of ``w``x``h`` at ``anchor`` on a screen.

    Pure, so the placement arithmetic is testable without a display.
    """
    vert, _, horiz = anchor.partition("-")
    if horiz == "left":
        x = off_x
    elif horiz == "right":
        x = screen_w - w - off_x
    else:
        x = (screen_w - w) // 2 + off_x
    y = off_y if vert == "top" else screen_h - h - off_y
    return x, y


# ── the window ────────────────────────────────────────────────────────────────

def shadow_colour(colour: str) -> str:
    """A shadow colour derived from the text it will sit behind.

    Flat black is the obvious choice and it is wrong twice over. Against a
    tinted palette it reads as a separate colour — a black fringe on Elite
    orange looks like a printing error — and it does nothing at all for dark
    text on the light theme, where the shadow has to be *lighter* than the ink
    to separate it from the background.

    So the shadow keeps the text's hue and moves its lightness to the far end:
    near-black behind light text, near-white behind dark. Saturation is pulled
    down so it reads as depth rather than as a second colour in the palette.

    Pure and string-in string-out, so the choice can be checked without a
    display.
    """
    import colorsys

    raw = (colour or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    try:
        r, g, b = (int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "#000000"

    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    # The threshold is deliberately low. What matters is not whether the ink
    # is light in the abstract but whether it is lighter than what is behind
    # it, and what is behind it is the game — overwhelmingly dark. A midpoint
    # threshold gave the muted amber label colour a near-white shadow, which
    # against a starfield would have been the brightest thing on screen. Only
    # genuinely dark ink, the sort a light theme uses, needs a light shadow.
    out = colorsys.hls_to_rgb(h, 0.06 if light > 0.25 else 0.94, min(sat, 0.35))
    return "#" + "".join(f"{int(round(c * 255)):02x}" for c in out)


#: Rough height of one line, for sizing a window to its content. The exact
#: figure comes from the layout's own line height; this only has to be close
#: enough to leave the last row room to draw.
LINE_HEIGHT_HINT = 22


def _make_windows(app, cfg):
    """One widget per window id, built up front on the GUI thread.

    Built eagerly rather than on first use because a widget must be created on
    the thread that will paint it, and frames arrive on the reader. Each stays
    hidden until it is sent something, so a commander with nothing docked has
    two windows that never map and cost nothing.
    """
    from core.overlay_panels import WINDOWS

    return {name: _build(app, cfg, name) for name in WINDOWS}


def _make_bridge(widget):
    """A GUI-thread object that frames can be delivered to from any thread.

    ``QTimer.singleShot`` creates its timer in the *calling* thread. Called
    from the stdin reader — a plain worker thread with no Qt event loop — that
    timer has nothing to fire it, so every frame was accepted, marshalled, and
    then silently never delivered. The parent logged ``sent=True`` twice a
    second and was telling the truth: the frames reached the process and
    stopped at the thread boundary.

    That is also precisely why --overlay-selftest worked. It calls singleShot
    from the main thread, before app.exec(), where there *is* a loop to fire
    it — so the one path that proved the renderer was the one path that did
    not use the mechanism the renderer actually depends on.

    A Qt signal is the supported mechanism. Emitting from any thread queues the
    call onto the receiver's thread, and the receiver is created here, on the
    GUI thread, which is what makes that true.
    """
    from PySide6.QtCore import QObject, Signal

    class _Bridge(QObject):
        frame = Signal(str, list)

        def __init__(self) -> None:
            super().__init__()
            self.frame.connect(self._deliver)

        def _deliver(self, window: str, elements: list) -> None:
            target = widget.get(window) if isinstance(widget, dict) else widget
            if target is not None:
                target.set_elements(elements)

    return _Bridge()


def _build(app, cfg: dict, window: str = "top"):
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QColor, QFont, QPainter, QPen
    from PySide6.QtWidgets import QWidget

    class Overlay(QWidget):
        def __init__(self) -> None:
            super().__init__(None)
            self._elements: list[dict] = []
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool                      # keeps it off the taskbar
                | Qt.WindowTransparentForInput
                | Qt.X11BypassWindowManagerHint
            )
            # Without a compositor there is no alpha channel to composite
            # into, so a translucent window simply does not render. Falling
            # back to a painted panel keeps the overlay readable instead of
            # invisible; it is less pretty and it is actually there.
            self._composited = bool(cfg.get("_compositing", True))
            self.setAttribute(Qt.WA_TranslucentBackground, self._composited)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)

            screens = app.screens()
            idx = min(int(cfg.get("Monitor", 0) or 0), len(screens) - 1)
            geo = screens[max(0, idx)].geometry()

            if window == "top":
                w = int(cfg.get("Width", 720))
                h = 1   # grown to fit on the first frame

                # OffsetX/OffsetY are the old names, read as a fallback so an
                # existing config keeps the position it had.
                x, y = anchor_position(
                    str(cfg.get("Anchor", "top-centre")),
                    geo.width(), geo.height(), w, h,
                    int(cfg.get("MarginX", cfg.get("OffsetX", 0))),
                    int(cfg.get("MarginY", cfg.get("OffsetY", 40))))
            else:
                # A dock hugs its screen edge, inset by the same padding the
                # top bar uses, and starts below it so the two never overlap.
                w = int(cfg.get("DockWidth", 260))
                h = 1   # grown to fit on the first frame

                # The dock's gap from the side of the monitor is the same
                # margin the top bar uses, so the three windows line up.
                margin = int(cfg.get("MarginX", cfg.get("OffsetX", 0))) or 16
                y = int(cfg.get("DockTop", 140))
                x = margin if window == "dock-left" else geo.width() - w - margin
            self.setGeometry(geo.x() + x, geo.y() + y, w, h)
            # NOT setWindowOpacity().  On a WA_TranslucentBackground window
            # that asks the compositor for a semi-transparent *surface*, and
            # several compositors answer by giving the window an opaque one to
            # fade — which is how an overlay with nothing on it turned up as a
            # black rectangle over the cockpit.  Opacity is applied to the ink
            # instead, in _shadowed(), so an empty frame is genuinely nothing.
            self._alpha = max(0.05, min(1.0, float(cfg.get("Opacity", 0.85))))
            # Capped at two: past that it stops reading as depth and starts
            # reading as a second, blurry copy of the text.
            self._shadow_offset = max(0, min(2, int(cfg.get("ShadowOffset", 1))))
            self._shadow_strength = max(0.0, min(1.0,
                                                 float(cfg.get("ShadowStrength", 0.85))))

        def set_elements(self, elements: list[dict]) -> None:
            self._elements = elements
            self._frames = getattr(self, "_frames", 0) + 1
            # An empty frame means hide, not "paint nothing".  A shown window
            # with no content is still a window: it can be picked up by a
            # compositor, a screen recorder or a task switcher, and on some
            # setups it renders as a filled rectangle.  Nothing placed should
            # look like nothing.
            self._fit_to(elements)
            if elements and not self.isVisible():
                self.show()
            elif not elements and self.isVisible():
                self.hide()
            self.update()
            # First frame only: say where the window went and whether the
            # server actually mapped it. "The renderer is running" and "there
            # is something on screen" are different claims, and only the
            # second one matters — without this there was no way to tell them
            # apart from outside.
            if self._frames == 1:
                g = self.geometry()
                _emit({"event": "shown",
                       "elements": len(elements),
                       "visible": bool(self.isVisible()),
                       "geometry": [g.x(), g.y(), g.width(), g.height()],
                       "screen": (self.screen().name() if self.screen() else "?"),
                       "alpha": self._alpha})

        def _fit_to(self, elements: list[dict]) -> None:
            """Grow or shrink the window to the content it was just handed.

            The height used to be a setting, which meant a stack taller than it
            was silently clipped — and the commander had no way to know whether
            a panel was missing or merely cut off. With career figures in play
            the stacks got taller and the number that had been generous became
            the wrong one.

            Only the height moves. The width is a real choice: it sets where a
            centred zone centres and where a right zone right-aligns, and
            resizing it under the commander would move text they had placed.
            """
            if not elements:
                return
            scale = float(cfg.get("Scale", 1.0) or 1.0)
            pad = int(cfg.get("PadY", 8))
            needed = int(max(float(e.get("y", 0)) for e in elements) * scale)
            # One line of headroom below the last baseline, plus the padding
            # that was applied above the first.
            needed += int(LINE_HEIGHT_HINT * scale) + pad
            geo = self.geometry()
            if needed != geo.height() and needed > 0:
                self.setGeometry(geo.x(), geo.y(), geo.width(), needed)

        # ── painting ──────────────────────────────────────────────────────────

        def paintEvent(self, _event) -> None:
            p = QPainter(self)
            if not self._composited and self._elements:
                bg = QColor(8, 12, 18)
                bg.setAlphaF(min(1.0, self._alpha))
                p.fillRect(self.rect(), bg)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setRenderHint(QPainter.TextAntialiasing, True)
            scale = float(cfg.get("Scale", 1.0) or 1.0)
            for el in self._elements:
                try:
                    kind = el.get("type")
                    if kind == "text":
                        self._text(p, el, scale)
                    elif kind == "tape":
                        self._tape(p, el, scale)
                except Exception as exc:
                    # One malformed element must not take the frame with it.
                    _emit({"event": "error",
                           "message": f"element {el.get('id','?')}: "
                                      f"{type(exc).__name__}: {exc}"})
            p.end()

        def _ink(self, colour: str, alpha_scale: float = 1.0):
            c = QColor(colour)
            c.setAlphaF(max(0.0, min(1.0, self._alpha * alpha_scale)))
            return c

        def _shadowed(self, p, x: float, y: float, s: str, colour: str) -> None:
            """Draw text over an offset copy of itself in a derived shadow.

            The overlay sits on whatever the game is showing, which over one
            session includes a black starfield, a white station interior and a
            ring full of ice. No single ink colour is readable against all
            three; a shadow behind it is.
            """
            off = self._shadow_offset
            if off:
                shadow = QColor(shadow_colour(colour))
                shadow.setAlphaF(max(0.0, min(1.0, self._alpha
                                              * self._shadow_strength)))
                p.setPen(QPen(shadow))
                p.drawText(QPointF(x + off, y + off), s)
            p.setPen(QPen(self._ink(colour)))
            p.drawText(QPointF(x, y), s)

        def _text(self, p, el: dict, scale: float) -> None:
            f = QFont()
            family = str(cfg.get("FontFamily", "") or "").strip()
            if family:
                f.setFamily(family)
            f.setPointSizeF(float(el.get("size", 13)) * scale)
            f.setBold(el.get("weight") == "bold")
            p.setFont(f)
            body = str(el.get("text", ""))
            x = float(el["x"]) * scale

            # The layout works in anchor points, not boxes, because it has no
            # font metrics — a right-hand zone is "this x is the right edge",
            # and only here is there a QFontMetrics to turn that into a draw
            # position.  Without this every zone would render left-aligned and
            # the right-hand stack would run off the screen.
            align = el.get("align", "left")
            if align in ("right", "centre"):
                w = p.fontMetrics().horizontalAdvance(body)
                x -= w if align == "right" else w / 2

            # drawText takes a *baseline*, the layout works in tops. Passing a
            # top as a baseline puts the whole ascent above the requested y —
            # which is why the first row was clipped no matter how much the
            # window was padded away from the screen edge. The padding was
            # never the problem; the first line was being drawn above the
            # window.
            y = float(el["y"]) * scale + p.fontMetrics().ascent()
            self._shadowed(p, x, y, body, el.get("colour", "#cfd6e4"))

        def _tape(self, p, el: dict, scale: float) -> None:
            from core.overlay import tape_positions

            x0 = float(el["x"]) * scale
            y0 = float(el["y"]) * scale
            w = float(el["width"]) * scale

            p.setPen(QPen(QColor(207, 214, 228, 90), 1))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + w, y0))

            # Centre notch: where the nose is pointing.
            p.setPen(QPen(QColor(230, 236, 246, 220), 2))
            p.drawLine(QPointF(x0 + w / 2, y0 - 7), QPointF(x0 + w / 2, y0 + 7))

            f = QFont()
            family = str(cfg.get("FontFamily", "") or "").strip()
            if family:
                f.setFamily(family)
            f.setPointSizeF(11 * scale)
            p.setFont(f)
            for offset, mark in tape_positions(el.get("heading", 0.0),
                                               el.get("span", 90.0),
                                               int(w), el.get("marks", [])):
                mx = x0 + offset
                colour = mark.get("colour", "#8fd1ff")
                p.setPen(QPen(QColor(colour), 2))
                p.drawLine(QPointF(mx, y0 - 5), QPointF(mx, y0 + 5))
                label = str(mark.get("label", ""))
                if label:
                    metrics = p.fontMetrics()
                    self._shadowed(p, mx - metrics.horizontalAdvance(label) / 2,
                                   y0 + 22, label, colour)

    return Overlay()


# ── capability probe ──────────────────────────────────────────────────────────

def _x11_compositing() -> bool:
    """Is an X11 compositor actually running?

    The previous check called ``app.isEffectivelyCompositing()``, which does
    not exist on QApplication — so ``getattr(..., lambda: True)`` returned True
    every time and the answer was never measured. That mattered: without a
    compositor there is no alpha channel to composite into, a
    WA_TranslucentBackground window has no meaningful backing store, and the
    overlay draws nothing visible at all. A bare i3 session with no picom is
    exactly that case, and it is common.

    The real test is whether anything owns the _NET_WM_CM_S0 selection, which
    is how a compositor announces itself. libX11 is already loaded in any X
    session, so this asks it directly through ctypes rather than adding a
    dependency or shelling out.
    """
    # Definitive: does anyone own the compositing manager selection?
    try:
        from PySide6.QtGui import QGuiApplication  # noqa: F401
        import ctypes
        import ctypes.util

        name = ctypes.util.find_library("X11")
        if name:
            xlib = ctypes.cdll.LoadLibrary(name)
            xlib.XOpenDisplay.restype = ctypes.c_void_p
            dpy = xlib.XOpenDisplay(None)
            if dpy:
                try:
                    xlib.XInternAtom.restype = ctypes.c_ulong
                    atom = xlib.XInternAtom(ctypes.c_void_p(dpy),
                                            b"_NET_WM_CM_S0", False)
                    xlib.XGetSelectionOwner.restype = ctypes.c_ulong
                    owner = xlib.XGetSelectionOwner(ctypes.c_void_p(dpy),
                                                    ctypes.c_ulong(atom))
                    return bool(owner)
                finally:
                    xlib.XCloseDisplay(ctypes.c_void_p(dpy))
    except Exception:
        pass

    # Could not determine. Assume none, because assuming one and being wrong
    # renders an invisible overlay, while assuming none and being wrong renders
    # a readable one with a backing panel.
    return False


def probe(app, widget=None) -> dict:
    """Report what this machine could actually do."""
    from PySide6.QtCore import Qt

    platform = app.platformName() or "unknown"
    caps = {
        "event":     "capabilities",
        "available": True,
        "platform":  platform,
        "screens":   len(app.screens()),
        "reason":    "",
    }

    if platform.startswith("wayland"):
        # Not a degradation to work around. A Wayland client cannot place
        # itself at an absolute position or request always-on-top, and the
        # protocol that would allow it is a compositor extension Qt does not
        # surface. Reporting this honestly is better than a window that appears
        # somewhere arbitrary and sinks behind the game.
        return {**caps, "available": False, "translucent": False,
                "click_through": False, "always_on_top": False,
                "compositing": True,
                "reason": "Wayland does not permit always-on-top positioning "
                          "for ordinary clients; run the session on X11 for "
                          "the overlay"}

    compositing = _x11_compositing() if platform == "xcb" else True

    if widget is None:
        caps.update(translucent=compositing, click_through=True,
                    always_on_top=True, compositing=compositing)
        return caps

    caps.update(
        translucent  = bool(widget.testAttribute(Qt.WA_TranslucentBackground))
                       and compositing,
        click_through= bool(widget.testAttribute(Qt.WA_TransparentForMouseEvents))
                       and bool(widget.windowFlags() & Qt.WindowTransparentForInput),
        always_on_top= bool(widget.windowFlags() & Qt.WindowStaysOnTopHint),
        compositing  = compositing,
    )
    if not compositing and platform == "xcb":
        caps["reason"] = ("no X11 compositor running; the overlay will draw on "
                          "an opaque background")
    return caps


# ── main ──────────────────────────────────────────────────────────────────────

def _reader(widget, app, bridge) -> None:
    """Pump stdin into the Qt thread.

    Frames arrive on this thread and must not touch the widget from it; Qt
    requires painting on the GUI thread and the failure when you ignore that is
    an intermittent crash rather than an error.
    """
    from PySide6.QtCore import QTimer

    # readline(), not `for line in sys.stdin`.
    #
    # Iterating a file object uses an internal read-ahead buffer: on a pipe it
    # will not yield a line until several kilobytes have accumulated or the
    # writer closes. Frames are a couple of hundred bytes each at two a second,
    # so the first one would have surfaced somewhere north of a minute later,
    # if at all — the renderer started, reported itself ready, was sent a
    # perfectly good frame, and sat there holding it in a buffer.
    #
    # This is also exactly why --overlay-selftest worked while the real path
    # did not: the selftest hands the frame straight to the widget and never
    # touches stdin.
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("event") == "quit":
            break
        if msg.get("event") != "frame":
            continue
        bridge.frame.emit(str(msg.get("window", "top")),
                          list(msg.get("elements", [])))

    # EOF on stdin is the parent closing the pipe. Same hazard as above: from
    # this thread there is no event loop to run a singleShot, so quit is
    # invoked on the application's own thread.
    from PySide6.QtCore import QMetaObject, Qt as _Qt
    QMetaObject.invokeMethod(app, "quit", _Qt.QueuedConnection)


def _watch_parent(app, original_ppid: int) -> None:
    """Quit when the parent process disappears.

    Closing stdin is the normal shutdown and is handled by the reader thread,
    but a parent that is killed, crashes, or is stopped without running its
    unload path leaves this process alive and drawing over the game with
    nothing feeding it — an overlay that outlives the dashboard, which is
    exactly what happened.  getppid() changing means we have been reparented,
    which is the portable way to notice on Linux and macOS; on Windows the
    stdin EOF path covers it.
    """
    from PySide6.QtCore import QTimer
    import time as _time

    while True:
        _time.sleep(1.0)
        try:
            if os.getppid() != original_ppid:
                break
        except Exception:
            break
    from PySide6.QtCore import QMetaObject, Qt as _Qt
    QMetaObject.invokeMethod(app, "quit", _Qt.QueuedConnection)


_SELFTEST_FRAME = [
    {"type": "text", "id": "t1", "x": 16, "y": 24, "align": "left",
     "text": "EDLD OVERLAY SELFTEST", "colour": "#7ee787", "size": 18,
     "weight": "bold"},
    {"type": "text", "id": "t2", "x": 16, "y": 48, "align": "left",
     "text": "If you can read this, the renderer works.", "colour": "#cfd6e4",
     "size": 14, "weight": "normal"},
    {"type": "text", "id": "t3", "x": 16, "y": 70, "align": "left",
     "text": "Closes itself after 20 seconds.", "colour": "#9aa4b2",
     "size": 12, "weight": "normal"},
]


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    probe_only = "--probe" in argv
    selftest = "--selftest" in argv

    if __package__ in (None, ""):
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        _fail(f"PySide6 is not installed in this build ({exc})")
        return 0

    try:
        app = QApplication(sys.argv[:1])
    except Exception as exc:
        _fail(f"no display available: {type(exc).__name__}: {exc}")
        return 0

    if probe_only:
        caps = probe(app)
        caps["fonts"] = _load_fonts()
        _emit(caps)
        return 0

    families = _load_fonts()
    if families:
        _emit({"event": "fonts", "families": families})
    cfg = _config()
    cfg["_compositing"] = _x11_compositing() if app.platformName() == "xcb" \
        else True
    try:
        windows = _make_windows(app, cfg)
        widget = windows["top"]
    except Exception as exc:
        _fail(f"could not create the overlay window: {type(exc).__name__}: {exc}")
        return 0

    caps = probe(app, widget)
    _emit(caps)
    if not caps.get("available"):
        return 0

    # Deliberately not shown here.  The window appears with its first
    # non-empty frame and hides again when a frame is empty; starting visible
    # put an empty overlay on screen for everyone who had not placed a panel.
    if selftest:
        # Draws a fixed frame with no parent and no panel pipeline, so "the
        # renderer cannot draw" and "nothing is being sent to it" stop looking
        # identical from outside.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: widget.set_elements(list(_SELFTEST_FRAME)))
        QTimer.singleShot(20000, app.quit)
        return app.exec()

    bridge = _make_bridge(windows)
    threading.Thread(target=_reader, args=(widget, app, bridge), daemon=True,
                     name="overlay-stdin").start()
    threading.Thread(target=_watch_parent, args=(app, os.getppid()), daemon=True,
                     name="overlay-parent").start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

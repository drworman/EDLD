"""
core/clipboard.py — put text on the system clipboard.

No UI-framework imports.  The route follower copies the next system from a
journal-event thread, which rules out touching Qt: ``QClipboard`` may only be
used from the GUI thread, and the TUI has no Qt at all.  Everything here is
either a subprocess call or a direct Win32 call, so it is safe to invoke from
any thread in any of the three front ends.

Backends, tried in order per platform:

    Windows   Win32 clipboard via ctypes.  ``clip.exe`` would be simpler but
              it appends a newline and mangles non-ASCII system names, and a
              trailing newline is exactly the thing that breaks a galaxy-map
              paste.
    macOS     pbcopy
    Linux/BSD wl-copy (Wayland), xclip, xsel

A terminal session over SSH usually has none of these — the clipboard lives on
the machine running the terminal emulator, not on the host.  That case is
handled separately by the TUI, which emits an OSC 52 sequence through
Textual's ``App.copy_to_clipboard``; see tui/blocks/navigation.py.  This
module reports failure honestly so the caller can say so rather than claiming
a copy that did not happen.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

__all__ = ["copy", "available_backend"]


def _linux_backends() -> list[tuple[str, list[str]]]:
    """Clipboard commands available on this Linux/BSD session, best first.

    Wayland first when the session is Wayland, because xclip under XWayland
    can appear to work and then serve nothing to native clients.
    """
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    candidates: list[tuple[str, list[str]]] = []
    if wayland:
        candidates.append(("wl-copy", ["wl-copy", "--type", "text/plain"]))
    candidates.append(("xclip", ["xclip", "-selection", "clipboard", "-in"]))
    candidates.append(("xsel", ["xsel", "--clipboard", "--input"]))
    if not wayland:
        candidates.append(("wl-copy", ["wl-copy", "--type", "text/plain"]))
    return [(name, cmd) for name, cmd in candidates if shutil.which(cmd[0])]


def _copy_windows(text: str) -> tuple[bool, str]:
    """Set CF_UNICODETEXT through the Win32 API."""
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    if not user32.OpenClipboard(None):
        return False, "could not open the Windows clipboard"
    try:
        user32.EmptyClipboard()
        buf = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buf)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False, "clipboard allocation failed"
        locked = kernel32.GlobalLock(handle)
        if not locked:
            return False, "clipboard lock failed"
        try:
            ctypes.memmove(locked, buf, size)
        finally:
            kernel32.GlobalUnlock(handle)
        # Ownership of the handle passes to the clipboard on success, so it
        # must not be freed here.
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            return False, "SetClipboardData failed"
        return True, "windows"
    finally:
        user32.CloseClipboard()


def _run(cmd: list[str], text: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        return False, f"{cmd[0]}: {type(exc).__name__}"
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        return False, f"{cmd[0]} exited {proc.returncode}{': ' + detail if detail else ''}"
    return True, cmd[0]


def available_backend() -> str | None:
    """Name of the backend that would be used, or None if there is none.

    Lets the UI say "no clipboard tool found — install wl-clipboard or xclip"
    before the user presses anything, rather than after.
    """
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "pbcopy" if shutil.which("pbcopy") else None
    backends = _linux_backends()
    return backends[0][0] if backends else None


def copy(text: str) -> tuple[bool, str]:
    """Put ``text`` on the system clipboard.

    Returns ``(ok, detail)``.  On success ``detail`` names the backend used;
    on failure it explains what went wrong, which the caller is expected to
    surface rather than swallow.
    """
    if not text:
        return False, "nothing to copy"

    try:
        if sys.platform == "win32":
            return _copy_windows(text)

        if sys.platform == "darwin":
            if not shutil.which("pbcopy"):
                return False, "pbcopy not found"
            return _run(["pbcopy"], text)

        backends = _linux_backends()
        if not backends:
            return False, ("no clipboard tool found — install wl-clipboard "
                           "(Wayland) or xclip/xsel (X11)")
        last = ""
        for _name, cmd in backends:
            ok, detail = _run(cmd, text)
            if ok:
                return True, detail
            last = detail
        return False, last or "all clipboard backends failed"

    except Exception as exc:      # never let a clipboard failure escape
        return False, f"{type(exc).__name__}: {exc}"

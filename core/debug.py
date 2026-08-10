"""
core/debug.py — Debug / trace / error log facility.

Purpose
-------
A dedicated, file-only logging channel that is completely separate from
standard output.  Standard output remains the terminal in terminal mode
and goes to /dev/null after fork in UI modes.  Diagnostic information
(``--trace`` output, plugin errors, unhandled exceptions, intentional
``debug.log(...)`` calls) is written here and *only* here.

File layout
-----------
Path:  ``<data_dir>/logs/error[_<profile>]_<YYYYMMDD>.log``

The file is opened in append mode the first time anything actually writes
to it, so runs that never trip --trace or an error path leave no file
behind.  Multiple runs on the same day append into the same file,
separated by a clearly fenced run header that records:

  - EDLD version
  - human-readable start timestamp
  - exact launch command (sys.argv joined)
  - the effective config — defaults section followed by per-profile
    overrides, each fenced as ``# [Section] key = value`` comment lines
    so the block can be pasted back into a config.toml without edits

API
---
    init(data_dir, profile, version, config_dict, profile_overrides=None)
        — capture metadata; the header is written lazily on first log().

    log(message, *, level="DEBUG")
        — append one line.  Triggers file open + header write on first call.

    trace(message)
        — alias for log(message, level="TRACE").

    is_enabled() -> bool
        — True once init() has been called.  The log file itself remains
          unopened until the first log()/trace() call.

    path() -> Path | None
        — current target file path, or None if init() not yet called.

The module is thread-safe: writes serialize through a single lock so
plugin threads and the main thread can call log() concurrently without
interleaving partial lines.
"""

from __future__ import annotations

import io
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


# ── Module state ──────────────────────────────────────────────────────────────

_LOCK:              threading.Lock = threading.Lock()
_LOG_PATH:          Path | None    = None
_FH:                io.TextIOBase | None = None  # opened lazily
_HEADER_WRITTEN:    bool           = False
_PENDING_HEADER:    str            = ""          # built at init(), written on first log()
_INITIALIZED:       bool           = False
_TRACE_ECHO:        bool           = False        # set by init() — when True, log(..., echo=True) also prints


# ── Public API ────────────────────────────────────────────────────────────────

def init(data_dir: Path,
         profile: str | None,
         version: str,
         config_dict: dict | None = None,
         profile_overrides: dict | None = None,
         trace_echo: bool = False) -> None:
    """Configure where the log will go and build the run header.

    The log file is NOT opened here — it opens lazily on the first
    log() / trace() call so that runs which never exercise the debug
    facility leave no log file behind.

    Args
    ----
    data_dir          base data directory (``<data_dir>/logs/`` is created)
    profile           active config profile name, or None / empty for none
    version           EDLD version string for the header
    config_dict       effective config defaults as a dict-of-dicts
                      (section -> {key: value}); rendered into the header
    profile_overrides per-profile overrides as a dict-of-dicts, or None
                      if no profile is active
    trace_echo        when True (typically set from the --trace flag),
                      ``log(msg, echo=True)`` mirrors to stdout in addition
                      to writing to the log file.  Used to make routine
                      info-level lines visible on the terminal in trace
                      runs without spamming them in normal runs.
    """
    global _LOG_PATH, _PENDING_HEADER, _HEADER_WRITTEN, _INITIALIZED, _TRACE_ECHO

    today = datetime.now().strftime("%Y%m%d")
    name  = f"error_{profile}_{today}.log" if profile else f"error_{today}.log"
    logs_dir = data_dir / "logs"
    _LOG_PATH = logs_dir / name

    _PENDING_HEADER = _build_header(version, config_dict, profile, profile_overrides)
    _HEADER_WRITTEN = False
    _INITIALIZED    = True
    _TRACE_ECHO     = bool(trace_echo)


def log(message: str, *, level: str = "DEBUG", echo: bool = False) -> None:
    """Append a single line to the debug log file.

    The first call after init() opens the file (creating ``logs/`` if
    needed) and emits the run header.  Failures (disk full, permission
    denied) are silently swallowed — the log facility must never crash
    the application it is meant to diagnose.

    When ``echo`` is True AND the facility was initialised with
    ``trace_echo=True``, the message is also printed to stdout.  Routine
    informational lines from the startup path use ``echo=True`` so that
    a ``--trace`` run sees them on the terminal while a normal UI run
    sees them only in the log.
    """
    if not _INITIALIZED:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {message}\n"
    _write_line(line)
    if echo and _TRACE_ECHO:
        # Print to stdout WITHOUT the timestamp/level prefix — keep the
        # terminal-side appearance identical to what the call site would
        # have printed before the migration to debug.log.
        try:
            print(message)
        except Exception:
            pass


def info(message: str) -> None:
    """Convenience: an INFO-level line that echoes to stdout when --trace
    is on.  Equivalent to ``log(message, level='INFO', echo=True)``."""
    log(message, level="INFO", echo=True)


def trace(message: str) -> None:
    """Convenience wrapper for trace-level lines (``--trace`` output)."""
    log(message, level="TRACE")


def exception(message: str = "", exc: BaseException | None = None) -> None:
    """Log a Python exception with full traceback.

    If ``exc`` is None the current exception is captured from sys.exc_info().
    Used by the installed sys.excepthook and threading.excepthook handlers,
    and can be called directly from any except clause that wants to record
    a stack trace without spamming stdout.
    """
    if exc is None:
        exc_type, exc_val, exc_tb = sys.exc_info()
    else:
        exc_type = type(exc)
        exc_val  = exc
        exc_tb   = exc.__traceback__
    if exc_type is None:
        if message:
            log(message, level="ERROR")
        return
    tb_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb)).rstrip()
    prefix = f"{message}: " if message else ""
    log(f"{prefix}{exc_type.__name__}: {exc_val}\n{tb_str}", level="ERROR")


def is_enabled() -> bool:
    """True once init() has been called.  The log file itself may or may
    not yet exist (it opens lazily on the first log line)."""
    return _INITIALIZED


def path() -> Path | None:
    """Target log file path, or None if init() not yet called."""
    return _LOG_PATH


def install_exception_hooks() -> None:
    """Install sys.excepthook and threading.excepthook handlers that route
    unhandled exceptions to the debug log.  Pre-existing hooks (if any)
    are chained: we log first, then delegate."""
    prior_sys_hook    = sys.excepthook
    prior_thread_hook = getattr(threading, "excepthook", None)

    def _sys_hook(exc_type, exc_value, exc_tb):
        try:
            exception("Unhandled exception",
                      exc_value if isinstance(exc_value, BaseException) else None)
        except Exception:
            pass
        if prior_sys_hook:
            prior_sys_hook(exc_type, exc_value, exc_tb)

    def _thread_hook(args):
        try:
            thread_name = getattr(args.thread, "name", "<unknown>")
            exception(f"Unhandled exception in thread {thread_name!r}",
                      args.exc_value)
        except Exception:
            pass
        if prior_thread_hook:
            try:
                prior_thread_hook(args)
            except Exception:
                pass

    sys.excepthook       = _sys_hook
    threading.excepthook = _thread_hook


# ── Internals ─────────────────────────────────────────────────────────────────

def _build_header(version: str,
                  config_dict: dict | None,
                  profile: str | None,
                  profile_overrides: dict | None) -> str:
    """Compose the per-run header block.

    Format
    ------
        ================================================================
        EDLD v<version> — <weekday day month year hh:mm:ss tz>
        Launch: <argv joined>

        # Effective config (defaults from config file)
        # [Section]
        # key = value
        # ...
        # [Section]
        # key = value

        # Profile overrides (<profile_name>)     ← only if profile active
        # [Section]
        # key = value
        # ...
        ================================================================

    The config and overrides sections are rendered as comment lines so the
    block reads as a paste-back-able snippet for support workflows.
    """
    bar  = "=" * 72
    when = time.strftime("%a %d %b %Y %H:%M:%S %Z").strip()
    cmd  = _format_argv(sys.argv)

    lines = [
        "",
        bar,
        f"EDLD v{version} — {when}",
        f"Launch: {cmd}",
        "",
    ]

    if config_dict:
        lines.append("# Effective config (defaults from config file)")
        lines.extend(_format_toml_block(config_dict))
        lines.append("")
    else:
        lines.append("# Effective config: (not available)")
        lines.append("")

    if profile and profile_overrides:
        lines.append(f"# Profile overrides ({profile})")
        lines.extend(_format_toml_block(profile_overrides))
        lines.append("")
    elif profile:
        lines.append(f"# Profile: {profile} (no overrides)")
        lines.append("")

    lines.append(bar)
    lines.append("")
    return "\n".join(lines)


def _format_argv(argv: list[str]) -> str:
    """Quote argv elements that contain whitespace or special characters
    so the launch line can be copy-pasted back into a shell."""
    out: list[str] = []
    safe = set("-_./=:")
    for arg in argv:
        if arg and all(c.isalnum() or c in safe for c in arg):
            out.append(arg)
        else:
            out.append('"' + arg.replace('"', '\\"') + '"')
    return " ".join(out)


def _format_toml_block(cfg: dict) -> list[str]:
    """Render a dict-of-dicts as TOML-style comment lines.

    Top-level scalars (rare in this codebase) are emitted before any
    sections.  Each section becomes ``# [Name]`` followed by its
    ``# key = value`` lines.  Values use repr-style formatting for
    strings and Python's native repr for everything else, which is
    close enough to TOML for human readability.
    """
    lines: list[str] = []

    # Top-level scalars first (rare but possible)
    scalars = {k: v for k, v in cfg.items() if not isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"# {k} = {_fmt_val(v)}")

    for section, body in cfg.items():
        if not isinstance(body, dict):
            continue
        lines.append(f"# [{section}]")
        for k, v in body.items():
            lines.append(f"# {k} = {_fmt_val(v)}")
    return lines


def _fmt_val(v: Any) -> str:
    """Render a single value in TOML-ish form for log readability."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        # Use double quotes; escape backslashes and embedded double quotes.
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, list):
        return "[" + ", ".join(_fmt_val(x) for x in v) + "]"
    return repr(v)


def _write_line(line: str) -> None:
    """Open the file (writing header first) if needed, then append.

    All disk-touching failures are swallowed — the log facility is never
    allowed to take the process down.
    """
    global _FH, _HEADER_WRITTEN
    with _LOCK:
        if _FH is None:
            if _LOG_PATH is None:
                return
            try:
                _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                _FH = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
            except OSError:
                return
        if not _HEADER_WRITTEN:
            try:
                _FH.write(_PENDING_HEADER)
                _HEADER_WRITTEN = True
            except OSError:
                pass
        try:
            _FH.write(line)
        except OSError:
            pass

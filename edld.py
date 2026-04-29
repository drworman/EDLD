#!/usr/bin/env python3
"""
edld.py — ED Linux Dash — entry point

All business logic lives in the packages below:
  core/       — state, config, emit, journal loop, plugin loader, shared API
  components/ — all application components
  plugins/    — user plugin directory
  gui/        — GTK4 interface (helpers, block widgets, EdmdApp)
  tui/        — Textual TUI interface
"""

import argparse
import json
import os
import sys
import threading
import time
import queue
from pathlib import Path
from urllib.request import urlopen

# ── Ensure repo root is on sys.path ───────────────────────────────────────────
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from core.state  import PROGRAM, VERSION, AUTHOR, GITHUB_REPO, DEBUG_MODE

from core.emit   import Terminal
from core.config import resolve_config_path, load_config_file, ConfigManager, migrate_config_if_needed


# ── Argument parsing ──────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    prog=PROGRAM,
    description="Continuous monitoring of Elite Dangerous AFK sessions.",
)
parser.add_argument("-p", "--config_profile",
                    help="Load a specific config profile")
parser.add_argument("-t", "--test", action="store_true", default=None,
                    help="Re-route Discord output to terminal instead of webhook")
parser.add_argument("-d", "--trace", action="store_true", default=None,
                    help="Print verbose debug/trace output")
parser.add_argument("-g", "--gui", action="store_true", default=None,
                    help="Alias for --mode gtk4 (launch GTK4 GUI)")
parser.add_argument("--mode", choices=["terminal", "textual", "gtk4"],
                    default=None, metavar="MODE",
                    help="UI mode: terminal (default) | textual | gtk4")
parser.add_argument("--log-file", metavar="PATH",
                    help="Tee all terminal output to PATH (safe with --mode gtk4; avoids pipe buffer deadlock)")

args = parser.parse_args()



# ── Header ────────────────────────────────────────────────────────────────────

title = f"{PROGRAM} v{VERSION} by {AUTHOR}"
print(f"{Terminal.CYAN}{'=' * len(title)}\n{title}\n{'=' * len(title)}{Terminal.END}\n")


# ── Background update check ───────────────────────────────────────────────────
# Checks two things in order of severity:
#   1. New tagged release on GitHub   → "release" notice
#   2. New commits on origin/main     → "commits" notice (only if git is present
#      and _HERE is a git working tree)
#
# _update_notice  = ("release", version_str)   — a tagged release is available
# _update_notice  = ("commits", N_str)          — N new commits ahead of local
# _update_notice  = None                        — nothing new
#
# In both cases File → Upgrade runs the same git-pull path.

_update_notice: tuple[str, str] | None = None

def _check_for_update() -> None:
    global _update_notice
    import re as _re

    # Check for a newer tagged release via GitHub API.
    # Compares VERSION against the latest release tag using a (date, suffix) key
    # so 20260325a < 20260325b < 20260326 all sort correctly.
    # Commits that land on main after a release do NOT trigger a notice.
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        with urlopen(url, timeout=4) as resp:
            if resp.status == 200:
                tag = json.loads(resp.read()).get("tag_name", "").lstrip("v").strip()
                if tag and tag != VERSION:
                    def _vkey(v):
                        m = _re.match(r"^(\d+)([a-z]*)$", v)
                        return (int(m.group(1)), m.group(2)) if m else (0, "")
                    if _vkey(tag) > _vkey(VERSION):
                        _update_notice = ("release", tag)
    except Exception:
        pass

_update_thread = threading.Thread(target=_check_for_update, daemon=True)
_update_thread.start()


# ── Config ────────────────────────────────────────────────────────────────────

config_path = resolve_config_path(Path(__file__))
if config_path is None:
    # No config found — generate a default one in the user data directory
    # so EDLD can start immediately.  The user can edit it via Preferences.
    from core.state import EDLD_DATA_DIR
    from core.config import (
        config_to_toml,
        CFG_DEFAULTS_SETTINGS, CFG_DEFAULTS_EXTRA, CFG_DEFAULTS_UI,
        CFG_DEFAULTS_DISCORD, CFG_DEFAULTS_EDDN, CFG_DEFAULTS_EDSM,
        CFG_DEFAULTS_EDASTRO, CFG_DEFAULTS_INARA, CFG_DEFAULTS_NOTIFY,
    )
    config_path = EDLD_DATA_DIR / "config.toml"
    _default_cfg = {
        "Settings":  {**CFG_DEFAULTS_SETTINGS, **CFG_DEFAULTS_EXTRA},
        "Discord":   CFG_DEFAULTS_DISCORD,
        "UI":        CFG_DEFAULTS_UI,
        "LogLevels": CFG_DEFAULTS_NOTIFY,
        "EDDN":      CFG_DEFAULTS_EDDN,
        "EDSM":      CFG_DEFAULTS_EDSM,
        "EDAstro":   CFG_DEFAULTS_EDASTRO,
        "Inara":     CFG_DEFAULTS_INARA,
    }
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(config_to_toml(_default_cfg), encoding="utf-8")
        print(f"[EDLD] No config found — wrote default config to: {config_path}")
    except OSError as _e:
        print(f"{Terminal.WARN}WARNING:{Terminal.END} Could not write default config: {_e}")
        # Fall through — ConfigManager will use built-in defaults

migrate_config_if_needed(config_path)  # silently rewrite old [GUI]/sub-table format before loading
config_dict = load_config_file(config_path)
notify_test = bool(args.test)  if args.test  is not None else False
trace_mode  = bool(args.trace) if args.trace is not None else DEBUG_MODE

# ── Log file (--log-file) ─────────────────────────────────────────────────────
# Opens a log file and tees ALL stdout output to it alongside the terminal.
# This is intentionally separate from shell redirection (> file) to avoid
# the pipe-buffer deadlock that occurs when running with --gui and --trace:
# shell pipes are bounded buffers; a blocked print() in the monitor thread
# stalls the journal loop, starving the GTK main loop of events.
# Opening the file directly bypasses the pipe entirely.

_log_fh = None

if args.log_file:
    import io as _io
    _log_path = Path(args.log_file).expanduser().resolve()
    try:
        _log_fh = open(_log_path, "w", encoding="utf-8", buffering=1)

        class _TeeWriter(_io.TextIOBase):
            """Write to both the original stdout and a log file simultaneously."""
            def __init__(self, primary, secondary):
                self._primary   = primary
                self._secondary = secondary
            def write(self, text):
                self._primary.write(text)
                self._primary.flush()
                try:
                    self._secondary.write(text)
                    self._secondary.flush()
                except Exception:
                    pass
                return len(text)
            def flush(self):
                self._primary.flush()
                try:
                    self._secondary.flush()
                except Exception:
                    pass
            @property
            def encoding(self):
                return getattr(self._primary, "encoding", "utf-8")

        sys.stdout = _TeeWriter(sys.stdout, _log_fh)
        print(f"[EDLD] Logging to: {_log_path}")
    except OSError as _e:
        print(f"[EDLD] Warning: could not open log file {_log_path!r}: {_e}")
        _log_fh = None

# Preliminary manager — profile may be updated after commander name is known
mgr = ConfigManager(config_dict, config_path, config_profile=args.config_profile)


# ── State and session objects ─────────────────────────────────────────────────

from core.state import MonitorState, SessionData, load_session_state

state          = MonitorState()
active_session = SessionData()
lifetime       = SessionData()
gui_queue: queue.Queue = queue.Queue()


# ── Find journal ──────────────────────────────────────────────────────────────

from core.journal import find_latest_journal

journal_dir_str = mgr.app_settings.get("JournalFolder", "")
journal_dir     = Path(journal_dir_str).expanduser() if journal_dir_str else None

if not journal_dir or not journal_dir.is_dir():
    # Auto-detect the standard Linux (Steam/Proton) journal location as a fallback.
    # This lets users launch without needing to set JournalFolder up front.
    _candidates = [
        Path.home() / ".steam" / "steam" / "steamapps" / "compatdata"
        / "359320" / "pfx" / "drive_c" / "users" / "steamuser"
        / "Saved Games" / "Frontier Developments" / "Elite Dangerous",
        Path.home() / ".local" / "share" / "Steam" / "steamapps"
        / "compatdata" / "359320" / "pfx" / "drive_c" / "users"
        / "steamuser" / "Saved Games" / "Frontier Developments"
        / "Elite Dangerous",
    ]
    for _c in _candidates:
        if _c.is_dir():
            print(f"[EDLD] JournalFolder not set — auto-detected: {_c}")
            journal_dir = _c
            journal_dir_str = str(_c)
            break

if not journal_dir or not journal_dir.is_dir():
    _msg = (
        f"JournalFolder is not set or the directory does not exist.\n\n"
        f"Configured path: {journal_dir_str!r}\n\n"
        f"Set JournalFolder in your config.toml to the Elite Dangerous journal directory.\n"
        f"For Steam/Proton on Linux the default location is:\n"
        f"  ~/.steam/steam/steamapps/compatdata/359320/pfx/drive_c/users/"
        f"steamuser/Saved Games/Frontier Developments/Elite Dangerous"
    )
    print(f"{Terminal.WARN}ERROR:{Terminal.END} {_msg}")
    sys.exit(1)

journal_file = find_latest_journal(journal_dir)
if not journal_file:
    _msg = (
        f"No Elite Dangerous journal files found in:\n  {journal_dir}\n\n"
        f"Launch Elite Dangerous at least once to generate journal files, "
        f"or check that JournalFolder points to the correct directory."
    )
    print(f"{Terminal.WARN}ERROR:{Terminal.END} {_msg}")
    sys.exit(1)


# ── Commander name — for profile auto-detection ───────────────────────────────

try:
    for _raw in journal_file.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            _j = json.loads(_raw.strip())
            if _j.get("event") in ("Commander", "LoadGame") and _j.get("Name"):
                state.pilot_name = _j["Name"]
                break
        except ValueError:
            pass
except OSError:
    pass

# ── Commander FID — for per-commander data directory ─────────────────────────
# Scan backwards through journals to find FID.  The current journal may only
# contain a Fileheader if the game just created it; prior journals are reliable.

def _scan_fid_from_journals(jdir: Path) -> str:
    """Return the Frontier account FID from the most recent journal that has one."""
    for _jp in sorted(jdir.glob("Journal*.log"), reverse=True):
        try:
            for _line in reversed(_jp.read_text(encoding="utf-8", errors="replace").splitlines()):
                try:
                    _ev = json.loads(_line.strip())
                    if _ev.get("event") in ("Commander", "LoadGame") and _ev.get("FID"):
                        return _ev["FID"]
                except ValueError:
                    pass
        except OSError:
            pass
    return ""

from core.state import set_active_fid, get_last_fid

_fid = _scan_fid_from_journals(journal_dir) or get_last_fid()
if _fid:
    set_active_fid(_fid)
    state.pilot_fid = _fid
    print(f"{Terminal.YELL}Commander FID:{Terminal.END} {_fid}")
else:
    print(f"{Terminal.YELL}Commander FID:{Terminal.END} (not yet determined)")

print(f"{Terminal.YELL}Commander name:{Terminal.END} {state.pilot_name or '(unknown)'}")

_config_profile = args.config_profile
_config_info    = ""
if not _config_profile and state.pilot_name and state.pilot_name in config_dict:
    _config_profile = state.pilot_name
    _config_info    = " (auto)"
    mgr = ConfigManager(config_dict, config_path, config_profile=_config_profile)

print(
    f"{Terminal.YELL}Config profile:{Terminal.END} "
    f"{_config_profile or 'Default'}{_config_info}"
)


# ── UI mode ───────────────────────────────────────────────────────────────────
# Priority: --mode CLI flag > --gui alias > config [UI] Mode value > default
# --gui is kept as a backwards-compatible alias for --mode gtk4.

_cfg_mode = mgr.ui_cfg.get("Mode", "terminal").lower().strip()

if args.mode:
    ui_mode = args.mode
elif args.gui:
    ui_mode = "gtk4"
elif _cfg_mode in ("terminal", "textual", "gtk4"):
    ui_mode = _cfg_mode
else:
    ui_mode = "terminal"

gui_mode = (ui_mode == "gtk4")   # kept for internal compat (emitter, update notices)


# ── Emitter ───────────────────────────────────────────────────────────────────

from core.emit import Emitter, emit_summary

emitter = Emitter(
    mgr, state,
    gui_queue=gui_queue,
    notify_test=notify_test,
    gui_mode=gui_mode,
)


# ── CoreAPI + plugins ─────────────────────────────────────────────────────────

from core.core_api      import CoreAPI
from core.plugin_loader import PluginLoader, PluginStorage
from core.journal       import build_dispatch_map
from core.data          import DataProvider
from core.state         import EDLD_DATA_DIR, cmdr_data_dir

# DataProvider — unified source of truth, instantiated before CoreAPI
_dp_storage = PluginStorage(cmdr_data_dir() / "core")
data_provider = DataProvider(
    state=state,
    storage=_dp_storage,
    gui_queue_fn=lambda: gui_queue,
    print_fn=lambda m: print(m) if trace_mode else None,
)

core = CoreAPI(
    state=state,
    active_session=active_session,
    lifetime=lifetime,
    cfg_mgr=mgr,
    emitter=emitter,
    gui_queue=gui_queue,
    journal_dir=journal_dir,
    data_provider=data_provider,
    launch_argv=sys.argv,
)
data_provider._plugin_call = core.plugin_call

loader = PluginLoader(_HERE)
loader.load_all(core)
plugin_dispatch = build_dispatch_map(list(core._plugins.values()))
data_provider.start()   # start CAPI poll thread after plugins loaded


# ── Bootstrap from journal history ────────────────────────────────────────────

print("\nStarting... (Press Ctrl+C to stop)\n")

from core.journal import bootstrap_fighter_bay, bootstrap_slf, bootstrap_crew, bootstrap_missions, bootstrap_burn_rate

bootstrap_fighter_bay(state, journal_dir)
bootstrap_slf(state, journal_dir, trace_mode=trace_mode)
bootstrap_crew(state, journal_dir, trace_mode=trace_mode)
bootstrap_missions(state, journal_dir, mgr, trace_mode=trace_mode)
bootstrap_burn_rate(state, journal_dir, active_session, trace_mode=trace_mode)

# ── Update notice ─────────────────────────────────────────────────────────────

_update_thread.join(timeout=2)
if _update_notice:
    _kind, _value = _update_notice   # _kind is always "release" now
    _repo_url = f"https://github.com/{GITHUB_REPO}"
    _term_msg = (
        f"{Terminal.YELL}\u26a0 Update available: v{_value}{Terminal.END}"
        f"  {Terminal.WHITE}{_repo_url}/releases{Terminal.END}\n"
    )
    if not gui_mode:
        print(_term_msg)
    if gui_mode:
        gui_queue.put(("update_notice", ("release", _value)))
    emitter.set_update_notice(_value)


# ── Session restore + startup banner ─────────────────────────────────────────

load_session_state(journal_file, active_session)
state.sessionstart(active_session)
emit_summary(
    emitter, state,
    core.session_providers,
    core._plugins.get("session_stats"),
)


# ── Monitor + launch ──────────────────────────────────────────────────────────

from core.journal      import run_monitor as _run_monitor, _poll_status_json
from core.state        import save_session_state

_edld_start_mono = time.monotonic()

def run_monitor() -> None:
    _run_monitor(
        journal_file,
        state, active_session, lifetime,
        emitter, mgr, gui_queue, journal_dir,
        _edld_start_mono,
        trace_mode=trace_mode,
        plugin_dispatch=plugin_dispatch,
        data_provider=data_provider,
        core=core,
    )


if __name__ == "__main__":
    if ui_mode == "textual":
        try:
            from tui.app import run_tui
        except ImportError as _tui_err:
            import traceback as _tb
            print(
                f"{Terminal.WARN}ERROR:{Terminal.END} Textual TUI import failed: {_tui_err}\n"
                f"sys.path: {sys.path}\n"
                f"Traceback:\n{_tb.format_exc()}"
                f"\nIf textual is missing: pip install textual"
            )
            sys.exit(1)

        _tui_theme = mgr.ui_cfg.get("Theme", "default")

        monitor_thread = threading.Thread(target=run_monitor, daemon=True)
        monitor_thread.start()

        status_thread = threading.Thread(
            target=_poll_status_json,
            args=(journal_dir, state, gui_queue),
            daemon=True,
        )
        status_thread.start()

        run_tui(core, PROGRAM, VERSION, theme=_tui_theme)

    elif ui_mode == "gtk4":
        try:
            from gui.app import EdmdApp
        except ImportError as e:
            print(
                f"{Terminal.WARN}ERROR:{Terminal.END} GTK4 mode requested but gui/ could not be loaded: {e}\n"
                f"Ensure PyGObject (GTK4) is installed: pacman -S python-gobject gtk4"
            )
            sys.exit(1)

        monitor_thread = threading.Thread(target=run_monitor, daemon=True)
        monitor_thread.start()

        status_thread = threading.Thread(
            target=_poll_status_json,
            args=(journal_dir, state, gui_queue),
            daemon=True,
        )
        status_thread.start()

        # ── Suppress known-unfixable GTK progress bar sizing warning ─────────
        # "GtkGizmo (progress) reported min width -2" fires on every window
        # close when a ProgressBar widget is present.  This is a GTK internal
        # bug with no application-level fix.
        #
        # GTK emits this via g_log() directly to fd 2 (C-level stderr) so
        # GLib.log_set_handler from Python does NOT intercept it.  We redirect
        # fd 2 through a pipe whose pump thread pattern-matches and drops the
        # offending line before writing everything else to the original stderr.
        # In trace mode the filter is never installed so the line still shows.
        if not trace_mode:
            try:
                import os as _os, threading as _th

                _orig_fd   = _os.dup(2)                     # save real stderr
                _r, _w     = _os.pipe()
                _os.dup2(_w, 2)                             # stderr → pipe write end
                _os.close(_w)
                _orig_out  = _os.fdopen(_orig_fd, "wb", buffering=0)
                _DROP      = (b"GtkGizmo", b"progress", b"min width")

                def _pump():
                    buf = b""
                    with _os.fdopen(_r, "rb", buffering=0) as pipe:
                        while True:
                            chunk = pipe.read(256)
                            if not chunk:
                                break
                            buf += chunk
                            while b"\n" in buf:
                                line, buf = buf.split(b"\n", 1)
                                line += b"\n"
                                if not all(p in line for p in _DROP):
                                    _orig_out.write(line)
                                    _orig_out.flush()
                                    if _log_fh is not None:
                                        try:
                                            _log_fh.write(line.decode("utf-8", errors="replace"))
                                            _log_fh.flush()
                                        except Exception:
                                            pass
                    if buf and not all(p in buf for p in _DROP):
                        _orig_out.write(buf)
                        _orig_out.flush()
                        if _log_fh is not None:
                            try:
                                _log_fh.write(buf.decode("utf-8", errors="replace"))
                                _log_fh.flush()
                            except Exception:
                                pass

                _th.Thread(target=_pump, daemon=True,
                           name="stderr-filter").start()
            except Exception:
                pass  # non-fatal

        app = EdmdApp(core, PROGRAM, VERSION)
        app.run(None)

    else:  # terminal
        run_monitor()

    if _log_fh is not None:
        try:
            _log_fh.close()
        except Exception:
            pass

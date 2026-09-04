"""
core — EDLD core package.

Public surface for edld.py and the dashboard.  Import from here
rather than from individual submodules to keep call-site coupling minimal.

Usage:
    from core import (
        MonitorState, SessionData,
        ConfigManager, resolve_config_path, load_config_file,
        Emitter, Terminal, emit_summary,
        fmt_credits, fmt_duration, rate_per_hour, clip_name,
        handle_event, run_monitor, build_dispatch_map,
        find_latest_journal,
        bootstrap_slf, bootstrap_crew, bootstrap_missions,
        BasePlugin, PluginLoader,
        CoreAPI,
    )
"""

# ── State ──────────────────────────────────────────────────────────────────────
from core.state import (
    MonitorState,
    SessionData,
    EDLD_DATA_DIR,
    STATE_FILE,
    PROGRAM,
    VERSION,
    AUTHOR,
    GITHUB_REPO,
    save_session_state,
    load_session_state,
)

# ── Config ─────────────────────────────────────────────────────────────────────
from core.config import (
    ConfigManager,
    resolve_config_path,
    load_config_file,
    load_setting,
    CFG_DEFAULTS_SETTINGS,
    CFG_DEFAULTS_EXTRA,
    CFG_DEFAULTS_UI,
    CFG_DEFAULTS_DISCORD,
    CFG_DEFAULTS_NOTIFY,
)

# ── Emit ───────────────────────────────────────────────────────────────────────
from core.emit import (
    Emitter,
    Terminal,
    WARNING,
    emit_summary,
    fmt_credits,
    fmt_duration,
    rate_per_hour,
    clip_name,
)

# ── Journal ────────────────────────────────────────────────────────────────────
from core.journal import (
    handle_event,
    run_monitor,
    monitor_journal,
    build_dispatch_map,
    find_latest_journal,
    bootstrap_slf,
    bootstrap_crew,
    bootstrap_missions,
    trace,
)

# ── Plugin infrastructure ──────────────────────────────────────────────────────
from core.plugin_loader import BasePlugin, PluginLoader
from core.core_api      import CoreAPI

__all__ = [
    # state
    "MonitorState", "SessionData",
    "EDLD_DATA_DIR", "STATE_FILE", "PROGRAM", "VERSION", "AUTHOR", "GITHUB_REPO",
    "save_session_state", "load_session_state",
    # config
    "ConfigManager", "resolve_config_path", "load_config_file",
    "load_setting",
    "CFG_DEFAULTS_SETTINGS", "CFG_DEFAULTS_EXTRA", "CFG_DEFAULTS_UI",
    "CFG_DEFAULTS_DISCORD", "CFG_DEFAULTS_NOTIFY",
    # emit
    "Emitter", "Terminal", "WARNING", "emit_summary",
    "fmt_credits", "fmt_duration", "rate_per_hour", "clip_name",
    # journal
    "handle_event", "run_monitor", "monitor_journal", "build_dispatch_map",
    "find_latest_journal",
    "bootstrap_slf", "bootstrap_crew", "bootstrap_missions", "trace",
    # plugin infrastructure
    "BasePlugin", "PluginLoader", "CoreAPI",
]

"""
core/core_api.py — CoreAPI: the interface every component receives via on_load().

Plugins must not import from edld.py or from each other.
All shared access goes through this object.
"""

import queue
from pathlib import Path

from core.emit import (
    Emitter,
    fmt_credits,
    fmt_duration,
    rate_per_hour,
    clip_name,
)


class CoreAPI:
    """Read-only view of core state and shared services for components.

    Attributes (read-only by convention — plugins must not mutate these):
        state          — MonitorState instance (low-level; prefer core.data)
        data           — DataProvider — unified source of truth for all state
        active_session — SessionData for the current session
        lifetime       — SessionData accumulating lifetime totals
        cfg            — ConfigManager instance
        emitter        — Emitter instance (call emitter.emit(...))
        gui_queue      — thread-safe queue for GUI update messages
        journal_dir    — Path to the journal directory
        trace_mode     — bool

    Helper functions (thin wrappers, always available):
        fmt_credits(n)
        fmt_duration(s)
        rate_per_hour(s, precision)
        clip_name(name, max_len)

    Plugin registration:
        register_block(component) — register a dashboard block (GUI only)
        register_alert(component) — register as an alert source
        plugin_call(name, method, *args, **kwargs)
                                  — call a method on another component by name
    """

    def __init__(
        self,
        state,
        active_session,
        lifetime,
        cfg_mgr,
        emitter: Emitter,
        gui_queue: queue.Queue | None,
        journal_dir: Path,
        data_provider=None,
        trace_mode: bool = False,
        launch_argv: list[str] | None = None,
    ):
        self.state          = state
        self.data           = data_provider   # DataProvider — unified source of truth
        self.active_session = active_session
        self.lifetime       = lifetime
        self.cfg            = cfg_mgr
        self.emitter        = emitter
        self.gui_queue      = gui_queue
        self.journal_dir    = journal_dir
        self.trace_mode     = trace_mode
        # Original sys.argv captured at startup — used for in-process restart
        self.launch_argv: list[str] = list(launch_argv) if launch_argv else []

        # Formatting helpers — available as core.fmt_credits(...) etc.
        self.fmt_credits  = fmt_credits
        self.fmt_duration = fmt_duration
        self.rate_per_hour = rate_per_hour
        self.clip_name    = clip_name

        # Component registry — populated by PluginLoader after all components load
        self._blocks:  list = []   # plugins with GUI blocks, in priority order
        self._alerts:  list = []   # plugins that feed the Alerts block
        self._session_providers: list = []   # ActivityProviderMixin instances
        self._plugins: dict = {}   # name -> plugin instance
        self._loader         = None  # PluginLoader — set after load_all()

    # ── Component-to-component calls ─────────────────────────────────────────

    def plugin_call(self, component_name: str, method: str, *args, **kwargs):
        """Call a method on a named component. Returns None if not loaded."""
        plugin = self._plugins.get(component_name)
        if plugin is None:
            return None
        fn = getattr(plugin, method, None)
        if fn is None:
            return None
        return fn(*args, **kwargs)

    # ── Registration (called by components during on_load) ───────────────────

    def register_block(self, plugin, priority: int = 50) -> None:
        """Register plugin as a dashboard block provider."""
        self._blocks.append((priority, plugin))
        self._blocks.sort(key=lambda x: x[0])

    def register_alert(self, plugin) -> None:
        """Register plugin as an alert source for the Alerts block."""
        self._alerts.append(plugin)

    def register_session_provider(self, plugin) -> None:
        """Register plugin as an activity data provider for Session Stats.

        Plugins must implement ActivityProviderMixin.  Tabs appear in the
        Session Stats block in alphabetical order after the Summary tab.
        """
        self._session_providers.append(plugin)

    @property
    def session_providers(self) -> list:
        """Return registered activity providers, sorted by tab title."""
        return sorted(
            self._session_providers,
            key=lambda p: getattr(p, "ACTIVITY_TAB_TITLE", "z"),
        )

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def emit(self, **kwargs) -> None:
        """Shorthand for self.emitter.emit(...)."""
        self.emitter.emit(**kwargs)

    def load_setting(self, category: str, defaults: dict, warn: bool = True) -> dict:
        """Shorthand for self.cfg.load_setting(...)."""
        return self.cfg.load_setting(category, defaults, warn)

    @property
    def app_settings(self) -> dict:
        return self.cfg.app_settings

    @property
    def notify_levels(self) -> dict:
        return self.cfg.notify_levels

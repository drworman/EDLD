"""
core/plugin_loader.py — Discover, import, initialise, and lifecycle-manage
                        all components.

All components live in components/ at the repo root.
Integration components (eddn, edsm, edastro, inara) are user-togglable.
All other components are always-on.
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import sys
import tomllib
from functools import wraps
from pathlib import Path
from typing import Any

from core.emit import Terminal
from core.state import EDLD_DATA_DIR, cmdr_data_dir


# ── PluginStorage ─────────────────────────────────────────────────────────────

class PluginStorage:
    """Sandboxed, scoped data storage for a single plugin.

    Each plugin receives a PluginStorage instance pre-bound to:
        EDLD_DATA_DIR/plugins/<plugin_name>/

    Read operations are unrestricted.  Write operations are restricted to
    that directory — any attempt to write outside it raises PermissionError.

    Supported file types: JSON (.json) and TOML (.toml, read-only).
    TOML writing is not supported because the stdlib ships no TOML writer;
    use JSON for mutable state.

    API
    ---
    storage.read_json(filename)          → dict  (empty dict if file absent)
    storage.write_json(data, filename)   → None
    storage.read_toml(filename)          → dict  (empty dict if file absent)
    storage.path                         → Path  (the plugin's data directory)
    """

    # Allowed bare filenames — no path separators permitted.
    _ALLOWED_NAMES = frozenset({
        "data.json", "config.json", "state.json", "tokens.json",
        "config.toml", "state.toml",
        # CAPI persisted data — raw endpoint responses for cross-plugin use
        "capi_profile.json", "capi_market.json", "capi_shipyard.json",
        "capi_fleetcarrier.json", "capi_communitygoals.json", "fleet.json",
        "poll_times.json",   # CAPI poll timestamps — survive rapid restarts
        "capi_tokens.json",  # DataProvider CAPI OAuth tokens
    })

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir

    @property
    def path(self) -> Path:
        return self._dir

    # ── internal ──────────────────────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _validate_filename(self, filename: str) -> Path:
        """Reject any filename that contains path separators or is not on
        the allowed list, then return the resolved absolute path."""
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(
                f"Plugin storage filename must be a bare name (got {filename!r})"
            )
        if filename not in self._ALLOWED_NAMES:
            raise ValueError(
                f"Plugin storage filename {filename!r} is not permitted. "
                f"Allowed: {sorted(self._ALLOWED_NAMES)}"
            )
        return self._dir / filename

    # ── public API ────────────────────────────────────────────────────────────

    def read_json(self, filename: str = "data.json") -> dict:
        """Read a JSON file from the plugin data directory.
        Returns an empty dict if the file does not exist.
        Re-derives path from cmdr_data_dir() at read time so it always reads
        from the correct commander directory even if the FID changed after load.
        """
        from core.state import cmdr_data_dir
        real_dir = cmdr_data_dir() / "plugins" / self._dir.name
        p = real_dir / self._validate_filename(filename).name
        if not p.exists():
            return {}
        with builtins.open(p, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except (json.JSONDecodeError, ValueError):
                return {}

    def write_json(self, data: dict, filename: str = "data.json") -> None:
        """Write a JSON file to the plugin data directory (atomic via temp file)."""
        p = self._validate_filename(filename)
        # Re-resolve directory at write time — the FID may have changed since
        # this PluginStorage was created (e.g. "unknown" → real FID at LoadGame).
        # Re-derive the path from cmdr_data_dir() so we always write to the right place.
        from core.state import cmdr_data_dir
        real_dir = cmdr_data_dir() / "plugins" / self._dir.name
        real_dir.mkdir(parents=True, exist_ok=True)
        real_p = real_dir / p.name
        tmp    = real_p.with_suffix(".tmp")
        import os as _os
        content = json.dumps(data, indent=2, default=str)
        with builtins.open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        _os.replace(tmp, real_p)

    def read_sibling_json(self, plugin_name: str, filename: str) -> dict:
        """Read a JSON file from another plugin's data directory (read-only).

        Allows plugins to consume data written by other plugins — e.g. assets
        reading CAPI's persisted profile data.  Write operations are still
        restricted to the plugin's own directory.

        Returns an empty dict if the file does not exist or cannot be parsed.
        """
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(f"Filename must be bare (got {filename!r})")
        if filename not in self._ALLOWED_NAMES:
            raise ValueError(f"Filename {filename!r} not in allowlist")
        p = self._dir.parent / plugin_name / filename
        if not p.exists():
            return {}
        with builtins.open(p, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except (json.JSONDecodeError, ValueError):
                return {}

    def write_sibling_json(self, plugin_name: str, filename: str, data: dict) -> None:
        """Write a JSON file to another plugin's data directory.

        Only permitted for files in _ALLOWED_NAMES.  Used by assets plugin to
        update CAPI's persisted capi_profile.json when a ship is sold, so that
        the sold ship does not reappear on the next restart before a fresh poll.
        """
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(f"Filename must be bare (got {filename!r})")
        if filename not in self._ALLOWED_NAMES:
            raise ValueError(f"Filename {filename!r} not in allowlist")
        p = self._dir.parent / plugin_name / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with builtins.open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(p)

    def read_toml(self, filename: str = "config.toml") -> dict:
        """Read a TOML file from the plugin data directory.
        Returns an empty dict if the file does not exist."""
        if not filename.endswith(".toml"):
            raise ValueError("read_toml() requires a .toml filename")
        p = self._validate_filename(filename)
        if not p.exists():
            return {}
        with builtins.open(p, "rb") as f:
            try:
                return tomllib.load(f)
            except tomllib.TOMLDecodeError:
                return {}


# ── DisabledPluginMeta ────────────────────────────────────────────────────────

class DisabledPluginMeta:
    """Lightweight record for a plugin that was found but not loaded.
    Used by the Installed Plugins dialog to show disabled plugins."""

    __slots__ = (
        "PLUGIN_NAME", "PLUGIN_DISPLAY", "PLUGIN_VERSION",
        "PLUGIN_DESCRIPTION", "_is_builtin",
    )

    def __init__(
        self,
        name: str,
        display: str,
        version: str,
        description: str,
        is_builtin: bool,
    ) -> None:
        self.PLUGIN_NAME        = name
        self.PLUGIN_DISPLAY     = display
        self.PLUGIN_VERSION     = version
        self.PLUGIN_DESCRIPTION = description


# ── BasePlugin ────────────────────────────────────────────────────────────────

class BasePlugin:
    """Base class for all builtins and plugins.

    Subclass this and override the methods you need.
    PLUGIN_NAME, PLUGIN_DISPLAY, and SUBSCRIBED_EVENTS are required class
    attributes.  All other class attributes have sensible defaults.

    The loader guarantees that before on_load() is called:
      • self.storage  — PluginStorage scoped to this component's data directory

    Components must call super().on_load(core) or assign self.core manually.
    """

    # ── Required class attributes ─────────────────────────────────────────────
    PLUGIN_NAME:        str       = ""      # machine name, e.g. "missions"
    PLUGIN_DISPLAY:     str       = ""      # human name,   e.g. "Mission Stack"
    PLUGIN_VERSION:     str       = "0.0.1"
    PLUGIN_DESCRIPTION: str       = ""      # one-line description shown in dialog
    SUBSCRIBED_EVENTS:  list[str] = []

    # Set False to ship disabled by default (user can enable in Installed Plugins)
    PLUGIN_DEFAULT_ENABLED: bool  = True

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_load(self, core) -> None:
        """Called once at startup after storage is assigned.
        Always call super().on_load(core) first."""
        self.core = core

    def on_unload(self) -> None:
        """Called on clean shutdown."""

    # ── Event dispatch ────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        """Called for every journal event whose name is in SUBSCRIBED_EVENTS."""

    def on_capi_fleetcarrier(self, cargo: dict) -> None:
        """Called after a successful CAPI /fleetcarrier poll with the full
        physical cargo hold as {commodity_name_lower: total_qty}.
        Override to act on fresh authoritative carrier cargo data."""

    # ── GUI integration ───────────────────────────────────────────────────────
    BLOCK_WIDGET_CLASS: type | None = None

    # ── Summary / alerts ─────────────────────────────────────────────────────

    def get_summary_line(self) -> str | None:
        """Return a line for the periodic terminal/Discord summary, or None."""
        return None

    def get_alert_events(self) -> list[str]:
        """Return a list of (emoji, text) alert tuples for the Alerts block."""
        return []


# ── Write sandbox ─────────────────────────────────────────────────────────────

def _make_sandboxed_open(allowed_dir: Path, plugin_name: str):
    """Return a replacement open() that raises PermissionError on any write
    attempt whose resolved path is outside allowed_dir."""

    resolved_allowed = allowed_dir.resolve()

    def _sandboxed_open(file, mode="r", *args, **kwargs):
        if any(c in str(mode) for c in ("w", "a", "x", "+")):
            try:
                target = Path(file).resolve()
            except Exception:
                target = Path(str(file)).resolve()
            if not str(target).startswith(str(resolved_allowed)):
                raise PermissionError(
                    f"[EDLD] Plugin '{plugin_name}' attempted to write to "
                    f"{target} — plugins may only write to "
                    f"{resolved_allowed}. "
                    f"Use self.storage.write_json() instead."
                )
        return builtins.open(file, mode, *args, **kwargs)

    return _sandboxed_open


# ── Plugin state persistence ──────────────────────────────────────────────────

# ── Plugin state persistence ──────────────────────────────────────────────────


def _states_file() -> Path:
    return cmdr_data_dir() / "plugin_states.json"


def _load_plugin_states() -> dict[str, bool]:
    """Read persisted enabled/disabled overrides.  Missing = use class default."""
    p = _states_file()
    if not p.exists():
        return {}
    try:
        with builtins.open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {k: bool(v) for k, v in raw.items() if isinstance(k, str)}
    except Exception:
        return {}


def _save_plugin_states(states: dict[str, bool]) -> None:
    p   = _states_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with builtins.open(tmp, "w", encoding="utf-8") as f:
        json.dump(states, f, indent=2)
    tmp.replace(p)


# ── Loader ────────────────────────────────────────────────────────────────────

class PluginLoader:
    """Discovers plugin directories and manages their lifecycle."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root    = repo_root
        self._plugins:     list[BasePlugin]        = []
        self._plugin_map:  dict[str, BasePlugin]   = {}
        self._disabled:    list[DisabledPluginMeta] = []
        self._states:      dict[str, bool]         = _load_plugin_states()
        self._dirty:       bool                    = False   # states changed, restart needed

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def plugins(self) -> list[BasePlugin]:
        return self._plugins

    @property
    def plugin_map(self) -> dict[str, BasePlugin]:
        return self._plugin_map

    @property
    def disabled_meta(self) -> list[DisabledPluginMeta]:
        """Metadata records for installed-but-disabled plugins."""
        return self._disabled

    @property
    def pending_restart(self) -> bool:
        """True if enable/disable changes have been made this session."""
        return self._dirty

    # ── Enable / disable ──────────────────────────────────────────────────────

    def is_enabled(self, plugin_name: str, default: bool = True) -> bool:
        return self._states.get(plugin_name, default)

    def set_enabled(self, plugin_name: str, enabled: bool) -> None:
        """Persist a new enabled/disabled state for a plugin.
        Changes take effect on next restart."""
        self._states[plugin_name] = enabled
        _save_plugin_states(self._states)
        self._dirty = True

    # ── Loading ───────────────────────────────────────────────────────────────

    INTEGRATION_NAMES = frozenset({"eddn", "edsm", "edastro", "inara"})

    def load_all(self, core_api) -> None:
        """Load all components from components/.

        Integration components (eddn, edsm, edastro, inara) are user-togglable.
        All others are always-on.
        """
        components_dir = self._repo_root / "components"

        for plugin_dir in sorted(components_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            plugin_file = plugin_dir / "plugin.py"
            if not plugin_file.exists():
                continue
            dir_name       = plugin_dir.name
            is_integration = dir_name in self.INTEGRATION_NAMES
            self._load_one(
                plugin_file, "component", True, core_api,
                always_on=not is_integration,
                show_in_menu=is_integration,
            )

        core_api._plugins = self._plugin_map
        core_api._loader  = self

    def _load_one(
        self,
        plugin_file: Path,
        label: str,
        is_builtin: bool,
        core_api,
        always_on: bool = False,
        show_in_menu: bool = True,
    ) -> None:
        dir_name    = plugin_file.parent.name
        module_name = f"_edld_plugin_{dir_name}"

        try:
            spec   = importlib.util.spec_from_file_location(module_name, plugin_file)
            module = importlib.util.module_from_spec(spec)

            # ── Write sandbox ───────────────────────────────────────────────
            # Patch open() in this module's namespace before execution so that
            # any write attempt outside the plugin's data dir is blocked.
            storage_dir = cmdr_data_dir() / "plugins" / dir_name
            module.__builtins__ = vars(builtins).copy()
            module.__builtins__["open"] = _make_sandboxed_open(storage_dir, dir_name)

            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # ── Find the BasePlugin subclass ─────────────────────────────────
            plugin_cls = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BasePlugin)
                    and attr is not BasePlugin
                ):
                    plugin_cls = attr
                    break

            if plugin_cls is None:
                print(
                    f"{Terminal.WARN}Warning:{Terminal.END} "
                    f"{label} {dir_name!r}: no BasePlugin subclass found, skipping"
                )
                return

            # ── Read metadata before deciding whether to load ────────────────
            name        = getattr(plugin_cls, "PLUGIN_NAME",        dir_name)
            display     = getattr(plugin_cls, "PLUGIN_DISPLAY",     name)
            version     = getattr(plugin_cls, "PLUGIN_VERSION",     "0.0.1")
            description = getattr(plugin_cls, "PLUGIN_DESCRIPTION", "")
            cls_default = getattr(plugin_cls, "PLUGIN_DEFAULT_ENABLED", True)

            # always_on plugins (core components, activity plugins) bypass
            # the enable/disable system entirely.
            if not always_on:
                enabled = self.is_enabled(name, default=cls_default)
                if not enabled:
                    if show_in_menu:
                        self._disabled.append(
                            DisabledPluginMeta(name, display, version,
                                               description, is_builtin)
                        )
                    print(
                        f"  [skipped]  {display} v{version} (disabled)"
                    )
                    return

            # ── Instantiate and wire up ──────────────────────────────────────
            instance               = plugin_cls()
            instance._is_builtin   = is_builtin
            instance._always_on    = always_on
            instance._show_in_menu = show_in_menu
            instance.storage       = PluginStorage(storage_dir)

            instance.on_load(core_api)

            self._plugins.append(instance)
            self._plugin_map[instance.PLUGIN_NAME] = instance

            note = getattr(instance, "_load_note", "")
            suffix = f"  ({note})" if note else ""
            if show_in_menu:
                print(
                    f"  [integration]  {instance.PLUGIN_DISPLAY} "
                    f"v{instance.PLUGIN_VERSION}{suffix}"
                )
            else:
                print(
                    f"  [component]  {instance.PLUGIN_DISPLAY} "
                    f"v{instance.PLUGIN_VERSION}{suffix}"
                )

        except Exception as e:
            tier = "core component" if label == "component" else label
            print(
                f"{Terminal.WARN}Warning:{Terminal.END} "
                f"Failed to load {tier} from {plugin_file}: {e}"
            )
            import traceback
            traceback.print_exc()

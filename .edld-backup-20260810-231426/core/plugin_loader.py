"""
core/plugin_loader.py — Discover, import, initialise, and lifecycle-manage
                        all components.

All components live as single files at the repo root in components/, named
``components/<plugin_name>.py``.  The file stem is the plugin identifier;
it determines:
  - the file prefix for persisted state under ``<cmdr_data>/data/`` (e.g.
    primary ``<plugin>.json``, sidecars ``<plugin>.<purpose>.json``)
  - the sandboxed open() filename-prefix scope
  - the module name in sys.modules

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
    """Per-plugin persistent storage rooted at the shared data directory.

    Layout
    ------
    Every plugin's state lives in a single flat directory at
    ``<cmdr>/data/`` — there is no per-plugin sub-tree.  Files are
    plugin-namespaced by filename prefix instead of by directory:

        <cmdr>/data/<plugin>.json           ← primary (was <plugin>/data.json)
        <cmdr>/data/<plugin>.<purpose>.json ← sidecars (e.g. core.tokens.json)
        <cmdr>/data/<plugin>.<name>.<ext>   ← arbitrary sidecars
                                              (e.g. inara.queue.jsonl)

    API
    ---
        storage.path                   → Path to the primary <plugin>.json
        storage.file_path("name.ext")  → Path to a non-JSON sidecar
                                         (returns <cmdr>/data/<plugin>.name.ext)
        storage.read_json()            → dict from <plugin>.json
        storage.read_json("purpose")   → dict from <plugin>.<purpose>.json
        storage.write_json(d)          → write primary
        storage.write_json(d, "purpose") → write sidecar
        storage.read_sibling_json(plugin)
        storage.read_sibling_json(plugin, "purpose")
        storage.write_sibling_json(plugin, "purpose", d)

    Back-compat
    -----------
    Old call sites that passed full filenames (``read_json("data.json")``,
    ``read_json("capi_tokens.json")``, ``read_sibling_json("core",
    "capi_profile.json")``) continue to work — ``_resolve_purpose`` strips
    a trailing ``.json`` and a leading ``capi_`` so they land at the new
    flattened paths without code changes.  New code should pass clean
    purpose names without prefix or extension.
    """

    def __init__(self, plugin_name: str) -> None:
        # The plugin identifier — also the filename prefix on disk.
        # Must be a bare name (no path separators) since it's interpolated
        # directly into filenames.
        if "/" in plugin_name or "\\" in plugin_name or ".." in plugin_name:
            raise ValueError(f"Plugin name must be bare (got {plugin_name!r})")
        self._name = plugin_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def path(self) -> Path:
        """Path to this plugin's primary data file: ``<cmdr>/data/<name>.json``.

        Re-derived from ``cmdr_data_dir()`` on every access so it stays
        correct if the FID changes after the plugin loads (e.g. went from
        "unknown" → real FID once LoadGame fires).
        """
        from core.state import cmdr_data_dir
        return cmdr_data_dir() / "data" / f"{self._name}.json"

    def file_path(self, filename: str) -> Path:
        """Path for an arbitrary plugin file, prefixed with the plugin name.

        Used for non-JSON sidecars such as upload-queue persistence:

            storage.file_path("queue.jsonl")
            → <cmdr>/data/<plugin>.queue.jsonl

        The plugin prefix is added automatically — callers pass just the
        basename.  Path separators are rejected.
        """
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(f"file_path: bare filename only (got {filename!r})")
        from core.state import cmdr_data_dir
        return cmdr_data_dir() / "data" / f"{self._name}.{filename}"

    # ── public API ────────────────────────────────────────────────────────────

    def read_json(self, purpose: str | None = None) -> dict:
        """Read the primary file (purpose=None) or a ``<plugin>.<purpose>.json``
        sidecar.  Returns an empty dict if the file is absent or malformed.
        """
        p = self._resolve(self._name, purpose)
        return self._read(p)

    def write_json(self, data: dict, purpose: str | None = None) -> None:
        """Atomic write of the primary file or a sidecar."""
        p = self._resolve(self._name, purpose)
        self._write(p, data)

    def read_sibling_json(self, plugin_name: str,
                          purpose: str | None = None) -> dict:
        """Read another plugin's primary or sidecar file.

        Permits cross-plugin data consumption (e.g. assets reading core's
        capi_profile sidecar) without granting write access.  Returns an
        empty dict if the target file does not exist.
        """
        p = self._resolve(plugin_name, purpose)
        return self._read(p)

    def write_sibling_json(self, plugin_name: str,
                           purpose: str | None,
                           data: dict) -> None:
        """Write to another plugin's namespace.  Rare — used by assets to
        update core's cached CAPI profile after a fleet enrichment so the
        sold ship doesn't reappear on the next restart before a fresh poll.
        """
        p = self._resolve(plugin_name, purpose)
        self._write(p, data)

    # ── internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _resolve(plugin_name: str, purpose: str | None) -> Path:
        """Map (plugin_name, purpose) → absolute path under ``<cmdr>/data/``.

        Back-compat normalisation:
          - purpose in (None, "", "data", "data.json") → primary file
          - trailing ``.json`` is stripped
          - leading ``capi_`` is stripped (legacy core sidecar names)
        """
        from core.state import cmdr_data_dir
        base = cmdr_data_dir() / "data"

        if purpose in (None, "", "data", "data.json"):
            return base / f"{plugin_name}.json"

        # Reject any traversal/path attempts before normalising
        if "/" in purpose or "\\" in purpose or ".." in purpose:
            raise ValueError(f"Purpose must be bare (got {purpose!r})")

        clean = purpose
        if clean.endswith(".json"):
            clean = clean[:-5]
        if clean.startswith("capi_"):
            clean = clean[5:]
        if not clean:
            return base / f"{plugin_name}.json"
        return base / f"{plugin_name}.{clean}.json"

    @staticmethod
    def _read(p: Path) -> dict:
        if not p.exists():
            return {}
        try:
            with builtins.open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError):
            return {}

    @staticmethod
    def _write(p: Path, data: dict) -> None:
        import os as _os
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        content = json.dumps(data, indent=2, default=str)
        with builtins.open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        _os.replace(tmp, p)


def migrate_legacy_storage_layout(cmdr_dir: Path) -> int:
    """One-shot migration from the old ``<cmdr>/plugins/<X>/<file>`` tree
    to the flat ``<cmdr>/data/<X>[.<purpose>].<ext>`` layout.

    Walks every file under ``<cmdr>/plugins/`` and moves it to its
    flattened name in ``<cmdr>/data/``.  The translation:

        plugins/<X>/data.json     → data/<X>.json
        plugins/<X>/capi_foo.json → data/<X>.foo.json
        plugins/<X>/<name>.<ext>  → data/<X>.<name>.<ext>

    Files that already exist at the target are left in place (we never
    overwrite — a same-name target means a previous migration ran).
    Empty plugin directories and the plugins/ root are removed when their
    contents are gone.

    Returns the number of files actually moved.  Errors are swallowed so a
    migration glitch never blocks startup; callers can re-check on next run.
    """
    import os as _os
    legacy = cmdr_dir / "plugins"
    target = cmdr_dir / "data"
    if not legacy.is_dir():
        return 0
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 0

    moved = 0
    for plugin_dir in sorted(legacy.iterdir()):
        if not plugin_dir.is_dir():
            continue
        plugin = plugin_dir.name
        for old_file in sorted(plugin_dir.iterdir()):
            if not old_file.is_file():
                continue
            new_name = _migrate_filename(plugin, old_file.name)
            new_path = target / new_name
            if new_path.exists():
                # Target already migrated; leave the legacy file alone for
                # the user to inspect and remove if they want.
                continue
            try:
                _os.replace(str(old_file), str(new_path))
                moved += 1
            except OSError:
                continue
        try:
            plugin_dir.rmdir()
        except OSError:
            pass
    try:
        legacy.rmdir()
    except OSError:
        pass
    return moved


def _migrate_filename(plugin: str, old: str) -> str:
    """Compute the new flat filename for a legacy ``plugins/<plugin>/<old>``.

    The rules:
      - ``data.json``       → ``<plugin>.json``
      - ``capi_<x>.<ext>``  → ``<plugin>.<x>.<ext>``
      - ``<name>.<ext>``    → ``<plugin>.<name>.<ext>``
      - ``<stem>``  (no ext) → ``<plugin>.<stem>``
    """
    if old == "data.json":
        return f"{plugin}.json"
    stem, sep, ext = old.rpartition(".")
    if not sep:
        # No dot in filename — treat whole thing as a stem.
        return f"{plugin}.{old}"
    if stem.startswith("capi_"):
        stem = stem[5:]
    return f"{plugin}.{stem}.{ext}"


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

    # ── Dashboard integration ──────────────────────────────────────────────────
    BLOCK_WIDGET_CLASS: type | None = None

    # ── Summary / alerts ─────────────────────────────────────────────────────

    def get_summary_line(self) -> str | None:
        """Return a line for the periodic terminal/Discord summary, or None."""
        return None

    def get_alert_events(self) -> list[str]:
        """Return a list of (emoji, text) alert tuples for the Alerts block."""
        return []


# ── Write sandbox ─────────────────────────────────────────────────────────────

def _make_sandboxed_open(plugin_name: str):
    """Return a replacement open() that raises PermissionError on any write
    whose resolved path is not inside the shared data directory AND whose
    filename is not prefixed with ``<plugin_name>.`` (or exactly
    ``<plugin_name>.json``).

    Under the flat storage layout every plugin's files live side-by-side
    in ``<cmdr>/data/``; the sandbox isolation that used to come from a
    dedicated sub-directory now comes from the filename prefix.
    """
    def _sandboxed_open(file, mode="r", *args, **kwargs):
        if any(c in str(mode) for c in ("w", "a", "x", "+")):
            try:
                target = Path(file).resolve()
            except Exception:
                target = Path(str(file)).resolve()
            from core.state import cmdr_data_dir
            data_root = (cmdr_data_dir() / "data").resolve()
            allowed_prefix_a = f"{plugin_name}."   # sidecars
            allowed_prefix_b = f"{plugin_name}.json"
            # Allow files within the shared data dir whose basename starts
            # with the plugin's prefix.  Anything else — including writes
            # outside data/ — is blocked.
            try:
                if target.parent != data_root:
                    raise PermissionError
                base = target.name
                if not (base == allowed_prefix_b
                        or base.startswith(allowed_prefix_a)):
                    raise PermissionError
            except PermissionError:
                raise PermissionError(
                    f"[EDLD] Plugin '{plugin_name}' attempted to write to "
                    f"{target} — plugins may only write to "
                    f"{data_root}/{plugin_name}[.*].  "
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

        Layout: each plugin is a single ``components/<name>.py`` file.  The
        file stem (``<name>``) is used as the plugin identifier for storage
        paths and for sandbox isolation.

        Before any plugin loads, runs the one-shot legacy-layout migration
        so that pre-flatten data in ``<cmdr>/plugins/<X>/`` is moved into
        the new ``<cmdr>/data/<X>[.<purpose>].<ext>`` layout.
        """
        # Migration first — must happen before any plugin reads its data.
        moved = migrate_legacy_storage_layout(cmdr_data_dir())
        if moved:
            from core import debug as _dbg
            _dbg.info(f"  [storage] migrated {moved} file(s) from plugins/ → data/")

        components_dir = self._repo_root / "components"

        for plugin_file in sorted(components_dir.glob("*.py")):
            if plugin_file.name == "__init__.py":
                continue
            dir_name       = plugin_file.stem
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
        # Plugin identifier — file stem in the new single-file layout.
        # This matches what was previously the parent directory name, so
        # storage paths (cmdr_data_dir() / "plugins" / <name>) are stable
        # across the refactor and user data continues to load.
        dir_name    = plugin_file.stem
        module_name = f"_edld_plugin_{dir_name}"

        try:
            spec   = importlib.util.spec_from_file_location(module_name, plugin_file)
            module = importlib.util.module_from_spec(spec)

            # ── Write sandbox ───────────────────────────────────────────────
            # Patch open() in this module's namespace before execution.  The
            # sandbox allows writes only to files in <cmdr>/data/ whose
            # basename is prefixed with this plugin's name.
            module.__builtins__ = vars(builtins).copy()
            module.__builtins__["open"] = _make_sandboxed_open(dir_name)

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
                    from core import debug as _dbg
                    _dbg.info(
                        f"  [skipped]  {display} v{version} (disabled)"
                    )
                    return

            # ── Instantiate and wire up ──────────────────────────────────────
            instance               = plugin_cls()
            instance._is_builtin   = is_builtin
            instance._always_on    = always_on
            instance._show_in_menu = show_in_menu
            instance.storage       = PluginStorage(dir_name)

            instance.on_load(core_api)

            self._plugins.append(instance)
            self._plugin_map[instance.PLUGIN_NAME] = instance

            note = getattr(instance, "_load_note", "")
            suffix = f"  ({note})" if note else ""
            from core import debug as _dbg
            if show_in_menu:
                _dbg.info(
                    f"  [integration]  {instance.PLUGIN_DISPLAY} "
                    f"v{instance.PLUGIN_VERSION}{suffix}"
                )
            else:
                _dbg.info(
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

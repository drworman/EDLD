"""
core/config.py — Configuration loading, defaults, profile resolution,
                 and hot-reload.

Depends only on core.state (for EDLD_DATA_DIR).
Does not import from emit, journal, or gui.
"""

import sys
import re
import tomllib
from pathlib import Path

from core.state import EDLD_DATA_DIR


# ── Minimal terminal colour for pre-emit warnings ────────────────────────────
# emit.py imports config, so we can't import Terminal from there.
# Only _WARNING is needed here; full Terminal lives in core.emit.

class _T:
    WARN = "\x1b[38;5;215m"
    END  = "\x1b[0m"

_WARNING = f"{_T.WARN}Warning:{_T.END}"


import re

# ── Canonical TOML format ─────────────────────────────────────────────────────

# Top-level config sections that are written as flat [Section] tables.
# Anything not in this set is treated as a profile and written under a single
# [ProfileName] header with dotted sub-keys (Settings.Key = ..., UI.Mode = ...).
# A [ProfileName.SubSection] sub-table header is NEVER written — that is the
# old format that this migration is designed to eliminate.
STANDARD_SECTIONS: frozenset[str] = frozenset({
    "Settings", "Discord", "LogLevels", "UI",
    "EDDN", "EDSM", "EDAstro", "Inara", "CAPI",
})

# Matches any TOML section header that indicates old-format content:
#   [GUI]               — old interface section name
#   [ProfileName.Sub]   — old profile sub-table style
_NEEDS_MIGRATION = re.compile(r'^\[(?:GUI|\w+\.\w+)\]', re.MULTILINE)


def _scalar(v) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(v, bool):  return "true" if v else "false"
    if isinstance(v, int):   return str(v)
    if isinstance(v, float): return str(v)
    escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def config_to_toml(d: dict) -> str:
    """Serialise a config dict to canonical TOML.

    Rules:
      • Standard sections (Settings, Discord, UI, LogLevels, EDDN, EDSM,
        EDAstro, Inara, CAPI) are written as flat [Section] tables.
      • Profile sections (EDP1, REMOTE, anything else) are written as a
        single [ProfileName] table whose sub-section keys use dotted notation:
            [EDP1]
            Settings.JournalFolder = "..."
            UI.Mode = "gtk4"
        The old [EDP1.Settings] / [EDP1.UI] sub-table style is NEVER produced.

    This is the single authoritative writer for config.toml.  Both
    gui/preferences.py and tui/preferences.py import and use this function.
    """
    lines: list[str] = []

    # ── Top-level bare scalars (rare) ─────────────────────────────────────────
    for k, v in d.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_scalar(v)}")

    # ── Standard flat sections ────────────────────────────────────────────────
    for section, val in d.items():
        if not isinstance(val, dict) or section not in STANDARD_SECTIONS:
            continue
        lines += ["", f"[{section}]"]
        for k, v in val.items():
            if not isinstance(v, dict):
                lines.append(f"{k} = {_scalar(v)}")

    # ── Profile sections — single header, dotted sub-keys ─────────────────────
    for section, val in d.items():
        if not isinstance(val, dict) or section in STANDARD_SECTIONS:
            continue
        lines += ["", f"[{section}]"]
        # Root-level scalars within the profile (QuitOnLowFuel, _adv_session_mgmt …)
        for k, v in val.items():
            if not isinstance(v, dict):
                lines.append(f"{k} = {_scalar(v)}")
        # Sub-section keys written as dotted pairs (never as [Profile.Sub] headers)
        for sub, sub_val in val.items():
            if not isinstance(sub_val, dict):
                continue
            for k, v in sub_val.items():
                if not isinstance(v, dict):
                    lines.append(f"{sub}.{k} = {_scalar(v)}")

    return "\n".join(lines) + "\n"


# ── Startup migration ─────────────────────────────────────────────────────────

def _apply_gui_to_ui(gui_dict: dict) -> dict:
    """Convert a [GUI] / profile GUI sub-dict to [UI] representation.

        Enabled = true   →  Mode = "gtk4"
        Enabled = false  →  Mode = "terminal"
        (absent)         →  Mode unchanged / not added
        All other keys   →  kept as-is (Theme, FontFamily, FontSize, …)
    """
    src = dict(gui_dict)
    enabled = src.pop("Enabled", None)
    result: dict = {}
    if enabled is True:
        result["Mode"] = "gtk4"
    elif enabled is False:
        result["Mode"] = "terminal"
    result.update(src)
    return result


def migrate_config_if_needed(config_path: Path) -> bool:
    """Detect old config formats and silently rewrite to canonical format.

    Handles all of:
      • [GUI] global section  →  [UI]  (Enabled= → Mode=)
      • [ProfileName.GUI] sub-table  →  ProfileName.UI.*  (dotted key)
      • ProfileName.GUI.Enabled = true in a profile block  →  UI.Mode = "gtk4"
      • [ProfileName.Section] sub-table headers  →  [ProfileName] + dotted keys

    Detection uses a raw-text regex so clean canonical files are never touched.
    Returns True if the file was rewritten, False if no migration was needed.

    MUST be called before load_config_file() in edld.py.
    """
    try:
        raw = config_path.read_text(encoding="utf-8")
    except Exception:
        return False

    if not _NEEDS_MIGRATION.search(raw):
        return False   # already canonical — nothing to do

    # File needs migration: parse it, transform, rewrite
    try:
        with open(config_path, "rb") as _f:
            d = tomllib.load(_f)
    except Exception:
        return False   # parse errors handled by load_config_file later

    changed = False

    # 1. Global [GUI] → [UI]
    if "GUI" in d:
        existing_ui = dict(d.get("UI") or {})
        migrated = _apply_gui_to_ui(d.pop("GUI"))
        # Migrated values fill gaps; they never overwrite an explicit [UI] key
        for k, v in migrated.items():
            existing_ui.setdefault(k, v)
        d["UI"] = existing_ui
        changed = True

    # 2. Profile-level GUI sub-dicts
    for key, val in d.items():
        if not isinstance(val, dict) or key in STANDARD_SECTIONS:
            continue
        if "GUI" in val:
            existing_ui = dict(val.get("UI") or {})
            migrated = _apply_gui_to_ui(val.pop("GUI"))
            for k, v in migrated.items():
                existing_ui.setdefault(k, v)
            val["UI"] = existing_ui
            changed = True

    # 3. Rewrite in canonical format (fixes [ProfileName.Section] sub-tables
    #    even if no GUI key was present — the regex already confirmed this file
    #    has at least one [X.Y] header that needs collapsing)
    try:
        config_path.write_text(config_to_toml(d), encoding="utf-8")
        return True
    except Exception as e:
        print(f"{_WARNING} Config migration failed — file unchanged: {e}")
        return False


# ── Config defaults ───────────────────────────────────────────────────────────

CFG_DEFAULTS_SETTINGS = {
    "JournalFolder":  "",
    "UseUTC":         False,
    "PrimaryInstance": True,   # Set False on remote/secondary instances to suppress data uploads
    "WarnKillRate":   20,
    "WarnNoKills":    20,
    "PirateNames":    False,
    "BountyFaction":  False,
    "BountyValue":    False,
    "ExtendedStats":  False,
    "MinScanLevel":   1,
}

CFG_DEFAULTS_EXTRA = {
    "TruncateNames":      30,
    "WarnNoKillsInitial": 5,
    "WarnCooldown":       15,
    "FullStackSize":      20,
}

CFG_DEFAULTS_UI = {
    "Mode":             "terminal",  # terminal | textual | gtk4
    "Theme":            "default",
    "FontSize":         14,
    "FontFamily":       "JetBrains Mono",
    "SoftwareRenderer": False,       # set True if EDLD causes compositor starvation on Linux
}

CFG_DEFAULTS_DISCORD = {
    "WebhookURL":      "",
    "UserID":          0,
    "PrependCmdrName": False,
    "ForumChannel":    False,
    "ThreadCmdrNames": False,
    "Timestamp":       True,
    "Identity":        True,
}

CFG_DEFAULTS_EDDN = {
    "Enabled":    False,
    "UploaderID": "",
    "TestMode":   False,
}

CFG_DEFAULTS_EDSM = {
    "Enabled":       False,
    "CommanderName": "",
    "ApiKey":        "",
}

CFG_DEFAULTS_EDASTRO = {
    "Enabled":             False,
    "UploadCarrierEvents": False,
}

CFG_DEFAULTS_INARA = {
    "Enabled":       False,
    "ApiKey":        "",
    "CommanderName": "",
}

CFG_DEFAULTS_CAPI = {
    "Enabled": False,   # set True automatically after first successful auth
}

CFG_DEFAULTS_COLONISATION = {
    # Raven Colonial API key for ravencolonial.com project tracking.
    # Leave blank to disable API integration (local tracking still works).
    "ApiKey": "",
}

CFG_DEFAULTS_NOTIFY = {
    "InboundScan":      1,
    "RewardEvent":      2,
    "FighterDamage":    2,
    "FighterLost":      3,
    "ShieldEvent":      3,
    "HullEvent":        3,
    "Died":             3,
    "CargoLost":        3,
    "LowCargoValue":    2,
    "PoliceScan":       2,
    "PoliceAttack":     3,
    "FuelStatus":       1,
    "FuelWarning":      2,
    "FuelCritical":     3,
    "MissionUpdate":    2,
    "AllMissionsReady": 3,
    "MeritEvent":       0,
    "InactiveAlert":    3,
    "RateAlert":        3,
    "PeriodicKills":    2,
    "PeriodicFaction":  0,
    "PeriodicCredits":  2,
    "PeriodicMerits":   2,
    # CAPI / external service health
    # Frontier's CAPI refresh token is valid for ~30 days.  When it expires,
    # all CAPI features stop working until the user re-runs the OAuth flow.
    # Default level 3 so it pings Discord and lands in the Alerts pane.
    "CapiAuthRequired": 3,
}


# ── Config file resolution ────────────────────────────────────────────────────
# Priority:
#   1. User data dir  (~/.local/share/EDLD/config.toml)
#   2. Repo-adjacent  (same dir as edld.py)   — dev / legacy fallback

def resolve_config_path(script_path: Path) -> Path | None:
    """Return the first existing config.toml candidate, or None."""
    candidates = [
        EDLD_DATA_DIR / "config.toml",
        script_path.parent / "config.toml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None



def load_config_file(config_path: Path) -> dict:
    """Read and parse a TOML config file.  Calls sys.exit on decode error."""
    with open(config_path, mode="rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            print(f"Config decode error: {e}")
            sys.exit(1)


# ── Setting resolution ────────────────────────────────────────────────────────

def _safe_section(d: dict, key: str) -> dict:
    """Return d[key] if it is a dict, else {}. Prevents crashes when a config
    key exists but holds a scalar value instead of a nested table."""
    v = d.get(key)
    return v if isinstance(v, dict) else {}


def load_setting(
    config: dict,
    config_profile: str | None,
    category: str,
    defaults: dict,
    warn_missing: bool = True,
) -> dict:
    """Resolve a settings block with profile → global → default fallback.

    Resolution order per key:
      1. config[config_profile][category][key]   (if profile active)
      2. config[category][key]
      3. defaults[key]
    """
    settings = {}

    # Pre-extract sections once so the loop is clean and type-safe.
    # _safe_section guards against any level being a non-dict value.
    profile_section: dict = _safe_section(config, config_profile) if config_profile else {}
    profile_cat:     dict = _safe_section(profile_section, category)
    global_cat:      dict = _safe_section(config, category)

    for key in defaults:
        value = None

        if profile_cat.get(key) is not None:
            value = profile_cat[key]
        elif global_cat.get(key) is not None:
            value = global_cat[key]
        else:
            value = defaults[key]
            if warn_missing:
                print(
                    f"{_WARNING} Config '{category}' -> '{key}' not found "
                    f"(using default: {defaults[key]})"
                )

        if type(value) != type(defaults[key]):
            print(
                f"{_WARNING} Config '{category}' -> '{key}' expected type "
                f"{type(defaults[key]).__name__} but got "
                f"{type(value).__name__} "
                f"(using default: {defaults[key]})"
            )
            value = defaults[key]

        settings[key] = value

    return settings


def pcfg(config: dict, config_profile: str | None, key: str, default=False):
    """Read a key from the active profile only, never from global config.

    These keys are profile-gated by design — they are never read from global config.
    """
    if config_profile:
        v = _safe_section(config, config_profile).get(key)
        if v is not None:
            return v
    return default


# ── ConfigManager ─────────────────────────────────────────────────────────────

class ConfigManager:
    """Holds live config state and supports hot-reload.

    Instantiated once in edld.py after initial load.  Passed into CoreAPI
    so all components access config through a single object.
    """

    def __init__(
        self,
        config: dict,
        config_path: Path,
        config_profile: str | None,
    ):
        self.config         = config
        self.config_path    = config_path
        self.config_profile = config_profile
        self._mtime         = config_path.stat().st_mtime

        # Resolved setting dicts — refreshed on hot-reload
        self.app_settings  = {}
        self.discord_cfg   = {}
        self.notify_levels = {}
        self.ui_cfg        = {}
        self.capi_cfg         = {}
        self.colonisation_cfg = {}
        self._resolve_all(warn=True)

    def _resolve_all(self, warn: bool = False):
        self.app_settings  = self.load_setting("Settings",  CFG_DEFAULTS_SETTINGS, warn)
        self.app_settings.update(
            self.load_setting("Settings", CFG_DEFAULTS_EXTRA, False)
        )
        self.discord_cfg   = self.load_setting("Discord",   CFG_DEFAULTS_DISCORD,  warn)
        self.notify_levels = self.load_setting("LogLevels", CFG_DEFAULTS_NOTIFY,   warn)
        self.ui_cfg        = self.load_setting("UI",        CFG_DEFAULTS_UI,       False)
        self.eddn_cfg      = self.load_setting("EDDN",      CFG_DEFAULTS_EDDN,     False)
        self.edsm_cfg      = self.load_setting("EDSM",      CFG_DEFAULTS_EDSM,     False)
        self.edastro_cfg   = self.load_setting("EDAstro",   CFG_DEFAULTS_EDASTRO,  False)
        self.inara_cfg     = self.load_setting("Inara",        CFG_DEFAULTS_INARA,        False)
        self.capi_cfg      = self.load_setting("CAPI",         CFG_DEFAULTS_CAPI,         False)
        self.colonisation_cfg = self.load_setting("Colonisation", CFG_DEFAULTS_COLONISATION, False)


    def save(self) -> None:
        """Write current resolved config sections back to config.toml.

        Writes into the global config sections (no profile nesting) which is
        the canonical flat format.  If a profile was active, the resolved
        values already incorporate it, so we write them to the global level
        to make the change permanent regardless of which profile is loaded.
        """
        d = dict(self.config)
        # Remove any existing section then write the resolved dict.
        # This preserves sections we don't own (e.g. EDDN, EDSM, CAPI).
        d["Settings"]  = dict(self.app_settings)
        d["LogLevels"] = dict(self.notify_levels)
        d["UI"]        = dict(self.ui_cfg)
        # Discord is not exposed in the prefs panel yet;
        # preserve whatever was loaded so we don't lose webhook URLs.
        if self.discord_cfg:
            d["Discord"] = dict(self.discord_cfg)
        self.config_path.write_text(config_to_toml(d), encoding="utf-8")
        try:
            self._mtime = self.config_path.stat().st_mtime
        except OSError:
            pass
        # Re-resolve so in-memory state matches what was written
        self._resolve_all(warn=False)


    def load_setting(
        self,
        category: str,
        defaults: dict,
        warn_missing: bool = True,
    ) -> dict:
        """Convenience wrapper using stored config and profile."""
        return load_setting(
            self.config,
            self.config_profile,
            category,
            defaults,
            warn_missing,
        )

    def pcfg(self, key: str, default=False):
        """Profile-gated key lookup."""
        return pcfg(self.config, self.config_profile, key, default)

    def refresh(self, terminal_print: bool = True) -> bool:
        """Re-read config.toml if modified.  Returns True if reloaded."""
        try:
            new_mtime = self.config_path.stat().st_mtime
        except OSError:
            return False

        if new_mtime <= self._mtime:
            return False

        try:
            self.config = load_config_file(self.config_path)
        except SystemExit:
            return False

        self._mtime = new_mtime
        self._resolve_all(warn=False)

        if terminal_print:
            # Deferred import avoids circular dependency at module load time
            from core.emit import Terminal
            print(f"{Terminal.YELL}Config reloaded.{Terminal.END}")

        return True
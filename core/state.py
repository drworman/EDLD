"""
core/state.py — Runtime state containers, constants, and session persistence.

No imports from other EDLD core modules — this is the bottom of the
dependency stack.  Everything else imports from here.

In-game reference data (ship names, module types, rank tables, etc.) now
lives in the ``data/`` package.  All names are re-exported from this module
so existing imports throughout the codebase continue to work unchanged.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


# ── Program identity ──────────────────────────────────────────────────────────

PROGRAM = "ED Linux Dash"
DESC    = "Continuous monitoring of Elite Dangerous AFK sessions."
AUTHOR  = "CMDR CALURSUS"
VERSION = (Path(__file__).parent / "version").read_text().strip()
GITHUB_REPO = "drworman/EDLD"
DEBUG_MODE  = False


# ── User data directory ───────────────────────────────────────────────────────
# Linux: ~/.local/share/EDLD/  (symlinked from ~/.config/EDLD)

def _user_data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "EDLD"
    d.mkdir(parents=True, exist_ok=True)
    config_link = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "EDLD"
    if not config_link.exists() and not config_link.is_symlink():
        try:
            config_link.symlink_to(d)
        except OSError:
            pass
    return d


EDLD_DATA_DIR: Path = _user_data_dir()

# ── Per-commander data directory ──────────────────────────────────────────────

_LAST_FID_FILE: Path = EDLD_DATA_DIR / "last_fid.json"
_active_fid: str     = ""


def set_active_fid(fid: str) -> None:
    """Set the active commander FID and persist it for next-startup fast-path."""
    global _active_fid
    if not fid:
        return
    _active_fid = fid
    cmdr_data_dir().mkdir(parents=True, exist_ok=True)
    try:
        import json as _json
        tmp = _LAST_FID_FILE.with_suffix(".tmp")
        tmp.write_text(_json.dumps({"fid": fid}), encoding="utf-8")
        tmp.replace(_LAST_FID_FILE)
    except OSError:
        pass


def get_last_fid() -> str:
    """Return the FID from last_fid.json, or '' if absent."""
    try:
        import json as _json
        return _json.loads(_LAST_FID_FILE.read_text(encoding="utf-8")).get("fid", "")
    except Exception:
        return ""


def cmdr_data_dir() -> Path:
    """Return the per-commander data directory, creating it if needed.

    Falls back to EDLD_DATA_DIR / "commanders" / "unknown" until FID is set.
    All commander-specific persistent data (plugins, layout, catalog, etc.)
    lives here.
    """
    fid = _active_fid or "unknown"
    p = EDLD_DATA_DIR / "commanders" / fid
    p.mkdir(parents=True, exist_ok=True)
    return p


STATE_FILE: Path = EDLD_DATA_DIR / "session_state.json"


# ── Numeric / display constants ───────────────────────────────────────────────

MAX_DUPLICATES       = 5
FUEL_WARN_THRESHOLD  = 0.2   # 20 %
FUEL_CRIT_THRESHOLD  = 0.1   # 10 %
RECENT_KILL_WINDOW   = 10
SESSION_GAP_MINUTES  = 15
LABEL_UNKNOWN        = "[Unknown]"
PATTERN_JOURNAL      = r"^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$"
PATTERN_WEBHOOK = r"^https:\/\/(?:canary\.|ptb\.)?discord(?:app)?\.com\/api\/webhooks\/\d+/[\w-]+$"

PIRATE_NOATTACK_MSGS = [
    "$Pirate_ThreatTooHigh",
    "$Pirate_NotEnoughCargo",
    "$Pirate_OnNoCargoFound",
]


# ── In-game reference data — imported from data/ package ─────────────────────
# All names are re-exported so existing ``from core.state import X`` calls
# throughout the codebase continue to work without modification.

from data.ships import (                          # noqa: E402
    SHIP_NAME_MAP,
    FIGHTER_TYPE_NAMES,
    FIGHTER_LOADOUT_NAMES,
    normalise_ship_name,
    resolve_fighter_name,
)

# Backward-compat alias used by some older callers
_SHIP_NAMES = SHIP_NAME_MAP

from data.ranks import (                          # noqa: E402
    RANK_NAMES,
    RANK_NAMES_TRADE,
    RANK_NAMES_EXPLORE,
    RANK_NAMES_CQC,
    RANK_NAMES_SOLDIER,
    RANK_NAMES_EXOBIO,
    RANK_NAMES_FEDERATION,
    RANK_NAMES_EMPIRE,
    CAPI_RANK_SKILLS,
)


class SessionData:
    def __init__(self):
        self.reset()

    def reset(self):
        self.recent_inbound_scans  = []
        self.recent_outbound_scans = []
        self.last_kill_time        = 0
        self.kill_interval_total   = 0
        self.recent_kill_times     = []
        self.inbound_scan_count    = 0
        self.kills                 = 0
        self.credit_total          = 0
        self.faction_tally         = {}
        self.merits                = 0
        self.last_security_ship    = ""
        self.low_cargo_count       = 0
        self.fuel_check_time       = 0
        self.fuel_check_level      = 0
        self.pending_merit_events  = 0


# ── Monitor state (persistent across the session, reflects game state) ────────

class MonitorState:
    def __init__(self):
        self.session_start_time      = None
        self.alerted_kill_rate       = None
        self.fuel_tank_size          = 64
        self.fuel_current:   "float | None" = None
        self.fuel_burn_rate: "float | None" = None
        self.reward_type             = "credit_total"
        self.fighter_integrity       = 0
        self.logged                  = 0
        self.lines                   = 0
        self.missions                = False
        self.active_missions         = []
        self.missions_complete       = 0
        self.prev_event              = None
        self.event_time              = None
        self.last_dup_key            = ""
        self.dup_count               = 1
        self.dup_suppressed          = False
        self.in_preload              = True
        self.pilot_name              = None
        self.pilot_fid               = ""
        self.pilot_squadron_name     = ""
        self.cargo_target_market     = {}
        self.cargo_target_market_name= ""
        self.cargo_target_market_ts  = 0.0
        self.slf_capi_type           = None
        self.pilot_squadron_tag      = ""
        self.pilot_squadron_rank     = ""
        self.pilot_ship              = None
        self.pilot_rank              = None
        self.pilot_rank_progress     = None
        self.pilot_mode              = None
        self.pilot_location          = None
        self.pilot_system            = None
        self.pilot_star_pos: list | None = None
        self.pilot_body              = None
        self.last_rate_check         = None
        self.last_kill_mono: float   = 0.0
        self.last_periodic_summary   = None
        self.last_rate_alert         = None
        self.last_offline_alert      = None
        self.offline_since_mono      = None
        self.in_game                 = False
        self.in_supercruise          = False
        self.last_sc_exit_mono       = None
        self.last_shutdown_time      = None
        self.mission_value_map       = {}
        self.mission_detail_map      = {}
        self.stack_value             = 0
        self.has_fighter_bay         = False
        self.mission_target_faction_map = {}

        # SLF state
        self.slf_deployed  = False
        self.slf_docked    = True
        self.slf_hull      = 100
        self.slf_orders    = None
        self.slf_loadout   = None

        # Powerplay state
        self.pp_power        = None
        self.pp_rank         = None
        self.pp_merits_total = None

        # Ship identity (from Loadout)
        self.ship_name  = None
        self.ship_ident = None

        # Ship hull and shields
        self.ship_hull              = 100
        self.ship_shields           = True
        self.ship_shields_recharging = False

        # ── Vehicle / on-foot state ────────────────────────────────────────
        self.vessel_mode:     str  = "ship"
        self.srv_type:        str  = ""
        self.srv_hull:        int  = 100
        self.suit_name:       str  = ""
        self.suit_loadout:    str  = ""
        self.suit_shields:    bool = True

        # Commander in SLF
        self.cmdr_in_slf = False

        # Live surface position (Status.json, Odyssey) — for on-foot exobiology aids
        self.surface_latitude:  "float | None" = None
        self.surface_longitude: "float | None" = None
        self.surface_heading:   "float | None" = None
        self.surface_altitude:  "float | None" = None
        self.planet_radius:     "float | None" = None   # metres
        self.on_foot:           bool           = False
        self.current_body_name: str            = ""

        # NPC Crew state
        self.crew_name         = None
        self.crew_rank         = None
        self.crew_hire_time    = None
        self.crew_total_paid   = None
        self.crew_paid_complete = False
        self.crew_active       = False

        # SLF type and stock
        self.slf_type            = None
        self.slf_stock_total     = 0
        self.slf_destroyed_count = 0

        # CAPI raw store and poll timestamps
        self.capi_raw:        dict = {}
        self.capi_last_poll:  dict = {}

        # CAPI-derived fields
        self.capi_ranks:           dict | None = None
        self.capi_progress:        dict | None = None
        self.capi_reputation:      dict | None = None
        self.capi_engineer_ranks:  list | None = None
        self.capi_statistics:      dict | None = None
        self.capi_permits:         list | None = None
        self.capi_ship_health:     dict | None = None
        self.capi_ship_value:      dict | None = None
        self.capi_loadout:         dict | None = None
        self.capi_market:          dict | None = None
        self.capi_shipyard:        dict | None = None
        self.capi_community_goals: list | None = None
        self.capi_debt:            float| None = None

        # Assets (fleet, wallet)
        self.assets_balance:       float| None = None
        self.assets_total_wealth:  float| None = None
        self.assets_current_ship:  dict | None = None
        self.assets_stored_ships:  list        = []
        self.assets_stored_modules:list        = []
        self.assets_carrier:       dict | None = None
        self.assets_fc_materials:  list        = []

        # At-risk holdings
        self.holdings_bounties:    int         = 0
        self.holdings_bonds:       int         = 0
        self.holdings_trade:       int         = 0
        self.holdings_cartography: int         = 0
        self.holdings_exobiology:  int         = 0

        # Cargo
        self.cargo_capacity:       int         = 0
        self.cargo_items:          dict        = {}
        self.cargo_market_info:    dict        = {}
        self.cargo_mean_prices:    dict        = {}

        # Engineering materials
        self.materials_raw:          dict = {}
        self.materials_manufactured: dict = {}
        self.materials_encoded:      dict = {}
        self.engineering_locker:     dict = {}
        self.engineering_backpack:   dict = {}

        # Navigation
        self.nav_route:              list = []

        # Pilot extended
        self.pilot_minor_reputation: dict | None = None
        self.pilot_reputation:       dict | None = None
        self.pilot_engineer_ranks:   list | None = None

    def sessionstart(self, active_session: SessionData, reset: bool = False):
        if not self.session_start_time or reset:
            self.session_start_time = self.event_time
            if reset or not active_session.kills:
                active_session.reset()
            self.alerted_kill_rate     = None
            self.last_rate_check       = time.monotonic()
            if reset or self.last_periodic_summary is None:
                self.last_periodic_summary = time.monotonic()
            self.last_rate_alert       = None
            global _session_start_iso
            _session_start_iso = (
                self.session_start_time.isoformat()
                if self.session_start_time else None
            )

    def sessionend(self):
        if self.session_start_time:
            self.session_start_time = None

    def reset_missions(self):
        """Clear mission state so a new game session bootstraps cleanly."""
        self.missions                   = False
        self.active_missions            = []
        self.missions_complete          = 0
        self.stack_value                = 0
        self.mission_value_map          = {}
        self.mission_detail_map         = {}
        self.mission_target_faction_map = {}


# ── Session state persistence ─────────────────────────────────────────────────

_session_start_iso: str | None = None


def save_session_state(journal_path: Path, active_session: SessionData) -> None:
    """Write active session counters to STATE_FILE so they can be restored
    on the next startup if the same journal is still active. Called on
    Ctrl+C exit; consumed by ``load_session_state`` at startup."""
    try:
        payload = {
            "journal":             str(journal_path),
            "session_start_time":  _session_start_iso,
            "kills":               active_session.kills,
            "credit_total":        active_session.credit_total,
            "merits":              active_session.merits,
            "faction_tally":       active_session.faction_tally,
            "kill_interval_total": active_session.kill_interval_total,
            "recent_kill_times":   [t.isoformat() for t in active_session.recent_kill_times],
            "inbound_scan_count":  active_session.inbound_scan_count,
            "low_cargo_count":     active_session.low_cargo_count,
        }
        sf = cmdr_data_dir() / "session_state.json"
        sf.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_session_state(
    journal_path: Path,
    active_session: SessionData,
) -> None:
    """Restore session counters from STATE_FILE if it matches journal_path."""
    global _session_start_iso
    try:
        sf = cmdr_data_dir() / "session_state.json"
        if not sf.exists():
            return
        payload = json.loads(sf.read_text(encoding="utf-8"))
        if payload.get("journal") != str(journal_path):
            return
        active_session.kills               = int(payload.get("kills", 0))
        active_session.credit_total        = int(payload.get("credit_total", 0))
        active_session.merits              = int(payload.get("merits", 0))
        active_session.faction_tally       = dict(payload.get("faction_tally", {}))
        active_session.kill_interval_total = float(payload.get("kill_interval_total", 0))
        active_session.inbound_scan_count  = int(payload.get("inbound_scan_count", 0))
        active_session.low_cargo_count     = int(payload.get("low_cargo_count", 0))
        active_session.recent_kill_times   = [
            datetime.fromisoformat(t)
            for t in payload.get("recent_kill_times", []) if t
        ]
        _session_start_iso = payload.get("session_start_time")
        sf.unlink(missing_ok=True)
    except Exception:
        pass

"""
components/ksw.py — Session management plugin.

Auto-terminates the Elite Dangerous game process when configured in-game
conditions are met (SLF destroyed, low fuel, low hull).  Termination can be
local (psutil) or remote over SSH for thin-client setups.

Hard-gated to Solo mode: flush_session() refuses to act unless the current
game mode is Solo, so a session is never terminated in Open or Private Group.
pilot_mode is populated from LoadGame.GameMode by the commander plugin.

Exposes via CoreAPI.plugin_call("ksw", ...):
  flush_session(reason="")  — terminate the game process (Solo mode only)
  check_ready()             — return bool: True when enabled in config

Config keys (resolved from [SessionMgmt]; profile → global → default):
  Enabled                  bool   Master enable.  All checks are no-ops without this.
  QuitOnSLFDead            bool   Quit when the SLF is destroyed.
  QuitOnLowFuel            bool   Quit when fuel % falls at or below threshold.
  QuitOnLowFuelPercent     int    Fuel % threshold (default 20).
  QuitOnLowFuelMinutes     int    Quit when estimated fuel remaining <= N minutes
                                  AND fuel % is also at or below QuitOnLowFuelPercent.
                                  Both conditions must be true.  0 or absent = disabled.
  QuitFuelSCGraceSeconds   int    Seconds after exiting supercruise before fuel kills
                                  are re-armed (default 60).  Set 0 to disable.
  QuitOnLowHull            bool   Quit when hull integrity falls at or below threshold.
  QuitOnLowHullThreshold   int    Hull % threshold (default 10).

Remote kill (thin-client / remote profile mode):
  RemoteKillHost    str    SSH host of the gaming machine (e.g. "gaming-pc" or IP).
                           When set, flush_session() kills the game over SSH instead
                           of using psutil on the local machine.
  RemoteKillUser    str    SSH username to use. Defaults to current OS user if absent.
                           Key auth must be configured — no password prompt is issued.
"""

import subprocess as _sp
import time

import psutil

from core.plugin_loader import BasePlugin


# -- Config --------------------------------------------------------------------

CFG_DEFAULTS = {
    "Enabled":                False,   # master enable
    "QuitOnSLFDead":          False,
    "QuitOnLowFuel":          False,
    "QuitOnLowFuelPercent":   20,
    "QuitOnLowFuelMinutes":   0,
    "QuitFuelSCGraceSeconds": 60,
    "QuitOnLowHull":          False,
    "QuitOnLowHullThreshold": 10,
    "QuitOnNoKillsMinutes":   0,       # evaluated by the combat plugin
    "RemoteKillHost":         "",
    "RemoteKillUser":         "",
}


# -- Process termination -------------------------------------------------------

# On Windows the game process is EliteDangerous64.exe directly.
# On Linux under Steam/Proton the host process is wine64-preloader (or similar)
# but EliteDangerous64.exe still appears verbatim in its cmdline, so the same
# pattern matches via the cmdline search in _release_handle.
_GAME_PATTERNS = [
    ("EliteDangerous64.exe", "Elite Dangerous"),
]


def _release_handle_local(pattern: str, description: str) -> None:
    """Kill the game process on the local machine using psutil."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if any(pattern.lower() in str(x).lower() for x in cmdline):
                print(f"Stopping {description} (PID {proc.pid})...")
                proc.terminate()
        except Exception:
            continue
    for _ in range(5):
        still_running = False
        for proc in psutil.process_iter(["cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                if any(pattern.lower() in str(x).lower() for x in cmdline):
                    still_running = True
                    break
            except Exception:
                continue
        if not still_running:
            print(f"{description} stopped.")
            return
        time.sleep(1)
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if any(pattern.lower() in str(x).lower() for x in cmdline):
                print(f"{description} did not stop gracefully. Forcing termination...")
                proc.kill()
        except Exception:
            continue


def _release_handle_remote(pattern: str, description: str,
                            host: str, user: str | None) -> None:
    """Kill the game process on a remote machine over SSH.

    Requires key-based SSH auth to be pre-configured (no password prompt).
    Uses tasklist/taskkill on Windows-hosted games, pkill on Linux.
    The remote OS is detected by attempting a Windows-style check first;
    if it fails we fall back to the Linux/pkill path.
    """
    dest = f"{user}@{host}" if user else host

    # Try Windows path first (game runs under Proton or native Windows)
    win_cmd = [
        "ssh", "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        dest,
        f'taskkill /f /im "{pattern}"',
    ]
    result = _sp.run(win_cmd, capture_output=True, timeout=10)
    if result.returncode == 0:
        print(f"[ksw] Remote kill sent to {host} (Windows/taskkill): {description}")
        return

    # Fall back to Linux pkill
    linux_cmd = [
        "ssh", "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        dest,
        f"pkill -f '{pattern}'",
    ]
    result = _sp.run(linux_cmd, capture_output=True, timeout=10)
    if result.returncode in (0, 1):
        print(f"[ksw] Remote kill sent to {host} (Linux/pkill): {description}")
    else:
        stderr = result.stderr.decode(errors="replace").strip()
        print(f"[ksw] Remote kill failed on {host}: {stderr or 'unknown error'}")


def _release_handle(pattern: str, description: str,
                     remote_host: str | None = None,
                     remote_user: str | None = None) -> None:
    """Dispatch to local or remote kill depending on configuration."""
    if remote_host:
        _release_handle_remote(pattern, description, remote_host, remote_user)
    else:
        _release_handle_local(pattern, description)



# -- Plugin --------------------------------------------------------------------

class KswPlugin(BasePlugin):
    PLUGIN_NAME         = "ksw"
    PLUGIN_DISPLAY      = "Session Management"
    PLUGIN_VERSION      = "1.5"
    PLUGIN_DESCRIPTION  = ""
    SUBSCRIBED_EVENTS   = [
        "ReservoirReplenished",   # fuel % and fuel time-remaining checks
        "FighterDestroyed",       # SLF destroyed check
        "HullDamage",             # hull % check
        "SupercruiseEntry",       # supercruise state tracking for fuel exclusion
        "SupercruiseExit",        # supercruise state tracking for fuel exclusion
        "FSDJump",                # also exits supercruise
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        _d = self.storage.read_json("data.json")
        self._flush_count       = _d.get("flush_count", 0)
        self._last_flush_time   = _d.get("last_flush_time", None)
        self._last_flush_reason = _d.get("last_flush_reason", "")
        # Runtime toggle — the GUI block can set this to False to disable
        # session management without changing config.toml.
        self._session_enabled = True
        # Supercruise exclusion tracking for fuel kills.
        # Maintained locally so the check doesn't depend on plugin dispatch order.
        self._in_supercruise:    bool        = False
        self._last_sc_exit_mono: float | None = None

    def on_event(self, event: dict, state) -> None:
        if state.in_preload:
            return
        s = self.core.load_setting("SessionMgmt", CFG_DEFAULTS, warn=False)
        if not s["Enabled"]:
            return
        if not self._session_enabled:
            return

        ev = event.get("event")

        # -- Supercruise state tracking ----------------------------------------
        # Track locally so the fuel exclusion check doesn't depend on the order
        # in which plugins dispatch the same event.
        if ev == "SupercruiseEntry":
            self._in_supercruise = True
            return

        elif ev in ("SupercruiseExit", "FSDJump"):
            self._in_supercruise    = False
            self._last_sc_exit_mono = time.monotonic()
            return

        # -- Solo-mode gate ----------------------------------------------------
        # Kill criteria are no-ops outside Solo mode.
        # pilot_mode is populated from LoadGame.GameMode by the commander plugin.
        # Supercruise tracking above runs regardless of mode so that the grace
        # period is accurate when the player does enter Solo.
        if (getattr(state, "pilot_mode", None) or "").lower() != "solo":
            return

        # -- SLF destroyed -----------------------------------------------------
        if ev == "FighterDestroyed":
            if s["QuitOnSLFDead"]:
                self.flush_session("SLF destroyed")

        # -- Hull integrity ----------------------------------------------------
        elif ev == "HullDamage":
            if not s["QuitOnLowHull"]:
                return
            if not (event.get("PlayerPilot") and not event.get("Fighter")):
                return
            hull_pct  = round(event["Health"] * 100)
            threshold = s["QuitOnLowHullThreshold"]
            if hull_pct <= threshold:
                self.flush_session(f"hull at {hull_pct}% (threshold {threshold}%)")

        # -- Fuel --------------------------------------------------------------
        elif ev == "ReservoirReplenished":
            tank = getattr(state, "fuel_tank_size", 0)
            if not tank:
                return

            fuel_main = event["FuelMain"]
            fuel_pct  = round((fuel_main / tank) * 100)

            # Supercruise exclusion.
            # No fuel kills while in supercruise or within the post-SC grace
            # period.  The player cannot refuel in SC; let them exit normally.
            # If they run out of fuel in SC that is their own decision.
            SC_GRACE_SECONDS = s["QuitFuelSCGraceSeconds"]
            now      = time.monotonic()
            in_sc    = self._in_supercruise or getattr(state, "in_supercruise", False)
            sc_recently = (
                self._last_sc_exit_mono is not None
                and (now - self._last_sc_exit_mono) < SC_GRACE_SECONDS
            )
            if in_sc or sc_recently:
                return

            if not s["QuitOnLowFuel"]:
                return

            pct_limit     = s["QuitOnLowFuelPercent"]
            minutes_limit = s["QuitOnLowFuelMinutes"]

            # Percentage threshold is mandatory for any fuel kill.
            if fuel_pct > pct_limit:
                return

            # If a minutes threshold is also configured, require time-remaining
            # to be low as well — makes the trigger more conservative and
            # protects against firing on small tanks that spend a lot of time
            # at low % even when burn time is plentiful.  Time-remaining alone
            # is intentionally not sufficient: too sensitive to transient burn
            # rate spikes from fuel scooping and system entry.
            if minutes_limit:
                burn_rate = getattr(state, "fuel_burn_rate", None)
                if not (burn_rate and burn_rate > 0):
                    return  # no burn rate yet; re-evaluate on next replenish
                minutes_remaining = (fuel_main / burn_rate) * 60
                if minutes_remaining > minutes_limit:
                    return
                self.flush_session(
                    f"fuel ~{minutes_remaining:.0f} min remaining "
                    f"and at {fuel_pct}% "
                    f"(thresholds: {minutes_limit} min, {pct_limit}%)"
                )
            else:
                self.flush_session(
                    f"fuel at {fuel_pct}% (threshold {pct_limit}%)"
                )

    # -- Public interface ------------------------------------------------------

    def flush_session(self, reason: str = "") -> None:
        """Terminate the game process — Solo mode only.

        Hard gate: refuses to act unless the current game mode is Solo, so no
        session is ever terminated in Open or Private Group, regardless of how
        this is reached (event-driven or a manual interface call).
        """
        if (getattr(self.core.state, "pilot_mode", None) or "").lower() != "solo":
            return
        if reason:
            print(f"[ksw] flush_session: {reason}")

        # Emit loglevel-3 so the user receives a Discord ping on every activation.
        msg = f"Session terminated: {reason}" if reason else "Session terminated"
        try:
            self.core.emitter.emit(
                msg_term=f"[session] {msg}",
                msg_discord=f"🛑 **{msg}**",
                emoji="🛑",
                sigil="!! TERM",
                timestamp=self.core.state.event_time,
                loglevel=3,
            )
        except Exception:
            pass

        s           = self.core.load_setting("SessionMgmt", CFG_DEFAULTS, warn=False)
        remote_host = s["RemoteKillHost"] or None
        remote_user = s["RemoteKillUser"] or None
        for pattern, description in _GAME_PATTERNS:
            _release_handle(pattern, description,
                            remote_host=remote_host, remote_user=remote_user)
        self._flush_count += 1
        import datetime as _dt
        self._last_flush_time   = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._last_flush_reason = reason or "Manual"
        try:
            self.storage.write_json({
                "flush_count":       self._flush_count,
                "last_flush_time":   self._last_flush_time,
                "last_flush_reason": self._last_flush_reason,
            }, "data.json")
        except Exception:
            pass

        # Push to alerts block so the termination is visible in the dashboard
        try:
            alert_text = f"Session terminated: {reason}" if reason else "Session terminated"
            self.core.plugin_call("alerts", "_push", "🛑", alert_text)
        except Exception:
            pass

    def check_ready(self) -> bool:
        """Return True if session management is enabled in config."""
        return bool(self.core.load_setting("SessionMgmt", CFG_DEFAULTS, warn=False)["Enabled"])


    # ── TUI integration ───────────────────────────────────────────────────────

    def register_tui_app(self, app) -> None:
        """Push the initial KSW status to the Header sub_title."""
        self._push_tui_status()

    def _tui_toggle(self, app) -> None:
        self._session_enabled = not self._session_enabled
        label = "enabled" if self._session_enabled else "disabled"
        try:
            app.notify(f"Session management {label}", timeout=3)
        except Exception:
            pass
        self._push_tui_status()

    def _push_tui_status(self, app=None) -> None:
        """Push armed/idle status to the app Header sub_title via gui_queue."""
        try:
            cfg_on = bool(self.core.load_setting("SessionMgmt", CFG_DEFAULTS, warn=False)["Enabled"])
            armed  = cfg_on and self._session_enabled
            symbol = "✕" if armed else "□"
            gq = self.core.gui_queue
            if gq:
                gq.put(("ksw_status", symbol))
        except Exception:
            pass

    def tui_preferences_tab(self) -> tuple | None:
        """Return (tab_id, tab_label, composer) for injection into TUI prefs."""
        s = self.core.load_setting("SessionMgmt", CFG_DEFAULTS, warn=False)

        def _compose():
            from textual.widgets import Label, Select, Input
            from textual.containers import Horizontal

            enabled  = bool(s["Enabled"])
            slf_dead = bool(s["QuitOnSLFDead"])
            low_fuel = bool(s["QuitOnLowFuel"])
            fuel_pct = int(s["QuitOnLowFuelPercent"])
            low_hull = bool(s["QuitOnLowHull"])
            hull_thr = int(s["QuitOnLowHullThreshold"])
            bool_opts = [("Off", "false"), ("On", "true")]

            yield Label("MASTER ENABLE  ⚠", classes="pref-section")
            with Horizontal(classes="pref-row"):
                yield Label("Session management", classes="key")
                yield Select(bool_opts, value="true" if enabled else "false",
                             id="ksw-master", classes="pref-bool-sel", allow_blank=False)
            yield Label("TRIGGERS", classes="pref-section")
            with Horizontal(classes="pref-row"):
                yield Label("Quit on SLF destroyed", classes="key")
                yield Select(bool_opts, value="true" if slf_dead else "false",
                             id="ksw-slf", classes="pref-bool-sel", allow_blank=False)
            with Horizontal(classes="pref-row"):
                yield Label("Quit on low fuel", classes="key")
                yield Select(bool_opts, value="true" if low_fuel else "false",
                             id="ksw-fuel", classes="pref-bool-sel", allow_blank=False)
            with Horizontal(classes="pref-row"):
                yield Label("Fuel threshold (%)", classes="key")
                yield Input(value=str(fuel_pct), id="ksw-fuel-pct", classes="pref-input")
            with Horizontal(classes="pref-row"):
                yield Label("Quit on low hull", classes="key")
                yield Select(bool_opts, value="true" if low_hull else "false",
                             id="ksw-hull", classes="pref-bool-sel", allow_blank=False)
            with Horizontal(classes="pref-row"):
                yield Label("Hull threshold (%)", classes="key")
                yield Input(value=str(hull_thr), id="ksw-hull-thr", classes="pref-input")

        return ("pref-tab-ksw", "Session Mgmt", _compose)


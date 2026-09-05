"""
components/navigation.py — route store and clipboard route-follower.

Two jobs:

1. **Route store.**  Routes plotted inside EDLD (Spansh neutron, EDSM FSD,
   Spansh fleet carrier) are converted to the game's own ``NavRoute.json``
   shape and persisted to ``<cmdr>/data/navigation.route.json``.  Keeping the
   game's schema means anything that can already read a NavRoute can read
   ours, and the follower below needs exactly one code path for both.

2. **Route follower.**  When enabled, arriving in a system copies the *next*
   system on the route to the clipboard, ready to paste into the galaxy map.
   That is the whole workflow for neutron jumping and carrier hauling, where
   every leg has to be plotted by hand.

Which route is followed
-----------------------
Whichever was created most recently — the EDLD route's stored timestamp
against ``NavRoute.json``'s.  A neutron route plotted in EDLD is the master
waypoint list, while the in-game route only ever holds the current leg, so
EDLD normally wins; but plotting fresh in-game then correctly takes over
instead of being shadowed by a week-old Spansh route.

Hyperspace awareness
--------------------
``StartJump`` with ``JumpType: "Hyperspace"`` names the system being jumped
to, and once that fires the jump cannot be cancelled.  The commander's
effective position is therefore the destination, not the system they are
leaving.  Copy Next uses that so pressing it mid-tunnel gives the system
*after* the one you are arriving at, not the one you are arriving at.

Clearing
--------
"Clear Route" wipes EDLD's stored route and suppresses the current
``NavRoute.json`` by recording a signature of it.  The game's file is left
alone: EDMC and other tools read it, and the game rewrites it on the next
plot anyway.  When NavRoute.json next changes, the signature stops matching
and following resumes automatically.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from core.plugin_loader import BasePlugin

#: Journal events that mean "the commander is now somewhere new".
_ARRIVAL_EVENTS = ("FSDJump", "CarrierJump", "Location")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(name) -> str:
    return str(name or "").strip().casefold()


def read_nav_route_file(journal_dir) -> dict | None:
    """Read the game's NavRoute.json, or None if absent/empty/unreadable."""
    try:
        path = Path(journal_dir) / "NavRoute.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not (data.get("Route") or []):
        return None
    return data


def route_signature(doc: dict | None) -> str:
    """Stable identity for a route document.

    Timestamp plus endpoints plus length — enough that re-plotting the same
    trip produces a different signature (the timestamp moves), which is what
    "Clear Route, then plot again" depends on.
    """
    if not doc:
        return ""
    route = doc.get("Route") or []
    if not route:
        return ""
    first = route[0].get("StarSystem", "")
    last = route[-1].get("StarSystem", "")
    return f"{doc.get('timestamp', '')}|{first}|{last}|{len(route)}"


def spansh_result_to_navroute(result: dict, kind: str) -> dict | None:
    """Convert an EDLD-plotted route into the game's NavRoute.json shape.

    Handles all three shapes EDLD produces:

      neutron  Spansh /api/route      → system_jumps[], keys system/x/y/z
      fsd      EDSM greedy router     → system_jumps[], keys system/star_pos
      carrier  Spansh fleetcarrier    → jumps[],        keys name/id64/x/y/z

    Extra per-waypoint detail that the game's schema has no room for
    (fuel, restock, neutron flags) is preserved under an ``EDLD`` key on each
    entry, so the route file stays readable as a NavRoute while keeping
    everything the UI wants to show.
    """
    if not isinstance(result, dict):
        return None
    waypoints = result.get("system_jumps") or result.get("jumps") or []
    if not waypoints:
        return None

    route: list[dict] = []
    for wp in waypoints:
        name = wp.get("system") or wp.get("name") or ""
        if not name:
            continue

        star_pos = wp.get("star_pos")
        if not star_pos:
            x, y, z = wp.get("x"), wp.get("y"), wp.get("z")
            if None not in (x, y, z):
                star_pos = [x, y, z]

        entry: dict = {
            "StarSystem": str(name),
            "SystemAddress": wp.get("id64") or wp.get("system_address") or 0,
            "StarPos": [float(v) for v in star_pos] if star_pos else [0.0, 0.0, 0.0],
            "StarClass": str(wp.get("star_class") or ("N" if wp.get("neutron_star") else "")),
        }

        extra = {k: wp[k] for k in (
            "distance", "distance_jumped", "distance_to_destination",
            "fuel_used", "fuel_in_tank", "must_restock", "restock_amount",
            "tritium_in_market", "has_icy_ring", "is_system_pristine",
            "neutron_star", "must_refuel", "is_supercharged", "jumps",
        ) if k in wp}
        if extra:
            entry["EDLD"] = extra
        route.append(entry)

    if not route:
        return None

    return {
        "timestamp": _utc_iso(),
        "event": "NavRoute",
        "Route": route,
        # EDLD provenance — ignored by anything reading this as a NavRoute.
        "EDLDSource": kind,
    }


class NavigationPlugin(BasePlugin):
    PLUGIN_NAME = "navigation"
    PLUGIN_DISPLAY = "Navigation & Route Follower"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = (
        "Stores routes plotted in EDLD and copies the next system on the "
        "route to the clipboard as you travel."
    )

    SUBSCRIBED_EVENTS = [
        "FSDJump", "CarrierJump", "Location",
        "StartJump", "NavRoute", "NavRouteClear",
    ]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_load(self, core) -> None:
        super().on_load(core)
        s = core.state
        s.nav_follow_enabled = False
        s.nav_follow_source = ""
        s.nav_follow_next = ""
        s.nav_follow_status = ""
        s.nav_transit_to = ""
        s.nav_last_copied = ""

        saved = self.storage.read_json()
        s.nav_follow_enabled = bool(saved.get("follow_enabled", False))
        self._dismissed_sig = str(saved.get("dismissed_journal_sig", ""))

        self._edld_route = self.storage.read_json("route") or None
        if self._edld_route and not (self._edld_route.get("Route") or []):
            self._edld_route = None

        self._refresh_status()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_settings(self) -> None:
        try:
            self.storage.write_json({
                "follow_enabled": bool(self.core.state.nav_follow_enabled),
                "dismissed_journal_sig": self._dismissed_sig,
            })
        except Exception as exc:
            from core import debug as _dbg
            _dbg.info(f"  [Nav] could not persist follower settings: {exc}")

    # ── Route access ──────────────────────────────────────────────────────────

    def _journal_route(self) -> dict | None:
        doc = read_nav_route_file(self.core.journal_dir)
        if doc and route_signature(doc) == self._dismissed_sig:
            return None      # cleared by the user and unchanged since
        return doc

    def active_route(self) -> tuple[list, str]:
        """Return (route entries, source label).

        Source is "edld", "journal", or "" when there is no route.  The more
        recently created of the two wins; see the module docstring.
        """
        edld = self._edld_route
        journal = self._journal_route()

        if edld and journal:
            if str(edld.get("timestamp", "")) >= str(journal.get("timestamp", "")):
                return edld.get("Route") or [], "edld"
            return journal.get("Route") or [], "journal"
        if edld:
            return edld.get("Route") or [], "edld"
        if journal:
            return journal.get("Route") or [], "journal"
        return [], ""

    def store_route(self, result: dict, kind: str) -> bool:
        """Persist an EDLD-plotted route and make it the followed route."""
        doc = spansh_result_to_navroute(result, kind)
        if not doc:
            return False
        self._edld_route = doc
        try:
            self.storage.write_json(doc, "route")
        except Exception as exc:
            from core import debug as _dbg
            _dbg.info(f"  [Nav] could not persist route: {exc}")
        # A freshly plotted route supersedes any earlier dismissal.
        self._dismissed_sig = ""
        self._save_settings()
        self._refresh_status()
        self._notify()
        return True

    def _retire_completed_route(self) -> None:
        """Drop the EDLD route once its final destination has been reached.

        Without this the route outlives the trip: the commander jumps onward,
        is no longer on it, and the footer reports being off a route they
        finished days ago.  Only EDLD's own route is retired — the game's
        NavRoute.json is the game's to manage.
        """
        doc = self._edld_route
        route = (doc or {}).get("Route") or []
        if not route:
            return
        current = self.effective_current_system()
        if not current:
            return
        if _norm(route[-1].get("StarSystem")) != _norm(current):
            return

        self._edld_route = None
        try:
            self.storage.write_json({}, "route")
        except Exception as exc:
            from core import debug as _dbg
            _dbg.info(f"  [Nav] could not retire completed route: {exc}")
        self.core.state.nav_last_copied = ""

    def clear_route(self) -> str:
        """Wipe the EDLD route and suppress the current NavRoute.json."""
        self._edld_route = None
        try:
            self.storage.write_json({}, "route")
        except Exception as exc:
            from core import debug as _dbg
            _dbg.info(f"  [Nav] could not clear stored route: {exc}")

        journal = read_nav_route_file(self.core.journal_dir)
        self._dismissed_sig = route_signature(journal)

        s = self.core.state
        s.nav_follow_next = ""
        s.nav_last_copied = ""
        self._save_settings()
        self._refresh_status()
        self._notify()
        return ("Route cleared — following resumes when a new route is "
                "plotted in EDLD or in game.")

    # ── Follower ──────────────────────────────────────────────────────────────

    def set_follow_enabled(self, enabled: bool) -> None:
        self.core.state.nav_follow_enabled = bool(enabled)
        self._save_settings()
        self._refresh_status()
        self._notify()

    def toggle_follow(self) -> bool:
        self.set_follow_enabled(not self.core.state.nav_follow_enabled)
        return self.core.state.nav_follow_enabled

    def effective_current_system(self) -> str:
        """The system to route from.

        Mid-hyperspace this is the destination, because the jump can no
        longer be cancelled — see the module docstring.
        """
        s = self.core.state
        return (s.nav_transit_to or "").strip() or (s.pilot_system or "").strip()

    @staticmethod
    def _index_of(route: list, system: str) -> int | None:
        target = _norm(system)
        if not target:
            return None
        for i, entry in enumerate(route):
            if _norm(entry.get("StarSystem")) == target:
                return i
        return None

    def next_system(self) -> tuple[str, str]:
        """Return (next system name, reason-if-empty).

        Never raises; an empty name always comes with an explanation the UI
        can show verbatim.
        """
        route, source = self.active_route()
        if not route:
            return "", "No route stored."

        current = self.effective_current_system()
        if not current:
            return "", "Current system unknown."

        idx = self._index_of(route, current)
        if idx is None:
            # Kept short: this renders in a one-row footer that clips.
            return "", f"Off the {source} route"
        if idx >= len(route) - 1:
            return "", "At final destination"
        return str(route[idx + 1].get("StarSystem") or ""), ""

    def copy_next(self) -> tuple[bool, str]:
        """Copy the next system to the clipboard.  Returns (ok, message)."""
        system, why = self.next_system()
        if not system:
            return False, why

        from core import clipboard
        ok, detail = clipboard.copy(system)
        if ok:
            self.core.state.nav_last_copied = system
            self._refresh_status()
            return True, f"Copied {system}"
        return False, f"Could not copy {system} — {detail}"

    # ── Status / notification ─────────────────────────────────────────────────

    def _refresh_status(self) -> None:
        s = self.core.state
        route, source = self.active_route()
        s.nav_follow_source = source

        if not route:
            s.nav_follow_next = ""
            s.nav_follow_status = "No route"
            return

        nxt, why = self.next_system()
        s.nav_follow_next = nxt
        label = {"edld": "EDLD", "journal": "in-game"}.get(source, source)

        if nxt:
            idx = self._index_of(route, self.effective_current_system())
            remaining = len(route) - 1 - (idx if idx is not None else 0)
            s.nav_follow_status = f"{label}: {nxt}  ({remaining} to go)"
        else:
            s.nav_follow_status = f"{label}: {why}"

    def _notify(self) -> None:
        gq = self.core.gui_queue
        if gq:
            gq.put(("plugin_refresh", "navigation"))

    # ── Events ────────────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event")

        if ev == "StartJump":
            # Only a hyperspace jump commits us to a destination; a
            # supercharge/supercruise StartJump does not move systems.
            if event.get("JumpType") == "Hyperspace":
                state.nav_transit_to = str(event.get("StarSystem") or "")
                self._refresh_status()
                self._notify()
            return

        if ev == "NavRouteClear":
            self._refresh_status()
            self._notify()
            return

        if ev == "NavRoute":
            # A newly plotted in-game route is never the one that was
            # dismissed, so drop the suppression.
            self._dismissed_sig = ""
            self._save_settings()
            self._refresh_status()
            self._notify()
            return

        if ev in _ARRIVAL_EVENTS:
            state.nav_transit_to = ""
            self._retire_completed_route()
            self._refresh_status()

            # Replaying history at startup must not touch the clipboard.
            if getattr(state, "in_preload", False):
                return
            if not state.nav_follow_enabled:
                self._notify()
                return

            nxt = state.nav_follow_next
            if nxt and nxt != state.nav_last_copied:
                from core import clipboard
                ok, detail = clipboard.copy(nxt)
                if ok:
                    state.nav_last_copied = nxt
                else:
                    from core import debug as _dbg
                    _dbg.info(f"  [Nav] clipboard copy failed: {detail}")
            self._notify()

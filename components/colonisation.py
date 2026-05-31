"""
components/colonisation.py — Colonisation construction tracking with
Raven Colonial API integration.

Local tracking
──────────────
Watches ColonisationConstructionDepot, ColonisationContribution, CargoDepot,
and related events to maintain a live picture of each active construction
site's resource requirements and delivery progress.  Data is persisted to
plugin storage and survives restarts.

Raven Colonial integration
──────────────────────────
Syncs supply and contribution data to the Raven Colonial server when an API
key is configured ([Colonisation] ApiKey in config.toml).  API calls run on
a background daemon thread via a queue — all journal event handlers return
immediately and never block.

API base: https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net
Auth:
  Construction endpoints — no authentication headers required.
  Fleet carrier endpoints — rcc-cmdr and rcc-key headers.

Commodity name normalisation
────────────────────────────
Raven Colonial identifies commodities by their normalised journal name:
  strip leading '$', strip trailing '_name;', lowercase.
  e.g. '$grain_name;' → 'grain'
       'grain' → 'grain' (already normalised)

State written to MonitorState
──────────────────────────────
  colonisation_sites   list[dict]  — active construction sites
  colonisation_docked  bool        — True when docked at a construction depot
"""

from __future__ import annotations
import json
import queue
import threading
import urllib.parse
import urllib.request
from core.plugin_loader import BasePlugin
from core.state import VERSION

_RAVEN_API_BASE = (
    "https://ravencolonial100-awcbdvabgze4c5cq.canadacentral-01.azurewebsites.net"
)
_RAVEN_UA = f"EDLD/{VERSION} (ravencolonial integration)"


def _raven_name(raw: str) -> str:
    """Normalise a commodity name to the Raven Colonial canonical form.

    Strips the '$' prefix and '_name;' suffix that Frontier uses in journal
    event fields, then lowercases.  Matches the reference plugin exactly:
        '$grain_name;' → 'grain'
        'Grain'         → 'grain'
        'grain'         → 'grain'
    """
    s = (raw or "").strip()
    if s.startswith("$"):
        s = s[1:]
    if s.endswith("_name;"):
        s = s[:-6]
    elif s.endswith("_name"):
        s = s[:-5]
    return s.lower()


def _short_station(station: str, system: str) -> str:
    """Return a compact display name for a construction site."""
    if not station:
        return system or "Unknown"
    if station.startswith("$EXT_PANEL_ColonisationShip"):
        return f"{system} (colonisation ship)" if system else "Colonisation Ship"
    if "Construction Site: " in station:
        return station.split("Construction Site: ", 1)[1].strip()
    return station


class ColonisationPlugin(BasePlugin):
    PLUGIN_NAME        = "colonisation"
    PLUGIN_DISPLAY     = "Colonisation"
    PLUGIN_DESCRIPTION = (
        "Tracks colonisation construction resource requirements and delivery "
        "progress.  Syncs to Raven Colonial (ravencolonial.com) when an API "
        "key is configured."
    )
    PLUGIN_VERSION     = "2.1.0"

    SUBSCRIBED_EVENTS = [
        "ColonisationSystemClaim",
        "ColonisationConstructionDepot",
        "ColonisationContribution",
        "ColonisationConstructionComplete",
        "ColonisationConstructionFailed",
        "CargoDepot",           # used by Raven Colonial for contribution attribution
        "LoadGame",             # new session — prune completed/failed sites + init FC
        "CarrierStats",         # identifies our own FC's marketId
        "FCMaterials",          # authoritative FC cargo snapshot
        "CargoTransfer",        # ship ↔ carrier transfers
        "MarketBuy",            # player bought from FC (reduces FC stock)
        "MarketSell",           # player sold to FC (increases FC stock)
        "Docked",
        "Undocked",
        "Location",
    ]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=55)

        s = core.state
        if not hasattr(s, "colonisation_sites"):
            s.colonisation_sites  = []
        if not hasattr(s, "colonisation_docked"):
            s.colonisation_docked = False

        self._current_market_id:      int | None = None
        self._current_system_address: int | None = None

        # Raven Colonial state
        self._api_key:      str        = core.cfg.colonisation_cfg.get("ApiKey", "")
        self._cmdr_name:    str        = ""
        self._last_depot:   dict       = {}    # last posted supply diff (change guard)

        # Fleet Carrier cargo tracking
        self._own_fc_market_id:   int | None = None   # our FC's marketId (from CarrierStats)
        self._current_station_type: str      = ""     # StationType of last Docked
        self._fc_linked: bool                = False  # whether our FC is linked on Raven

        # Background API worker
        self._api_queue:  queue.Queue = queue.Queue()
        self._api_thread: threading.Thread = threading.Thread(
            target=self._api_worker, daemon=True, name="edld-colonisation-api"
        )
        self._api_thread.start()

        # Periodic completion checker — waits for preload to finish before
        # the first check, then runs every hour.
        self._check_thread: threading.Thread = threading.Thread(
            target=self._completion_check_loop, daemon=True,
            name="edld-colonisation-check"
        )
        self._check_thread.start()

        self._restore()

    def on_unload(self) -> None:
        self._api_queue.put(None)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _restore(self) -> None:
        data = self.storage.read_json() or {}
        self.core.state.colonisation_sites = data.get("sites", [])
        # Prune sites that were completed or failed — clear them so the block
        # doesn't accumulate stale entries across sessions.
        self._prune_finished_sites()

    def _save(self) -> None:
        self.storage.write_json({"sites": self.core.state.colonisation_sites})

    def _prune_finished_sites(self) -> None:
        """Remove completed and failed sites from the tracked list.

        Called on startup (after restore) and at the start of each new
        session (LoadGame).  Completed/failed sites show a summary tick/cross
        in the block during the session they finish; on the next login they
        are gone automatically.
        """
        state = self.core.state
        before = len(state.colonisation_sites)
        state.colonisation_sites = [
            s for s in state.colonisation_sites
            if not s.get("complete") and not s.get("failed")
        ]
        if len(state.colonisation_sites) != before:
            self._save()

    # ── Site helpers ──────────────────────────────────────────────────────────

    def _find_site(self, market_id: int) -> dict | None:
        for site in self.core.state.colonisation_sites:
            if site.get("market_id") == market_id:
                return site
        return None

    def _upsert_site(self, market_id: int, system_address: int | None,
                     system: str, station: str,
                     progress: float, complete: bool, failed: bool,
                     resources: dict) -> None:
        state    = self.core.state
        existing = self._find_site(market_id)
        if existing is not None:
            if system_address:
                existing["system_address"] = system_address
            existing["system"]    = system    or existing["system"]
            existing["station"]   = station   or existing["station"]
            existing["progress"]  = progress
            existing["complete"]  = complete
            existing["failed"]    = failed
            existing["resources"] = resources
        else:
            state.colonisation_sites.append({
                "market_id":      market_id,
                "system_address": system_address,
                "system":         system,
                "station":        station,
                "progress":       progress,
                "complete":       complete,
                "failed":         failed,
                "resources":      resources,
            })

    # ── Event handling ────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        gq = self.core.gui_queue
        ev = event.get("event")

        # Always track commander name for contribution attribution
        if cmdr := getattr(state, "pilot_name", None):
            if cmdr and cmdr != self._cmdr_name:
                self._cmdr_name = cmdr
                # First time we know the cmdr name — check FC link status
                if self._api_key and not self._fc_linked:
                    self._queue_api(self._init_fc_link, cmdr)
            else:
                self._cmdr_name = cmdr

        match ev:

            case "ColonisationSystemClaim":
                market_id      = event.get("MarketID")
                system         = event.get("StarSystem", "")
                system_address = event.get("SystemAddress")
                if market_id is not None:
                    self._upsert_site(market_id, system_address, system, "",
                                      0.0, False, False, {})
                    self._save()
                    if gq: gq.put(("plugin_refresh", "colonisation"))

            case "ColonisationConstructionDepot":
                market_id   = event.get("MarketID")
                system      = state.pilot_system or ""
                station_raw = state.pilot_body or event.get("StationName", "")
                station     = _short_station(station_raw, system)
                progress    = float(event.get("ConstructionProgress", 0.0))
                complete    = bool(event.get("ConstructionComplete", False))
                failed      = bool(event.get("ConstructionFailed", False))

                resources: dict = {}
                needed:    dict = {}   # commodity → still_needed (Raven supply update)
                max_need   = 0

                for r in event.get("ResourcesRequired", []):
                    raw_name  = r.get("Name_Localised") or r.get("Name", "")
                    key       = _raven_name(r.get("Name", raw_name))
                    required  = int(r.get("RequiredAmount", 0))
                    provided  = int(r.get("ProvidedAmount", 0))
                    resources[key] = {
                        "name":     raw_name.strip(),
                        "required": required,
                        "provided": provided,
                    }
                    still = max(0, required - provided)
                    if required > 0:
                        needed[key] = still
                        max_need   += required

                if market_id is not None:
                    self._upsert_site(market_id, self._current_system_address,
                                      system, station,
                                      progress, complete, failed, resources)
                    self._current_market_id = market_id
                    state.colonisation_docked = True
                    self._save()
                    if gq: gq.put(("plugin_refresh", "colonisation"))

                # ── Raven Colonial: update supply when needs change ────────
                if (self._api_key and not complete and not failed
                        and needed != self._last_depot
                        and needed and self._current_system_address
                        and market_id is not None):
                    self._last_depot = dict(needed)
                    payload = {
                        "buildId":     "",     # filled in by _raven_update_supply after lookup
                        "commodities": needed,
                        "maxNeed":     max_need,
                    }
                    self._queue_api(self._raven_get_and_update_supply,
                                    self._current_system_address, market_id, payload)

                # ── Raven Colonial: mark complete when depot reports done ──
                if (self._api_key and complete and not state.in_preload
                        and self._current_system_address and market_id is not None):
                    site_obj = self._find_site(market_id)
                    self._queue_api(self._notify_project_complete,
                                    self._current_system_address, market_id,
                                    (site_obj or {}).get("station", ""))

            case "ColonisationContribution":
                # Journal event — authoritative source for cargo actually delivered.
                market_id = event.get("MarketID")
                site      = self._find_site(market_id) if market_id else None
                if site is None:
                    return

                cargo_diff: dict = {}
                for contrib in event.get("Contributions", []):
                    raw_name = contrib.get("Name_Localised") or contrib.get("Name", "")
                    key      = _raven_name(contrib.get("Name", raw_name))
                    amount   = int(contrib.get("Amount", 0))
                    if key in site["resources"]:
                        site["resources"][key]["provided"] = min(
                            site["resources"][key]["provided"] + amount,
                            site["resources"][key]["required"],
                        )
                    else:
                        site["resources"][key] = {
                            "name":     raw_name.strip(),
                            "required": amount,
                            "provided": amount,
                        }
                    if amount > 0:
                        cargo_diff[key] = cargo_diff.get(key, 0) + amount

                self._save()
                if gq: gq.put(("plugin_refresh", "colonisation"))

                # ── Raven Colonial: submit contribution ───────────────────
                if (self._api_key and cargo_diff and self._cmdr_name
                        and self._current_system_address and market_id is not None):
                    self._queue_api(self._raven_get_and_contribute,
                                    self._current_system_address, market_id,
                                    self._cmdr_name, cargo_diff)

            case "CargoDepot":
                # Raven Colonial also monitors CargoDepot (SubType="Deliver") for
                # contribution attribution — fired when cargo is deposited at a
                # construction depot via a mission.
                if event.get("SubType") != "Deliver":
                    return
                if not (self._api_key and self._cmdr_name
                        and self._current_market_id
                        and self._current_system_address):
                    return
                raw_type  = event.get("Type", "")
                key       = _raven_name(raw_type)
                count     = int(event.get("Count", 0))
                if not key or count <= 0:
                    return
                self._queue_api(self._raven_get_and_contribute,
                                self._current_system_address,
                                self._current_market_id,
                                self._cmdr_name,
                                {key: count})

            case "LoadGame":
                # New session — prune sites that finished while we were offline.
                self._prune_finished_sites()
                # Re-check whether our FC is linked on Raven Colonial.
                if self._api_key and self._cmdr_name:
                    self._queue_api(self._init_fc_link, self._cmdr_name)
                if gq: gq.put(("plugin_refresh", "colonisation"))

            case "CarrierStats":
                # Identifies our own FC — record the marketId so we know
                # which carrier is ours when CargoTransfer/MarketBuy/Sell fire.
                self._own_fc_market_id = event.get("CarrierID")

            case "FCMaterials":
                # FCMaterials contains only commodities listed on the carrier's
                # market, not the full physical cargo hold.  Full-replace syncs
                # are handled by on_capi_fleetcarrier() which receives the
                # authoritative hold contents from the CAPI /fleetcarrier poll.
                # Incremental deltas (CargoTransfer / MarketBuy / MarketSell)
                # keep the server in sync between CAPI polls.
                pass

            case "CargoTransfer":
                # Fired when cargo moves between ship and carrier.
                # Only act when we're docked at our own FC.
                if (not self._api_key
                        or not self._fc_linked
                        or self._current_station_type != "FleetCarrier"
                        or not self._own_fc_market_id):
                    return
                diff: dict = {}
                for t in event.get("Transfers", []):
                    key   = _raven_name(t.get("Type", ""))
                    n     = int(t.get("Count", 0))
                    dirn  = t.get("Direction", "")
                    if not key or n <= 0:
                        continue
                    if dirn == "tocarrier":
                        diff[key] = diff.get(key, 0) + n
                    elif dirn == "toship":
                        diff[key] = diff.get(key, 0) - n
                if diff:
                    self._queue_api(self._raven_supply_fc,
                                    self._own_fc_market_id, diff)

            case "MarketBuy":
                # Player bought from FC — reduces FC stock.
                if (not self._api_key
                        or not self._fc_linked
                        or self._current_station_type != "FleetCarrier"
                        or not self._own_fc_market_id):
                    return
                key = _raven_name(event.get("Type", ""))
                n   = int(event.get("Count", 0))
                if key and n > 0:
                    self._queue_api(self._raven_supply_fc,
                                    self._own_fc_market_id, {key: -n})

            case "MarketSell":
                # Player sold to FC — increases FC stock.
                if (not self._api_key
                        or not self._fc_linked
                        or self._current_station_type != "FleetCarrier"
                        or not self._own_fc_market_id):
                    return
                key = _raven_name(event.get("Type", ""))
                n   = int(event.get("Count", 0))
                if key and n > 0:
                    self._queue_api(self._raven_supply_fc,
                                    self._own_fc_market_id, {key: n})

            case "ColonisationConstructionComplete":
                market_id = event.get("MarketID")
                site      = self._find_site(market_id) if market_id else None
                if site is not None:
                    site["complete"] = True
                    site["progress"] = 1.0
                    self._save()
                    if gq: gq.put(("plugin_refresh", "colonisation"))
                    # Notify Raven Colonial that this project is complete and
                    # clean the build name (strip construction-site prefix).
                    # Guard against preload: a replayed completion event must
                    # never mark the current active project complete on the server.
                    if (self._api_key and not state.in_preload
                            and self._current_system_address and market_id):
                        self._queue_api(self._notify_project_complete,
                                        self._current_system_address, market_id,
                                        site.get("station", ""))

            case "ColonisationConstructionFailed":
                market_id = event.get("MarketID")
                site      = self._find_site(market_id) if market_id else None
                if site is not None:
                    site["failed"] = True
                    self._save()
                    if gq: gq.put(("plugin_refresh", "colonisation"))

            case "Docked":
                market_id      = event.get("MarketID")
                system_address = event.get("SystemAddress")
                self._current_station_type = event.get("StationType", "")
                if system_address:
                    self._current_system_address = system_address
                if market_id:
                    self._current_market_id = market_id
                site = self._find_site(market_id) if market_id else None
                if site:
                    state.colonisation_docked = True
                else:
                    state.colonisation_docked = False
                    self._last_depot = {}
                if gq: gq.put(("plugin_refresh", "colonisation"))

            case "Undocked":
                state.colonisation_docked    = False
                self._current_market_id      = None
                self._current_station_type   = ""
                self._last_depot             = {}
                if gq: gq.put(("plugin_refresh", "colonisation"))

            case "Location":
                system_address = event.get("SystemAddress")
                if system_address:
                    self._current_system_address = system_address
                if event.get("Docked"):
                    market_id = event.get("MarketID")
                    if market_id:
                        self._current_market_id = market_id
                    site = self._find_site(market_id) if market_id else None
                    state.colonisation_docked = bool(site)
                else:
                    state.colonisation_docked  = False
                    self._current_market_id    = None
                    self._last_depot           = {}
                if gq: gq.put(("plugin_refresh", "colonisation"))

    # ── Raven Colonial API — background thread ────────────────────────────────

    def _queue_api(self, func, *args) -> None:
        self._api_queue.put((func, args))

    def _api_worker(self) -> None:
        while True:
            task = self._api_queue.get()
            if task is None:
                break
            func, args = task
            try:
                func(*args)
            except Exception:
                pass
            finally:
                self._api_queue.task_done()

    # -- HTTP primitives ------------------------------------------------------

    def _get(self, path: str) -> dict | None:
        """GET from the Raven Colonial API. Returns parsed JSON or None."""
        url = f"{_RAVEN_API_BASE}{path}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _RAVEN_UA)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 404:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def _post(self, path: str, payload: dict,
              extra_headers: dict | None = None) -> bool:
        """POST JSON to the Raven Colonial API. Returns True on success."""
        url  = f"{_RAVEN_API_BASE}{path}"
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent",   _RAVEN_UA)
        if extra_headers:
            for k, v in extra_headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception:
            return False

    def _patch(self, path: str, payload: dict,
               extra_headers: dict | None = None) -> bool:
        """PATCH JSON to the Raven Colonial API. Returns True on success."""
        url  = f"{_RAVEN_API_BASE}{path}"
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=data, method="PATCH")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent",   _RAVEN_UA)
        if extra_headers:
            for k, v in extra_headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception:
            return False

    def _put(self, path: str, payload: dict) -> dict | None:
        """PUT JSON to the Raven Colonial API. Returns parsed response or None."""
        url  = f"{_RAVEN_API_BASE}{path}"
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=data, method="PUT")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent",   _RAVEN_UA)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    # -- Higher-level API calls -----------------------------------------------

    def _get_project(self, system_address: int, market_id: int) -> dict | None:
        """Fetch project metadata for a system/station."""
        return self._get(f"/api/system/{system_address}/{market_id}")

    def _get_cmdr_projects(self, cmdr_name: str) -> list:
        """Fetch all projects for a commander from GET /api/cmdr/{cmdr}."""
        if not cmdr_name:
            return []
        cmdr_enc = urllib.parse.quote(cmdr_name, safe="")
        result   = self._get(f"/api/cmdr/{cmdr_enc}")
        return result if isinstance(result, list) else []

    def _raven_mark_complete(self, build_id: str) -> None:
        """POST to /api/project/{buildId}/complete to notify server of completion."""
        if build_id:
            self._post(f"/api/project/{urllib.parse.quote(build_id)}/complete", {})

    def _raven_update_build_name(self, build_id: str, raw_name: str) -> None:
        """PATCH /api/project/{buildId} to strip construction-site prefix from buildName.

        The game writes station names like 'Orbital Construction Site: Khan Enterprise'.
        Raven Colonial's reference plugin strips the prefix before saving so the
        project shows a clean name on the website.
        """
        for prefix in ("Orbital Construction Site: ", "Planetary Construction Site: "):
            if raw_name.startswith(prefix):
                raw_name = raw_name[len(prefix):]
                break
        if raw_name and build_id:
            self._patch(f"/api/project/{urllib.parse.quote(build_id)}",
                        {"buildName": raw_name})

    def create_project(self, project_data: dict) -> dict | None:
        """PUT /api/project/ to create a new colonisation project on Raven Colonial.

        project_data should contain at minimum:
            buildId, buildName, systemAddress, marketId, systemName
        Returns the created project dict or None on failure.
        """
        return self._put("/api/project/", project_data)

    def _raven_get_and_update_supply(self, system_address: int, market_id: int,
                                      payload: dict) -> None:
        """Look up project then POST current supply needs.

        payload keys: commodities (dict[str,int]), maxNeed (int).
        buildId is filled in from the server response.
        """
        project = self._get_project(system_address, market_id)
        if not project:
            return
        build_id = project.get("buildId")
        if not build_id:
            return
        payload["buildId"] = build_id
        self._post(f"/api/project/{build_id}", payload)

    def _raven_get_and_contribute(self, system_address: int, market_id: int,
                                   cmdr: str, cargo_diff: dict) -> None:
        """Look up project then POST commander contribution.

        cargo_diff: {normalised_commodity_name: quantity_delivered}
        No auth headers required for construction contribution endpoints.
        """
        project = self._get_project(system_address, market_id)
        if not project:
            return
        build_id = project.get("buildId")
        if not build_id:
            return
        cmdr_enc = urllib.parse.quote(cmdr, safe="")
        self._post(f"/api/project/{build_id}/contribute/{cmdr_enc}", cargo_diff)

    def _notify_project_complete(self, system_address: int, market_id: int,
                                  station_name: str) -> None:
        """Look up the project, strip prefix from buildName, then mark complete.

        Called when ColonisationConstructionDepot or ColonisationConstructionComplete
        reports the build is finished.  Runs on the background API thread.
        """
        project = self._get_project(system_address, market_id)
        if not project:
            return
        build_id   = project.get("buildId")
        build_name = project.get("buildName") or station_name
        if not build_id:
            return
        # Clean the build name before marking complete
        self._raven_update_build_name(build_id, build_name)
        self._raven_mark_complete(build_id)

    def _raven_check_completion(self, system_address: int, market_id: int) -> None:
        """Check whether a project completed on Raven Colonial while offline.

        Fetches the project record and marks the local site complete if the
        server reports it is finished.  Fires a GUI refresh if state changes.
        Only called when the site is still active locally — avoids redundant
        network calls for sites already marked complete.
        """
        project = self._get_project(system_address, market_id)
        if not project:
            return
        if not project.get("complete"):
            return
        site = self._find_site(market_id)
        if site and not site.get("complete"):
            site["complete"] = True
            site["progress"] = 1.0
            self._save()
            gq = self.core.gui_queue
            if gq:
                gq.put(("plugin_refresh", "colonisation"))

    def _init_fc_link(self, cmdr_name: str) -> None:
        """Check whether this commander's FC is linked on Raven Colonial.

        Calls GET /api/cmdr/{cmdr}/fc/all.  If the response contains our
        FC's marketId we mark _fc_linked=True so cargo events are forwarded.
        Runs on the background API thread so it never blocks the event loop.

        Note: no initial cargo snapshot is pushed here.  assets_fc_materials
        contains only market-listed commodities, not the full physical hold.
        Sending it as a full replace would corrupt the server's cargo state by
        erasing unlisted cargo.  CargoTransfer / MarketBuy / MarketSell
        incremental events are the only reliable update mechanism.
        """
        if not cmdr_name:
            return
        cmdr_enc = urllib.parse.quote(cmdr_name, safe="")
        result   = self._get(f"/api/cmdr/{cmdr_enc}/fc/all")
        if not isinstance(result, list):
            return
        known_ids = {fc.get("marketId") for fc in result if fc.get("marketId")}
        if self._own_fc_market_id and self._own_fc_market_id in known_ids:
            self._fc_linked = True
        elif known_ids:
            self._fc_linked = True

    def _raven_update_fc_cargo(self, market_id: int, cargo: dict) -> None:
        """POST full cargo snapshot to /api/fc/{marketId}/cargo (full replace).

        Used when FCMaterials fires — this is the authoritative snapshot of
        what is physically stocked on the carrier.
        Requires rcc-cmdr and rcc-key authentication headers.
        """
        headers = {}
        if self._cmdr_name:
            headers["rcc-cmdr"] = self._cmdr_name
        if self._api_key:
            headers["rcc-key"] = self._api_key
        self._post(f"/api/fc/{market_id}/cargo", cargo,
                   extra_headers=headers if headers else None)

    def _raven_supply_fc(self, market_id: int, diff: dict) -> None:
        """PATCH incremental cargo delta to /api/fc/{marketId}/cargo.

        Used for CargoTransfer, MarketBuy, MarketSell — updates only the
        commodities that changed rather than replacing the full manifest.
        Positive values = cargo added to carrier; negative = removed.
        Requires rcc-cmdr and rcc-key authentication headers.
        """
        headers = {}
        if self._cmdr_name:
            headers["rcc-cmdr"] = self._cmdr_name
        if self._api_key:
            headers["rcc-key"] = self._api_key
        url  = f"{_RAVEN_API_BASE}/api/fc/{market_id}/cargo"
        data = json.dumps(diff).encode("utf-8")
        req  = urllib.request.Request(url, data=data, method="PATCH")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent",   _RAVEN_UA)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=15):
                pass
        except Exception:
            pass

    def _check_all_sites(self) -> None:
        """Query Raven Colonial for every active site and update completion state.

        Uses GET /api/cmdr/{cmdr} to fetch all known projects in one call,
        then matches against locally tracked sites by marketId.  Falls back
        to per-site GET /api/system/{addr}/{mid} for sites not returned by
        the commander endpoint (e.g. unlinked or legacy entries).
        """
        if not self._api_key:
            return
        sites = self.core.state.colonisation_sites
        active = [s for s in sites
                  if not s.get("complete") and not s.get("failed")
                  and s.get("market_id")]
        if not active:
            return

        # Batch lookup via commander projects endpoint
        cmdr_projects: dict = {}
        if self._cmdr_name:
            for proj in self._get_cmdr_projects(self._cmdr_name):
                mid = proj.get("marketId")
                if mid:
                    cmdr_projects[mid] = proj

        changed = False
        for site in active:
            market_id = site["market_id"]
            project   = cmdr_projects.get(market_id)
            # Fall back to per-site lookup if not in commander list and we
            # have a system address to query.
            if project is None and site.get("system_address"):
                project = self._get_project(site["system_address"], market_id)
            if not project:
                continue
            if project.get("complete") and not site.get("complete"):
                site["complete"] = True
                site["progress"] = 1.0
                changed = True

        if changed:
            self._save()
            gq = self.core.gui_queue
            if gq:
                gq.put(("plugin_refresh", "colonisation"))

    def _completion_check_loop(self) -> None:
        """Daemon thread: check all active sites for completion periodically.

        Waits 90 seconds on startup to let preload finish before the first
        check, then repeats every hour.  Uses the API queue so checks run
        on the API worker thread and don't block the main loop.
        """
        import time as _time
        _time.sleep(90)   # let preload complete before hitting the network
        while True:
            self._queue_api(self._check_all_sites)
            _time.sleep(3600)   # recheck every hour

    # ── Plugin interface ──────────────────────────────────────────────────────

    def on_capi_fleetcarrier(self, cargo: dict) -> None:
        """Called by DataProvider after a successful CAPI /fleetcarrier poll.

        cargo is the full physical hold: {commodity_name_lower: total_qty}.
        This is authoritative — it includes unlisted colonisation bulk goods
        that FCMaterials and Market.json do not expose.  Send as a full
        replace to Raven Colonial so the server's state is exactly in sync.
        """
        if not (self._api_key and self._fc_linked and self._own_fc_market_id):
            return
        if not cargo:
            return
        self._queue_api(self._raven_update_fc_cargo, self._own_fc_market_id, cargo)

    def get_api_key(self) -> str:
        return self._api_key

    def set_api_key(self, key: str) -> None:
        self._api_key = key.strip()

    def get_summary_line(self) -> str | None:
        sites  = self.core.state.colonisation_sites
        active = [s for s in sites if not s.get("complete") and not s.get("failed")]
        if not active:
            return None
        parts = []
        for s in active:
            pct       = round(s.get("progress", 0.0) * 100)
            remaining = sum(
                max(0, r["required"] - r["provided"])
                for r in s.get("resources", {}).values()
            )
            parts.append(
                f"{s['station'] or s['system']}: {pct}% ({remaining:,} t remaining)"
            )
        return "- Colonisation: " + " | ".join(parts)

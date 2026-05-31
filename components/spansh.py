"""
components/spansh.py — Spansh.co.uk market price fetcher.

Spansh /api/search response structure (confirmed from live API):
    {
        "type": "station",
        "record": {
            "name": "Rominger City",
            "system_name": "HIP 94521",
            "market_id": 4220594179,
            "market_updated_at": "2025-08-27 07:02:41+00",
            "market": [
                {"commodity": "Modular Terminals", "category": "Machinery",
                 "sell_price": 2481, "buy_price": 0, "demand": 4860, "supply": 0},
                ...
            ]
        }
    }

The market data is inline in the search response — no second API call needed.
Note: Spansh does not expose galactic average (mean_price); that column will
show "—" for target markets and only populate from Market.json (docked station).

Refresh interval: 30 minutes. Spansh crowd-sources from EDDN; busy stations
are typically 0–4 hours old. BGS tick is ~60 min so 30 min is appropriate.
"""

import json
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
from core.plugin_loader import BasePlugin

_SPANSH_SEARCH    = "https://spansh.co.uk/api/search"
_SPANSH_RESULTS   = "https://spansh.co.uk/api/results"
_REFRESH_INTERVAL = 1800   # 30 minutes

# ── Route-planning endpoints ─────────────────────────────────────────────────
# Spansh's route API is asynchronous: POST form-encoded params → the server
# responds 202 Accepted with {"job": id}, then you poll /api/results/<id>
# until status == "ok".  (202, not 200 — that bit us before.)
#
# Endpoint facts, confirmed against live request logs:
#   /api/route          — WORKS for both FSD and neutron routing.  Returns
#                         202.  Params: from, to, range, efficiency.
#   /api/fsd_route      — DEAD (404).  Removed.
#   /api/generic/route  — exists but wants source/destination param names;
#                         not needed since /api/route covers our cases.
#
# The fleet-carrier router is a different shape.  Its result URLs look like
#   /fleet-carrier/results/<job>?source_system=X&destinations=["A","B"]&used_capacity=N
# so the POST params are source_system / destinations (a JSON-array string)
# / used_capacity — NOT from/to/range.  The exact submit path isn't
# publicly documented and has moved before, so it carries a candidate list
# walked on 404.  All of these are overridable from config.json under
# "spansh_route_urls": {"fsd": [...], "neutron": [...], "carrier": [...]}.
_SPANSH_ROUTE_URLS: dict[str, list[str]] = {
    # FSD routing no longer goes through Spansh — see plot_fsd_route, which
    # uses EDSM's system database for genuine jump-by-jump routing.
    "neutron": ["https://spansh.co.uk/api/route"],
    "carrier": [
        # /api/fleetcarrier/search is the working POST endpoint.
        # /api/fleetcarrier/route returns HTTP 202 to POST but the resulting
        # UUID never resolves anywhere, so the other candidates remain only as
        # fallbacks if /search ever stops working.
        "https://spansh.co.uk/api/fleetcarrier/search",
        "https://spansh.co.uk/api/fleet-carrier/route",
        "https://spansh.co.uk/api/fleetcarrier/route",
        "https://spansh.co.uk/api/fleet_carrier/route",
    ],
}

# HTTP statuses Spansh uses to mean "job accepted" on the async route POST.
_SPANSH_OK_STATUSES = (200, 201, 202)


class SpanshPlugin(BasePlugin):
    PLUGIN_NAME        = "spansh"
    PLUGIN_DISPLAY     = "Spansh Market Prices"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = (
        "Fetches commodity sell prices for a target station from Spansh.co.uk. "
        "Target station is set from the Cargo block footer. Prices refresh every 30 min."
    )

    SUBSCRIBED_EVENTS = []

    def on_load(self, core) -> None:
        super().on_load(core)
        s = core.state
        if not hasattr(s, "cargo_target_market"):      s.cargo_target_market      = {}
        if not hasattr(s, "cargo_target_market_name"): s.cargo_target_market_name = ""
        if not hasattr(s, "cargo_target_market_ts"):   s.cargo_target_market_ts   = 0.0

        self._stop = threading.Event()

        # Restore last target from storage and re-fetch on startup.
        # Prefer market_id (unambiguous) over station name (fuzzy search
        # can return the wrong station when multiple share a name).
        saved     = self.storage.read_json()
        market_id = saved.get("target_market_id", 0)
        last      = saved.get("target_station", "")
        if market_id:
            threading.Thread(
                target=self._fetch_by_id,
                args=(int(market_id),),
                daemon=True,
                name="spansh-startup",
            ).start()
        elif last:
            threading.Thread(
                target=self._fetch_and_store,
                args=(last,),
                daemon=True,
                name="spansh-startup",
            ).start()

        threading.Thread(
            target=self._refresh_loop,
            daemon=True,
            name="spansh-refresh",
        ).start()

    def on_unload(self) -> None:
        self._stop.set()

    # ── Public API ────────────────────────────────────────────────────────────

    def search(self, query: str) -> list:
        """Search Spansh for stations matching query.

        Returns [{name, system, updated, id}] or [] on error.
        Call from a background thread.
        """
        if not query or len(query) < 3:
            return []
        try:
            params = urllib.parse.urlencode({"q": query})
            url = f"{_SPANSH_SEARCH}?{params}"
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.load(resp)

            raw = data.get("results") or []

            results = []
            for r in raw:
                if r.get("type") != "station":
                    continue
                rec = r.get("record") or {}
                name    = rec.get("name", "").strip()
                system  = rec.get("system_name", "").strip()
                updated = rec.get("market_updated_at", "")
                rid     = rec.get("market_id", 0) or rec.get("id", 0)
                if not name:
                    continue
                results.append({
                    "name":    name,
                    "system":  system,
                    "updated": updated,
                    "id":      rid,
                    "_rec":    rec,   # carry full record for immediate fetch
                })

            if not results:
                types = list(set(r.get("type", "?") for r in raw))
            return results[:5]

        except Exception as exc:
            return []

    def search_home(self, query: str) -> list:
        """Search Spansh for systems AND stations matching query.

        Returns [{name, system, is_station, star_pos, updated}] or [].
        star_pos is [x, y, z] when available (systems always have it;
        stations carry the system's coords from the search record).
        Call from a background thread.
        """
        if not query or len(query) < 3:
            return []
        try:
            import urllib.parse, urllib.request, json as _json
            params = urllib.parse.urlencode({"q": query})
            url = f"{_SPANSH_SEARCH}?{params}"
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = _json.load(resp)

            results = []
            for r in data.get("results") or []:
                rtype = r.get("type", "")
                rec   = r.get("record") or {}

                if rtype == "system":
                    name      = rec.get("name", "").strip()
                    if not name:
                        continue
                    x = rec.get("x"); y = rec.get("y"); z = rec.get("z")
                    star_pos  = [x, y, z] if all(v is not None for v in (x, y, z)) else None
                    results.append({
                        "name":       name,
                        "system":     name,
                        "is_station": False,
                        "star_pos":   star_pos,
                        "updated":    rec.get("updated_at", ""),
                    })

                elif rtype == "station":
                    name   = rec.get("name", "").strip()
                    system = rec.get("system_name", "").strip()
                    if not name:
                        continue
                    # Stations carry system coords when the search result includes them
                    x = rec.get("x"); y = rec.get("y"); z = rec.get("z")
                    star_pos  = [x, y, z] if all(v is not None for v in (x, y, z)) else None
                    results.append({
                        "name":       name,
                        "system":     system,
                        "is_station": True,
                        "star_pos":   star_pos,
                        "updated":    rec.get("market_updated_at", ""),
                        "_rec":       rec,
                    })

                if len(results) >= 8:
                    break

            return results

        except Exception:
            return []

    def set_target(self, station_name: str, system_name: str = "",
                   _record: dict | None = None) -> None:
        """Set target market. If _record supplied (from search result) use it
        directly without a second network request."""
        if _record:
            threading.Thread(
                target=self._store_record,
                args=(_record,),
                daemon=True,
                name="spansh-set",
            ).start()
        else:
            query = f"{station_name},{system_name}" if system_name else station_name
            threading.Thread(
                target=self._fetch_and_store,
                args=(query,),
                daemon=True,
                name="spansh-set",
            ).start()

    def clear_target(self) -> None:
        s = self.core.state
        s.cargo_target_market      = {}
        s.cargo_target_market_name = ""
        s.cargo_target_market_ts   = 0.0
        self.storage.write_json({"target_station": ""})
        gq = self.core.gui_queue
        if gq:
            gq.put(("plugin_refresh", "cargo"))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _refresh_loop(self) -> None:
        while not self._stop.wait(_REFRESH_INTERVAL):
            saved     = self.storage.read_json()
            last      = saved.get("target_station", "")
            market_id = saved.get("target_market_id", 0)
            if market_id:
                self._fetch_by_id(int(market_id))
            elif last:
                self._fetch_and_store(last)

    def _fetch_by_id(self, market_id: int) -> None:
        """Fetch market data for a specific station by market_id.

        Uses the Spansh station endpoint which returns a single unambiguous
        result regardless of how many stations share the same name.
        """
        try:
            url = f"https://spansh.co.uk/api/stations/{market_id}"
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.load(resp)
            rec = data.get("station") or data.get("record") or data
            if rec and rec.get("name"):
                # Normalise: station endpoint uses "system" not "system_name"
                if "system" in rec and "system_name" not in rec:
                    rec["system_name"] = (
                        rec["system"].get("name", "") if isinstance(rec["system"], dict)
                        else rec["system"]
                    )
                # market field may be nested under "market" key
                if "market" not in rec and "commodities" in rec:
                    rec["market"] = rec["commodities"]
                self._store_record(rec)
        except urllib.error.URLError:
            pass
        except Exception:
            pass

    def _fetch_and_store(self, query: str) -> None:
        """Search Spansh, take the first station result, store its market data."""
        try:
            params = urllib.parse.urlencode({"q": query})
            url = f"{_SPANSH_SEARCH}?{params}"
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.load(resp)

            raw = data.get("results") or []
            stations = [r for r in raw if r.get("type") == "station"]
            if not stations:
                return

            rec = stations[0].get("record") or {}
            self._store_record(rec)

        except urllib.error.URLError:
            pass
        except Exception:
            pass

    def _store_record(self, rec: dict) -> None:
        """Parse a Spansh station record dict and push to state."""
        stn_name = rec.get("name", "").strip()
        sys_name = (rec.get("system_name") or rec.get("system") or "").strip()
        updated  = rec.get("market_updated_at", "")
        market   = rec.get("market") or []

        commodities: dict = {}
        for item in market:
            # Spansh field: 'commodity' = display name (no mean_price available)
            raw_name = (item.get("commodity") or "").strip()
            if not raw_name:
                continue
            key  = raw_name.lower().replace(" ", "")
            sell = int(item.get("sell_price") or 0)
            commodities[key] = {
                "name_local":     raw_name,
                "category":       item.get("category", ""),
                "category_local": item.get("category", ""),
                "sell_price":     sell,
                "mean_price":     0,   # Spansh doesn't expose galactic average
            }


        # Persist station name + market_id so refreshes fetch the exact station.
        market_id = rec.get("market_id") or rec.get("id") or 0
        try:
            self.storage.write_json({
                "target_station":    stn_name,
                "target_market_id":  market_id,
            })
        except Exception as _exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "spansh: could not persist target station: %s", _exc
            )

        s = self.core.state
        s.cargo_target_market = {
            "station_name": stn_name,
            "star_system":  sys_name,
            "commodities":  commodities,
            "source":       "spansh",
            "updated":      updated,
        }
        s.cargo_target_market_name = f"{stn_name} | {sys_name}"
        s.cargo_target_market_ts   = time.time()

        gq = self.core.gui_queue
        if gq:
            gq.put(("plugin_refresh", "cargo"))

    # ── Route planning ────────────────────────────────────────────────────────

    # Spansh's route APIs are asynchronous: POST creates a job that runs
    # server-side, then GET /api/results/{job_id} polls for completion.
    # Typical ship-route jobs finish in 1–10 s.  Fleet-carrier routes are
    # far heavier (a galaxy-spanning carrier route can be 40+ jumps and
    # take a minute-plus server-side), so they get a longer budget.
    _ROUTE_POLL_INTERVAL_S = 2
    _ROUTE_POLL_TIMEOUT_S  = 60     # ship routes (fsd / neutron)
    _CARRIER_POLL_TIMEOUT_S = 180   # carrier routes — much slower

    def plot_neutron_route(self, source: str, destination: str,
                           range_ly: float, efficiency: int = 60) -> dict | None:
        """Plot a neutron-boosted route from source to destination.

        Args:
            source       — starting system name
            destination  — ending system name
            range_ly     — ship's FSD jump range (laden, light years)
            efficiency   — route efficiency 1-100 (lower = faster but more jumps;
                           Spansh default is 60).

        Uses the full neutron supercharge multiplier (4×) so the router
        detours via neutron stars wherever that reduces the jump count.

        Returns the full Spansh response dict on success, or
        {"_error": "<message>"} on failure.  Stores last successful result
        on state.spansh_neutron_route.
        """
        return self._plot_route("neutron", {
            "from":        source,
            "to":          destination,
            "range":       float(range_ly),
            "efficiency":  int(efficiency),
            "supercharge_multiplier": 4,
        }, store_key="spansh_neutron_route")

    # ── EDSM helpers (for the plain-FSD router + carrier ID resolution) ───────
    # The Spansh /api/route endpoint is a *neutron* router — pointed at a
    # plain route it just returns the destination as a single hop, which
    # is useless for FSD planning.  So the FSD tab uses EDSM's system
    # database to do real jump-by-jump routing instead.  EDSM is also how
    # we resolve system names to the id64 values the carrier router needs.

    _EDSM_SYSTEM = "https://www.edsm.net/api-v1/system"
    _EDSM_SPHERE = "https://www.edsm.net/api-v1/sphere-systems"
    _FSD_MAX_HOPS = 120   # safety cap for the greedy router

    def _edsm_get(self, url: str, params: dict) -> object | None:
        """GET an EDSM endpoint, return parsed JSON or None on any failure.

        EDSM blocks the default Python-urllib User-Agent (returns 403), so
        we always send a real UA string identifying this tool — same as
        the EDSM uploader plugin and every other HTTP client in the
        codebase.
        """
        from core import debug as _dbg
        try:
            qs = urllib.parse.urlencode(params)
            req = urllib.request.Request(
                f"{url}?{qs}",
                headers={"User-Agent": "EDLD/1.0 (+routing helper)"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    return None
                txt = resp.read().decode("utf-8")
                return json.loads(txt) if txt.strip() else None
        except Exception as exc:
            _dbg.log(f"  [EDSM] {url} failed: {type(exc).__name__}: {exc}")
            return None

    def _edsm_system(self, name: str) -> dict | None:
        """Resolve a system name to its EDSM record with coords + id64.
        Returns {"name", "id64", "coords": {x,y,z}} or None."""
        d = self._edsm_get(self._EDSM_SYSTEM, {
            "systemName": name, "showCoordinates": 1, "showId": 1,
        })
        # EDSM returns [] for an unknown system, or a dict for a known one.
        if not d or not isinstance(d, dict):
            return None
        return d

    def _edsm_sphere(self, name: str, radius: float) -> list:
        """All systems within `radius` ly of `name` (each with coords)."""
        d = self._edsm_get(self._EDSM_SPHERE, {
            "systemName": name, "radius": min(float(radius), 100.0),
            "showCoordinates": 1, "showId": 1,
        })
        return d if isinstance(d, list) else []

    @staticmethod
    def _dist3(a: dict, b: dict) -> float:
        return ((a["x"] - b["x"]) ** 2
                + (a["y"] - b["y"]) ** 2
                + (a["z"] - b["z"]) ** 2) ** 0.5

    def plot_fsd_route(self, source: str, destination: str,
                       range_ly: float) -> dict | None:
        """Plot a plain-FSD jump route from source to destination.

        Spansh has no plain-FSD endpoint — /api/route is a neutron router
        and degenerates to a single hop for non-neutron routes.  So this
        does real routing against EDSM's system database: a greedy
        best-first search that, from each system, jumps to whichever
        in-range system makes the most progress toward the destination.

        Limitations vs Spansh's neutron router:
          - EDSM only knows systems players have visited/uploaded, so in
            sparse regions the search can get stuck (reported clearly).
          - greedy ≠ optimal, but for bubble / populated-space routes it's
            very close.
          - capped at _FSD_MAX_HOPS jumps — longer trips should use the
            Neutron tab.

        Returns a Spansh-shaped dict (system_jumps / total_jumps /
        distance) so the UI renders it the same way, plus "_source":
        "EDSM".  On failure returns {"_error": "..."}.
        """
        from core import debug as _dbg

        src = self._edsm_system(source)
        if not src or "coords" not in src:
            return {"_error": f"EDSM doesn't know the system '{source}' "
                              f"(check spelling)."}
        dst = self._edsm_system(destination)
        if not dst or "coords" not in dst:
            return {"_error": f"EDSM doesn't know the system '{destination}' "
                              f"(check spelling)."}

        rng = float(range_ly)
        end_c = dst["coords"]
        total_distance = self._dist3(src["coords"], end_c)

        # Build the route greedily.
        waypoints = [{
            "system": src["name"], "distance_jumped": 0, "jumps": 0,
            "neutron_star": False,
        }]
        cur_name   = src["name"]
        cur_coords = src["coords"]
        hops       = 0

        while self._dist3(cur_coords, end_c) > rng:
            if hops >= self._FSD_MAX_HOPS:
                return {"_error": (
                    f"Route exceeds {self._FSD_MAX_HOPS} jumps — too long for "
                    f"the FSD planner.  Use the Neutron tab for long-haul "
                    f"routes (it plans far fewer galaxy-map plots)."
                )}
            sphere = self._edsm_sphere(cur_name, rng)
            if not sphere:
                return {"_error": (
                    f"EDSM returned no systems within {rng:.0f} ly of "
                    f"'{cur_name}' — its database may be sparse here.  Try "
                    f"the Neutron tab, or a shorter first leg."
                )}
            cur_to_end = self._dist3(cur_coords, end_c)
            best = None
            best_to_end = cur_to_end
            for s in sphere:
                c = s.get("coords")
                if not c or s.get("name") == cur_name:
                    continue
                d_to_end = self._dist3(c, end_c)
                # Only accept genuine progress toward the destination.
                if d_to_end < best_to_end:
                    best_to_end = d_to_end
                    best = s
            if best is None:
                return {"_error": (
                    f"FSD route got stuck near '{cur_name}' — no in-range "
                    f"system in EDSM's data makes progress toward "
                    f"'{destination}'.  Try the Neutron tab."
                )}
            leg = self._dist3(cur_coords, best["coords"])
            waypoints.append({
                "system": best["name"], "distance_jumped": leg,
                "jumps": 1, "neutron_star": False,
            })
            cur_name   = best["name"]
            cur_coords = best["coords"]
            hops += 1

        # Final hop to the destination itself.
        leg = self._dist3(cur_coords, end_c)
        waypoints.append({
            "system": dst["name"], "distance_jumped": leg,
            "jumps": 1, "neutron_star": False,
        })

        result = {
            "system_jumps":  waypoints,
            "total_jumps":   len(waypoints) - 1,   # each hop is exactly 1 jump
            "distance":      total_distance,
            "source_system": src["name"],
            "destination_system": dst["name"],
            "_source":       "EDSM",
        }
        self.core.state.spansh_fsd_route = result
        _dbg.info(f"  [FSD] EDSM route {src['name']} → {dst['name']}: "
                  f"{len(waypoints) - 1} jumps, {total_distance:.0f} ly")
        return result

    def plot_carrier_route(self, source: str, destination: str,
                            capacity_used: int = 0,
                            total_capacity: int = 25000,
                            current_fuel: int = 0,
                            calc_starting_fuel: bool = True) -> dict | None:
        """Plot a fleet carrier route from source to destination.

        The carrier router's parameters were reverse-engineered from a
        real Spansh website job — the exact param names and shapes matter:

          source_system        — the SOURCE system's id64 (NOT its name)
          destination_systems  — JSON array of destination id64s
          capacity             — the carrier's TOTAL capacity (25000 for a
                                 standard fleet carrier) — not the used
                                 figure
          capacity_used        — tonnes currently used on the carrier
          current_fuel         — tritium currently in the carrier's tank
          mass                 — carrier mass (= total capacity)
          tritium_amount       — tritium available to load (0 lets Spansh
                                 decide)
          calculate_starting_fuel — 1 to let Spansh work out the fill
          refuel_destinations  — JSON array, empty unless pre-specifying

        Because the endpoint wants id64s, source/destination names are
        resolved through EDSM first.

        Args:
            source / destination — system NAMES (resolved to id64 here)
            capacity_used        — used capacity in tonnes
            total_capacity       — total capacity (default 25000)
            current_fuel         — tritium on board
            calc_starting_fuel   — let Spansh compute the starting fill

        Returns the Spansh response dict on success, or
        {"_error": "<message>"} on failure.
        """
        # Resolve names → id64.  The carrier endpoint rejects plain names.
        src = self._edsm_system(source)
        if not src or "id64" not in src:
            return {"_error": f"Couldn't resolve '{source}' to a system ID "
                              f"via EDSM (check spelling)."}
        dst = self._edsm_system(destination)
        if not dst or "id64" not in dst:
            return {"_error": f"Couldn't resolve '{destination}' to a system "
                              f"ID via EDSM (check spelling)."}

        return self._plot_route("carrier", {
            "source_system":           str(src["id64"]),
            "destination_systems":     json.dumps([str(dst["id64"])]),
            "capacity":                int(total_capacity),
            "capacity_used":           int(capacity_used),
            "current_fuel":            int(current_fuel),
            "mass":                    int(total_capacity),
            "tritium_amount":          0,
            "refuel_destinations":     json.dumps([]),
            "calculate_starting_fuel": 1 if calc_starting_fuel else 0,
        }, store_key="spansh_carrier_route")

    def _plot_route(self, route_kind: str, params: dict,
                    store_key: str) -> dict | None:
        """Common driver: POST job, poll results, return parsed dict.

        route_kind is "fsd" / "neutron" / "carrier" — used to pick the
        candidate-endpoint list from _SPANSH_ROUTE_URLS (overridable via
        config "spansh_route_urls").  Each candidate is tried in turn; a
        404 falls through to the next, anything else (success, non-404
        error, network failure) stops the walk.

        Spansh accepts the parameters as application/x-www-form-urlencoded.
        The POST returns either {"job": "<job_id>"} or {"error": "..."}.
        Polling /api/results/{job_id} returns
        {"status":"queued|in_progress|ok|error", "result": {...}}.

        Returns:
          - On success: the parsed result dict from Spansh.
          - On failure: {"_error": "<message>"} describing what went wrong.
        """
        from core import debug as _dbg

        # Resolve the candidate endpoint list (config override wins).
        cfg_urls = {}
        try:
            cfg_urls = (self.core.cfg.config or {}).get("spansh_route_urls", {}) or {}
        except Exception:
            cfg_urls = {}
        candidates = cfg_urls.get(route_kind) or _SPANSH_ROUTE_URLS.get(route_kind, [])
        if not candidates:
            return {"_error": f"No Spansh endpoint configured for '{route_kind}' routes"}

        start    = None
        used_url = None
        tried:   list[str] = []
        last_err = ""

        for post_url in candidates:
            tried.append(post_url)
            try:
                body = urllib.parse.urlencode(params).encode("utf-8")
                req = urllib.request.Request(
                    post_url,
                    data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        # Spansh is fine without a UA, but identifying
                        # ourselves is polite and helps their logs.
                        "User-Agent": "EDLD/1.0 (+https://spansh.co.uk)",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    # Spansh's async route POST replies 202 Accepted (not
                    # 200) when it queues the job — treat the whole
                    # accepted-family as success.
                    if resp.status not in _SPANSH_OK_STATUSES:
                        last_err = f"HTTP {resp.status}"
                        _dbg.info(f"  [Spansh] {post_url} → {last_err}")
                        continue
                    start    = json.loads(resp.read().decode("utf-8"))
                    used_url = post_url
                    _dbg.info(f"  [Spansh] {route_kind} POST accepted by "
                              f"{post_url} (HTTP {resp.status})")
                    break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    # Endpoint moved/renamed — try the next candidate.
                    last_err = f"HTTP 404 at {post_url}"
                    _dbg.info(f"  [Spansh] {last_err} — trying next candidate")
                    continue
                # Non-404 HTTP error: Spansh received the request but
                # rejected it (bad params, system not found, etc).  That's
                # a real answer — surface it, don't keep walking.
                err_body = ""
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")
                    err_obj  = json.loads(err_body)
                    err_body = err_obj.get("error") or err_obj.get("message") or err_body
                except Exception:
                    pass
                msg = f"Spansh rejected request (HTTP {exc.code}): {err_body or exc.reason}"
                _dbg.info(f"  [Spansh] {msg}")
                return {"_error": msg}
            except urllib.error.URLError as exc:
                msg = f"Network error reaching Spansh: {exc.reason}"
                _dbg.info(f"  [Spansh] {msg}")
                return {"_error": msg}
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                _dbg.info(f"  [Spansh] Route POST failed ({last_err})")
                continue

        if start is None:
            return {"_error": (
                f"All Spansh {route_kind} endpoints failed "
                f"(last: {last_err}). Tried: {', '.join(tried)}"
            )}

        job_id = start.get("job")
        if not job_id:
            err = start.get("error") or "no job id returned"
            _dbg.info(f"  [Spansh] Route plot rejected: {err}")
            return {"_error": f"Spansh rejected request: {err}"}

        # Poll for completion.  Carrier routes are computationally heavy
        # and routinely need well over a minute server-side, so they get a
        # longer budget than ship routes.
        poll_timeout = (self._CARRIER_POLL_TIMEOUT_S
                        if route_kind == "carrier"
                        else self._ROUTE_POLL_TIMEOUT_S)
        # /api/results/<job> is the standard poll endpoint and handles
        # most async jobs.  For carrier routes we also try the
        # hyphenated variant matching the website URL pattern
        # (/fleet-carrier/results/<job>) and the no-hyphen variant
        # matching the /api/fleetcarrier/search POST endpoint.  Trying
        # all of them on every poll iteration is cheap and protects
        # against either side of the API rename being inconsistent.
        result_urls = [f"{_SPANSH_RESULTS}/{job_id}"]
        if route_kind == "carrier":
            for url in (
                f"https://spansh.co.uk/api/fleetcarrier/results/{job_id}",
                f"https://spansh.co.uk/api/fleet-carrier/results/{job_id}",
            ):
                if url not in result_urls:
                    result_urls.append(url)
            # Also derive a poll URL from whichever POST endpoint
            # accepted the job (covers cases where Spansh introduces
            # additional naming variants).
            if used_url:
                base = used_url.rsplit("/", 1)[0]   # strip the verb
                for tail in ("results", "route"):
                    cand = f"{base}/{tail}/{job_id}"
                    if cand not in result_urls:
                        result_urls.append(cand)

        deadline    = time.monotonic() + poll_timeout
        last_status = "queued"
        consecutive_5xx = 0
        while time.monotonic() < deadline:
            time.sleep(self._ROUTE_POLL_INTERVAL_S)
            poll = None
            for results_url in result_urls:
                try:
                    with urllib.request.urlopen(results_url, timeout=8) as resp:
                        if resp.status not in _SPANSH_OK_STATUSES:
                            continue
                        poll = json.loads(resp.read().decode("utf-8"))
                        consecutive_5xx = 0
                        break
                except urllib.error.HTTPError as exc:
                    # 5xx while polling is usually transient — Spansh is
                    # mid-computation.  Keep going, but if the server is
                    # *persistently* 5xx-ing, give up with a clear message
                    # rather than burning the whole timeout.
                    if 500 <= exc.code < 600:
                        consecutive_5xx += 1
                        _dbg.log(f"  [Spansh] Poll {results_url} → HTTP "
                                 f"{exc.code} (transient #{consecutive_5xx})")
                    else:
                        _dbg.log(f"  [Spansh] Poll {results_url} → HTTP {exc.code}")
                    continue
                except Exception as exc:
                    _dbg.log(f"  [Spansh] Poll error: {type(exc).__name__}: {exc}")
                    continue
            if poll is None:
                if consecutive_5xx >= 20:
                    msg = (f"Spansh's results endpoint is persistently "
                           f"erroring (HTTP 5xx ×{consecutive_5xx}) — the "
                           f"route job may have failed server-side.")
                    _dbg.info(f"  [Spansh] {msg}")
                    return {"_error": msg}
                continue
            status = poll.get("status") or last_status
            last_status = status
            if status == "ok":
                result = poll.get("result") or {}
                setattr(self.core.state, store_key, result)
                return result
            if status == "error":
                err = poll.get("error", "unknown error")
                _dbg.info(f"  [Spansh] Route plot error: {err}")
                return {"_error": f"Spansh: {err}"}
            # "queued" or "in_progress" — continue polling

        msg = (f"Spansh did not complete the {route_kind} route within "
               f"{poll_timeout}s (status={last_status}). "
               f"Long carrier routes can take several minutes — "
               f"try again, or plot a shorter leg.")
        _dbg.info(f"  [Spansh] {msg}")
        return {"_error": msg}

    def get_last_route(self, kind: str = "neutron") -> dict | None:
        """Return the most recent plotted route of the given kind, or None.

        Kind is 'neutron', 'fsd', or 'carrier'.
        """
        key = (f"spansh_{kind}_route"
               if kind in ("neutron", "fsd", "carrier") else None)
        if not key:
            return None
        return getattr(self.core.state, key, None)

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
# Route-planning endpoints — asynchronous (POST creates a job, poll for results)
_SPANSH_NEUTRON   = "https://spansh.co.uk/api/route"
_SPANSH_FSD       = "https://spansh.co.uk/api/fsd_route"
_SPANSH_RESULTS   = "https://spansh.co.uk/api/results"
_REFRESH_INTERVAL = 1800   # 30 minutes


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
    # Typical jobs finish in 1–10 seconds; neutron routes with long
    # journeys may take longer.  We poll up to _ROUTE_POLL_TIMEOUT_S total
    # at _ROUTE_POLL_INTERVAL_S between polls.
    _ROUTE_POLL_INTERVAL_S = 2
    _ROUTE_POLL_TIMEOUT_S  = 60

    def plot_neutron_route(self, source: str, destination: str,
                           range_ly: float, efficiency: int = 60) -> dict | None:
        """Plot a neutron-boosted route from source to destination.

        Args:
            source       — starting system name
            destination  — ending system name
            range_ly     — ship's FSD jump range (laden, light years)
            efficiency   — route efficiency 1-100 (lower = faster but more jumps;
                           Spansh default is 60).

        Returns the full Spansh response dict on success (contains the
        'jumps' list, each entry with system_name, system_address, distance,
        distance_jumped, distance_left, neutron_star bool), None on failure
        or timeout.

        Callable via core.plugin_call('spansh', 'plot_neutron_route', ...).
        Stores last successful result on state.spansh_neutron_route.
        """
        return self._plot_route(_SPANSH_NEUTRON, {
            "from":        source,
            "to":          destination,
            "range":       float(range_ly),
            "efficiency":  int(efficiency),
        }, store_key="spansh_neutron_route")

    def plot_fsd_route(self, source: str, destination: str,
                       range_ly: float, is_supercharged: bool = False,
                       use_supercharge: bool = True,
                       use_injections: bool = False,
                       exclude_secondary: bool = False) -> dict | None:
        """Plot a vanilla-FSD route from source to destination.

        Args:
            source / destination — system names
            range_ly             — ship's FSD jump range
            is_supercharged      — start from a supercharged FSD
            use_supercharge      — allow neutron supercharges (one-shot boosts;
                                   different from /api/route which is fully
                                   neutron-routed)
            use_injections       — allow FSD injection synthesis
            exclude_secondary    — exclude secondary stars

        Returns the Spansh response on success, None on failure.
        Stores last result on state.spansh_fsd_route.
        """
        return self._plot_route(_SPANSH_FSD, {
            "from":               source,
            "to":                 destination,
            "range":              float(range_ly),
            "is_supercharged":    bool(is_supercharged),
            "use_supercharge":    bool(use_supercharge),
            "use_injections":     bool(use_injections),
            "exclude_secondary":  bool(exclude_secondary),
        }, store_key="spansh_fsd_route")

    def _plot_route(self, post_url: str, params: dict, store_key: str) -> dict | None:
        """Common driver: POST job, poll results, return parsed dict.

        Spansh accepts the parameters as application/x-www-form-urlencoded.
        The POST returns either {"job": "<job_id>"} or {"error": "..."}.
        Polling /api/results/{job_id} returns {"status":"queued|in_progress|ok|error",
        "result": {...}} when complete.
        """
        try:
            body = urllib.parse.urlencode(params).encode("utf-8")
            req = urllib.request.Request(
                post_url,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status != 200:
                    return None
                start = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            print(f"  [Spansh] Route POST failed ({type(exc).__name__}: {exc})")
            return None

        job_id = start.get("job")
        if not job_id:
            err = start.get("error") or "no job id"
            print(f"  [Spansh] Route plot rejected: {err}")
            return None

        # Poll for completion
        deadline = time.monotonic() + self._ROUTE_POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(self._ROUTE_POLL_INTERVAL_S)
            try:
                with urllib.request.urlopen(
                    f"{_SPANSH_RESULTS}/{job_id}", timeout=8,
                ) as resp:
                    if resp.status != 200:
                        continue
                    poll = json.loads(resp.read().decode("utf-8"))
            except Exception:
                continue
            status = poll.get("status")
            if status == "ok":
                result = poll.get("result") or {}
                # Publish on state for any consumer (UI block, REPL, etc).
                setattr(self.core.state, store_key, result)
                return result
            if status == "error":
                print(
                    f"  [Spansh] Route plot error: "
                    f"{poll.get('error','unknown')}"
                )
                return None
            # "queued" or "in_progress" — continue polling

        print(f"  [Spansh] Route plot timed out after {self._ROUTE_POLL_TIMEOUT_S}s")
        return None

    def get_last_route(self, kind: str = "neutron") -> dict | None:
        """Return the most recent plotted route of the given kind, or None.

        Kind is 'neutron' or 'fsd'.  Callable via core.plugin_call('spansh',
        'get_last_route', 'neutron').
        """
        key = f"spansh_{kind}_route" if kind in ("neutron", "fsd") else None
        if not key:
            return None
        return getattr(self.core.state, key, None)

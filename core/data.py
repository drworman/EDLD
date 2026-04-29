"""
core/data.py — Unified DataProvider for EDLD.

Single source of truth for all game state. All core components, activity
plugins, and third-party plugins read from here rather than from individual
state fields or by scanning journals themselves.

Priority order: CAPI > Journal events > local JSON files.

Public API
----------
All access is via the DataProvider instance exposed as core.data.

  Ship vitals (live, sub-second via Status.json):
    data.ship.hull()            → int pct
    data.ship.shields()         → bool
    data.ship.shields_recharging() → bool
    data.ship.fuel_pct()        → float (0–100)
    data.ship.fuel_tons()       → float (main tank tons)
    data.ship.fuel_rate()       → float | None  (t/hr, None until established)
    data.ship.fuel_remaining_s()→ float | None  (seconds of fuel left)
    data.ship.identity()        → dict {name, ident, type, type_display, rebuy, value}

  Commander:
    data.commander.name()       → str | None
    data.commander.location()   → dict {system, body}
    data.commander.credits()    → float | None  (CAPI > journal)
    data.commander.ranks()      → dict  (CAPI > journal)
    data.commander.powerplay()  → dict {power, rank, merits_total}
    data.commander.squadron()   → dict {name, tag, rank}
    data.commander.mode()       → str | None  ("Solo", "Group", etc.)

  Fleet (CAPI primary, journal fallback):
    data.fleet.current_ship()   → dict | None
    data.fleet.stored_ships()   → list[dict]
    data.fleet.stored_modules() → list[dict]
    data.fleet.carrier()        → dict | None

  Market (CAPI docked+authed, Market.json fallback):
    data.market.commodities()   → dict {name_lower: commodity_dict}
    data.market.station_info()  → dict {station_name, market_id, star_system}
    data.market.mean_prices()   → dict {name_lower: int}

  Fighter / NPC crew:
    data.crew.active()          → bool
    data.crew.name()            → str | None
    data.crew.rank()            → str | None
    data.crew.total_paid()      → float | None
    data.crew.slf_hull()        → int pct
    data.crew.slf_deployed()    → bool
    data.crew.slf_type()        → str | None
    data.crew.has_fighter_bay() → bool

  Event ring buffer (last N journal events of any type):
    data.events(event_type, n=1)  → list[dict]  (newest first)

  Source transparency:
    data.source(key)            → "capi" | "journal" | "status_json" | "unknown"

  CAPI auth (for preferences UI):
    data.capi.is_connected()    → bool
    data.capi.commander_name()  → str | None
    data.capi.auth_status()     → dict
    data.capi.authenticate()    (starts OAuth flow)
    data.capi.disconnect()
    data.capi.manual_poll()
    data.capi.request_refresh(endpoint, min_age_s)
    data.capi.last_poll(endpoint) → float (unix ts)

Architecture notes
------------------
DataProvider wraps MonitorState rather than replacing it. state.* fields are
still the underlying store — DataProvider provides a clean typed API over them
so consumers never need to know field names or which source provided the data.

CAPI machinery (OAuth, polling, token management) lives in CAPISource, a
private inner object that runs the background poll thread. CAPISource is
configured here rather than as a standalone plugin.

The event ring buffer holds the last RING_SIZE events (default 200) per event
type. Consumers call data.events("HullDamage", n=5) to get the 5 most recent
HullDamage events, newest first.
"""

from __future__ import annotations

import json
import queue
import secrets
import socket
import threading
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── Ring buffer size ──────────────────────────────────────────────────────────

RING_SIZE = 200   # max events stored per event type

# ── CAPI constants ────────────────────────────────────────────────────────────

CAPI_BASE    = "https://companion.orerve.net"
AUTH_BASE    = "https://auth.frontierstore.net"
CLIENT_ID    = "61b25957-b56c-4a68-b1f0-4c9bf46dd00c"
REDIRECT_URI = "https://drworman.github.io/EDLD/auth/callback"
SCOPE        = "auth capi"

EP_PROFILE       = "profile"
EP_MARKET        = "market"
EP_SHIPYARD      = "shipyard"
EP_FLEETCARRIER  = "fleetcarrier"
EP_COMMUNITYGOALS = "communitygoals"
ALL_ENDPOINTS = [EP_PROFILE, EP_MARKET, EP_SHIPYARD, EP_FLEETCARRIER, EP_COMMUNITYGOALS]
EP_URLS = {
    EP_PROFILE:       f"{CAPI_BASE}/profile",
    EP_MARKET:        f"{CAPI_BASE}/market",
    EP_SHIPYARD:      f"{CAPI_BASE}/shipyard",
    EP_FLEETCARRIER:  f"{CAPI_BASE}/fleetcarrier",
    EP_COMMUNITYGOALS:f"{CAPI_BASE}/communitygoals",
}
EP_COOLDOWN = {
    EP_PROFILE:       30,
    EP_MARKET:        60,
    EP_SHIPYARD:      60,
    EP_FLEETCARRIER:  120,
    EP_COMMUNITYGOALS:300,
}
AUTH_TIMEOUT_S        = 120
TOKEN_REFRESH_MARGIN_S = 60
STARTUP_DELAY_S        = 10
HTTP_EXPIRED           = 422


# ── Helpers (from capi/plugin.py) ─────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _make_pkce() -> tuple[str, str]:
    import hashlib, os
    verifier  = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge

class _SilentHandler(urllib.request.BaseHandler):
    def http_error_default(self, req, fp, code, msg, hdrs):
        raise urllib.error.HTTPError(req.full_url, code, msg, hdrs, fp)

def _http_post(url: str, data: dict, timeout: int = 20) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req  = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def _http_get(url: str, token: str, timeout: int = 20) -> dict:
    class _NR(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
    opener = urllib.request.build_opener(_NR(), _SilentHandler())
    req    = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read())

class _CallbackHandler(urllib.request.BaseHandler):
    """Minimal HTTP server to receive OAuth callback."""
    def __init__(self, result_q: queue.Queue):
        self._q = result_q
    def do_GET(self): pass   # implemented in _listen_for_callback

def _listen_for_callback(port: int, result_q: queue.Queue, timeout: int) -> None:
    import http.server
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = dict(urllib.parse.parse_qsl(parsed.query))
            code   = params.get("code")
            err    = params.get("error")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            msg = "Auth complete — return to EDLD." if code else "Auth failed."
            self.wfile.write(f"<html><body><p>{msg}</p></body></html>".encode())
            result_q.put(("code", code) if code else ("error", err))
        def log_message(self, fmt, *args): pass
    try:
        srv = http.server.HTTPServer(("127.0.0.1", port), H)
        srv.timeout = timeout
        srv.handle_request()
    except Exception:
        result_q.put(("error", None))


# ── Sub-namespaces ────────────────────────────────────────────────────────────

class _ShipView:
    def __init__(self, dp: "DataProvider"): self._dp = dp

    def hull(self) -> int:
        s = self._dp._state
        # CAPI hull supersedes journal hull — capi_ship_health is more accurate
        capi_h = getattr(s, "capi_ship_health", None)
        if capi_h:
            raw = capi_h.get("hull", None)
            if raw is not None:
                hf = float(raw)
                return round(hf / 10000) if hf > 1.0 else round(hf * 100)
        return getattr(s, "ship_hull", 100)

    def shields(self) -> bool:
        return bool(getattr(self._dp._state, "ship_shields", True))

    def shields_recharging(self) -> bool:
        return bool(getattr(self._dp._state, "ship_shields_recharging", False))

    def fuel_tons(self) -> float | None:
        return getattr(self._dp._state, "fuel_current", None)

    def fuel_pct(self) -> float | None:
        s    = self._dp._state
        cur  = getattr(s, "fuel_current", None)
        tank = getattr(s, "fuel_tank_size", None)
        if cur is None or not tank or tank <= 0:
            return None
        return cur / tank * 100

    def fuel_rate(self) -> float | None:
        return getattr(self._dp._state, "fuel_burn_rate", None)

    def fuel_remaining_s(self) -> float | None:
        cur  = self.fuel_tons()
        rate = self.fuel_rate()
        if cur is None or not rate or rate <= 0:
            return None
        return (cur / rate) * 3600

    def identity(self) -> dict:
        s = self._dp._state
        cur = getattr(s, "assets_current_ship", None) or {}
        return {
            "name":         getattr(s, "ship_name",  None) or cur.get("name",  ""),
            "ident":        getattr(s, "ship_ident", None) or cur.get("ident", ""),
            "type":         getattr(s, "pilot_ship",  None) or cur.get("type",  ""),
            "type_display": cur.get("type_display", getattr(s, "pilot_ship", "") or ""),
            "rebuy":        cur.get("rebuy", 0),
            "value":        cur.get("value", 0),
        }


class _CommanderView:
    def __init__(self, dp: "DataProvider"): self._dp = dp

    def name(self) -> str | None:
        return getattr(self._dp._state, "pilot_name", None)

    def location(self) -> dict:
        s = self._dp._state
        return {
            "system": getattr(s, "pilot_system", None),
            "body":   getattr(s, "pilot_body",   None),
        }

    def credits(self) -> float | None:
        # CAPI balance is authoritative
        bal = getattr(self._dp._state, "assets_balance", None)
        return bal

    def ranks(self) -> dict:
        s = self._dp._state
        # CAPI ranks supersede journal ranks
        capi_r = getattr(s, "capi_ranks", None)
        if capi_r:
            return dict(capi_r)
        # Fall back to journal rank fields
        r = {}
        if getattr(s, "pilot_rank", None) is not None:
            r["combat"] = s.pilot_rank
        return r

    def powerplay(self) -> dict:
        s = self._dp._state
        return {
            "power":        getattr(s, "pp_power",        None),
            "rank":         getattr(s, "pp_rank",         None),
            "merits_total": getattr(s, "pp_merits_total", None),
        }

    def squadron(self) -> dict:
        s = self._dp._state
        return {
            "name": getattr(s, "pilot_squadron_name", ""),
            "tag":  getattr(s, "pilot_squadron_tag",  ""),
            "rank": getattr(s, "pilot_squadron_rank", ""),
        }

    def mode(self) -> str | None:
        return getattr(self._dp._state, "pilot_mode", None)


class _FleetView:
    def __init__(self, dp: "DataProvider"): self._dp = dp

    def current_ship(self) -> dict | None:
        return getattr(self._dp._state, "assets_current_ship", None)

    def stored_ships(self) -> list:
        return getattr(self._dp._state, "assets_stored_ships", []) or []

    def stored_modules(self) -> list:
        return getattr(self._dp._state, "assets_stored_modules", []) or []

    def carrier(self) -> dict | None:
        return getattr(self._dp._state, "assets_carrier", None)


class _MarketView:
    def __init__(self, dp: "DataProvider"): self._dp = dp

    def commodities(self) -> dict:
        mkt = getattr(self._dp._state, "capi_market", None)
        if mkt:
            return mkt.get("commodities", {})
        return {}

    def station_info(self) -> dict:
        mkt = getattr(self._dp._state, "capi_market", None) or {}
        return {
            "station_name": mkt.get("station_name", ""),
            "market_id":    mkt.get("market_id",    0),
            "star_system":  mkt.get("star_system",  ""),
        }

    def mean_prices(self) -> dict:
        return getattr(self._dp._state, "cargo_mean_prices", {}) or {}


class _CrewView:
    def __init__(self, dp: "DataProvider"): self._dp = dp

    def active(self) -> bool:
        return bool(getattr(self._dp._state, "crew_active", False))

    def name(self) -> str | None:
        return getattr(self._dp._state, "crew_name", None)

    def rank(self) -> str | None:
        return getattr(self._dp._state, "crew_rank", None)

    def total_paid(self) -> float | None:
        return getattr(self._dp._state, "crew_total_paid", None)

    def slf_hull(self) -> int:
        return int(getattr(self._dp._state, "slf_hull", 100))

    def slf_deployed(self) -> bool:
        return bool(getattr(self._dp._state, "slf_deployed", False))

    def slf_type(self) -> str | None:
        return getattr(self._dp._state, "slf_type", None)

    def has_fighter_bay(self) -> bool:
        return bool(getattr(self._dp._state, "has_fighter_bay", False))


# ── CAPISource ────────────────────────────────────────────────────────────────

class CAPISource:
    """
    Manages CAPI OAuth, token lifecycle, and background polling.
    Owned exclusively by DataProvider — not a plugin.
    """

    def __init__(self, dp: "DataProvider", storage, print_fn=None):
        self._dp        = dp
        self._storage   = storage
        self._print     = print_fn or (lambda m: None)
        self._tokens:   dict  = {}
        self._lock      = threading.Lock()
        self._docked    = False
        self._poll_q: queue.Queue = queue.Queue(maxsize=32)
        self._last_refresh        = 0.0
        self._auth_result         = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Load saved tokens and start background poll thread."""
        loaded = self._load_tokens()
        if loaded.get("access_token"):
            self._tokens = loaded
            self._trace(f"Loaded saved CAPI tokens for {loaded.get('cmdr', 'unknown')}")
        self._thread = threading.Thread(
            target=self._poll_worker, daemon=True, name="data-capi-poll"
        )
        self._thread.start()
        threading.Timer(STARTUP_DELAY_S, self._enqueue, args=(None, False)).start()

    def stop(self) -> None:
        try:
            self._poll_q.put_nowait(None)
        except queue.Full:
            pass

    def notify_docked(self, docked: bool) -> None:
        self._docked = docked
        if not docked:
            self._enqueue(EP_PROFILE, False)

    # ── Public API (exposed via data.capi.*) ──────────────────────────────────

    def is_connected(self) -> bool:
        return bool(self._tokens.get("access_token"))

    def commander_name(self) -> str | None:
        # Prefer the in-game pilot name from the journal over the Frontier
        # OAuth account firstname (which is the account holder's real name).
        pilot = getattr(getattr(self._dp, "_state", None), "pilot_name", None)
        return pilot or self._tokens.get("cmdr")

    def auth_status(self) -> dict:
        t = self._tokens
        # pilot_name from the game journal is the actual in-game CMDR name.
        # The stored "cmdr" token field is the Frontier account firstname —
        # not the same thing.  Prefer pilot_name when available.
        pilot = getattr(getattr(self._dp, "_state", None), "pilot_name", None)
        return {
            "connected":   bool(t.get("access_token")),
            "cmdr":        pilot or t.get("cmdr"),
            "expiry":      t.get("expiry"),
            "fresh":       time.time() < t.get("expiry", 0) - TOKEN_REFRESH_MARGIN_S,
            "auth_result": self._auth_result,
        }

    def authenticate(self) -> None:
        threading.Thread(
            target=self._run_auth_flow, daemon=True, name="data-capi-auth"
        ).start()

    def disconnect(self) -> None:
        self._tokens = {}
        self._save_tokens({})

    def manual_poll(self) -> None:
        self._enqueue(None, True)

    def request_refresh(self, endpoint: str, min_age_s: float = 60) -> bool:
        s = self._dp._state
        last = (getattr(s, "capi_last_poll", None) or {}).get(endpoint, 0.0)
        if (time.time() - last) < min_age_s:
            return False
        self._enqueue(endpoint, False)
        return True

    def last_poll(self, endpoint: str) -> float:
        s = self._dp._state
        return (getattr(s, "capi_last_poll", None) or {}).get(endpoint, 0.0)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _trace(self, msg: str) -> None:
        self._print(f"  [CAPI] {msg}")

    def _load_tokens(self) -> dict:
        try:
            raw = self._storage.read_json("capi_tokens.json")
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _save_tokens(self, tokens: dict) -> None:
        try:
            self._storage.write_json(tokens, "capi_tokens.json")
        except Exception:
            pass

    def _enqueue(self, endpoint_or_none, force: bool) -> None:
        try:
            self._poll_q.put_nowait((endpoint_or_none, force))
        except queue.Full:
            pass

    def _valid_token(self) -> str | None:
        t  = self._tokens
        at = t.get("access_token")
        if not at:
            return None
        if time.time() > t.get("expiry", 0) - TOKEN_REFRESH_MARGIN_S:
            if not self._refresh_token():
                return None
            at = self._tokens.get("access_token")
        return at

    def _refresh_token(self) -> bool:
        rt = self._tokens.get("refresh_token")
        if not rt:
            return False
        try:
            resp = _http_post(f"{AUTH_BASE}/token", {
                "grant_type": "refresh_token", "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI, "refresh_token": rt,
            })
            at = resp.get("access_token")
            if not at:
                return False
            self._tokens.update({
                "access_token":  at,
                "refresh_token": resp.get("refresh_token", rt),
                "expiry":        time.time() + resp.get("expires_in", 7200),
            })
            self._save_tokens(self._tokens)
            return True
        except urllib.error.HTTPError as e:
            if e.code in (400, 401):
                self._tokens = {}
                self._save_tokens({})
            return False
        except Exception:
            return False

    def _run_auth_flow(self) -> None:
        try:
            verifier, challenge = _make_pkce()
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            nonce    = secrets.token_hex(8)
            state_p  = f"{port}:{nonce}"
            auth_url = (
                f"{AUTH_BASE}/auth?response_type=code&client_id={CLIENT_ID}"
                f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
                f"&scope={SCOPE}&code_challenge={challenge}"
                f"&code_challenge_method=S256&state={state_p}"
            )
            cb_q: queue.Queue = queue.Queue()
            threading.Thread(
                target=_listen_for_callback,
                args=(port, cb_q, AUTH_TIMEOUT_S), daemon=True
            ).start()
            webbrowser.open(auth_url)
            try:
                kind, value = cb_q.get(timeout=AUTH_TIMEOUT_S + 5)
            except queue.Empty:
                self._finish_auth("timeout"); return
            if kind == "error" or not value:
                self._finish_auth("error"); return

            resp = _http_post(f"{AUTH_BASE}/token", {
                "grant_type": "authorization_code", "client_id": CLIENT_ID,
                "code": value, "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            })
            at = resp.get("access_token")
            if not at:
                self._finish_auth("error"); return

            cmdr = None
            try:
                me   = _http_get(f"{AUTH_BASE}/decode", at)
                cmdr = me.get("usr", {}).get("firstname") or me.get("customer_id")
            except Exception:
                pass

            self._tokens = {
                "access_token":  at,
                "refresh_token": resp.get("refresh_token"),
                "expiry":        time.time() + resp.get("expires_in", 7200),
                "cmdr":          cmdr,
                "scope":         SCOPE,
            }
            self._save_tokens(self._tokens)
            self._finish_auth("ok")
            self.manual_poll()
        except Exception as exc:
            self._trace(f"Auth flow error: {exc}")
            self._finish_auth("error")

    def _finish_auth(self, result: str) -> None:
        self._auth_result = result
        gq = self._dp._gui_queue
        if gq:
            gq.put(("plugin_refresh", "capi"))

    def _poll_worker(self) -> None:
        while True:
            item = self._poll_q.get()
            if item is None:
                break
            pending = [item]
            while True:
                try:   pending.append(self._poll_q.get_nowait())
                except queue.Empty: break
            seen: dict = {}
            for ep, force in pending:
                seen[ep] = force or seen.get(ep, False)
            token = self._valid_token()
            if not token:
                continue
            if None in seen:
                self._do_full_cycle(token, force=seen[None])
            else:
                for ep, force in seen.items():
                    self._do_single(token, ep, force)

    def _elapsed_ok(self, endpoint: str, force: bool) -> bool:
        if force:
            return True
        s = self._dp._state
        last = (getattr(s, "capi_last_poll", None) or {}).get(endpoint, 0.0)
        return (time.time() - last) >= EP_COOLDOWN[endpoint]

    def _do_full_cycle(self, token: str, force: bool = False) -> None:
        self._do_single(token, EP_PROFILE, force)
        if self._docked:
            self._do_single(token, EP_MARKET,  force)
            self._do_single(token, EP_SHIPYARD, force)
        self._do_single(token, EP_FLEETCARRIER,    force)
        self._do_single(token, EP_COMMUNITYGOALS, force)

    def _do_single(self, token: str, endpoint: str, force: bool = False) -> None:
        if not self._elapsed_ok(endpoint, force):
            return
        try:
            data = _http_get(EP_URLS[endpoint], token)
        except urllib.error.HTTPError as e:
            if e.code == 404 and endpoint in (EP_FLEETCARRIER, EP_COMMUNITYGOALS):
                return
            if e.code in (HTTP_EXPIRED, 401):
                since = time.time() - self._last_refresh
                if since < 60:
                    return
                if self._refresh_token():
                    self._last_refresh = time.time()
                    new_token = self._tokens.get("access_token")
                    if new_token:
                        try:
                            data = _http_get(EP_URLS[endpoint], new_token)
                        except Exception:
                            return
                    else:
                        return
                else:
                    gq = self._dp._gui_queue
                    if gq: gq.put(("plugin_refresh", "capi"))
                    return
            return
        except Exception:
            return

        if not data:
            return

        s = self._dp._state
        if not hasattr(s, "capi_raw"):
            s.capi_raw       = {}
            s.capi_last_poll = {}
        s.capi_raw[endpoint]       = data
        s.capi_last_poll[endpoint] = time.time()
        try:
            self._storage.write_json(data, f"capi_{endpoint}.json")
        except Exception:
            pass
        try:
            self._storage.write_json(
                {k: v for k, v in s.capi_last_poll.items()},
                "poll_times.json",
            )
        except Exception:
            pass

        # Extract to state
        extractor = getattr(self, f"_extract_{endpoint.replace('/', '_')}", None)
        if extractor:
            try:
                extractor(data, s)
            except Exception as exc:
                self._trace(f"{endpoint} extraction error: {exc}")

        gq = self._dp._gui_queue
        if gq:
            gq.put(("capi_updated", endpoint))
            if endpoint == EP_PROFILE:
                gq.put(("plugin_refresh", "assets"))
                gq.put(("plugin_refresh", "commander"))
            elif endpoint in (EP_MARKET, EP_SHIPYARD):
                gq.put(("plugin_refresh", "assets"))
                gq.put(("plugin_refresh", "cargo"))

        # Push credits to Inara after profile poll
        if endpoint == EP_PROFILE:
            bal = getattr(s, "assets_balance", None)
            if bal is not None:
                try:
                    self._dp._plugin_call("inara", "push_credits", int(bal))
                except Exception:
                    pass

    # ── Extractors ────────────────────────────────────────────────────────────

    @staticmethod
    def _capi_hull_pct(raw) -> int:
        h = float(raw) if raw is not None else 1000000
        return round(h / 10000) if h > 1.0 else round(h * 100)

    def _extract_profile(self, data: dict, state) -> None:
        from core.state import normalise_ship_name as _norm
        try:
            from components.assets.plugin import normalise_module_name as _nmn
        except ImportError:
            try:
                from components.assets.plugin import normalise_module_name as _nmn
            except ImportError:
                _nmn = lambda x: x

        def _make_loadout_list(modules_dict):
            result = []
            for sl, sm in (modules_dict or {}).items():
                mod  = sm.get("module") or sm
                mi   = mod.get("name", "")
                disp = mod.get("locName") or _nmn(mi)
                eng_raw = sm.get("engineer") or {}
                exp_raw = sm.get("specialModifications") or {}
                eng = {}
                if eng_raw.get("recipeName"):
                    eng["BlueprintName"]    = eng_raw["recipeName"]
                    eng["Level"]            = int(eng_raw.get("recipeLevel", 0))
                    eng["Quality"]          = 1.0
                    eng["BlueprintLocName"] = eng_raw.get("recipeLocName", "")
                    if exp_raw:
                        eng["ExperimentalEffect"] = next(iter(exp_raw))
                result.append({
                    "slot":          sl,
                    "name_internal": mi,
                    "name_display":  disp,
                    "on":            bool(mod.get("on", True)),
                    "priority":      int(mod.get("priority", 0)),
                    "value":         int(mod.get("value", 0)),
                    "health":        int(mod.get("health", 1000000)),
                    "engineering":   eng,
                })
            return result

        cmdr    = data.get("commander") or {}
        ship    = data.get("ship")      or {}
        ships   = data.get("ships")     or {}
        modules = data.get("modules")   or {}

        bal = cmdr.get("credits")
        if bal is not None:
            state.assets_balance = float(bal)
        debt = cmdr.get("debt")
        if debt is not None:
            state.capi_debt = float(debt)

        raw_ranks    = cmdr.get("rank",     {})
        raw_progress = cmdr.get("progress", {})
        raw_rep      = cmdr.get("reputation", {})
        raw_eng      = cmdr.get("engineerProgress", [])
        raw_stats    = cmdr.get("statistics")
        raw_permits  = cmdr.get("permits", [])

        if raw_ranks:
            state.capi_ranks    = {k: int(v) for k, v in raw_ranks.items()
                                   if isinstance(v, (int, float))}
        if raw_progress:
            state.capi_progress = {k: int(v) for k, v in raw_progress.items()
                                   if isinstance(v, (int, float))}
        if raw_rep:
            state.capi_reputation = {k: float(v) for k, v in raw_rep.items()
                                     if isinstance(v, (int, float))}
        if isinstance(raw_eng, list) and raw_eng:
            state.capi_engineer_ranks = [
                {
                    "name":     e.get("Engineer", ""),
                    "rank":     e.get("Rank"),
                    "progress": e.get("RankProgress"),
                    "unlocked": e.get("Rank") is not None,
                }
                for e in raw_eng if isinstance(e, dict)
            ]
        if raw_stats:
            state.capi_statistics = raw_stats
        if isinstance(raw_permits, list):
            state.capi_permits = raw_permits

        sq = data.get("squadron") or cmdr.get("squadron") or {}
        state.pilot_squadron_name = sq.get("name", "")
        state.pilot_squadron_tag = (
            sq.get("tag") or sq.get("Tag") or sq.get("TAG") or
            sq.get("shortName") or sq.get("ShortName") or
            sq.get("shortname") or sq.get("short_name") or ""
        )
        _sq_rank_raw = (
            sq.get("rank") or sq.get("Rank") or
            sq.get("rankName") or sq.get("currentRankName") or ""
        )
        # Strip Frontier localisation key wrapper: $SQUADRON_DEFAULTRANKNAME_RANK0;
        if _sq_rank_raw.startswith("$") and _sq_rank_raw.endswith(";"):
            _m = re.match(r"\$SQUADRON_(?:DEFAULT)?RANKNAME_(?:\w+);", _sq_rank_raw, re.I)
            _sq_rank_raw = ""  # unresolved key — show nothing rather than raw key
        state.pilot_squadron_rank = _sq_rank_raw

        if ship:
            ship_type   = ship.get("name",          "")
            ship_type_l = ship.get("nameLocalized") or ship_type
            health_obj  = ship.get("health",         {})
            value_obj   = ship.get("value",          {})
            location    = ship.get("starsystem",     {})

            state.capi_ship_health = {
                "hull":      health_obj.get("hull",      100.0),
                "shields":   health_obj.get("shieldup",  True),
                "paintwork": health_obj.get("paintwork", 1.0),
            }
            state.capi_ship_value = {
                "hull":    value_obj.get("hull",    0),
                "modules": value_obj.get("modules", 0),
                "cargo":   value_obj.get("cargo",   0),
                "total":   value_obj.get("total",   0),
                "free":    value_obj.get("free",    0),
            }
            hull_raw = health_obj.get("hull")
            if hull_raw is not None:
                hf = float(hull_raw)
                state.ship_hull = round(hf / 10000) if hf > 1.0 else round(hf * 100)
            shields_up = health_obj.get("shieldup")
            if shields_up is not None:
                state.ship_shields = bool(shields_up)
                if bool(shields_up):
                    state.ship_shields_recharging = False

            fitted = ship.get("modules") or {}
            state.capi_loadout = fitted

            state.assets_current_ship = {
                "_key":         "current",
                "current":      True,
                "ship_id":      ship.get("id"),
                "type":         ship_type,
                "type_display": ship_type_l,
                "name":         ship.get("shipName",  ""),
                "ident":        ship.get("shipIdent", ""),
                "system":       (location.get("name") if isinstance(location, dict)
                                 else getattr(state, "pilot_system", None)) or "—",
                "value":        value_obj.get("hull", 0),
                "hull":         self._capi_hull_pct(health_obj.get("hull", 1000000)),
                "rebuy":        value_obj.get("free", 0),
                "capi":         True,
                "loadout":      _make_loadout_list(fitted),
            }

        current_id = (getattr(state, "assets_current_ship", None) or {}).get("ship_id")
        journal_extra: dict = {}
        for es in getattr(state, "assets_stored_ships", []) or []:
            sid = es.get("ship_id")
            if sid is not None:
                journal_extra[sid] = {"system": es.get("system","—"), "hot": es.get("hot",False)}

        stored = []
        for sid_str, sv in ships.items():
            try:   sid = int(sid_str)
            except Exception: sid = sid_str
            if sid == current_id:
                continue
            val   = sv.get("value") or {}
            sv_h  = sv.get("health") or {}
            sv_hr = float(sv_h.get("hull", 1000000))
            loc   = sv.get("starsystem") or {}
            capi_sys = loc.get("name", "—") if isinstance(loc, dict) else "—"
            jx   = journal_extra.get(sid, {})
            sys_n = jx.get("system","—") if jx.get("system","—") != "—" else capi_sys
            stored.append({
                "_key":         f"ship_{sid}",
                "ship_id":      sid,
                "current":      False,
                "type":         sv.get("name", ""),
                "type_display": sv.get("nameLocalized") or _norm(sv.get("name", "")),
                "name":         sv.get("shipName",  ""),
                "ident":        sv.get("shipIdent", ""),
                "system":       sys_n,
                "value":        val.get("hull", 0),
                "rebuy":        val.get("free", 0),
                "hull":         self._capi_hull_pct(sv_h.get("hull", 1000000)),
                "hot":          jx.get("hot", False),
                "loadout":      _make_loadout_list(sv.get("modules") or {}),
                "capi":         True,
            })
        if stored:
            # CAPI /profile ships{} is the authoritative owned-ship list.
            # Replace state directly — do not merge with any prior list.
            # Ships absent from this response are no longer owned (sold,
            # transferred, etc.).  journal_extra location/hot enrichment
            # is already applied per-ship during the stored[] construction
            # above, so no data is lost by replacing rather than merging.
            state.assets_stored_ships = stored

        try:
            self._storage.write_json({
                "current_ship": state.assets_current_ship,
                "stored_ships": stored,
            }, "fleet.json")
        except Exception:
            pass

        cur = getattr(state, "assets_current_ship", None)
        if cur and current_id:
            capi_cur = ships.get(str(current_id)) or ships.get(current_id)
            if capi_cur:
                c_val = capi_cur.get("value") or {}
                c_h   = capi_cur.get("health") or {}
                cur["hull"]    = self._capi_hull_pct(c_h.get("hull", 1000000))
                cur["rebuy"]   = c_val.get("free", 0)
                cur["loadout"] = _make_loadout_list(capi_cur.get("modules") or {})
                if not cur.get("ident") and capi_cur.get("shipIdent"):
                    cur["ident"] = capi_cur["shipIdent"]
                if not cur.get("name") and capi_cur.get("shipName"):
                    cur["name"] = capi_cur["shipName"]

        if isinstance(modules, dict) and modules:
            mods = []
            for i, (slot, m) in enumerate(modules.items()):
                internal = m.get("name", "")
                disp     = m.get("nameLocalized") or internal
                mods.append({
                    "_key":          f"{i}_{internal}",
                    "name_internal": internal,
                    "name_display":  disp,
                    "slot":          slot,
                    "system":        "—",
                    "mass":          m.get("mass",  0.0),
                    "value":         m.get("value", 0),
                    "hot":           False,
                })
            if mods:
                state.assets_stored_modules = mods

    def _extract_communitygoals(self, data: dict, state) -> None:
        goals = data if isinstance(data, list) else data.get("communityGoals", [])
        state.capi_community_goals = [
            {
                "id":                   g.get("id"),
                "title":                g.get("title", ""),
                "expiry":               g.get("expiry", ""),
                "system":               g.get("starsystem", ""),
                "station":              (g.get("market", {}).get("name", "")
                                         if isinstance(g.get("market"), dict) else ""),
                "objective":            g.get("objective", ""),
                "description":          g.get("description", ""),
                "target_tier":          g.get("targetTier", 0),
                "current_tier":         g.get("tierReached", 0),
                "player_contribution":  g.get("contribution", 0),
                "player_reward":        g.get("reward", 0),
            }
            for g in (goals if isinstance(goals, list) else [])
        ]

    def _extract_market(self, data: dict, state) -> None:
        items = data.get("commodities") or data.get("items") or []
        if not isinstance(items, list):
            items = []
        processed = {}
        for c in items:
            key = (c.get("name") or "").lower()
            if not key:
                continue
            processed[key] = {
                "name":       c.get("name",        key),
                "name_local": c.get("displayName") or c.get("name", key),
                "buy_price":  int(c.get("buyPrice",  0)),
                "sell_price": int(c.get("sellPrice", 0)),
                "mean_price": int(c.get("meanPrice", 0)),
                "stock":      int(c.get("stock",     0)),
                "demand":     int(c.get("demand",    0)),
                "category":   c.get("categoryname", ""),
                "rare":       bool(c.get("rare",     False)),
            }
        state.capi_market = {
            "station_name": data.get("name",      ""),
            "market_id":    data.get("id",          0),
            "star_system":  data.get("starsystem", ""),
            "commodities":  processed,
        }
        mean_prices = {k: v["mean_price"] for k, v in processed.items() if v["mean_price"]}
        if mean_prices:
            state.cargo_mean_prices = mean_prices

        # ── Fleet Carrier bartender (fcmaterials_capi/1) ─────────────────────
        # CAPI /market for a fleet carrier includes orders.onfootmicroresources
        # for the bartender service. Push to EDDN if present.
        orders = data.get("orders") or {}
        micro  = orders.get("onfootmicroresources")
        if micro is not None:
            import time as _time
            market_id  = data.get("id", 0)
            carrier_id = data.get("name", "")   # callsign is CAPI "name" field
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            try:
                self._dp._plugin_call(
                    "eddn", "push_fcmaterials_capi",
                    int(market_id), str(carrier_id), micro, ts,
                )
            except Exception:
                pass

    def _extract_shipyard(self, data: dict, state) -> None:
        ships_raw  = data.get("ships") or {}
        ships_list = []
        if isinstance(ships_raw, dict):
            for sid, sv in ships_raw.items():
                ships_list.append({
                    "type":       sv.get("name",          ""),
                    "name_local": sv.get("nameLocalized") or sv.get("name", ""),
                    "price":      int(sv.get("basevalue", 0)),
                })
        state.capi_shipyard = {
            "station_name": data.get("name", ""),
            "market_id":    data.get("id",    0),
            "ships":        ships_list,
        }

    def _extract_fleetcarrier(self, data: dict, state) -> None:
        def _int(v):
            try: return int(v)
            except Exception: return 0
        def _pct(v):
            try: return round(float(v), 1)
            except Exception: return 0.0
        def _decode_vanity(s: str) -> str:
            try:    return bytes.fromhex(s).decode("ascii").strip()
            except Exception: return s

        name_obj     = data.get("name") or {}
        callsign     = name_obj.get("callsign") or data.get("callsign") or "—"
        raw_vanity   = name_obj.get("vanityName") or name_obj.get("filteredVanityName") or ""
        carrier_name = _decode_vanity(raw_vanity) if raw_vanity else callsign
        fin  = data.get("finance")  or {}
        cap  = data.get("capacity") or {}
        mkt  = data.get("market")   or {}
        tax  = fin.get("service_taxation") or {}
        state.assets_carrier = {
            "callsign":         callsign,
            "name":             carrier_name,
            "system":           data.get("currentStarSystem", "—"),
            "theme":            data.get("theme",   "—"),
            "fuel":             _int(data.get("fuel", 0)),
            "carrier_state":    data.get("state",   "—"),
            "docking":          data.get("dockingAccess") or "—",
            "notorious":        bool(data.get("notoriousAccess", False)),
            "balance":          _int(fin.get("bankBalance",         0)),
            "reserve":          _int(fin.get("bankReservedBalance",  0)),
            "available":        _int(fin.get("bankBalance", 0)) - _int(fin.get("bankReservedBalance", 0)),
            "tax_refuel":       _pct(tax.get("refuel",          0)),
            "tax_repair":       _pct(tax.get("repair",          0)),
            "tax_rearm":        _pct(tax.get("rearm",           0)),
            "tax_pioneer":      _pct(tax.get("pioneersupplies", 0)),
            "maintenance":      _int(fin.get("maintenance",       0)),
            "maintenance_wtd":  _int(fin.get("maintenanceToDate", 0)),
            "cargo_crew":       _int(cap.get("crew",             0)),
            "cargo_free":       _int(cap.get("freeSpace",        0)),
            "cargo_used":       (_int(cap.get("cargoForSale",    0)) +
                                 _int(cap.get("cargoNotForSale", 0)) +
                                 _int(cap.get("cargoSpaceReserved", 0))),
            "ship_packs":       _int(cap.get("shipPacks",   0)),
            "module_packs":     _int(cap.get("modulePacks", 0)),
            "micro_total":      _int(cap.get("microresourceCapacityTotal", 0)),
            "micro_free":       _int(cap.get("microresourceCapacityFree",  0)),
            "micro_used":       _int(cap.get("microresourceCapacityUsed",  0)),
            "services":         dict(mkt.get("services") or {}),
            "capi":             True,
        }

        # Extract full physical cargo hold — CAPI format:
        # [{"commodity": "steel", "qty": 3720, "value": N}, ...]
        # This includes unlisted cargo (e.g. colonisation bulk goods) that
        # FCMaterials and Market.json do not expose.
        cargo_hold: dict = {}
        for item in (data.get("cargo") or []):
            name = (item.get("commodity") or "").lower().strip()
            qty  = _int(item.get("qty", 0))
            if name and qty > 0:
                cargo_hold[name] = cargo_hold.get(name, 0) + qty
        state.assets_carrier_hold = cargo_hold

        # Notify the colonisation plugin with the authoritative cargo snapshot.
        if cargo_hold:
            try:
                self._dp._plugin_call("colonisation", "on_capi_fleetcarrier", cargo_hold)
            except Exception:
                pass

class EventBuffer:
    """
    Ring buffer of recent journal events keyed by event type.
    Thread-safe. Holds the last RING_SIZE events per type.
    """

    def __init__(self, size: int = RING_SIZE):
        self._size  = size
        self._lock  = threading.Lock()
        self._store: dict[str, deque] = {}

    def push(self, event: dict) -> None:
        ev_type = event.get("event")
        if not ev_type:
            return
        with self._lock:
            if ev_type not in self._store:
                self._store[ev_type] = deque(maxlen=self._size)
            self._store[ev_type].appendleft(event)

    def get(self, event_type: str, n: int = 1) -> list[dict]:
        with self._lock:
            buf = self._store.get(event_type)
            if not buf:
                return []
            return list(buf)[:n]

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# ── DataProvider ──────────────────────────────────────────────────────────────

class DataProvider:
    """
    Unified data provider — single source of truth for all EDLD consumers.

    Instantiated once by edld.py and exposed as core.data.
    All core components, activity plugins, and third-party plugins read
    from here. No consumer should access MonitorState fields directly.
    """

    def __init__(self, state, storage, gui_queue_fn=None, plugin_call_fn=None,
                 print_fn=None):
        self._state       = state
        self._storage     = storage
        self._gui_queue_fn = gui_queue_fn   # callable → queue | None
        self._plugin_call  = plugin_call_fn or (lambda *a, **k: None)
        self._print        = print_fn or (lambda m: None)

        # Public sub-namespaces
        self.ship       = _ShipView(self)
        self.commander  = _CommanderView(self)
        self.fleet      = _FleetView(self)
        self.market     = _MarketView(self)
        self.crew       = _CrewView(self)
        self.capi       = CAPISource(self, storage, print_fn)

        # Event ring buffer
        self._buffer    = EventBuffer()

        # Source tracking
        self._sources: dict[str, str] = {}

    @property
    def _gui_queue(self):
        if self._gui_queue_fn:
            return self._gui_queue_fn()
        return None

    def start(self) -> None:
        """Start background services (CAPI poll thread)."""
        self.capi.start()

    def stop(self) -> None:
        """Shut down background services."""
        self.capi.stop()

    # ── Event ring buffer ─────────────────────────────────────────────────────

    def push_event(self, event: dict) -> None:
        """Called by journal.py for every event during preload and live monitoring."""
        self._buffer.push(event)

    def events(self, event_type: str, n: int = 1) -> list[dict]:
        """
        Return the last *n* journal events of the given type, newest first.

        Example:
            recent_hull = core.data.events("HullDamage", n=3)
        """
        return self._buffer.get(event_type, n)

    # ── Source transparency ───────────────────────────────────────────────────

    def set_source(self, key: str, source: str) -> None:
        """Record which source provided a given data key. Called by extractors."""
        self._sources[key] = source

    def source(self, key: str) -> str:
        """
        Return the source that last provided a data key.
        Returns one of: "capi", "journal", "status_json", "unknown".

        Example:
            src = core.data.source("ship.hull")  # → "capi"
        """
        return self._sources.get(key, "unknown")

    # ── CAPI dock notification ────────────────────────────────────────────────

    def notify_docked(self, docked: bool) -> None:
        """Called by journal processing when Docked/Undocked events fire."""
        self.capi.notify_docked(docked)

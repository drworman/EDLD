"""
core/server/duckdns.py — keep a DuckDNS name pointed at this connection.

Off unless ``[Server] DuckDNSDomain`` and ``DuckDNSToken`` are both set.  Many
people already run DuckDNS's own updater, or have their router do it; they
leave these blank and nothing here runs.

When set, EDLD sends DuckDNS one HTTPS request at start and every ten minutes,
leaving the address blank so DuckDNS records the one the request came from.
That is the only contact with any outside service server mode ever makes, and
it happens only because the commander asked for it.

The token is a credential.  It is never logged, and the config key's name puts
it under the trace log's redaction.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

UPDATE_URL = "https://www.duckdns.org/update"
INTERVAL_S = 600


def domain_only(domain: str) -> str:
    """``cmdr``, from any of ``cmdr``, ``cmdr.duckdns.org`` or a pasted URL."""
    d = str(domain or "").strip().lower()
    if "://" in d:
        d = urllib.parse.urlparse(d).hostname or ""
    if d.endswith(".duckdns.org"):
        d = d[: -len(".duckdns.org")]
    return d.strip(".")


def hostname(domain: str) -> str:
    d = domain_only(domain)
    return f"{d}.duckdns.org" if d else ""


class DuckDNSUpdater:
    def __init__(self, domain: str, token: str, *,
                 log: Callable[[str], None] | None = None,
                 alert: Callable[[str], None] | None = None,
                 url: str = UPDATE_URL, interval_s: int = INTERVAL_S):
        self.domain = domain_only(domain)
        self._token = str(token or "").strip()
        self._log = log or (lambda m: None)
        self._alert = alert or (lambda m: None)
        self._url = url
        self._interval = interval_s
        self._stop = threading.Event()
        self.status = "not started"

    @property
    def configured(self) -> bool:
        return bool(self.domain and self._token)

    def update_once(self) -> tuple[bool, str]:
        query = urllib.parse.urlencode(
            {"domains": self.domain, "token": self._token, "ip": ""})
        try:
            with urllib.request.urlopen(f"{self._url}?{query}", timeout=15) as r:
                body = r.read(64).decode("ascii", "replace").strip()
        except urllib.error.HTTPError as e:
            return False, f"DuckDNS answered HTTP {e.code}"
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            return False, f"could not reach DuckDNS ({reason})"
        if body.startswith("OK"):
            return True, f"{hostname(self.domain)} updated"
        return False, ("DuckDNS refused the update — check the domain and the "
                       "token in [Server]")

    def start(self) -> None:
        if self.configured:
            threading.Thread(target=self._run, name="edld-duckdns",
                             daemon=True).start()

    def _run(self) -> None:
        last_ok: bool | None = None
        while not self._stop.is_set():
            ok, text = self.update_once()
            self.status = text
            if ok != last_ok:
                # Reported on a change of state, not every ten minutes.
                self._log(f"[server] DuckDNS: {text}")
                if not ok:
                    self._alert(f"DuckDNS: {text}")
                last_ok = ok
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()

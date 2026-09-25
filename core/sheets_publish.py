"""
core/sheets_publish.py — Publishing the surface survey to a Google Sheet.

EDLD POSTs batches of deposits to an Apps Script web app bound to the target
spreadsheet. The script is in ``sheets/Code.gs`` and the setup walkthrough in
``sheets/README.md``.

Why Apps Script and not the Sheets API
--------------------------------------
Writing to Sheets needs OAuth or a service account; an API key authenticates
reads of public data and nothing else. Both alternatives cost the user a
Google Cloud project, and neither can ship in an open-source binary — an
embedded client secret is a published one. An Apps Script deployment needs no
project, no OAuth, and no Google client library: it is a URL and a token, which
is also the whole of what a squadron leader has to hand out.

Why the dedupe is on the far side
---------------------------------
Only the sheet knows what is in the sheet. Several commanders write to a
squadron sheet and none of them can see the others' local stores, so a client
that checked before sending would still have two of them appending the same
deposit on the same evening, each correct about what it had seen. The script
holds a lock and resolves it.

EDLD's side of the contract is the deposit id: same system, same body, same
commodity, within 75 m is one deposit with one stable id, worked out here where
the body radius is known. The script matches on that string and never has to
reimplement the geometry.

Failure is reported, never assumed
----------------------------------
Every send returns a :class:`PublishResult` that says plainly whether the rows
landed. Deposits are only marked published on an explicit ``ok`` from the
script with a matching count; a transport error, an HTML error page, a bad
token or a partial write all leave the rows pending, so the next flush retries
them rather than losing them to a success that never happened.

Apps Script redirect handling
-----------------------------
Google Apps Script web apps return ContentService responses through a redirect
to a temporary script.googleusercontent.com URL.

The correct flow is:

    POST /macros/s/<deployment>/exec
        -> 302
        -> GET https://script.googleusercontent.com/...

The redirected URL is not another POST endpoint. Re-posting the original body
to that URL causes HTTP 405.

Therefore this module explicitly converts 301/302/303 redirects to GET.
307/308 redirects retain the original POST, as required by HTTP semantics.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, Optional
from urllib.parse import urlparse


#: Config section owned by this module and the surface_mining component.
CFG_DEFAULTS = {
    "Enabled": False,
    "WebAppURL": "",
    "Token": "",
    "ReporterName": "",
    "IncludeTest": False,
    "MarkFindsAsTest": False,
    "BatchSize": 200,
    "Fetch": True,            # read other commanders' deposits back down
    "AutoConfirm": True,
    "ConfirmMetres": 25.0,
}


#: Must match COLUMNS in sheets/Code.gs, in the same order.
COLUMNS = (
    "deposit_id",
    "system",
    "system_address",
    "body",
    "body_id",
    "planet_class",
    "gravity",
    "body_radius_m",
    "atmosphere",
    "volcanism",
    "signal_no",
    "commodity",
    "latitude",
    "longitude",
    "density_claimed",
    "density_observed",
    "amount",
    "rigs",
    "refine_count",
    "first_seen",
    "last_confirmed",
    "reported_by",
    "is_test",
    "depleted_on",
    "notes",
    "notes_updated",
    "assessment_updated",
)


_TIMEOUT_S = 30

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)


class _AppsScriptRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Handle Apps Script web-app redirects correctly.

    Apps Script commonly returns:

        POST /exec -> 302 -> GET script.googleusercontent.com/...

    The old implementation deliberately preserved POST across 302, which is
    the cause of the HTTP 405 response from the redirected Google endpoint.

    301/302/303:
        Convert POST to GET.

    307/308:
        Preserve the original method and body.
    """

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        if code in (301, 302, 303):
            return urllib.request.Request(
                newurl,
                data=None,
                method="GET",
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                },
                origin_req_host=req.origin_req_host,
                unverifiable=True,
            )

        if code in (307, 308):
            request_headers = {
                key: value
                for key, value in req.header_items()
                if key.lower() not in ("host", "content-length")
            }

            return urllib.request.Request(
                newurl,
                data=req.data,
                method=req.get_method(),
                headers=request_headers,
                origin_req_host=req.origin_req_host,
                unverifiable=True,
            )

        return None


@dataclass
class PublishResult:
    ok: bool = False
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    error: str = ""
    sent_ids: list[str] = field(default_factory=list)
    deposits: list[dict] = field(default_factory=list)
    #: How many columns the sheet's script knows, where it says (ping only).
    columns: int = 0

    @property
    def accounted(self) -> int:
        return self.added + self.updated + self.unchanged

    def summary(self) -> str:
        if not self.ok:
            return f"publish failed — {self.error}"

        return (
            f"published {self.added} new, "
            f"{self.updated} updated, "
            f"{self.unchanged} unchanged"
        )


def safe_endpoint(url: str) -> str:
    """Return only the host portion of a URL for logging."""
    try:
        host = urlparse(url).netloc
        return host or "<no host>"
    except Exception:
        return "<unparseable url>"


def row_from_deposit(
    dep: dict,
    reporter: str = "",
) -> dict:
    """Flatten a joined deposit row into the sheet's column set."""
    return {
        "deposit_id": dep.get("deposit_id", ""),
        "system": dep.get("system_name", "") or "",
        "system_address": dep.get("system_address"),
        "body": dep.get("body_name", "") or "",
        "body_id": dep.get("body_id"),
        "planet_class": dep.get("planet_class", "") or "",
        "gravity": dep.get("gravity"),
        "body_radius_m": dep.get("radius_m"),
        "atmosphere": dep.get("atmosphere", "") or "",
        "volcanism": dep.get("volcanism", "") or "",
        "signal_no": dep.get("signal_no"),
        "commodity": (
            dep.get("commodity_display")
            or dep.get("commodity", "")
        ),
        "latitude": dep.get("latitude"),
        "longitude": dep.get("longitude"),
        "density_claimed": (
            dep.get("density_claimed", "") or ""
        ),
        "density_observed": (
            dep.get("density_observed", "") or ""
        ),
        "amount": dep.get("amount", "") or "",
        "rigs": dep.get("rigs"),
        "refine_count": dep.get("refine_count", 0),
        "first_seen": dep.get("first_seen", ""),
        "last_confirmed": dep.get("last_confirmed", ""),
        "reported_by": dep.get("reported_by") or reporter,
        "is_test": int(dep.get("is_test", 0) or 0),
        # When the site was last seen worked out. It lives in its own table
        # rather than on the deposit row, so the query feeding this fetches it
        # — and it belongs on the sheet because it is the one fact about a
        # deposit that any commander can contribute and every commander needs:
        # a site somebody emptied last week is a wasted trip.
        "depleted_on": (dep.get("depleted_on", "") or "")[:10],
        # The note travels with the moment it was written, and the sheet keeps
        # whichever is newer — a blank included, since that is a withdrawal.
        # See the Notes section of core/mining_db.py for why last_confirmed
        # cannot stand in for it.
        "notes": dep.get("notes", "") or "",
        "notes_updated": dep.get("notes_updated", "") or "",
        # When amount or density was last corrected by hand. The sheet lets a
        # newer correction replace its values and otherwise only fills blanks,
        # so a later sighting cannot put back a value somebody fixed.
        "assessment_updated": dep.get("assessment_updated", "") or "",
    }


class SheetsPublisher:
    """Posts deposit batches to an Apps Script endpoint."""

    def __init__(
        self,
        url: str,
        token: str,
        log=None,
        opener=None,
        timeout: int = _TIMEOUT_S,
    ) -> None:
        self._url = (url or "").strip()
        self._token = (token or "").strip()
        self._log = log or (lambda _m: None)
        self._timeout = timeout
        self._lock = threading.Lock()

        # Injected in tests.
        #
        # Signature:
        #     (url, data_bytes, timeout) -> str
        self._opener = opener or self._urlopen

    @property
    def configured(self) -> bool:
        return bool(self._url and self._token)

    # ── transport ────────────────────────────────────────────────────────────

    def _urlopen(
        self,
        url: str,
        data: bytes,
        timeout: int,
    ) -> str:
        """POST JSON to Apps Script and return the final response body."""

        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": _USER_AGENT,
                "Accept": "application/json, text/plain, */*",
            },
        )

        opener = urllib.request.build_opener(
            _AppsScriptRedirectHandler()
        )

        with opener.open(req, timeout=timeout) as response:
            return response.read().decode(
                "utf-8",
                errors="replace",
            )

    @staticmethod
    def _http_error_text(
        exc: urllib.error.HTTPError,
    ) -> str:
        """Return a compact representation of an HTTP error body."""

        try:
            raw = exc.read().decode(
                "utf-8",
                errors="replace",
            )
        except Exception:
            return ""

        text = " ".join((raw or "").split())

        if len(text) > 300:
            text = text[:300] + "..."

        return text

    def _post(
        self,
        payload: dict,
    ) -> PublishResult:
        """POST one request and convert the response to PublishResult."""

        if not self.configured:
            return PublishResult(
                error="no web app URL or token configured"
            )

        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        try:
            raw = self._opener(
                self._url,
                body,
                self._timeout,
            )

        except urllib.error.HTTPError as exc:
            response = self._http_error_text(exc)

            error = (
                f"HTTP {exc.code} from "
                f"{safe_endpoint(self._url)}"
            )

            if response:
                error += f": {response}"

            return PublishResult(error=error)

        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)

            return PublishResult(
                error=(
                    f"cannot reach "
                    f"{safe_endpoint(self._url)}: "
                    f"{reason}"
                )
            )

        except TimeoutError:
            return PublishResult(
                error=(
                    f"request timed out after "
                    f"{self._timeout}s at "
                    f"{safe_endpoint(self._url)}"
                )
            )

        except Exception as exc:
            return PublishResult(
                error=f"{type(exc).__name__}: {exc}"
            )

        try:
            data = json.loads(raw)

        except (ValueError, TypeError):
            text = " ".join(
                (raw or "").strip().split()
            )

            if len(text) > 300:
                text = text[:300] + "..."

            return PublishResult(
                error=(
                    f"unreadable response from "
                    f"{safe_endpoint(self._url)}"
                    + (
                        f": {text}"
                        if text
                        else ": empty response"
                    )
                )
            )

        if not isinstance(data, dict):
            return PublishResult(
                error="invalid JSON response from sheet endpoint"
            )

        if not data.get("ok"):
            return PublishResult(
                error=str(
                    data.get(
                        "error",
                        "rejected",
                    )
                )
            )

        try:
            added = int(data.get("added", 0))
            updated = int(data.get("updated", 0))
            unchanged = int(data.get("unchanged", 0))
        except (TypeError, ValueError):
            return PublishResult(
                error="sheet returned invalid result counts"
            )

        try:
            columns = int(data.get("columns", 0) or 0)
        except (TypeError, ValueError):
            columns = 0

        return PublishResult(
            ok=True,
            added=added,
            updated=updated,
            unchanged=unchanged,
            deposits=list(data.get("deposits") or []),
            columns=columns,
        )

    # ── public API ───────────────────────────────────────────────────────────

    def test_connection(self) -> PublishResult:
        """Round-trip a ping through the Apps Script web app."""

        with self._lock:
            result = self._post(
                {
                    "token": self._token,
                    "ping": True,
                }
            )

        # A script deployed before a column was added accepts every write and
        # quietly drops the fields it has no column for, so nothing else would
        # ever say the sheet is not storing them. This is the one place that
        # can: the ping reports the script's column count.
        if result.ok and 0 < result.columns < len(COLUMNS):
            missing = ", ".join(COLUMNS[result.columns:])
            result.ok = False
            result.error = (
                f"the sheet's script is out of date — it stores "
                f"{result.columns} columns and this EDLD sends {len(COLUMNS)} "
                f"(missing: {missing}). Paste the current sheets/Code.gs into "
                f"the sheet's Apps Script and deploy a new version"
            )

        self._log(
            f"sheet test — {result.summary()}"
        )

        return result

    def fetch_body(self, system_address: int,
                   body_id: int) -> tuple[list[dict], str]:
        """Everything the sheet knows about one body.

        Returns ``(rows, error)``; an error is a string and the rows are empty.

        Scoped to a body rather than fetching the whole sheet because that is
        the question actually being asked — a commander arriving somewhere
        wants to know what is on *this* rock, and a squadron sheet will
        eventually have more rows than anyone wants to pull down to answer it.
        """
        with self._lock:
            result = self._post(
                {
                    "token": self._token,
                    "fetch": {
                        "system_address": int(system_address),
                        "body_id": int(body_id),
                    },
                }
            )
        if not result.ok:
            return [], result.error
        return list(result.deposits), ""

    def delete(self, deposit_id: str) -> PublishResult:
        """Remove one deposit from the sheet.

        A row, not a tombstone. Imported deposits are stamped as published and
        never re-sent, so the only copy that could put it back is the one held
        by whoever recorded it — and that is the commander doing the deleting.
        A commander who imported it will simply not see it again after their
        next fetch.
        """
        with self._lock:
            return self._post({"token": self._token,
                               "delete": {"deposit_id": str(deposit_id)}})

    def publish(
        self,
        deposits: Iterable[dict],
        reporter: str = "",
    ) -> PublishResult:
        """Send one batch.

        ``sent_ids`` is populated only when Apps Script explicitly returns
        ``ok`` and accounts for every submitted row.
        """

        rows: list[dict] = []
        ids: list[str] = []

        for dep in deposits:
            row = row_from_deposit(
                dep,
                reporter,
            )

            if not row["deposit_id"]:
                continue

            rows.append(row)
            ids.append(row["deposit_id"])

        if not rows:
            return PublishResult(ok=True)

        with self._lock:
            result = self._post(
                {
                    "token": self._token,
                    "deposits": rows,
                }
            )

        if not result.ok:
            self._log(
                f"{len(rows)} deposit(s) not published — "
                f"{result.error}"
            )
            return result

        if result.accounted != len(rows):
            result.ok = False

            result.error = (
                f"sheet accounted for "
                f"{result.accounted} of "
                f"{len(rows)} row(s); "
                f"left pending for retry"
            )

            self._log(result.error)

            return result

        result.sent_ids = ids

        self._log(result.summary())

        return result


def publisher_from_config(
    cfg: dict,
    log=None,
) -> Optional[SheetsPublisher]:
    """Build a publisher from a config section.

    Returns None if publishing is disabled or incompletely configured.
    """

    if not cfg or not cfg.get("Enabled"):
        return None

    pub = SheetsPublisher(
        cfg.get("WebAppURL", ""),
        cfg.get("Token", ""),
        log=log,
    )

    if not pub.configured:
        if log:
            log(
                "sheet publishing is enabled but has no "
                "URL or token"
            )

        return None

    return pub

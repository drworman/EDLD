"""
components/surface_mining.py — Planetary surface mining survey.

Records where surface deposits are, automatically, while you mine them.

The 4.4.1 surface mining feature added no journal events.  What it added was a
new ``SAASignalsFound`` signal type — ``$PlanetaryMiningLocation_Name;``, which
says how many mining location signals a body has — and a set of commodities
that come out of ``MiningRefined`` exactly as ring ore does.  Neither carries
a position.

So the survey is built from two joins:

  body census    A surface scan reports the mining location count for the body
                 before any of them has been visited.  ``components.mining``
                 already recognises this token and discards it, correctly, so
                 it does not appear in the hotspot table as "Human 3 hotspots".
                 Here it is the thing being counted.

  deposit        A ``MiningRefined`` arriving while the commander is in an SRV
                 with a live latitude is proof of a deposit underneath them.
                 The position comes from the Status.json ring in
                 :mod:`core.surface_survey`, matched on time.

Nothing has to be pressed and nothing has to be set up.  A deposit you drove
to and dug is recorded because you dug it.

Tab title: Survey
"""

from __future__ import annotations

import threading
import time

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core import mining_db
from core.mining_db import AMOUNT_LEVELS, DENSITY_LEVELS
from core import surface_survey as survey
from core.surface_survey import POSITIONS, canonical_commodity, parse_journal_ts
from core.sheets_publish import CFG_DEFAULTS as SHEET_DEFAULTS, publisher_from_config
from core.overlay_content import nearest_deposits
from core.proximity import DEFAULT_ENTER_M, ProximityTracker, distances_to

#: A run of refines from one deposit produces hundreds of events — 608 in one
#: real session.  Every one of them resolves to the same row, but resolving it
#: means a distance query per event.  Refines closer together than this against
#: the same resolved deposit are collapsed into a counter and flushed once.
_CONFIRM_INTERVAL_S = 15.0

#: How often the proximity check runs. Matches the Status.json write rate; an
#: SRV at 30 m/s covers 15 m between samples, comfortably inside the 25 m
#: arrival radius, so a deposit cannot be driven past unnoticed.
_PROX_TICK_S = 0.5

#: Older than this and a MiningRefined is history being replayed at startup
#: rather than something that just happened. Generous, because the journal is
#: written in batches and a live event can be many seconds old by the time it
#: is read.
_LIVE_MAX_LAG_S = 120.0

#: Overlay redraw cadence. Status.json is rewritten twice a second and the SRV
#: does about 30 m/s, so half a second is roughly 15 m of lag on a bearing —
#: below what is readable on a compass tape.
_OVERLAY_TICK_S = 0.5

#: A position older than this means the game has stopped writing Status.json:
#: quit, alt-tabbed into a menu, or crashed. Bearings from it are fiction.
_POSITION_STALE_S = 3.0


def _gravity_g(raw) -> float | None:
    """Journal gravity is in m/s^2 scaled by 10; the game shows g."""
    try:
        return round(float(raw) / 9.80665, 3)
    except (TypeError, ValueError):
        return None


class SurfaceMiningPlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME        = "surface_mining"
    ACTIVITY_TAB_TITLE = "Survey"
    PLUGIN_DISPLAY     = "Surface Survey"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = ("Records planetary surface mining deposits and their "
                          "positions as they are worked.")

    SUBSCRIBED_EVENTS = [
        "SAASignalsFound",   # body census: how many mining locations exist
        "MiningRefined",     # the deposit itself, joined to a position
        "Scan",              # body facts: class, gravity, radius, atmosphere
        "Location",          # body identity on resume
        "FSDJump",           # the system name, which Scan may never supply
        "ApproachBody",
        "LeaveBody",
        "Touchdown",
        "SupercruiseExit",
    ]

    def on_load(self, core) -> None:
        self._core = core
        # Without this the component is not in core.session_providers and
        # get_tab_rows() is never called by either front end.
        core.register_session_provider(self)
        self._lock = threading.RLock()
        self._db = mining_db.get_db(log=self._log)

        # Current body, as far as the journal has said.  Status.json gives a
        # body *name* but no address or id, so the identity has to be carried
        # forward from the last journal event that supplied one.
        self._system_address: int | None = None
        self._system_name = ""
        self._body_id:     int | None = None
        self._body_name    = ""

        # Collapse a run of refines against one deposit.
        self._pending: dict[str, dict] = {}

        # Session counters, reported in the tab and the log.
        self._new_this_session       = 0
        self._confirmed_this_session = 0
        self._replayed_unpositioned  = 0
        self._replay_warned          = False
        self._live_miss_warned       = False
        self._body_mismatch_warned   = False

        # Sheet publishing.  Off unless configured; see core/sheets_publish.py.
        self._publisher   = None
        self._reporter    = ""
        self._include_test = False
        self._batch_size  = 200
        self._last_publish = 0.0
        self._publish_status = "off"
        self._mark_as_test   = False
        self._fetch_enabled  = False
        #: Bodies already fetched this session, so arriving, leaving and
        #: returning does not spend a request each time.
        self._fetched: set[tuple[int, int]] = set()
        self._fetch_status = ""
        try:
            cfg = core.load_setting("SurfaceSurvey", SHEET_DEFAULTS, warn=False)
            self._publisher     = publisher_from_config(cfg, log=self._log)
            self._reporter      = str(cfg.get("ReporterName", "") or "")
            self._include_test  = bool(cfg.get("IncludeTest", False))
            self._mark_as_test  = bool(cfg.get("MarkFindsAsTest", False))
            self._fetch_enabled = bool(cfg.get("Fetch", True))
            self._reporter      = str(cfg.get("ReporterName", "") or "")
            self._batch_size    = max(1, int(cfg.get("BatchSize", 200) or 200))
            if self._publisher:
                self._publish_status = "configured"
        except Exception as exc:
            self._log(f"sheet publishing unavailable: {type(exc).__name__}: {exc}")

        # Overlay.  Off unless configured; the renderer is a child process and
        # is not started until the first frame is due, so a commander who never
        # Overlay ownership moved to components/overlay.py.  This component
        # contributes a panel; it does not own a window.

        # Proximity confirmation.  Driving within a few metres of a recorded
        # deposit is evidence it is still there, which is the one thing about a
        # deposit that goes stale and that nobody will ever update by hand.
        self._prox = None
        self._stop_prox = threading.Event()
        self._confirmed_by_visit = 0
        try:
            self._prox_enabled = bool(cfg.get("AutoConfirm", True))
            self._prox = ProximityTracker(
                enter_m=float(cfg.get("ConfirmMetres", DEFAULT_ENTER_M)))
            # Started unconditionally: the pending-deposit flush runs on this
            # tick too, and it is not optional.
            threading.Thread(target=self._prox_loop, daemon=True,
                             name="edld-survey").start()
        except Exception as exc:
            self._log(f"proximity confirmation unavailable: "
                      f"{type(exc).__name__}: {exc}")

        try:
            counts = self._db.counts()
            self._log(f"survey store ready — {counts['deposits']} deposit(s) "
                      f"across {counts['bodies']} bod(ies), "
                      f"{counts['pending']} unpublished")
        except Exception as exc:
            # The store failing to open must not be silent; the plugin carries
            # on so the rest of the dashboard is unaffected, but every write
            # below will report its own failure rather than pretending.
            self._log(f"survey store unavailable: {type(exc).__name__}: {exc}")

    def on_unload(self) -> None:
        self._flush_pending(force=True)
        self.publish_now()
        self._stop_prox.set()
        if self._overlay:
            self._overlay.stop()

    # ── logging ───────────────────────────────────────────────────────────────

    def _log(self, message: str) -> None:
        try:
            from core import debug as _debug
            _debug.info(f"[surface_mining] {message}")
        except Exception:
            pass

    # ── event dispatch ────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        name = event.get("event")
        if name == "SAASignalsFound":
            self._on_saa_signals(event)
        elif name == "MiningRefined":
            self._on_refined(event, state)
        elif name == "Scan":
            self._on_scan(event)
        elif name in ("Location", "FSDJump", "ApproachBody", "Touchdown",
                      "SupercruiseExit"):
            self._body_mismatch_warned = False
            was = (self._system_address, self._body_id)
            self._track_body(event)
            if name == "ApproachBody" and (self._system_address, self._body_id) != was:
                self.fetch_body()
        elif name == "LeaveBody":
            self._flush_pending(force=True)
            self.publish_now()
            self._body_id, self._body_name = None, ""

    # ── publishing ────────────────────────────────────────────────────────────

    def publish_now(self) -> str:
        """Send everything pending to the configured sheet.  Returns a summary.

        Called when the commander leaves a body rather than per deposit.
        Sheets allows roughly sixty writes a minute per user, and one real
        session produced 608 refine events; a send per event would be rate
        limited within the first minute of a rig run. Leaving a body is the
        natural boundary — the survey of that body is finished.
        """
        if not self._publisher:
            return "off"
        try:
            pending = self._db.unpublished(limit=self._batch_size,
                                           include_test=self._include_test)
        except Exception as exc:
            self._publish_status = f"store error: {exc}"
            self._log(f"cannot read pending deposits: {type(exc).__name__}: {exc}")
            return self._publish_status
        if not pending:
            self._publish_status = "nothing pending"
            return self._publish_status

        result = self._publisher.publish(pending, reporter=self._reporter)
        if result.ok and result.sent_ids:
            marked = self._db.mark_published(result.sent_ids)
            if marked != len(result.sent_ids):
                # Rows went to the sheet but the local store did not record it,
                # so the next flush would send them again. Harmless on the far
                # side — the script updates rather than duplicates — but it is
                # not silent.
                self._log(f"published {len(result.sent_ids)} row(s) but marked "
                          f"only {marked} locally; they will be re-sent")
        self._last_publish = time.time()
        self._publish_status = result.summary()
        return self._publish_status

    # ── body identity ─────────────────────────────────────────────────────────

    def _track_body(self, event: dict) -> None:
        sa = event.get("SystemAddress")
        if sa is not None:
            self._system_address = int(sa)
        sysname = event.get("StarSystem") or event.get("SystemName")
        if sysname:
            self._system_name = str(sysname)
        bid = event.get("BodyID")
        if bid is not None:
            self._body_id = int(bid)
        bname = event.get("Body") or event.get("BodyName")
        if bname:
            self._body_name = str(bname)

    def _on_scan(self, event: dict) -> None:
        """Record the body facts the survey needs — chiefly the radius, which
        every distance comparison depends on."""
        sa, bid = event.get("SystemAddress"), event.get("BodyID")
        if sa is None or bid is None:
            return
        if not event.get("PlanetClass") and event.get("Radius") is None:
            return  # a star, or a scan too thin to be worth a row
        try:
            self._db.upsert_body(
                int(sa), int(bid),
                system_name  = event.get("StarSystem", "") or "",
                body_name    = event.get("BodyName", "") or "",
                planet_class = event.get("PlanetClass", "") or "",
                gravity      = _gravity_g(event.get("SurfaceGravity")),
                radius_m     = event.get("Radius"),
                atmosphere   = event.get("Atmosphere", "") or "",
                volcanism    = event.get("Volcanism", "") or "",
                surface_temp = event.get("SurfaceTemperature"),
            )
        except Exception as exc:
            self._log(f"body upsert failed for {event.get('BodyName','?')}: "
                      f"{type(exc).__name__}: {exc}")

    def _enrich_body(self, system_address: int, body_id: int) -> None:
        """Fill a body's facts from the exploration catalogue.

        The survey only learns a planet's class, gravity, atmosphere and
        volcanism from a ``Scan`` in the current session. A body scanned months
        ago produces none, so its deposits were published with five of the
        twenty-three columns empty — coordinates and a commodity, but nothing
        telling a squadron whether the site is drivable.

        EDLD already has all of it. ``explo.db`` holds 1074 planets with
        exactly these columns, and it is the same data from the same scans; it
        was simply never asked. Only blanks are filled, so a Scan seen live
        still wins.
        """
        try:
            from core.bodies_db import get_db as _get_bodies
        except Exception:
            return
        try:
            cat = _get_bodies()
            conn = cat._connect()
            row = conn.execute(
                "SELECT p.type, p.atmosphere, p.volcanism, p.radius, p.gravity "
                "FROM planets p JOIN systems s ON p.system_id = s.id "
                "WHERE s.address = ? AND p.body_id = ?",
                (int(system_address), int(body_id))).fetchone()
        except Exception as exc:
            self._log(f"body catalogue lookup failed: {type(exc).__name__}: {exc}")
            return
        if row is None:
            return

        have = self._db.body(system_address, body_id) or {}
        fields: dict = {}
        for key, col, blank in (("planet_class", 0, ""), ("atmosphere", 1, ""),
                                ("volcanism", 2, ""), ("radius_m", 3, None),
                                ("gravity", 4, None)):
            value = row[col]
            if value not in (None, "") and (have.get(key) in (blank, None)):
                fields[key] = value
        if fields:
            try:
                self._db.upsert_body(system_address, body_id, **fields)
                self._log(f"filled {', '.join(sorted(fields))} for body "
                          f"{body_id} from the body catalogue")
            except Exception as exc:
                self._log(f"body enrichment failed: {type(exc).__name__}: {exc}")

    # ── body census ───────────────────────────────────────────────────────────

    def _on_saa_signals(self, event: dict) -> None:
        sa, bid = event.get("SystemAddress"), event.get("BodyID")
        if sa is None or bid is None:
            return
        count = 0
        hotspots = []
        for sig in event.get("Signals", []) or []:
            raw = str(sig.get("Type", "") or "")
            low = raw.lower()
            if low.startswith("$planetarymininglocation"):
                count = int(sig.get("Count", 0) or 0)
            elif not low.startswith("$saa_signaltype_"):
                # Bare commodity names on a surface scan are ring hotspots; the
                # survey keeps them as context for the body, not as deposits.
                nm = sig.get("Type_Localised") or raw
                hotspots.append(f"{nm}:{sig.get('Count', 0)}")
        if count <= 0 and not hotspots:
            return
        # Deliberately does NOT change which body the commander is on.
        #
        # A surface scan is about a body you may be nowhere near — they are
        # done from orbit, often several in a row. Adopting the scanned body as
        # the current one meant that scanning two bodies back to back while
        # parked in an SRV on the first filed every later refine against the
        # second: three deposits landed on a body the commander had never
        # approached, carrying the coordinates of the one they were standing
        # on.
        #
        # Where the commander is comes from ApproachBody, Location, Touchdown
        # and SupercruiseExit — events about the ship rather than about a
        # telescope.
        scanned = str(event.get("BodyName", "") or "")
        self.fetch_body(int(sa), int(bid))
        try:
            self._db.upsert_body(int(sa), int(bid),
                                 system_name=self._system_name or None,
                                 body_name=scanned or None)
            if count > 0:
                self._db.record_survey(int(sa), int(bid), count,
                                       ",".join(sorted(hotspots)))
                self._log(f"{scanned or bid}: "
                          f"{count} mining location signal(s)")
        except Exception as exc:
            self._log(f"survey record failed for {scanned or bid}: "
                      f"{type(exc).__name__}: {exc}")

    # ── deposits ──────────────────────────────────────────────────────────────

    def _on_refined(self, event: dict, state) -> None:
        ts  = parse_journal_ts(event.get("timestamp", ""))
        pos = POSITIONS.at(ts) if ts is not None else None
        matched = "window"

        if pos is None and ts is not None and (time.time() - ts) < _LIVE_MAX_LAG_S:
            # The journal is buffered: the game writes lines in batches, and
            # the gap between a refine happening and EDLD reading the line
            # routinely exceeds the two-second match window. Every live refine
            # was falling through this hole — 190 of them in one session —
            # and, because only the replay branch logged anything, silently.
            #
            # The current position is the right answer anyway. Refining
            # requires the SRV to be parked on the deposit, so where the
            # commander is now IS where the refine happened; it is only stale
            # once they have driven off, which the freshness check below
            # covers.
            latest = POSITIONS.latest()
            if latest is not None and (time.time() - latest.ts) <= _POSITION_STALE_S:
                pos, matched = latest, "latest"

        if not survey.is_surface_refine(pos):
            # Either a ring refine (no latitude at all, the common case) or a
            # replayed one from a journal read at startup, where there is no
            # Status.json to join against.  The first is not interesting here;
            # the second is counted so the gap is visible.
            if ts is not None and (time.time() - ts) > _LIVE_MAX_LAG_S:
                self._replayed_unpositioned += 1
                if not self._replay_warned:
                    self._replay_warned = True
                    self._log("replayed MiningRefined events carry no position "
                              "and are not being recorded as deposits")
            elif not self._live_miss_warned:
                # A live refine that could not be placed is a defect, not
                # housekeeping. Saying so once beats the silence that hid this.
                self._live_miss_warned = True
                age = "unknown" if ts is None else f"{time.time() - ts:.1f}s old"
                self._log(f"live MiningRefined could not be placed ({age}); "
                          f"position={'none' if pos is None else 'not in SRV'} "
                          f"— deposits are not being recorded")
            return

        if pos.body_name and self._body_name \
                and pos.body_name != self._body_name:
            # Status.json names the body underneath the commander. If the
            # tracked identity disagrees with it, the id is stale or wrong and
            # a deposit written now would carry the right coordinates under the
            # wrong body — which is exactly the failure that put three of them
            # on a body nobody had visited. Refuse rather than guess.
            if not self._body_mismatch_warned:
                self._body_mismatch_warned = True
                self._log(f"tracked body is {self._body_name!r} but the game "
                          f"says {pos.body_name!r}; not recording until they "
                          f"agree")
            return

        if self._system_address is None or self._body_id is None:
            # Status.json has a body name but no address or id, and no journal
            # event this session has supplied one.  Recording a deposit with no
            # body to hang it off would produce a row nothing could find again.
            self._log("surface refine seen before any body identity — "
                      "not recorded")
            return

        commodity = canonical_commodity(event.get("Type", ""))
        if not commodity:
            return

        with self._lock:
            key = f"{self._system_address}:{self._body_id}:{commodity}"
            pending = self._pending.get(key)
            now = time.time()
            if pending is None:
                self._pending[key] = {
                    "system_address": self._system_address,
                    "body_id":        self._body_id,
                    "commodity":      commodity,
                    "display":        event.get("Type_Localised", "") or "",
                    "lat":            pos.latitude,
                    "lon":            pos.longitude,
                    "radius_m":       pos.radius_m,
                    "count":          1,
                    "first":          now,
                    "last":           now,
                }
            else:
                pending["count"] += 1
                pending["last"]   = now
                # Track the position too: a rig run drifts a little and the
                # first sample is no more authoritative than the last.
                pending["lat"] = pos.latitude
                pending["lon"] = pos.longitude
        self._flush_pending()

    def _flush_pending(self, force: bool = False) -> None:
        now = time.time()
        with self._lock:
            ready = [k for k, p in self._pending.items()
                     if force or (now - p["first"]) >= _CONFIRM_INTERVAL_S]
            batch = [self._pending.pop(k) for k in ready]
        for p in batch:
            try:
                # The system name comes from whatever event last told us
                # where we were, not from the Scan — a body scanned in an
                # earlier session has no Scan in this one, and its deposits
                # were being published with an empty system column. A shared
                # row that names the rock but not the system is one nobody
                # else can use.
                self._db.upsert_body(p["system_address"], p["body_id"],
                                     system_name=self._system_name or None,
                                     body_name=self._body_name or None,
                                     radius_m=p["radius_m"] or None)
                self._enrich_body(p["system_address"], p["body_id"])
                dep_id, created = self._db.record_deposit(
                    p["system_address"], p["body_id"], p["commodity"],
                    p["lat"], p["lon"],
                    commodity_display = p["display"],
                    reported_by       = self._reporter,
                    is_test           = self._mark_as_test,
                    refined           = int(p["count"]),
                )
                if created:
                    self._new_this_session += 1
                    self._log(f"new deposit {dep_id} — {p['display'] or p['commodity']} "
                              f"at {p['lat']:.5f}, {p['lon']:.5f}")
                else:
                    self._confirmed_this_session += 1
            except Exception as exc:
                self._log(f"deposit write failed for {p['commodity']}: "
                          f"{type(exc).__name__}: {exc}")

    # ── overlay ───────────────────────────────────────────────────────────────


            return []

    # ── recording what a deposit is actually like ─────────────────────────────

    def record_here(self, commodity: str = "", *, amount: str = "",
                    density: str = "") -> str:
        """Record the deposit the commander is parked on.

        Automatic capture creates a deposit from a MiningRefined, which is the
        only event the game emits that implies one. Driving onto a deposit
        emits nothing at all — across eighteen minutes of approaching and
        parking on one, the journal produced a single ModuleInfo and nothing
        else. So a deposit seen but not yet worked cannot be captured without
        the commander saying so.

        Position comes from Status.json, so the only thing asked for is what is
        on screen and in no file: what it is, how much, how dense.

        Creates if there is nothing recorded nearby, annotates if there is.
        """
        pos = POSITIONS.latest()
        if pos is None or (time.time() - pos.ts) > _POSITION_STALE_S:
            return "no live position — is the game running?"
        if self._system_address is None or self._body_id is None:
            return "no body identified yet"
        if amount and amount not in AMOUNT_LEVELS:
            return f"amount must be one of {', '.join(AMOUNT_LEVELS)}"
        if density and density not in DENSITY_LEVELS:
            return f"density must be one of {', '.join(DENSITY_LEVELS)}"

        radius = pos.radius_m or self._db.body_radius(self._system_address,
                                                      self._body_id)
        try:
            near = self._db.nearest_deposit(
                self._system_address, self._body_id,
                pos.latitude, pos.longitude, radius)
            if near is not None:
                changed = self._db.annotate_deposit(
                    near["deposit_id"], amount=amount, density_observed=density)
                name = near.get("commodity_display") or near.get("commodity", "")
                return (f"updated {name}" if changed
                        else f"{name} already recorded here")

            commodity = (commodity or "").strip()
            if not commodity:
                return "nothing recorded here — name the commodity to add it"
            self._db.upsert_body(self._system_address, self._body_id,
                                 system_name=self._system_name or None,
                                 body_name=self._body_name or None,
                                 radius_m=radius or None)
            self._enrich_body(self._system_address, self._body_id)
            dep_id, created = self._db.record_deposit(
                self._system_address, self._body_id,
                canonical_commodity(commodity), pos.latitude, pos.longitude,
                commodity_display=commodity, density_observed=density,
                amount=amount, reported_by=self._reporter,
                is_test=self._mark_as_test)
            self._new_this_session += int(created)
            self._log(f"recorded {commodity} at {pos.latitude:.5f}, "
                      f"{pos.longitude:.5f} as {dep_id}")
            return f"recorded {commodity}"
        except Exception as exc:
            msg = f"could not record: {type(exc).__name__}: {exc}"
            self._log(msg)
            return msg

    def mark_here(self, *, amount: str = "", density: str = "",
                  rigs: int | None = None) -> str:
        """Record a judgement about the deposit the commander is standing on.

        Automatic capture gets the position, the commodity and the fact that a
        deposit exists. It cannot get how much is left or how dense the seam
        is, because nothing in the journal says. Those are the commander's
        assessment, and this is where they land.

        Resolution is by position rather than by selection: standing on the
        thing you are describing is both the natural way to do it and the only
        way that needs no list to pick from. The deposit is matched with the
        same proximity rule that records one in the first place, so it cannot
        attach a judgement to a neighbour.
        """
        pos = POSITIONS.latest()
        if pos is None or (time.time() - pos.ts) > _POSITION_STALE_S:
            return "no live position — is the game running?"
        if self._system_address is None or self._body_id is None:
            return "no body identified yet"
        if amount and amount not in AMOUNT_LEVELS:
            return f"amount must be one of {', '.join(AMOUNT_LEVELS)}"
        if density and density not in DENSITY_LEVELS:
            return f"density must be one of {', '.join(DENSITY_LEVELS)}"

        radius = pos.radius_m or self._db.body_radius(self._system_address,
                                                      self._body_id)
        try:
            near = self._db.nearest_deposit(
                self._system_address, self._body_id,
                pos.latitude, pos.longitude, radius)
            if near is None:
                return "no recorded deposit within range of this position"
            changed = self._db.annotate_deposit(
                near["deposit_id"], amount=amount, density_observed=density,
                rigs=rigs)
        except Exception as exc:
            msg = f"could not update the deposit: {type(exc).__name__}: {exc}"
            self._log(msg)
            return msg

        if not changed:
            return "nothing to change"
        name = near.get("commodity_display") or near.get("commodity", "")
        note = ", ".join(x for x in (amount, density) if x)
        self._log(f"marked {near['deposit_id']} ({name}) as {note}")
        return f"{name}: {note}"

    def form_for_here(self) -> tuple[dict, str]:
        """Form contents for the deposit underfoot, and a heading.

        Returns blanks and an "add" heading when there is nothing recorded
        here, the stored values and an "edit" heading when there is. One call
        answers both, so a front end needs one keybind and one window rather
        than two of each — the commander does not know which they are doing
        until EDLD has looked.
        """
        from core.deposit_form import prefill

        # A refine queues its deposit and does not write it until the confirm
        # interval has passed, so pressing Ctrl+D moments after mining the
        # first unit would have offered to add a deposit that was already on
        # its way in. Flushing first makes the window describe what is actually
        # there.
        self._flush_pending(force=True)

        pos = POSITIONS.latest()
        if pos is None or (time.time() - pos.ts) > _POSITION_STALE_S:
            return prefill(None), "No live position — is the game running?"
        if self._system_address is None or self._body_id is None:
            return prefill(None), "No body identified yet"

        radius = pos.radius_m or self._db.body_radius(self._system_address,
                                                      self._body_id)
        try:
            near = self._db.nearest_deposit(self._system_address, self._body_id,
                                            pos.latitude, pos.longitude, radius)
        except Exception as exc:
            return prefill(None), f"Could not read the store: {exc}"

        if near is None:
            return prefill(None), (f"New deposit at {pos.latitude:.5f}, "
                                   f"{pos.longitude:.5f}")
        name = near.get("commodity_display") or near.get("commodity", "")
        # The depletion date lives in its own table, so it has to be fetched
        # rather than read off the row — without it the field would show blank
        # on a site already known to be worked out, and saving would silently
        # re-stamp it with today.
        try:
            history = self._db.depletion_history(near["deposit_id"])
        except Exception:
            history = []
        record = dict(near)
        if history:
            record["depleted_on"] = history[-1]["noted_at"]
        return prefill(record), f"Editing {name} ({near['deposit_id']})"

    def submit_form(self, raw: dict) -> str:
        """Apply a filled-in form to the deposit underfoot, adding if absent.

        Both front ends call this rather than each assembling their own write,
        so validation, the add-or-edit decision and the wording of the result
        cannot drift between them.
        """
        from core.deposit_form import clean, describe

        pos = POSITIONS.latest()
        if pos is None or (time.time() - pos.ts) > _POSITION_STALE_S:
            return "no live position — is the game running?"
        if self._system_address is None or self._body_id is None:
            return "no body identified yet"

        radius = pos.radius_m or self._db.body_radius(self._system_address,
                                                      self._body_id)
        try:
            near = self._db.nearest_deposit(self._system_address, self._body_id,
                                            pos.latitude, pos.longitude, radius)
        except Exception as exc:
            return f"could not read the store: {type(exc).__name__}: {exc}"

        cleaned = clean(raw, require_commodity=near is None)
        if cleaned.errors:
            return describe(cleaned.errors)
        values = dict(cleaned.values)

        try:
            if near is None:
                self._db.upsert_body(self._system_address, self._body_id,
                                     system_name=self._system_name or None,
                                     body_name=self._body_name or None,
                                     radius_m=radius or None)
                self._enrich_body(self._system_address, self._body_id)
                dep_id, _created = self._db.record_deposit(
                    self._system_address, self._body_id,
                    values.pop("commodity"), pos.latitude, pos.longitude,
                    commodity_display=values.pop("commodity_display", ""),
                    reported_by=self._reporter,
                    is_test=bool(values.pop("is_test", self._mark_as_test)))
                self._new_this_session += 1
                verb = "recorded"
            else:
                dep_id = near["deposit_id"]
                # A commodity cannot be corrected in place: it is part of the
                # deposit's identity, and changing it would leave the id
                # pointing at something else on every sheet that has it.
                values.pop("commodity", None)
                values.pop("commodity_display", None)
                verb = "updated"
            if values:
                self._db.annotate_deposit(dep_id, **values)
        except Exception as exc:
            msg = f"could not save: {type(exc).__name__}: {exc}"
            self._log(msg)
            return msg

        self._log(f"{verb} {dep_id} from the deposit form")
        return f"{verb} {dep_id}"

    def delete_here(self) -> str:
        """Remove the deposit underfoot, locally and from the shared sheet.

        Restricted to being at the site, like every other action here, and for
        a stronger reason than convenience: a deposit that reached the sheet is
        something other commanders will fly to, and being able to remove one
        from a list would make a stray click somebody else's wasted trip.
        Standing on it is the closest thing to proof the commander knows what
        they are removing.

        This is for a row that should never have existed — a wrong commodity, a
        position filed under the wrong body. A site that is merely empty should
        be given a depletion date instead: that is information the next commander
        wants, and deleting it invites them to rediscover it.
        """
        pos = POSITIONS.latest()
        if pos is None or (time.time() - pos.ts) > _POSITION_STALE_S:
            return "no live position — is the game running?"
        if self._system_address is None or self._body_id is None:
            return "no body identified yet"

        radius = pos.radius_m or self._db.body_radius(self._system_address,
                                                      self._body_id)
        try:
            near = self._db.nearest_deposit(self._system_address, self._body_id,
                                            pos.latitude, pos.longitude, radius)
        except Exception as exc:
            return f"could not read the store: {type(exc).__name__}: {exc}"
        if near is None:
            return "no recorded deposit within range of this position"

        dep_id = near["deposit_id"]
        name = near.get("commodity_display") or near.get("commodity", "")
        shared = ""
        if self._publisher and near.get("published_at"):
            # Only rows that actually reached the sheet are worth a request,
            # and a failure there must not stop the local removal — otherwise a
            # bad row survives on the machine that knows it is bad.
            result = self._publisher.delete(dep_id)
            shared = (" and from the sheet" if result.ok
                      else f" (sheet not updated — {result.error})")

        if not self._db.delete_deposit(dep_id):
            return f"{name} was already gone"
        self._log(f"deleted {dep_id} ({name}){shared}")
        return f"deleted {name}{shared}"

    def flag_here(self, is_test: bool) -> str:
        """Mark the deposit underfoot as test data, or clear the mark.

        Per deposit, because the config switch flags everything recorded from
        now on and cannot reach the one row that was a mistake. Flagged rows
        stay in the local store and are held back from the sheet, so this is
        how a bad row is retired without deleting evidence.
        """
        pos = POSITIONS.latest()
        if pos is None or (time.time() - pos.ts) > _POSITION_STALE_S:
            return "no live position — is the game running?"
        if self._system_address is None or self._body_id is None:
            return "no body identified yet"
        radius = pos.radius_m or self._db.body_radius(self._system_address,
                                                      self._body_id)
        try:
            near = self._db.nearest_deposit(self._system_address, self._body_id,
                                            pos.latitude, pos.longitude, radius)
            if near is None:
                return "no recorded deposit within range of this position"
            changed = self._db.annotate_deposit(near["deposit_id"],
                                                is_test=is_test)
        except Exception as exc:
            return f"could not flag: {type(exc).__name__}: {exc}"
        name = near.get("commodity_display") or near.get("commodity", "")
        if not changed:
            return f"{name} was already {'test' if is_test else 'live'} data"
        return f"{name} marked as {'test' if is_test else 'live'} data"

    def mark_depleted_here(self) -> str:
        """Stamp today as the day the deposit underfoot was worked out.

        Not a delete, and not a change of amount: the date is the whole record
        of depletion, and the amount stays what the site holds when full.
        """
        pos = POSITIONS.latest()
        if pos is None or (time.time() - pos.ts) > _POSITION_STALE_S:
            return "no live position — is the game running?"
        if self._system_address is None or self._body_id is None:
            return "no body identified yet"
        radius = pos.radius_m or self._db.body_radius(self._system_address,
                                                      self._body_id)
        try:
            near = self._db.nearest_deposit(
                self._system_address, self._body_id,
                pos.latitude, pos.longitude, radius)
            if near is None:
                return "no recorded deposit within range of this position"
            self._db.mark_depleted(near["deposit_id"])
        except Exception as exc:
            msg = f"could not mark the deposit: {type(exc).__name__}: {exc}"
            self._log(msg)
            return msg
        name = near.get("commodity_display") or near.get("commodity", "")
        today = time.strftime("%Y-%m-%d", time.gmtime())
        self._log(f"marked {near['deposit_id']} ({name}) worked out {today}")
        return f"{name}: depleted {today}"

    # ── overlay ───────────────────────────────────────────────────────────────

    OVERLAY_PANELS = ("survey_compass",)

    def overlay_panel(self, panel_id: str, ctx):
        """Bearings to deposits already found on this body.

        Returning None is this component's relevance test and the whole of what
        `auto` consults: outside an SRV, or with nothing recorded within range,
        there is nothing worth covering the game for.
        """
        if panel_id != "survey_compass" or not ctx.in_srv:
            return None
        if ctx.latitude is None or ctx.longitude is None or not ctx.body_radius:
            return None
        if self._system_address is None or self._body_id is None:
            return None
        from core.overlay_panels import Panel
        try:
            deposits = self._db.deposits_on(self._system_address, self._body_id)
        except Exception as exc:
            self._log(f"overlay panel could not read deposits: "
                      f"{type(exc).__name__}: {exc}")
            return None
        near = nearest_deposits(ctx.latitude, ctx.longitude,
                                float(ctx.body_radius), deposits, limit=4)
        if not near:
            return None
        rows = []
        for dep in near:
            name = dep.get("commodity_display") or dep.get("commodity", "")
            d = dep["distance_m"]
            dist = f"{d:.0f}m" if d < 1000 else f"{d / 1000:.1f}km"
            rows.append((name, f"{dist}  {dep['bearing']:.0f}\u00b0"))
        return Panel(id="survey_compass", title="DEPOSITS", rows=rows)

    # ── display ───────────────────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return bool(self._new_this_session or self._confirmed_this_session)

    def get_summary_line(self) -> str | None:
        if not self.has_activity():
            return None
        return (f"Survey: {self._new_this_session} new, "
                f"{self._confirmed_this_session} confirmed")

    def get_tab_rows(self) -> list[dict]:
        self._flush_pending()
        rows: list[dict] = []
        try:
            counts = self._db.counts()
        except Exception as exc:
            return [{"label": "Survey store", "value": f"unavailable ({exc})"}]

        rows.append({"label": "Deposits recorded", "value": str(counts["deposits"])})
        rows.append({"label": "Bodies surveyed",   "value": str(counts["surveyed"])})
        rows.append({"label": "Awaiting publish",  "value": str(counts["pending"])})
        rows.append({"label": "New this session",  "value": str(self._new_this_session)})
        rows.append({"label": "Confirmed",         "value": str(self._confirmed_this_session)})

        if self._system_address is not None and self._body_id is not None:
            surv = self._db.survey(self._system_address, self._body_id)
            here = self._db.deposits_on(self._system_address, self._body_id)
            label = self._body_name or f"body {self._body_id}"
            if surv:
                rows.append({"label": f"{label} signals",
                             "value": f"{len(here)} of {surv['signal_count']} found"})
            elif here:
                rows.append({"label": f"{label} deposits",
                             "value": str(len(here))})

        if self._publisher:
            rows.append({"label": "Sheet", "value": self._publish_status})

        if self._replayed_unpositioned:
            rows.append({"label": "Replayed, no position",
                         "value": str(self._replayed_unpositioned)})
        return rows

    # ── preferences ───────────────────────────────────────────────────────────
    #
    # One tab with three sections rather than three tabs. The injection hook
    # gives a component one tab, and splitting these across three would mean
    # three plugins or three hooks for settings a commander configures in one
    # sitting. Sections inside a tab read the same and click less.

    #: Widget id to (section, key, type). Read by both front ends so the
    #: controls below actually save. See tui/preferences.py _plugin_bindings.
    # ── fetching what other commanders found ─────────────────────────────────

    def fetch_body(self, system_address: int | None = None,
                   body_id: int | None = None) -> str:
        """Pull this body's known deposits down from the shared sheet.

        Runs on arrival rather than on a schedule, because that is when the
        answer is worth having and when a stale one costs nothing: a deposit
        recorded last week is still where it was.

        Once per body per session. Arriving, leaving and coming back should not
        spend three requests to learn the same thing.
        """
        if not (self._publisher and self._fetch_enabled):
            return ""
        sa = self._system_address if system_address is None else system_address
        bid = self._body_id if body_id is None else body_id
        if sa is None or bid is None:
            return ""
        key = (int(sa), int(bid))
        if key in self._fetched:
            return ""
        self._fetched.add(key)

        rows, error = self._publisher.fetch_body(sa, bid)
        if error:
            # Recorded, not raised: a sheet that cannot be reached is a reason
            # to have fewer deposits on the compass, not a reason to stop
            # surveying.
            self._fetch_status = f"fetch failed — {error}"
            self._log(self._fetch_status)
            return self._fetch_status
        if not rows:
            self._fetch_status = "no shared deposits on this body"
            return self._fetch_status
        try:
            added, updated = self._db.import_deposits(rows, log=self._log)
        except Exception as exc:
            self._fetch_status = f"import failed — {type(exc).__name__}: {exc}"
            self._log(self._fetch_status)
            return self._fetch_status
        self._fetch_status = (f"{added} shared deposit(s) added, "
                              f"{updated} updated")
        self._log(f"{self._fetch_status} for body {bid}")
        return self._fetch_status

    # ── proximity confirmation ────────────────────────────────────────────────

    def _tick(self) -> None:
        """Flush pending deposits, then confirm anything driven onto.

        The flush has to be on a clock. It used to run only at the end of
        _on_refined, and a run of refines collapses into one pending entry that
        is not ready to write until _CONFIRM_INTERVAL_S has passed — so a
        commander who mined four tonnes and stopped left the deposit sitting in
        memory with nothing left to trigger the write. Four refines, no log
        line, no row, because the code had succeeded right up to the last step
        and then had no reason to run again.
        """
        self._flush_pending()
        if self._prox is not None and self._prox_enabled:
            self.check_proximity()

    def _prox_loop(self) -> None:
        while not self._stop_prox.wait(_PROX_TICK_S):
            try:
                self._tick()
            except Exception as exc:
                self._log(f"survey tick failed: {type(exc).__name__}: {exc}")

    def check_proximity(self) -> list[str]:
        """Confirm any deposit the commander has just driven onto.

        Runs on its own tick rather than off the overlay's, because a
        commander with the overlay switched off should still have their survey
        stay current — tying data collection to a display would make the data
        depend on whether anyone was looking at it.

        Returns the deposit ids confirmed, for tests.
        """
        if not self._prox:
            return []
        pos = POSITIONS.latest()
        if pos is None or (time.time() - pos.ts) > _POSITION_STALE_S \
                or not pos.in_srv:
            self._prox.reset()
            return []
        if self._system_address is None or self._body_id is None:
            return []

        try:
            deposits = self._db.deposits_on(self._system_address, self._body_id)
        except Exception as exc:
            self._log(f"proximity could not read deposits: "
                      f"{type(exc).__name__}: {exc}")
            return []
        if not deposits:
            return []

        radius = pos.radius_m or self._db.body_radius(self._system_address,
                                                      self._body_id)
        arrived = self._prox.update(
            distances_to(pos.latitude, pos.longitude, radius, deposits))

        for dep_id in arrived:
            try:
                # A visit confirms the deposit is still there; it says nothing
                # about how much is left, which is a judgement and stays with
                # the commander.  annotate_deposit with no fields would be a
                # no-op, so the timestamp is moved explicitly.
                self._db.touch_deposit(dep_id)
                self._confirmed_by_visit += 1
            except Exception as exc:
                self._log(f"could not confirm {dep_id}: "
                          f"{type(exc).__name__}: {exc}")
        if arrived:
            self._log(f"confirmed {len(arrived)} deposit(s) by proximity")
        return arrived

    def preferences_action(self, action_id: str, values: dict | None = None):
        """Handle a button from this component's preferences tab.

        Shared by both front ends so the Test button means the same thing in
        each. Returns None for ids that are not ours, so the screen can keep
        looking.
        """
        values = values or {}

        if action_id == "btn-srv-record":
            return self.record_here(
                values.get("srv-rec-commodity", "").strip(),
                amount=values.get("srv-rec-amount", "").strip(),
                density=values.get("srv-rec-density", "").strip())

        if action_id == "btn-srv-depleted":
            return self.mark_depleted_here()

        if action_id == "btn-srv-delete":
            return self.delete_here()

        if action_id in ("btn-srv-test-on", "btn-srv-test-off"):
            return self.flag_here(action_id.endswith("-on"))

        if action_id == "btn-srv-fetch":
            if not (self._publisher and self._fetch_enabled):
                return "Sheet fetching is off, or no sheet is configured."
            if self._system_address is None or self._body_id is None:
                return "No body identified yet."
            self._fetched.discard((int(self._system_address), int(self._body_id)))
            return self.fetch_body() or "nothing to fetch"

        if action_id != "btn-srv-test":
            return None
        cfg = self._core.load_setting("SurfaceSurvey", SHEET_DEFAULTS, warn=False)
        pub = publisher_from_config({**cfg, "Enabled": True}, log=self._log)
        if pub is None:
            return "Enter a web app URL and a token first."
        return pub.test_connection().summary()

    def preferences_bindings(self) -> dict:
        return {
            "srv-sheet-enabled":  ("SurfaceSurvey", "Enabled",      bool),
            "srv-sheet-url":      ("SurfaceSurvey", "WebAppURL",    str),
            "srv-sheet-token":    ("SurfaceSurvey", "Token",        str),
            "srv-sheet-reporter": ("SurfaceSurvey", "ReporterName", str),
            "srv-sheet-test":     ("SurfaceSurvey", "IncludeTest",  bool),
            "srv-sheet-fetch":    ("SurfaceSurvey", "Fetch",        bool),
            "srv-mark-test":      ("SurfaceSurvey", "MarkFindsAsTest", bool),
        }

    def _store_lines(self) -> list[tuple[str, str]]:
        """Label/value pairs describing the store, shared by both front ends."""
        from core.state import shared_data_dir
        try:
            counts = self._db.counts()
        except Exception as exc:
            return [("Store", f"unavailable — {type(exc).__name__}: {exc}")]
        return [
            ("Location",  str(shared_data_dir())),
            ("Deposits",  str(counts["deposits"])),
            ("Bodies",    str(counts["bodies"])),
            ("Surveyed",  str(counts["surveyed"])),
            ("Unpublished", str(counts["pending"])),
        ]


    def gui_preferences_tab(self):
        # Called with no arguments by gui/preferences.py _extra_tabs() purely to
        # discover the tab; the builder it returns is what receives the dialog.
        # Returning None here when handed no dialog — which is what this used to
        # do — meant the tab was never registered at all.
        def _build(dlg):
            from PySide6.QtWidgets import (
                QLabel, QVBoxLayout, QFormLayout, QWidget, QPushButton,
                QHBoxLayout)

            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(10, 10, 10, 10)
            lay.setSpacing(6)

            def section(title: str) -> QFormLayout:
                label = QLabel(title)
                label.setProperty("role", "section")
                lay.addWidget(label)
                form = QFormLayout()
                lay.addLayout(form)
                return form

            store = section("STORE")
            for key, value in self._store_lines():
                store.addRow(key, QLabel(value))

            # core.load_setting(), not dlg._cfg.load_setting().  The two are
            # not the same call: ConfigManager's takes ``warn_missing`` while
            # the core wrapper takes ``warn``, so passing warn= to the former
            # raises TypeError.  The tab loop catches that and logs it, so the
            # Survey page simply never appeared in the GUI while the TUI — which
            # goes through the core wrapper — showed it fine.
            sheet_cfg = self._core.load_setting("SurfaceSurvey", SHEET_DEFAULTS,
                                               warn=False)
            sheet = section("SHARING")
            sheet.addRow("Publish to a sheet",
                         dlg._bool_combo(bool(sheet_cfg.get("Enabled")),
                                         "SurfaceSurvey", "Enabled"))
            sheet.addRow("Web app URL",
                         dlg._text_edit(sheet_cfg.get("WebAppURL", ""),
                                        "SurfaceSurvey", "WebAppURL",
                                        placeholder="https://script.google.com/"
                                                    "macros/s/.../exec"))
            sheet.addRow("Token",
                         dlg._text_edit(sheet_cfg.get("Token", ""),
                                        "SurfaceSurvey", "Token", password=True))
            sheet.addRow("Report as",
                         dlg._text_edit(sheet_cfg.get("ReporterName", ""),
                                        "SurfaceSurvey", "ReporterName",
                                        placeholder="blank to publish anonymously"))
            sheet.addRow("Flag my finds as test data",
                         dlg._bool_combo(bool(sheet_cfg.get("MarkFindsAsTest")),
                                         "SurfaceSurvey", "MarkFindsAsTest"))
            sheet.addRow("Fetch others' deposits",
                         dlg._bool_combo(bool(sheet_cfg.get("Fetch", True)),
                                         "SurfaceSurvey", "Fetch"))
            sheet.addRow("Publish test rows too",
                         dlg._bool_combo(bool(sheet_cfg.get("IncludeTest")),
                                         "SurfaceSurvey", "IncludeTest"))

            from PySide6.QtWidgets import QComboBox, QLineEdit

            rec = section("RECORD A DEPOSIT")
            rec_note = QLabel("Park on the deposit, then record it. EDLD takes "
                              "the position from the game; the commodity, "
                              "amount and density are on your HUD and in no "
                              "journal event.")
            rec_note.setWordWrap(True)
            rec_note.setProperty("role", "dim")
            lay.addWidget(rec_note)

            commodity = QLineEdit()
            commodity.setPlaceholderText("e.g. Helium-3")
            rec.addRow("Commodity", commodity)
            amount_box = QComboBox()
            amount_box.addItem("", "")
            for _a in AMOUNT_LEVELS:
                amount_box.addItem(_a, _a)
            rec.addRow("Amount", amount_box)
            density_box = QComboBox()
            density_box.addItem("", "")
            for _d in DENSITY_LEVELS:
                density_box.addItem(_d, _d)
            rec.addRow("Density", density_box)

            rec_row = QHBoxLayout()
            record_btn = QPushButton("Record here")
            depleted_btn = QPushButton("Mark depleted")
            rec_result = QLabel("")
            rec_result.setWordWrap(True)
            rec_result.setProperty("role", "dim")

            def _record() -> None:
                # Read straight from the widgets. These are not settings and
                # must not be saved; they describe one rock, once.
                rec_result.setText(self.preferences_action("btn-srv-record", {
                    "srv-rec-commodity": commodity.text(),
                    "srv-rec-amount": amount_box.currentData() or "",
                    "srv-rec-density": density_box.currentData() or "",
                }))

            record_btn.clicked.connect(_record)
            depleted_btn.clicked.connect(
                lambda: rec_result.setText(
                    self.preferences_action("btn-srv-depleted", {})))
            fetch_btn = QPushButton("Fetch this body")
            fetch_btn.clicked.connect(
                lambda: rec_result.setText(
                    self.preferences_action("btn-srv-fetch", {}) or ""))
            rec_row.addWidget(fetch_btn)
            rec_row.addWidget(record_btn)
            rec_row.addWidget(depleted_btn)
            for _label, _act in (("Delete here", "btn-srv-delete"),
                                 ("Flag as test", "btn-srv-test-on"),
                                 ("Unflag", "btn-srv-test-off")):
                _b = QPushButton(_label)
                _b.clicked.connect(
                    lambda _checked=False, a=_act: rec_result.setText(
                        self.preferences_action(a, {}) or ""))
                rec_row.addWidget(_b)
            rec_row.addWidget(rec_result, 1)
            lay.addLayout(rec_row)

            row = QHBoxLayout()
            test_btn = QPushButton("Test connection")
            result = QLabel("")
            result.setWordWrap(True)
            result.setProperty("role", "dim")

            def _test() -> None:
                # Same code path as the TUI button.  Two implementations of
                # "test the connection" would eventually disagree about what
                # counts as success.
                # Tests what is in the boxes now, not what was loaded at open:
                # a Test button that checks the saved value tells you nothing
                # about the credentials you just typed in.
                pending = getattr(dlg, "_pending", {})
                live = {**sheet_cfg,
                        "Enabled": True,
                        "WebAppURL": pending.get(("SurfaceSurvey", "WebAppURL"),
                                                 sheet_cfg.get("WebAppURL", "")),
                        "Token": pending.get(("SurfaceSurvey", "Token"),
                                             sheet_cfg.get("Token", ""))}
                pub = publisher_from_config(live, log=self._log)
                if pub is None:
                    result.setText("Enter a web app URL and a token first.")
                    return
                result.setText(pub.test_connection().summary())

            test_btn.clicked.connect(_test)
            row.addWidget(test_btn)
            row.addWidget(result, 1)
            lay.addLayout(row)

            note = QLabel("Deposits are recorded automatically while you mine "
                          "them. Overlay display is configured on the Overlay "
                          "tab.")
            note.setWordWrap(True)
            note.setProperty("role", "dim")
            lay.addWidget(note)
            lay.addStretch(1)
            return page

        return ("pref-tab-survey", "Survey", _build)

    def tui_preferences_tab(self) -> tuple | None:
        def _compose():
            from textual.widgets import Label, Select, Input
            from textual.containers import Horizontal

            bools = [("Off", "false"), ("On", "true")]
            sheet_cfg = self._core.load_setting("SurfaceSurvey", SHEET_DEFAULTS,
                                                warn=False)

            def row(label: str, widget):
                with Horizontal(classes="pref-row"):
                    yield Label(label, classes="key")
                    yield widget

            yield Label("STORE", classes="pref-section")
            for key, value in self._store_lines():
                with Horizontal(classes="pref-row"):
                    yield Label(key, classes="key")
                    yield Label(value)

            yield Label("SHARING", classes="pref-section")
            yield from row("Publish to a sheet",
                           Select(bools,
                                  value="true" if sheet_cfg.get("Enabled") else "false",
                                  id="srv-sheet-enabled", classes="pref-bool-sel",
                                  allow_blank=False))
            yield from row("Web app URL",
                           Input(value=str(sheet_cfg.get("WebAppURL", "")),
                                 id="srv-sheet-url", classes="pref-input"))
            yield from row("Token",
                           Input(value=str(sheet_cfg.get("Token", "")),
                                 password=True, id="srv-sheet-token",
                                 classes="pref-input"))
            yield from row("Report as",
                           Input(value=str(sheet_cfg.get("ReporterName", "")),
                                 id="srv-sheet-reporter", classes="pref-input"))
            yield from row("Flag my finds as test data",
                           Select(bools,
                                  value="true" if sheet_cfg.get("MarkFindsAsTest") else "false",
                                  id="srv-mark-test", classes="pref-bool-sel",
                                  allow_blank=False))
            yield from row("Fetch others' deposits",
                           Select(bools,
                                  value="true" if sheet_cfg.get("Fetch", True) else "false",
                                  id="srv-sheet-fetch", classes="pref-bool-sel",
                                  allow_blank=False))
            yield from row("Publish test rows too",
                           Select(bools,
                                  value="true" if sheet_cfg.get("IncludeTest") else "false",
                                  id="srv-sheet-test", classes="pref-bool-sel",
                                  allow_blank=False))

            from textual.widgets import Button

            yield Label("RECORD A DEPOSIT", classes="pref-section")
            yield Label("Park on the deposit, then record it. EDLD takes the "
                        "position from the game; the commodity, amount and "
                        "density are on your HUD and in no journal event.",
                        classes="pref-note")
            yield from row("Commodity",
                           Input(placeholder="e.g. Helium-3",
                                 id="srv-rec-commodity", classes="pref-input"))
            yield from row("Amount",
                           Select([(a, a) for a in AMOUNT_LEVELS], value=None,
                                  id="srv-rec-amount", classes="pref-choice",
                                  allow_blank=True))
            yield from row("Density",
                           Select([(d, d) for d in DENSITY_LEVELS], value=None,
                                  id="srv-rec-density", classes="pref-choice",
                                  allow_blank=True))
            with Horizontal(classes="pref-row"):
                yield Button("Record here", id="btn-srv-record")
                yield Button("Mark depleted", id="btn-srv-depleted")
                yield Button("Delete here", id="btn-srv-delete")
                yield Button("Flag as test", id="btn-srv-test-on")
                yield Button("Unflag", id="btn-srv-test-off")
                yield Label("", id="btn-srv-record-result", classes="pref-note")

            yield Label("SHARING TEST", classes="pref-section")
            with Horizontal(classes="pref-row"):
                yield Button("Test connection", id="btn-srv-test")
                yield Button("Fetch this body", id="btn-srv-fetch")
                yield Label("", id="btn-srv-test-result", classes="pref-note")

            yield Label("Deposits are recorded automatically while you mine "
                        "them. Overlay display is configured on the Overlay "
                        "tab.", classes="pref-note")

        return ("pref-tab-survey", "Survey", _compose)

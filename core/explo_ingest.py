"""
core/explo_ingest.py — Journal event → body-database ingestion.

A single :class:`Ingestor` translates the exploration- and exobiology-relevant
journal events into writes against :mod:`core.explo_db`.  Both the historical
journal importer and the live write-through path use it, so the event-to-row
mapping exists in exactly one place.

The ingestor is stateful: it tracks the current commander (resolved from
``Commander`` / ``LoadGame``) and the current system, so that the body facts
(commander-independent) and the per-commander status are recorded against the
right rows.  Body *facts* are written whenever they appear; per-commander
*status* is only written once a commander is known.

Identifiers
-----------
Systems are keyed by ``SystemAddress`` and bodies by their per-system
``BodyID`` — the game's own stable identifiers — so re-scanning a body updates
the same rows instead of duplicating them, and events that arrive before a full
``Scan`` (e.g. ``FSSBodySignals``) create a stub row the later scan fills in.

``scan_state`` convention: 0 = unscanned, 1 = auto/basic, 2 = detailed,
3 = nav-beacon detail.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from core.explo_db import ExploDB, get_db

# Standard gravity used to convert journal surface gravity (m/s²) to g.
_G = 9.80665

_SCAN_STATE = {
    "Basic": 1,
    "AutoScan": 1,
    "Detailed": 2,
    "NavBeaconDetail": 3,
}

# Events the importer / live path care about.  Exposed so callers can subscribe
# exactly this set rather than the firehose.
INGEST_EVENTS = (
    "Commander", "LoadGame",
    "Location", "FSDJump", "CarrierJump",
    "FSSDiscoveryScan", "FSSAllBodiesFound",
    "Scan", "FSSBodySignals", "SAASignalsFound", "SAAScanComplete",
    "ScanOrganic", "Disembark",
)


def _ts(event: dict) -> str:
    """ISO timestamp for status rows, from ``_logtime`` or the raw field."""
    lt = event.get("_logtime")
    if lt is not None:
        try:
            return lt.isoformat()
        except Exception:
            pass
    return str(event.get("timestamp", ""))


def _name(event: dict, key: str) -> str:
    """Prefer a localised field when the game provides one."""
    return str(event.get(f"{key}_Localised") or event.get(key) or "")


def _signal_kind(type_str: str) -> str:
    s = (type_str or "").lower()
    if "biolog" in s:
        return "bio"
    if "geolog" in s:
        return "geo"
    if "human" in s:
        return "human"
    return "other"


def _materials_json(event: dict) -> str:
    m = event.get("Materials")
    out: dict[str, Any] = {}
    if isinstance(m, list):
        for it in m:
            if isinstance(it, dict) and "Name" in it:
                out[str(it["Name"]).lower()] = it.get("Percent", 0.0)
    elif isinstance(m, dict):
        for k, v in m.items():
            out[str(k).lower()] = v
    return json.dumps(out) if out else ""


class Ingestor:
    """Stateful translator from journal events to body-database rows."""

    def __init__(self, db: Optional[ExploDB] = None) -> None:
        self._db = db or get_db()
        self._cmdr_id: Optional[int] = None
        self._cmdr_fid: str = ""
        self._sys_id: Optional[int] = None
        self._sys_addr: Optional[int] = None
        self._last_flora_id: Optional[int] = None   # set on ScanOrganic, for waypoint capture

    # ── commander / system context ────────────────────────────────────────

    def set_commander(self, fid: str, name: str = "") -> Optional[int]:
        if fid and fid != self._cmdr_fid:
            self._cmdr_fid = fid
            self._cmdr_id = self._db.ensure_commander(fid, name)
        return self._cmdr_id

    @property
    def commander_id(self) -> Optional[int]:
        return self._cmdr_id

    def current_system_address(self) -> Optional[int]:
        """The SystemAddress of the system last entered (live location)."""
        return self._sys_addr

    def current_commander_id(self) -> Optional[int]:
        """The db id of the active commander (None until LoadGame/Commander)."""
        return self._cmdr_id

    def last_flora_id(self) -> Optional[int]:
        """Flora id from the most recent ScanOrganic (for waypoint capture)."""
        return self._last_flora_id

    def _resolve_system(self, event: dict) -> Optional[int]:
        addr = event.get("SystemAddress")
        if addr is None:
            return self._sys_id
        props: dict[str, Any] = {}
        name = event.get("StarSystem") or event.get("SystemName") or event.get("System")
        if name:
            props["name"] = name
        pos = event.get("StarPos")
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            props["x"], props["y"], props["z"] = pos
        if "Population" in event:
            props["population"] = event["Population"]
        sid = self._db.upsert_system(int(addr), **props)
        self._sys_id, self._sys_addr = sid, int(addr)
        return sid

    # ── dispatch ──────────────────────────────────────────────────────────

    def ingest(self, event: dict) -> None:
        ev = event.get("event")
        if ev == "Commander" or ev == "LoadGame":
            self.set_commander(event.get("FID", ""), event.get("Name") or event.get("Commander", ""))
        elif ev in ("Location", "FSDJump", "CarrierJump"):
            self._resolve_system(event)
        elif ev == "FSSDiscoveryScan":
            self._fss_discovery(event)
        elif ev == "FSSAllBodiesFound":
            self._all_bodies_found(event)
        elif ev == "Scan":
            self._scan(event)
        elif ev in ("FSSBodySignals", "SAASignalsFound"):
            self._body_signals(event)
        elif ev == "SAAScanComplete":
            self._saa_complete(event)
        elif ev == "ScanOrganic":
            self._scan_organic(event)
        elif ev == "Disembark":
            self._disembark(event)

    def ingest_line(self, line: str) -> bool:
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            return False
        self.ingest(event)
        return True

    # ── system-level events ───────────────────────────────────────────────

    def _fss_discovery(self, event: dict) -> None:
        sid = self._resolve_system(event)
        if sid is None:
            return
        props: dict[str, Any] = {}
        if "BodyCount" in event:
            props["body_count"] = event["BodyCount"]
        if "NonBodyCount" in event:
            props["non_body_count"] = event["NonBodyCount"]
        if props:
            self._db.upsert_system(int(event["SystemAddress"]), **props)
        if self._cmdr_id is not None:
            self._db.set_system_status(sid, self._cmdr_id, honked=1)

    def _all_bodies_found(self, event: dict) -> None:
        sid = self._resolve_system(event)
        if sid is not None and self._cmdr_id is not None:
            self._db.set_system_status(sid, self._cmdr_id, fully_scanned=1)

    # ── Scan ──────────────────────────────────────────────────────────────

    def _scan(self, event: dict) -> None:
        sid = self._resolve_system(event)
        body_id = event.get("BodyID")
        if sid is None or body_id is None:
            return
        ts = _ts(event)
        scan_state = _SCAN_STATE.get(event.get("ScanType", ""), 1)

        if "StarType" in event:
            star_id = self._db.upsert_star(
                sid, int(body_id),
                name=event.get("BodyName", ""),
                type=event.get("StarType", ""),
                subclass=event.get("Subclass", 0),
                luminosity=event.get("Luminosity", ""),
                mass=event.get("StellarMass", 0.0),
                radius=event.get("Radius", 0.0),
                temp=event.get("SurfaceTemperature"),
                distance=event.get("DistanceFromArrivalLS", 0.0),
                rotation=event.get("RotationPeriod", 0.0),
                orbital_period=event.get("OrbitalPeriod", 0.0),
            )
            for r in event.get("Rings", []) or []:
                if isinstance(r, dict) and r.get("Name"):
                    self._db.add_ring("star", star_id, r["Name"], r.get("RingClass", ""))
            if self._cmdr_id is not None:
                self._db.set_star_status(
                    star_id, self._cmdr_id, discovered=1,
                    was_discovered=1 if event.get("WasDiscovered") else 0,
                    scan_state=scan_state, scanned_at=ts,
                )
            return

        if "PlanetClass" in event or event.get("Landable") is not None:
            gravity = event.get("SurfaceGravity")
            planet_id = self._db.upsert_planet(
                sid, int(body_id),
                name=event.get("BodyName", ""),
                type=event.get("PlanetClass", ""),
                atmosphere=event.get("Atmosphere", "") or event.get("AtmosphereType", ""),
                volcanism=event.get("Volcanism", ""),
                terraform_state=event.get("TerraformState", ""),
                distance=event.get("DistanceFromArrivalLS", 0.0),
                mass=event.get("MassEM", 0.0),
                radius=event.get("Radius", 0.0),
                gravity=(gravity / _G) if isinstance(gravity, (int, float)) else 0.0,
                temp=event.get("SurfaceTemperature"),
                pressure=event.get("SurfacePressure"),
                rotation=event.get("RotationPeriod", 0.0),
                orbital_period=event.get("OrbitalPeriod", 0.0),
                parent_stars=json.dumps(event.get("Parents")) if isinstance(event.get("Parents"), list) else "",
                materials=_materials_json(event),
                landable=1 if event.get("Landable") else 0,
            )
            for g in event.get("AtmosphereComposition", []) or []:
                if isinstance(g, dict) and g.get("Name"):
                    self._db.set_planet_gas(planet_id, g["Name"], g.get("Percent", 0.0))
            for r in event.get("Rings", []) or []:
                if isinstance(r, dict) and r.get("Name"):
                    self._db.add_ring("planet", planet_id, r["Name"], r.get("RingClass", ""))
            if self._cmdr_id is not None:
                self._db.set_planet_status(
                    planet_id, self._cmdr_id, discovered=1,
                    was_discovered=1 if event.get("WasDiscovered") else 0,
                    was_mapped=1 if event.get("WasMapped") else 0,
                    scan_state=scan_state, scanned_at=ts,
                )
            return

        # Neither star nor planet — a belt cluster / asteroid grouping.
        self._db.upsert_non_body(sid, int(body_id), event.get("BodyName", ""))

    # ── signals / mapping ─────────────────────────────────────────────────

    def _body_signals(self, event: dict) -> None:
        sid = self._resolve_system(event)
        body_id = event.get("BodyID")
        if sid is None or body_id is None:
            return
        planet_id = self._db.upsert_planet(sid, int(body_id), name=event.get("BodyName", ""))
        bio = geo = 0
        for sig in event.get("Signals", []) or []:
            if not isinstance(sig, dict):
                continue
            kind = _signal_kind(sig.get("Type", ""))
            cnt = int(sig.get("Count", 0) or 0)
            if kind == "bio":
                bio += cnt
            elif kind == "geo":
                geo += cnt
            self._db.set_planet_signal(planet_id, kind, cnt)
        for g in event.get("Genuses", []) or []:
            if isinstance(g, dict):
                genus = g.get("Genus_Localised") or g.get("Genus") or ""
                if genus:
                    self._db.set_planet_signal(planet_id, "bio", 0, genus=genus)
        props: dict[str, Any] = {}
        if bio:
            props["bio_signals"] = bio
        if geo:
            props["geo_signals"] = geo
        if props:
            self._db.upsert_planet(sid, int(body_id), **props)

    def _saa_complete(self, event: dict) -> None:
        sid = self._resolve_system(event)
        body_id = event.get("BodyID")
        if sid is None or body_id is None or self._cmdr_id is None:
            return
        planet_id = self._db.upsert_planet(sid, int(body_id), name=event.get("BodyName", ""))
        probes = event.get("ProbesUsed")
        target = event.get("EfficiencyTarget")
        efficient = (
            1 if isinstance(probes, (int, float)) and isinstance(target, (int, float))
            and probes <= target else 0
        )
        self._db.set_planet_status(
            planet_id, self._cmdr_id, mapped=1, efficient=efficient,
            mapped_at=_ts(event),
        )

    # ── exobiology ────────────────────────────────────────────────────────

    def _scan_organic(self, event: dict) -> None:
        addr = event.get("SystemAddress")
        body_id = event.get("Body")
        if addr is None or body_id is None:
            return
        sid = self._db.upsert_system(int(addr))
        planet_id = self._db.upsert_planet(sid, int(body_id))
        genus = _name(event, "Genus")
        species = _name(event, "Species")
        if not genus:
            return
        variant = _name(event, "Variant")
        flora_id = self._db.upsert_flora(planet_id, genus, species, variant)
        self._last_flora_id = flora_id
        if self._cmdr_id is None:
            return
        stage = {"Log": 1, "Sample": 2, "Analyse": 3}.get(event.get("ScanType", ""), 1)
        self._db.set_flora_status(
            flora_id, self._cmdr_id, count=stage,
            logged=1 if stage >= 3 else 0, scanned_at=_ts(event),
        )

    def _disembark(self, event: dict) -> None:
        if not event.get("OnPlanet"):
            return
        sid = self._resolve_system(event)
        body_id = event.get("BodyID")
        if sid is None or body_id is None or self._cmdr_id is None:
            return
        planet_id = self._db.upsert_planet(sid, int(body_id))
        self._db.set_planet_status(planet_id, self._cmdr_id, footfall=1)

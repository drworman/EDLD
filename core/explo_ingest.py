"""
core/explo_ingest.py — Exploration journal events → body-database writes.

The honk, the FSS sweep, the Scan and the surface mapping: everything that
records what a body *is* and how far the commander has got with surveying it.
Sibling: :mod:`core.exobio_ingest` handles sampling.

These are plain functions taking the :class:`core.body_ingest.Ingestor` that
owns the commander/system context, rather than methods on it, so the dispatcher
can import both domains without either importing the other.

:data:`EVENTS` is the set this module handles.
"""

from __future__ import annotations

import json
from typing import Any

from core.journal_fields import G, SCAN_STATE, materials_json, ts

# Journal events handled here.
EVENTS = (
    "FSSDiscoveryScan", "FSSAllBodiesFound",
    "Scan", "SAAScanComplete",
)


# ── system-level events ───────────────────────────────────────────────────────

def fss_discovery(ing, event: dict) -> None:
    """``FSSDiscoveryScan`` — the honk: body counts and the honked flag."""
    sid = ing.resolve_system(event)
    if sid is None:
        return
    props: dict[str, Any] = {}
    if "BodyCount" in event:
        props["body_count"] = event["BodyCount"]
    if "NonBodyCount" in event:
        props["non_body_count"] = event["NonBodyCount"]
    if props:
        ing.db.upsert_system(int(event["SystemAddress"]), **props)
    if ing.commander_id is not None:
        ing.db.set_system_status(sid, ing.commander_id, honked=1)


def all_bodies_found(ing, event: dict) -> None:
    """``FSSAllBodiesFound`` — every body in the system resolved."""
    sid = ing.resolve_system(event)
    if sid is not None and ing.commander_id is not None:
        ing.db.set_system_status(sid, ing.commander_id, fully_scanned=1)


# ── Scan ──────────────────────────────────────────────────────────────────────

def scan(ing, event: dict) -> None:
    """``Scan`` — the body facts, for a star, a planet, or a belt cluster.

    This is the only writer of a body's physical properties.  Everything the
    Exobiology window derives from those properties — landability, gravity,
    atmosphere, temperature — arrives here and nowhere else, which is why the
    Exobiology repaint list has to include ``Scan`` even though the event
    carries no biology of its own.
    """
    sid = ing.resolve_system(event)
    body_id = event.get("BodyID")
    if sid is None or body_id is None:
        return
    stamp = ts(event)
    scan_state = SCAN_STATE.get(event.get("ScanType", ""), 1)

    if "StarType" in event:
        star_id = ing.db.upsert_star(
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
                ing.db.add_ring("star", star_id, r["Name"], r.get("RingClass", ""))
        if ing.commander_id is not None:
            ing.db.set_star_status(
                star_id, ing.commander_id, discovered=1,
                was_discovered=1 if event.get("WasDiscovered") else 0,
                scan_state=scan_state, scanned_at=stamp,
            )
        return

    if "PlanetClass" in event or event.get("Landable") is not None:
        gravity = event.get("SurfaceGravity")
        planet_id = ing.db.upsert_planet(
            sid, int(body_id),
            name=event.get("BodyName", ""),
            type=event.get("PlanetClass", ""),
            atmosphere=event.get("Atmosphere", "") or event.get("AtmosphereType", ""),
            volcanism=event.get("Volcanism", ""),
            terraform_state=event.get("TerraformState", ""),
            distance=event.get("DistanceFromArrivalLS", 0.0),
            mass=event.get("MassEM", 0.0),
            radius=event.get("Radius", 0.0),
            gravity=(gravity / G) if isinstance(gravity, (int, float)) else 0.0,
            temp=event.get("SurfaceTemperature"),
            pressure=event.get("SurfacePressure"),
            rotation=event.get("RotationPeriod", 0.0),
            orbital_period=event.get("OrbitalPeriod", 0.0),
            parent_stars=json.dumps(event.get("Parents")) if isinstance(event.get("Parents"), list) else "",
            materials=materials_json(event),
            landable=1 if event.get("Landable") else 0,
        )
        for g in event.get("AtmosphereComposition", []) or []:
            if isinstance(g, dict) and g.get("Name"):
                ing.db.set_planet_gas(planet_id, g["Name"], g.get("Percent", 0.0))
        for r in event.get("Rings", []) or []:
            if isinstance(r, dict) and r.get("Name"):
                ing.db.add_ring("planet", planet_id, r["Name"], r.get("RingClass", ""))
        if ing.commander_id is not None:
            ing.db.set_planet_status(
                planet_id, ing.commander_id, discovered=1,
                was_discovered=1 if event.get("WasDiscovered") else 0,
                was_mapped=1 if event.get("WasMapped") else 0,
                scan_state=scan_state, scanned_at=stamp,
            )
        return

    # Neither star nor planet — a belt cluster / asteroid grouping.
    ing.db.upsert_non_body(sid, int(body_id), event.get("BodyName", ""))


# ── surface mapping ───────────────────────────────────────────────────────────

def saa_complete(ing, event: dict) -> None:
    """``SAAScanComplete`` — surface mapped, with the efficiency bonus flag."""
    sid = ing.resolve_system(event)
    body_id = event.get("BodyID")
    if sid is None or body_id is None or ing.commander_id is None:
        return
    planet_id = ing.db.upsert_planet(sid, int(body_id), name=event.get("BodyName", ""))
    probes = event.get("ProbesUsed")
    target = event.get("EfficiencyTarget")
    efficient = (
        1 if isinstance(probes, (int, float)) and isinstance(target, (int, float))
        and probes <= target else 0
    )
    ing.db.set_planet_status(
        planet_id, ing.commander_id, mapped=1, efficient=efficient,
        mapped_at=ts(event),
    )

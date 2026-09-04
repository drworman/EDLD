"""
core/exobio_ingest.py — Exobiology journal events → body-database writes.

Organic sampling and footfall: everything that records what the commander has
*done* on a body's surface, as opposed to what the body is.  Sibling:
:mod:`core.explo_ingest` handles scanning and mapping.

These are plain functions taking the :class:`core.body_ingest.Ingestor` that
owns the commander/system context, rather than methods on it, so the dispatcher
can import both domains without either importing the other.

:data:`EVENTS` is the set this module handles.
"""

from __future__ import annotations

from core.journal_fields import name, ts

# Journal events handled here.
EVENTS = (
    "ScanOrganic", "Disembark",
)

# ``ScanType`` → sample stage.  Three samples of a species complete it.
_STAGE = {"Log": 1, "Sample": 2, "Analyse": 3}


def scan_organic(ing, event: dict) -> None:
    """``ScanOrganic`` — a sample of a species, at one of three stages."""
    addr = event.get("SystemAddress")
    body_id = event.get("Body")
    if addr is None or body_id is None:
        return
    sid = ing.db.upsert_system(int(addr))
    planet_id = ing.db.upsert_planet(sid, int(body_id))
    genus = name(event, "Genus")
    species = name(event, "Species")
    if not genus:
        return
    variant = name(event, "Variant")
    flora_id = ing.db.upsert_flora(planet_id, genus, species, variant)
    ing.note_flora(flora_id)
    if ing.commander_id is None:
        return
    stage = _STAGE.get(event.get("ScanType", ""), 1)
    ing.db.set_flora_status(
        flora_id, ing.commander_id, count=stage,
        logged=1 if stage >= 3 else 0, scanned_at=ts(event),
    )
    # Only one organic sample can be in progress at a time — sampling this
    # species drops any incomplete progress on a different one.
    ing.db.reset_other_in_progress_flora(ing.commander_id, flora_id)


def disembark(ing, event: dict) -> None:
    """``Disembark`` — footfall on a body, for the first-footfall bonus."""
    if not event.get("OnPlanet"):
        return
    sid = ing.resolve_system(event)
    body_id = event.get("BodyID")
    if sid is None or body_id is None or ing.commander_id is None:
        return
    planet_id = ing.db.upsert_planet(sid, int(body_id))
    ing.db.set_planet_status(planet_id, ing.commander_id, footfall=1)

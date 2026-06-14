"""
core/exobio_view.py — Exobiology window view builder.

Turns the stored biology facts for one system (from :mod:`core.explo_db`) plus a
commander's sample progress into a structured view the TUI Exobiology
blocks render.  Values and clonal distances come from :mod:`core.exobio_data`.

Only accurate, journal-derived information is reported: the bio-signal count per
body, the genera the game has revealed (after a bio surface scan), and the
species actually sampled with their stage (Logged / Sampled / Analysed).  Genus
value ranges are shown as hints for revealed-but-unsampled genera.
"""

from __future__ import annotations

from typing import Optional

from core.explo_db import ExploDB, get_db
from core import exobio_data as B
from core import geo
from core.exobio_predict import (
    predict_genera, value_range, first_footfall_potential, FIRST_FOOTFALL_MAX_MULT,
)

_STAGE_LABEL = {1: "Logged", 2: "Sampled", 3: "Analysed"}


def _short_name(body_name: str, system_name: str) -> str:
    if system_name and body_name.startswith(system_name):
        return (body_name[len(system_name):].strip() or body_name)
    return body_name


def build_exobio_view(
    system_address: Optional[int],
    commander_id: Optional[int],
    db: Optional[ExploDB] = None,
    position: Optional[dict] = None,
) -> Optional[dict]:
    """Build the exobiology view for a system, or None if unknown/unset.

    ``position`` (optional, from live status) carries the on-foot aid context:
    ``{"lat", "lon", "radius", "heading", "on_foot", "body"}``.  When the
    commander is on a body with in-progress samples, each such species gains an
    ``aid`` giving distance/bearing to its nearest previous sample and whether
    that already clears the clonal-spacing requirement.
    """
    if system_address is None or commander_id is None:
        return None
    db = db or get_db()
    sysrow = db.get_system(int(system_address))
    if not sysrow:
        return None
    system_id = sysrow["id"]
    sys_name  = sysrow.get("name", "") or ""

    grouped = db.system_bodies(system_id, commander_id)
    bodies: list[dict] = []
    tot_signals = tot_scanned = tot_analysed = value_logged = 0
    pot_min = pot_max = 0

    for p in grouped["planets"]:
        planet_id = p["id"]
        bio = int(p.get("bio_signals", 0) or 0)
        flora_rows = db.planet_flora(planet_id, commander_id)
        if bio <= 0 and not flora_rows:
            continue

        # Genera the game has revealed (kind='bio' signal rows carrying a genus).
        genera = []
        seen = set()
        for sig in db.planet_signals(planet_id):
            if sig.get("kind") == "bio" and sig.get("genus"):
                g = sig["genus"]
                if g in seen:
                    continue
                seen.add(g)
                rng = B.genus_value_range(g)
                genera.append({
                    "genus": g,
                    "value_min": rng[0] if rng else 0,
                    "value_max": rng[1] if rng else 0,
                })

        # Is this the body the commander is currently on? (drives the on-foot aid)
        body_name  = p.get("name", "")
        is_current = bool(position and position.get("body") and body_name == position.get("body"))
        pos_ok = bool(is_current and position.get("lat") is not None
                      and position.get("lon") is not None and position.get("radius"))

        flora = []
        scanned = analysed = 0
        for f in flora_rows:
            name  = f.get("species") or f.get("genus") or ""
            stage = int(f.get("count", 0) or 0)
            logged = bool(f.get("logged"))
            base = B.species_base_by_name(name)
            clonal = B.clonal_distance(name)
            if stage >= 1:
                scanned += 1
            if logged:
                analysed += 1
                value_logged += base
            wps = [(w["latitude"], w["longitude"])
                   for w in db.flora_waypoints(f["id"], commander_id)]
            aid = None
            if pos_ok and not logged and stage in (1, 2) and wps:
                near = geo.nearest_waypoint(position["lat"], position["lon"],
                                            position["radius"], wps)
                if near:
                    aid = {
                        "distance": round(near["distance"]),
                        "bearing":  round(near["bearing"]),
                        "heading":  position.get("heading"),
                        "clonal":   clonal,
                        "ok":       near["distance"] >= clonal,
                    }
            flora.append({
                "name": name,
                "genus": f.get("genus", ""),
                "species": f.get("species", ""),
                "stage": stage,
                "stage_label": _STAGE_LABEL.get(stage, "—"),
                "logged": logged,
                "value": base,
                "clonal": clonal,
                "waypoints": wps,
                "aid": aid,
            })

        tot_signals  += bio
        tot_scanned  += scanned
        tot_analysed += analysed

        # Prediction: when the game has revealed genera, narrow to them; otherwise
        # predict from body properties.  Confirmed genera (from signals) stay
        # authoritative in "genera"; "predicted_genera" carries the estimate.
        confirmed  = [g["genus"] for g in genera]
        predicting = bio > 0 and not confirmed
        pred_genera = []
        vmin = vmax = vmax_possible = 0
        if bio > 0 and p.get("landable"):
            gf = set(confirmed) or None
            pred_genera = predict_genera(p, genera_filter=gf)
            vmin, vmax        = value_range(p, bio, genera_filter=gf, include_gated=False)
            _, vmax_possible  = value_range(p, bio, genera_filter=gf, include_gated=True)
        first_ff = first_footfall_potential(bool(p.get("was_discovered")), bool(p.get("footfall")))
        pot_min += vmin
        pot_max += max(vmax, vmax_possible)

        bodies.append({
            "name": p.get("name", ""),
            "short": _short_name(p.get("name", ""), sys_name),
            "body_id": p.get("body_id"),
            "bio_signals": bio,
            "genera": genera,
            "predicting": predicting,
            "predicted_genera": pred_genera,
            "value_min": vmin,
            "value_max": vmax,
            "value_max_possible": vmax_possible,
            "first_footfall": first_ff,
            "first_footfall_mult": FIRST_FOOTFALL_MAX_MULT if first_ff else 1,
            "flora": flora,
            "scanned": scanned,
            "analysed": analysed,
            "complete": bio > 0 and analysed >= bio,
            "landable": bool(p.get("landable")),
            "current": is_current,
        })

    # Focus the body the commander is currently on (stable; others keep order).
    bodies.sort(key=lambda b: not b.get("current"))

    return {
        "system": {
            "name": sys_name,
            "address": int(system_address),
        },
        "on_foot": bool(position and position.get("on_foot")),
        "current_body": (position or {}).get("body", ""),
        "bodies": bodies,
        "totals": {
            "bodies_with_bio": len(bodies),
            "total_signals": tot_signals,
            "scanned": tot_scanned,
            "analysed": tot_analysed,
            "value_logged": value_logged,
            "potential_value_min": pot_min,
            "potential_value_max": pot_max,
        },
    }

"""
core/exobio_predict.py — Exobiology genus/species prediction & value estimation.

Given a body's stored properties (planet class, atmosphere, gravity, surface
temperature, pressure, volcanism), determine which organic species can occur
there and, from the bio-signal count, a credit value range — so a commander can
judge whether a body is worth landing on before committing to a surface scan.

Accuracy
--------
* Conditions come from the species catalog in :mod:`core.exobio_rules`; values
  from the verified table in :mod:`core.exobio_data`.
* Genera the game has already revealed (a surface bio scan) are authoritative;
  prediction only fills the gap before that.
* Rules carrying location constraints this engine doesn't fully evaluate
  (region / nebula / specific star) are reported as *gated*: the species is
  possible if those extra conditions also hold, so it's surfaced but flagged.
* A property the body doesn't yet expose never excludes a species (conservative).

First footfall
--------------
A body never previously discovered almost certainly still has its first footfall
available, which multiplies a sample sharply (first-logged x5, first-footfall
+x4 of base — up to x9 combined).
"""

from __future__ import annotations

from typing import Optional

from core.exobio_rules import SPECIES_RULES
from core import exobio_data as B

FIRST_LOGGED_MULT       = 5
FIRST_FOOTFALL_BONUS    = 4
FIRST_FOOTFALL_MAX_MULT = FIRST_LOGGED_MULT + FIRST_FOOTFALL_BONUS  # x9 best case

_PA_PER_ATM = 101325.0
_GASES = ("carbon dioxide", "sulphur dioxide", "ammonia", "water", "methane",
          "nitrogen", "oxygen", "neon", "argon", "helium")


def normalize_atmosphere(atmosphere: str) -> str:
    a = (atmosphere or "").lower()
    if not a or "no atmosphere" in a:
        return ""
    for g in _GASES:
        if g in a:
            return g
    return ""


def _has_volcanism(volcanism: str) -> Optional[bool]:
    v = (volcanism or "").strip().lower()
    if not v:
        return None  # unknown
    return "no volcanism" not in v


def _rule_matches(rule: dict, *, atm: str, body_type: str, gravity: float,
                  temp: Optional[float], pressure_atm: Optional[float],
                  has_volc: Optional[bool]) -> bool:
    if rule.get("no_atm"):
        if atm:
            return False
    elif "atm" in rule:
        if atm and atm not in rule["atm"]:
            return False
    if rule.get("body") and body_type and body_type not in rule["body"]:
        return False
    if gravity:
        if "g_min" in rule and gravity < rule["g_min"] - 1e-6:
            return False
        if "g_max" in rule and gravity > rule["g_max"] + 1e-6:
            return False
    if temp:
        if "t_min" in rule and temp < rule["t_min"]:
            return False
        if "t_max" in rule and temp > rule["t_max"]:
            return False
    if pressure_atm:
        if "p_min" in rule and pressure_atm < rule["p_min"]:
            return False
        if "p_max" in rule and pressure_atm > rule["p_max"]:
            return False
    volc = rule.get("volc")
    if volc == "none" and has_volc is True:
        return False
    if volc in ("any", "required") and has_volc is False:
        return False
    return True


def predict_species(body: dict, genera_filter: Optional[set] = None) -> list[dict]:
    """Possible species for a body dict (planet row + status).

    Expects: type, atmosphere, gravity (G), temp (K), pressure (Pa), volcanism,
    landable.  ``genera_filter`` (localised genus names) narrows the result to
    genera the game has revealed.  Each result: {key, name, genus, value, gated}.
    """
    if not body.get("landable"):
        return []
    atm       = normalize_atmosphere(body.get("atmosphere", ""))
    body_type = (body.get("type") or "").lower().strip()
    gravity   = float(body.get("gravity", 0.0) or 0.0)
    temp      = body.get("temp")
    temp      = float(temp) if isinstance(temp, (int, float)) else None
    praw      = body.get("pressure")
    pressure  = (float(praw) / _PA_PER_ATM) if isinstance(praw, (int, float)) and praw else None
    has_volc  = _has_volcanism(body.get("volcanism", ""))
    gfilter   = {g.lower() for g in genera_filter} if genera_filter else None

    out = []
    for key, sp in SPECIES_RULES.items():
        if gfilter and sp["genus"].lower() not in gfilter:
            continue
        best_gated = None
        for rule in sp["rules"]:
            if _rule_matches(rule, atm=atm, body_type=body_type, gravity=gravity,
                             temp=temp, pressure_atm=pressure, has_volc=has_volc):
                gated = bool(rule.get("gated"))
                best_gated = gated if best_gated is None else (best_gated and gated)
        if best_gated is not None:
            out.append({"key": key, "name": sp["name"], "genus": sp["genus"],
                        "value": sp["value"], "gated": best_gated})
    return out


def predict_genera(body: dict, genera_filter: Optional[set] = None) -> list[dict]:
    """Possible genera for a body: [{genus, value_min, value_max, gated}]."""
    by_genus: dict[str, dict] = {}
    for sp in predict_species(body, genera_filter):
        g = by_genus.setdefault(sp["genus"], {"genus": sp["genus"], "value_min": sp["value"],
                                              "value_max": sp["value"], "gated": True})
        g["value_min"] = min(g["value_min"], sp["value"])
        g["value_max"] = max(g["value_max"], sp["value"])
        g["gated"]     = g["gated"] and sp["gated"]
    return sorted(by_genus.values(), key=lambda g: -g["value_max"])


def value_range(body: dict, signal_count: int,
                genera_filter: Optional[set] = None,
                include_gated: bool = True) -> tuple[int, int]:
    """Estimated total base-value range for ``signal_count`` species on a body."""
    sps = predict_species(body, genera_filter)
    if not include_gated:
        sps = [s for s in sps if not s["gated"]]
    vals = sorted(s["value"] for s in sps)
    if not vals or signal_count <= 0:
        return (0, 0)
    n = min(signal_count, len(vals))
    lo = sum(vals[:n])
    hi = sum(vals[-n:])
    if signal_count > len(vals):
        extra = signal_count - len(vals)
        lo += extra * vals[0]
        hi += extra * vals[-1]
    return (lo, hi)


def first_footfall_potential(was_discovered: bool, footfall_done: bool) -> bool:
    return (not was_discovered) and (not footfall_done)

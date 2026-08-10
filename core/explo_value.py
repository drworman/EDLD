"""
core/explo_value.py — Body cartographic value math.

The single implementation of the body-value formula, shared by the session
exploration tracker and the Exploration window so both always agree.

Model
-----
    base               = k + (3 * k * mass^0.199977 / 5.3)
    terraform bonus    = same shape with the terraform k-factor (planets only)
    first discovery    = scan value × 2.5
    mapped (DSS)       = scan value × 3.3 × 1.3
    efficiency bonus   = mapped value × 1.25

``scan_value`` combines these for a planet given its discovery / mapping state;
``star_value`` covers stars (which are not surface-mapped).
"""

from __future__ import annotations

# ── k-factors ─────────────────────────────────────────────────────────────────

PLANET_K: dict[str, int] = {
    "metal rich body":             52292,
    "ammonia world":              232619,
    "sudarsky class i gas giant":   3974,
    "sudarsky class ii gas giant": 23168,
    "high metal content body":     23168,
    "water world":                155581,
    "earthlike body":             155581,
}
PLANET_K_DEFAULT = 720

TERRA_K: dict[str, int] = {
    "high metal content body":  241607,
    "water world":              279088,
    "earthlike body":           279088,
    "rocky body":               223971,
}

STAR_K: dict[str, int] = {
    "black hole":   54309,
    "neutron star": 54309,
    "white dwarf":  33737,
}
STAR_K_DEFAULT = 2880

FIRST_DISC_MULT = 2.5
MAP_MULT        = 3.3 * 1.3
EFFICIENCY_MULT = 1.25


# ── value functions ─────────────────────────────────────────────────────────

def planet_base(planet_class: str, mass_em: float) -> int:
    pc = planet_class.lower().strip()
    k  = PLANET_K.get(pc, PLANET_K_DEFAULT)
    return round(k + (3 * k * (mass_em ** 0.199977) / 5.3))


def terra_bonus(planet_class: str, mass_em: float) -> int:
    pc = planet_class.lower().strip()
    kt = TERRA_K.get(pc, 0)
    if not kt:
        return 0
    return round(kt + (3 * kt * (mass_em ** 0.199977) / 5.3))


def star_value(star_type: str, solar_mass: float) -> int:
    st = star_type.lower()
    k  = next((v for key, v in STAR_K.items() if key in st), STAR_K_DEFAULT)
    return round(k + (solar_mass * k / 66.25))


def is_terraformable(terraform_state: str) -> bool:
    return bool(terraform_state and terraform_state.lower()
                not in ("", "not terraformable"))


def scan_value(planet_class: str, mass_em: float, terraform_state: str,
               was_discovered: bool, was_mapped: bool,
               dss_mapped: bool, efficient: bool) -> int:
    base  = planet_base(planet_class, mass_em)
    bonus = terra_bonus(planet_class, mass_em) if is_terraformable(terraform_state) else 0
    scan_val = base + bonus
    value = round(scan_val * FIRST_DISC_MULT) if not was_discovered else scan_val
    if dss_mapped:
        map_val = round(scan_val * MAP_MULT)
        if not was_mapped:
            map_val = round(map_val)
        if efficient:
            map_val = round(map_val * EFFICIENCY_MULT)
        value += map_val
    return value

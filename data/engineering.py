"""
data/engineering.py — Engineering blueprint and experimental effect display names.

Keys are lowercase internal names as emitted in journal events
(BlueprintName, ExperimentalEffect).  Values are the in-game display strings.
"""
from __future__ import annotations
import re as _re

BLUEPRINT_NAMES: dict[str, str] = {
    # ── Weapons ───────────────────────────────────────────────────────────────
    "weapon_longrange":             "Long Range",
    "weapon_highcapacity":          "High Capacity Magazine",
    "weapon_rapidfire":             "Rapid Fire",
    "weapon_overcharged":           "Overcharged",
    "weapon_lightweight":           "Lightweight",
    "weapon_focused":               "Focused",
    "weapon_efficient":             "Efficient",
    "weapon_shorterange":           "Short Range Blaster",
    "weapon_dazzle":                "Dazzle Shell",
    "weapon_scramblespectrum":      "Scramble Spectrum",
    "weapon_incendiary":            "Incendiary Rounds",
    "weapon_screening":             "Screening Shell",
    # ── Engines ───────────────────────────────────────────────────────────────
    "engine_dirty":                 "Dirty Drive Tuning",
    "engine_reinforced":            "Drive Strengthening",
    "engine_clean":                 "Clean Drive Tuning",
    "engine_tuned":                 "Tuned Drive Tuning",
    # ── FSD ───────────────────────────────────────────────────────────────────
    "fsd_longrange":                "Increased Range",
    "fsd_fastboot":                 "Faster Boot Sequence",
    "fsd_shielded":                 "Shielded FSD",
    # ── Shields ───────────────────────────────────────────────────────────────
    "shieldgenerator_thermic":      "Thermal Resistance",
    "shieldgenerator_kinetic":      "Kinetic Resistance",
    "shieldgenerator_reinforced":   "Reinforced",
    "shieldgenerator_enhanced":     "Enhanced Low Power",
    # ── Power plant ───────────────────────────────────────────────────────────
    "powerplant_boosted":           "Overcharged",
    "powerplant_armoured":          "Armoured",
    "powerplant_lightweight":       "Low Emissions",
    # ── Power distributor ─────────────────────────────────────────────────────
    "powerdistributor_priorityengines": "Charge Enhanced",
    "powerdistributor_highfrequency":   "High Frequency Distributor",
    "powerdistributor_shielded":        "Shielded",
    # ── Armour ────────────────────────────────────────────────────────────────
    "armour_heavyduty":             "Heavy Duty",
    "armour_kinetic":               "Kinetic Armour",
    "armour_thermic":               "Thermal Armour",
    "armour_explosive":             "Explosive Armour",
    "armour_advanced":              "Advanced",
    # ── Hull reinforcement ────────────────────────────────────────────────────
    "hullreinforcement_heavyduty":  "Heavy Duty",
    "hullreinforcement_kinetic":    "Kinetic Armour",
    "hullreinforcement_thermic":    "Thermal Armour",
    "hullreinforcement_explosive":  "Explosive Armour",
    "hullreinforcement_advanced":   "Advanced",
    # ── Sensors ───────────────────────────────────────────────────────────────
    "sensor_longrange":             "Long Range",
    "sensor_fastscan":              "Fast Scan",
    "sensor_wideangle":             "Wide Angle",
    "sensor_lightweight":           "Lightweight",
    # ── Misc ──────────────────────────────────────────────────────────────────
    "cargoscanner_fastscan":        "Fast Scan",
    "cargoscanner_longrange":       "Long Range",
    "cargorack_increasedcapacity":  "Expanded",
    "misc_highpowerercapacity":     "Stripped Down",
}

EXP_EFFECT_NAMES: dict[str, str] = {
    "special_weapon_damage":              "Oversized",
    "special_weapon_multidestabiliser":   "Multi-Servos",
    "special_weapon_dazzle":              "Dazzle Shell",
    "special_weapon_scramblespectrum":    "Scramble Spectrum",
    "special_weapon_incendiary":          "Incendiary Rounds",
    "special_weapon_autoloader":          "Auto Loader",
    "special_weapon_empconduit":          "Stripped Down",
    "special_weapon_thermalshock":        "Thermal Shock",
    "special_weapon_inertialimpact":      "Inertial Impact",
    "special_weapon_corrosive":           "Corrosive Shell",
    "special_weapon_screening":           "Screening Shell",
    "special_engine_dirty":               "Dirty Drive Tuning",
    "special_engine_clean":               "Clean Drive Tuning",
    "special_fsd_toughened":              "Mass Manager",
    "special_fsd_stripped":               "Deep Charge",
    "special_shield_regenerative":        "Fast Charge",
    "special_shield_toughened":           "Hi-Cap",
    "special_shield_resistive":           "Kinetic Resistance",
    "special_shield_thermic":             "Thermo Block",
    "special_powerplant_toughened":       "Double Braced",
    "special_powerplant_stealth":         "Low Emissions",
    "special_armour_chunky":              "Deep Plating",
    "special_armour_thermic":             "Heat Resistant",
    "special_hullreinforcement_chunky":   "Deep Plating",
    "special_hullreinforcement_thermic":  "Heat Resistant",
    "special_misc_chunkybursts":          "Chunky Bursts",
    "special_misc_shielddampen":          "Dispersal Field",
    "special_misc_concordant":            "Concordant Sequence",
    "special_misc_heatdissipation":       "Recycling Cell",
    "special_misc_coolingblock":          "Cooling Block",
    "special_misc_expanded":              "Expanded Capture Arc",
}


def normalise_eng_name(name: str) -> str:
    """Convert a BlueprintName or ExperimentalEffect to a readable form."""
    if not name:
        return ""
    key = name.lower().strip()
    if key in EXP_EFFECT_NAMES:
        return EXP_EFFECT_NAMES[key]
    if key in BLUEPRINT_NAMES:
        return BLUEPRINT_NAMES[key]
    cleaned = _re.sub(r"^[A-Za-z]+_", "", name)
    return cleaned.replace("_", " ").title().strip()

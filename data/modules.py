"""
data/modules.py — Elite Dangerous module internal name → display name maps.

Keys in MODULE_TYPES follow the normalised internal format produced by
stripping the ``int_`` / ``hpt_`` prefix and any ``_size{N}_class{N}``
suffix from journal/CAPI module internal names.  Where the game uses a
variant suffix (e.g. ``_fast``, ``_overcharge``) that is kept as part of
the key.

Sources: in-game outfitting panels and journal/CAPI module identifiers.
Validated and augmented against in-game data as of 2026.
"""
from __future__ import annotations
import re as _re

# ── Class / rating helpers ────────────────────────────────────────────────────

MODULE_CLASS_MAP: dict[str, str] = {
    "1": "E", "2": "D", "3": "C", "4": "B", "5": "A",
}

MODULE_RATING_MAP: dict[str, str] = {
    "1": "E", "2": "D", "3": "C", "4": "B", "5": "A",
}

MODULE_MOUNT_MAP: dict[str, str] = {
    "fixed":    "Fixed",
    "gimbal":   "Gimballed",
    "turret":   "Turret",
}

MODULE_SIZE_MAP: dict[str, str] = {
    "tiny":   "0",
    "small":  "1",
    "medium": "2",
    "large":  "3",
    "huge":   "4",
}

ARMOUR_GRADES: dict[str, str] = {
    "grade1":   "Lightweight Alloy",
    "grade2":   "Reinforced Alloy",
    "grade3":   "Military Grade Composite",
    "mirrored": "Mirrored Surface Composite",
    "reactive": "Reactive Surface Composite",
}

# ── Module type map ────────────────────────────────────────────────────────────
# Keys are lower-case normalised internal names (prefix + size/class stripped).

MODULE_TYPES: dict[str, str] = {
    # ── Thrusters / drives ────────────────────────────────────────────────────
    "engine":                       "Thrusters",
    "engine_fast":                  "Enhanced Performance Thrusters",
    "engine_gravityoptimised":      "Gravity Optimized Thrusters",
    "hyperdrive":                   "Frame Shift Drive",
    "hyperdrive_overcharge":        "Frame Shift Drive (SCO)",
    # ── Power ─────────────────────────────────────────────────────────────────
    "powerplant":                   "Power Plant",
    "powerdistributor":             "Power Distributor",
    # ── Shields / armour ──────────────────────────────────────────────────────
    "shieldgenerator":              "Shield Generator",
    "shieldgenerator_fast":         "Bi-Weave Shield Generator",
    "shieldgenerator_strong":       "Prismatic Shield Generator",
    "shieldbankfast":               "Shield Cell Bank",
    "shieldbank":                   "Shield Cell Bank",
    "hullreinforcement":            "Hull Reinforcement Package",
    "modulereinforcement":          "Module Reinforcement Package",
    "metaalloyhullreinforcement":   "Meta-Alloy Hull Reinforcement",
    "meta_alloy_hull_reinforcement":"Meta-Alloy Hull Reinforcement",
    "guardianshieldreinforcement":  "Guardian Shield Reinforcement",
    "guardianhullreinforcement":    "Guardian Hull Reinforcement",
    "guardianmodulereinforcement":  "Guardian Module Reinforcement",
    "guardianmodulereinforcementpackage": "Guardian Module Reinforcement",
    # ── Hardpoints — weapons ──────────────────────────────────────────────────
    "beamlaser":                    "Beam Laser",
    "beamlaser_heat":               "Retributor Beam Laser",
    "pulselaser":                   "Pulse Laser",
    "pulselaser_disruptor":         "Pulse Disruptor Laser",
    "pulselaserburst":              "Burst Laser",
    "pulselaserburst_scatter":      "Cytoscrambler Burst Laser",
    "multican":                     "Multi-Cannon",
    "multicannon":                  "Multi-Cannon",
    "multicannon_advanced":         "Advanced Multi-Cannon",
    "multicannon_strong":           "Enforcer Cannon",
    "cannon":                       "Cannon",
    "railgun":                      "Rail Gun",
    "railgun_burst":                "Imperial Hammer Rail Gun",
    "railgun_fixed_medium_burst":   "Imperial Hammer Rail Gun",
    "railgun_fixed_small_burst":    "Imperial Hammer Rail Gun",
    "plasmaaccelerator":            "Plasma Accelerator",
    "plasmaaccelerator_advanced":   "Advanced Plasma Accelerator",
    "plasmashockcannon":            "Shock Cannon",
    "plasmashockautocannon":        "Plasma Shock Cannon",
    "mkiiplasmashockautocannon":    "Plasma Shock Cannon Mk II",
    "mininglaser":                  "Mining Laser",
    "mininglaser_advanced":         "Mining Lance Beam Laser",
    "mininglance":                  "Mining Lance",
    "slugshot":                     "Fragment Cannon",
    "slugshot_range":               "Pacifier Frag-Cannon",
    "dumbfiremissilerack":          "Missile Rack",
    "dumbfiremissilerack_advanced": "Advanced Missile Rack",
    "dumbfiremissilerack_lasso":    "Rocket Propelled FSD Disruptor",
    "drunkmissilerack":             "Pack-Hound Missile Rack",
    "drunkmissilerack_advanced":    "Advanced Multi-Target Missiles",
    "basicmissilerack":             "Seeker Missile Rack",
    "causticmissile":               "Enzyme Missile Rack",
    "advancedtorpedopylon":         "Torpedo Pylon",
    "advancedtorppylon":            "Torpedo Pylon",
    "torpedopylon":                 "Torpedo Pylon",
    "minelauncher":                 "Mine Launcher",
    "minelauncher_impulse":         "Shock Mine Launcher",
    "flakmortar":                   "Remote Release Flak Launcher",
    "flechettelauncher":            "Remote Release Flechette Launcher",
    "atdumbfiremissile":            "AX Missile Rack",
    "atdumbfiremissile_v2":         "Enhanced AX Missile Rack",
    "atmulticannon":                "AX Multi-Cannon",
    "atmulticannon_v2":             "Enhanced AX Multi-Cannon",
    "atventdisruptorpylon":         "Guardian Nanite Torpedo Pylon",
    "guardian_gausscannon":         "Guardian Gauss Cannon",
    "guardian_plasmacarbine":       "Guardian Plasma Charger",
    "guardian_plasmalauncher":      "Guardian Plasma Charger",
    "guardian_shardcannon":         "Guardian Shard Cannon",
    "mining_abrblstr":              "Abrasion Blaster",
    "mining_seismchrgwarhd":        "Seismic Charge Launcher",
    "mining_subsurfdispmisle":      "Sub-Surface Displacement Missile",
    "human_extraction":             "Sub-Surface Extraction Missile",
    "subsurfaceextractionmissile":  "Sub-Surface Extraction Missile",
    # ── Utility hardpoints ────────────────────────────────────────────────────
    "shieldbooster":                "Shield Booster",
    "plasmapointdefence":           "Point Defence",
    "chafflauncher":                "Chaff Launcher",
    "electroniccountermeasure":     "ECM",
    "electronicscountermeasure":    "ECM",
    "heatsinklauncher":             "Heat Sink Launcher",
    "antiunknownshutdown":          "Shutdown Field Neutraliser",
    "antiunknownshutdown_v2":       "Thargoid Pulse Neutraliser",
    "xenoscanner":                  "Xeno Scanner",
    "cargoscanner":                 "Cargo Scanner",
    "cloudscanner":                 "Frame Shift Wake Scanner",
    "crimescanner":                 "Kill Warrant Scanner",
    "killwarrantscanner":           "Kill Warrant Scanner",
    "mrascanner":                   "Pulse Wave Analyser",
    "pulsewavescanner":             "Pulse Wave Analyser",
    "causticchafflauncher":         "Caustic Sink Launcher",
    "shipdatalinkscanner":          "Data Link Scanner",
    "sentinelweaponcontroller":     "Guardian Sentinel Weapon",
    # ── Core internals ────────────────────────────────────────────────────────
    "sensors":                      "Sensors",
    "lifesupport":                  "Life Support",
    "fueltank":                     "Fuel Tank",
    # ── Optional internals ────────────────────────────────────────────────────
    "fuelscoop":                    "Fuel Scoop",
    "cargorack":                    "Cargo Rack",
    "corrosionproofcargorack":      "Corrosion Resistant Cargo Rack",
    "dockingcomputer":              "Docking Computer",
    "dockingcomputer_advanced":     "Advanced Docking Computer",
    "dockingcomputer_standard":     "Standard Docking Computer",
    "supercruiseassist":            "Supercruise Assist",
    "detailedsurfacescanner":       "Detailed Surface Scanner",
    "fighterbay":                   "Fighter Hangar",
    "passengercabin":               "Passenger Cabin",
    "buggybay":                     "Planetary Vehicle Hangar",
    "repairer":                     "Auto Field-Maintenance Unit",
    "fsdinterdictor":               "Frame Shift Drive Interdictor",
    "stellarbodydiscoveryscanner":  "Discovery Scanner",
    "stellarbodydiscoveryscanner_standard":     "Basic Discovery Scanner",
    "stellarbodydiscoveryscanner_intermediate": "Intermediate Discovery Scanner",
    "stellarbodydiscoveryscanner_advanced":     "Advanced Discovery Scanner",
    "planetapproachsuite":          "Planetary Approach Suite",
    "codexscanner":                 "Codex Scanner",
    "colonisation":                 "Colonisation Suite",
    "colonisationmodule":           "Colonisation Module",
    "expmodulestabiliser":          "Experimental Weapon Stabiliser",
    # ── Limpet controllers — dronecontrol_* prefix form ──────────────────────
    "dronecontrol_prospector":      "Prospector Limpet Controller",
    "dronecontrol_collection":      "Collector Limpet Controller",
    "dronecontrol_fueltransfer":    "Fuel Transfer Limpet Controller",
    "dronecontrol_repair":          "Repair Limpet Controller",
    "dronecontrol_recon":           "Recon Limpet Controller",
    "dronecontrol_resourcesiphon":  "Resource Siphon Limpet Controller",
    "dronecontrol_decontamination": "Decontamination Limpet Controller",
    # ── Limpet controllers — short-form keys ────────────────────────────────
    "collection":                   "Collector Limpet Controller",
    "prospector":                   "Prospector Limpet Controller",
    "fueltransfer":                 "Fuel Transfer Limpet Controller",
    "repair":                       "Repair Limpet Controller",
    "recon":                        "Recon Limpet Controller",
    "resourcesiphon":               "Hatch Breaker Limpet Controller",
    "decontamination":              "Decontamination Limpet Controller",
    "rescue":                       "Rescue Limpet Controller",
    "unkvesselresearch":            "Research Limpet Controller",
    # ── Multi-limpet controllers ──────────────────────────────────────────────
    "multidronecontrol_universal":  "Universal Multi-Limpet Controller",
    "multidronecontrol_mining":     "Mining Multi-Limpet Controller",
    "multidronecontrol_operations": "Operations Multi-Limpet Controller",
    "multidronecontrol_xeno":       "Xeno Multi-Limpet Controller",
    "universal":                    "Universal Multi-Limpet Controller",
    "mining":                       "Mining Multi-Limpet Controller",
    "operations":                   "Operations Multi-Limpet Controller",
    "xeno":                         "Xeno Multi-Limpet Controller",
    # ── Refinery ──────────────────────────────────────────────────────────────
    "refinery":                     "Refinery",
    # ── Guardian technology ───────────────────────────────────────────────────
    "guardianpowerplant":           "Guardian Hybrid Power Plant",
    "guardian_powerplant":          "Guardian Hybrid Power Plant",
    "guardianpowerdistributor":     "Guardian Hybrid Power Distributor",
    "guardian_powerdistributor":    "Guardian Hybrid Power Distributor",
    "guardianfsdbooster":           "Guardian FSD Booster",
    "guardian_fsdbooster":          "Guardian FSD Booster",
    "guardian_modulereinforcement": "Guardian Module Reinforcement",
    # ── Mining equipment ──────────────────────────────────────────────────────
    "miningequipment":              "Abrasion Blaster",
    "seismiccharge":                "Seismic Charge Launcher",
    "subsurfacedisplacementmissile":"Sub-Surface Displacement Missile",
    # ── Additional internals ──────────────────────────────────────────────────
    "collectorlimpetcontroller":    "Collector Limpet Controller",
    "prospectorlimpetcontroller":   "Prospector Limpet Controller",
    "minelauncher_davs":            "AX Mine Launcher",
}


def normalise_module_name(internal: str) -> str:
    """Convert an internal module name to a human-readable display string.

    Examples
    --------
    int_engine_size7_class5           → 7A Thrusters
    int_shieldgenerator_size8_class5  → 8A Shield Generator
    hpt_pulselaser_turret_large       → Large Pulse Laser (Turret)
    int_dockingcomputer_advanced      → Advanced Docking Computer
    """
    if not internal:
        return "—"
    raw = internal.lower().strip()
    _is_hardpoint = raw.startswith("hpt_")

    # ── Armour detection ──────────────────────────────────────────────────────
    # Internal: {shiptype}_armour_grade{n}  (no int_ prefix)
    armour_m = _re.match(r"^(.+)_armour_(grade\d+|mirrored|reactive)$", raw)
    if armour_m:
        grade = armour_m.group(2)
        return ARMOUR_GRADES.get(grade, grade.replace("_", " ").title())

    # ── Strip module class prefix ─────────────────────────────────────────────
    # int_ / hpt_ / ext_ prefix
    body = _re.sub(r"^(?:int|hpt|ext)_", "", raw)

    # Strip _size{N}_class{N} suffix variants
    body = _re.sub(r"_size\d+_class\d+.*$", "", body)
    body = _re.sub(r"_class\d+.*$",          "", body)

    # ── Hardpoint: extract size, mount, base type ─────────────────────────────
    if _is_hardpoint:
        # Pattern: {type}_{mount}_{size}[_{variant}]
        # e.g. hpt_beamlaser_fixed_medium → "Medium Beam Laser (Fixed)"
        hp_m = _re.match(r"^(.+?)_(fixed|gimbal|turret|basic)_(tiny|small|smallfree|medium|large|huge)"
                         r"(?:_(.*?))?$", body)
        if hp_m:
            base_key = hp_m.group(1)
            mount    = hp_m.group(2)
            size_key = hp_m.group(3)
            variant  = hp_m.group(4) or ""
            lookup_key = f"{base_key}_{variant}" if variant else base_key
            type_name  = MODULE_TYPES.get(lookup_key) or MODULE_TYPES.get(base_key)
            size_str   = MODULE_SIZE_MAP.get(size_key, size_key.title())
            mount_str  = MODULE_MOUNT_MAP.get(mount, mount.title())
            if type_name:
                if mount == "basic":
                    return f"{size_str} {type_name}"
                return f"{size_str} {type_name} ({mount_str})"
        # Fallback for hardpoints
        type_name = MODULE_TYPES.get(body)
        if type_name:
            return type_name
        return body.replace("_", " ").title()

    # ── Standard internals ────────────────────────────────────────────────────
    # Try full body key first, then progressively shorter keys
    if body in MODULE_TYPES:
        type_name = MODULE_TYPES[body]
    else:
        # e.g. int_engine_size7_class5_fast → try "engine_fast" then "engine"
        parts     = body.split("_")
        type_name = None
        for n in range(len(parts), 0, -1):
            candidate = "_".join(parts[:n])
            if candidate in MODULE_TYPES:
                type_name = MODULE_TYPES[candidate]
                break

    if not type_name:
        return body.replace("_", " ").title()

    # Extract size + class for annotation (e.g. "7A Thrusters")
    size_m  = _re.search(r"_size(\d+)", raw)
    class_m = _re.search(r"_class(\d+)", raw)
    if size_m and class_m:
        size_digit  = size_m.group(1)
        class_digit = class_m.group(1)
        rating      = MODULE_CLASS_MAP.get(class_digit, class_digit)
        return f"{size_digit}{rating} {type_name}"

    return type_name

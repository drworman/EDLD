"""
data/ships.py — Elite Dangerous ship and fighter reference data.

Contains:
  SHIP_NAME_MAP          Internal ship type → canonical display name
  FIGHTER_TYPE_NAMES     SLF type internal key → short display name
  FIGHTER_LOADOUT_NAMES  (type, loadout) tuple → full display name
  normalise_ship_name    Resolve any journal ship string to display name
  resolve_fighter_name   Resolve fighter type + loadout to display name

Sources: Inara ship database, EDMC ship_name_map, in-game Shipyard.json,
         Frontier journal documentation.  Validated against EDMC as of 2026.
"""
from __future__ import annotations
import re as _re

# ── SLF type names ────────────────────────────────────────────────────────────

FIGHTER_TYPE_NAMES: dict[str, str] = {
    "independent_fighter":   "Taipan",        # Faulcon DeLacy — Independent/Alliance
    "empire_fighter":        "GU-97",          # Gutamaya — Imperial
    "federation_fighter":    "F63 Condor",     # Core Dynamics — Federal
    "gdn_hybrid_fighter_v1": "XG7 Trident",   # Guardian hybrid
    "gdn_hybrid_fighter_v2": "XG8 Javelin",   # Guardian hybrid
    "gdn_hybrid_fighter_v3": "XG9 Lance",     # Guardian hybrid
}

# ── SLF loadout names ─────────────────────────────────────────────────────────

FIGHTER_LOADOUT_NAMES: dict[tuple, str] = {
    # ── Base / stock ──────────────────────────────────────────────────────────
    ("independent_fighter",   "zero"):  "Taipan",
    ("federation_fighter",    "zero"):  "F63 Condor",
    ("empire_fighter",        "zero"):  "GU-97",
    ("gdn_hybrid_fighter_v1", "zero"):  "XG7 Trident",
    ("gdn_hybrid_fighter_v2", "zero"):  "XG8 Javelin",
    ("gdn_hybrid_fighter_v3", "zero"):  "XG9 Lance",

    # ── GU-97  (empire_fighter — Gutamaya, Imperial) ──────────────────────────
    ("empire_fighter", "one"):       "GU-97 (Gelid F)",
    ("empire_fighter", "two"):       "GU-97 (Rogue F)",
    ("empire_fighter", "three"):     "GU-97 (Aegis F)",
    ("empire_fighter", "four"):      "GU-97 (Gelid G)",
    ("empire_fighter", "five"):      "GU-97 (Rogue G)",
    ("empire_fighter", "one_g1"):    "GU-97 (Gelid F G1)",
    ("empire_fighter", "one_g2"):    "GU-97 (Gelid F G2)",
    ("empire_fighter", "one_g3"):    "GU-97 (Gelid F G3)",
    ("empire_fighter", "two_g1"):    "GU-97 (Rogue F G1)",
    ("empire_fighter", "two_g2"):    "GU-97 (Rogue F G2)",
    ("empire_fighter", "two_g3"):    "GU-97 (Rogue F G3)",
    ("empire_fighter", "three_g1"):  "GU-97 (Aegis F G1)",
    ("empire_fighter", "three_g2"):  "GU-97 (Aegis F G2)",
    ("empire_fighter", "three_g3"):  "GU-97 (Aegis F G3)",
    ("empire_fighter", "four_g1"):   "GU-97 (Gelid G G1)",
    ("empire_fighter", "four_g2"):   "GU-97 (Gelid G G2)",
    ("empire_fighter", "four_g3"):   "GU-97 (Gelid G G3)",
    ("empire_fighter", "five_g1"):   "GU-97 (Rogue G G1)",
    ("empire_fighter", "five_g2"):   "GU-97 (Rogue G G2)",
    ("empire_fighter", "five_g3"):   "GU-97 (Rogue G G3)",
    ("empire_fighter", "six"):       "GU-97 (Aegis F)",
    ("empire_fighter", "six_g1"):    "GU-97 (Aegis F G1)",
    ("empire_fighter", "six_g2"):    "GU-97 (Aegis F G2)",
    ("empire_fighter", "six_g3"):    "GU-97 (Aegis F G3)",

    # ── F63 Condor  (federation_fighter — Core Dynamics, Federal) ────────────
    ("federation_fighter", "one"):      "F63 Condor (Gelid F)",
    ("federation_fighter", "two"):      "F63 Condor (Rogue F)",
    ("federation_fighter", "three"):    "F63 Condor (Aegis F)",
    ("federation_fighter", "four"):     "F63 Condor (Gelid G)",
    ("federation_fighter", "five"):     "F63 Condor (Rogue G)",
    ("federation_fighter", "df"):       "F63 Condor (Rogue F)",
    ("federation_fighter", "at"):       "F63 Condor (Aegis F)",
    ("federation_fighter", "one_g1"):   "F63 Condor (Gelid F G1)",
    ("federation_fighter", "one_g2"):   "F63 Condor (Gelid F G2)",
    ("federation_fighter", "one_g3"):   "F63 Condor (Gelid F G3)",
    ("federation_fighter", "two_g1"):   "F63 Condor (Rogue F G1)",
    ("federation_fighter", "two_g2"):   "F63 Condor (Rogue F G2)",
    ("federation_fighter", "two_g3"):   "F63 Condor (Rogue F G3)",
    ("federation_fighter", "three_g1"): "F63 Condor (Aegis F G1)",
    ("federation_fighter", "three_g2"): "F63 Condor (Aegis F G2)",
    ("federation_fighter", "three_g3"): "F63 Condor (Aegis F G3)",
    ("federation_fighter", "four_g1"):  "F63 Condor (Gelid G G1)",
    ("federation_fighter", "four_g2"):  "F63 Condor (Gelid G G2)",
    ("federation_fighter", "four_g3"):  "F63 Condor (Gelid G G3)",
    ("federation_fighter", "five_g1"):  "F63 Condor (Rogue G G1)",
    ("federation_fighter", "five_g2"):  "F63 Condor (Rogue G G2)",
    ("federation_fighter", "five_g3"):  "F63 Condor (Rogue G G3)",
    ("federation_fighter", "six"):      "F63 Condor (Aegis F)",
    ("federation_fighter", "six_g1"):   "F63 Condor (Aegis F G1)",
    ("federation_fighter", "six_g2"):   "F63 Condor (Aegis F G2)",
    ("federation_fighter", "six_g3"):   "F63 Condor (Aegis F G3)",

    # ── Taipan  (independent_fighter — Faulcon DeLacy, Independent/Alliance) ─
    ("independent_fighter", "one"):      "Taipan (Gelid F)",
    ("independent_fighter", "two"):      "Taipan (Rogue F)",
    ("independent_fighter", "three"):    "Taipan (Aegis F)",
    ("independent_fighter", "four"):     "Taipan (Gelid G)",
    ("independent_fighter", "five"):     "Taipan (Rogue G)",
    ("independent_fighter", "at"):       "Taipan (AX1 F)",
    ("independent_fighter", "df"):       "Taipan (Rogue F)",
    ("independent_fighter", "one_g1"):   "Taipan (Gelid F G1)",
    ("independent_fighter", "one_g2"):   "Taipan (Gelid F G2)",
    ("independent_fighter", "one_g3"):   "Taipan (Gelid F G3)",
    ("independent_fighter", "two_g1"):   "Taipan (Rogue F G1)",
    ("independent_fighter", "two_g2"):   "Taipan (Rogue F G2)",
    ("independent_fighter", "two_g3"):   "Taipan (Rogue F G3)",
    ("independent_fighter", "three_g1"): "Taipan (Aegis F G1)",
    ("independent_fighter", "three_g2"): "Taipan (Aegis F G2)",
    ("independent_fighter", "three_g3"): "Taipan (Aegis F G3)",
    ("independent_fighter", "four_g1"):  "Taipan (Gelid G G1)",
    ("independent_fighter", "four_g2"):  "Taipan (Gelid G G2)",
    ("independent_fighter", "four_g3"):  "Taipan (Gelid G G3)",
    ("independent_fighter", "five_g1"):  "Taipan (Rogue G G1)",
    ("independent_fighter", "five_g2"):  "Taipan (Rogue G G2)",
    ("independent_fighter", "five_g3"):  "Taipan (Rogue G G3)",
    ("independent_fighter", "six"):      "Taipan (Aegis F)",
    ("independent_fighter", "six_g1"):   "Taipan (Aegis F G1)",
    ("independent_fighter", "six_g2"):   "Taipan (Aegis F G2)",
    ("independent_fighter", "six_g3"):   "Taipan (Aegis F G3)",

    # ── Guardian hybrid SLFs (single loadout each) ────────────────────────────
    ("gdn_hybrid_fighter_v1", "one"):    "XG7 Trident",
    ("gdn_hybrid_fighter_v2", "one"):    "XG8 Javelin",
    ("gdn_hybrid_fighter_v3", "one"):    "XG9 Lance",
}

# ── Ship name map ─────────────────────────────────────────────────────────────
# Keys are ALWAYS lowercased.  Values are canonical display strings from
# Inara (https://inara.cz/elite/ships/) validated against EDMC ship_name_map.
# Every plausible journal emission variant has its own entry so we never fall
# back to .title() for a known ship.
#
# Corrections vs previous inline _SHIP_NAMES:
#   • independent_fighter: "Taipan Fighter" (was incorrectly "F63 Condor")
#   • federation_fighter:  "F63 Condor"     (was incorrectly "F/A-26 Strike")
#   • Added: explorer_nx → Caspian Explorer (EDMC)
#   • Added: clipper → Panther Clipper (base variant, EDMC)
#   • Added: scout → Taipan Fighter (EDMC)

SHIP_NAME_MAP: dict[str, str] = {
    # ── Faulcon DeLacy ────────────────────────────────────────────────────────
    "sidewinder":               "Sidewinder Mk I",
    "sidewindermki":            "Sidewinder Mk I",
    "sidewinder mk i":          "Sidewinder Mk I",
    "sidewindermkii":           "Sidewinder Mk II",
    "sidewinder mk ii":         "Sidewinder Mk II",
    "eagle":                    "Eagle Mk II",
    "eaglemkii":                "Eagle Mk II",
    "eagle mk ii":              "Eagle Mk II",
    "cobramkiii":               "Cobra Mk III",
    "cobra mkiii":              "Cobra Mk III",
    "cobra mk iii":             "Cobra Mk III",
    "cobra mk. iii":            "Cobra Mk III",
    "cobramkiv":                "Cobra Mk IV",
    "cobra mkiv":               "Cobra Mk IV",
    "cobra mk iv":              "Cobra Mk IV",
    "cobra mk. iv":             "Cobra Mk IV",
    "cobramkv":                 "Cobra Mk V",
    "cobra mkv":                "Cobra Mk V",
    "cobra mk v":               "Cobra Mk V",
    "cobra mk. v":              "Cobra Mk V",
    "python":                   "Python",
    "pythonmkii":               "Python Mk II",
    "python mkii":              "Python Mk II",
    "python mk ii":             "Python Mk II",
    "python mk. ii":            "Python Mk II",
    "python_nx":                "Python Mk II",
    "anaconda":                 "Anaconda",
    "mamba":                    "Mamba",
    "combat_multirole":         "Mamba",
    # ── Lakon Spaceways ───────────────────────────────────────────────────────
    "adder":                    "Adder",
    "asp":                      "Asp Explorer",
    "asp explorer":             "Asp Explorer",
    "aspscout":                 "Asp Scout",
    "asp_sa":                   "Asp Scout",
    "asp scout":                "Asp Scout",
    "hauler":                   "Hauler",
    "diamondbackscout":         "Diamondback Scout",
    "diamondback scout":        "Diamondback Scout",
    "diamondbackxl":            "Diamondback Explorer",
    "diamondback explorer":     "Diamondback Explorer",
    "type6":                    "Type-6 Transporter",
    "type6transporter":         "Type-6 Transporter",
    "type-6 transporter":       "Type-6 Transporter",
    "type7":                    "Type-7 Transporter",
    "type7transporter":         "Type-7 Transporter",
    "type-7 transporter":       "Type-7 Transporter",
    "type8":                    "Type-8 Transporter",
    "type8transporter":         "Type-8 Transporter",
    "type-8 transporter":       "Type-8 Transporter",
    "type9":                    "Type-9 Heavy",
    "type9heavy":               "Type-9 Heavy",
    "type-9 heavy":             "Type-9 Heavy",
    "type10":                   "Type-10 Defender",
    "type10defender":           "Type-10 Defender",
    "type-10 defender":         "Type-10 Defender",
    "type9_military":           "Type-10 Defender",
    "type_9_military":          "Type-10 Defender",
    "lakonminer":               "Type-11 Prospector",
    "type11":                   "Type-11 Prospector",
    "type11prospector":         "Type-11 Prospector",
    "type-11 prospector":       "Type-11 Prospector",
    "krait_mkii":               "Krait Mk II",
    "kraitmkii":                "Krait Mk II",
    "krait mkii":               "Krait Mk II",
    "krait mk ii":              "Krait Mk II",
    "krait mk. ii":             "Krait Mk II",
    "krait_light":              "Krait Phantom",
    "krait light":              "Krait Phantom",
    "krait phantom":            "Krait Phantom",
    "mandalay":                 "Mandalay",
    "manowarinterdictor":       "Mandalay",
    # ── Caspian Explorer (Lakon, 2025) ────────────────────────────────────────
    "caspian":                  "Caspian Explorer",
    "caspianexplorer":          "Caspian Explorer",
    "caspian explorer":         "Caspian Explorer",
    "explorer_nx":              "Caspian Explorer",   # confirmed EDMC + journal
    # ── Saud Kruger ───────────────────────────────────────────────────────────
    "belugaliner":              "Beluga Liner",
    "beluga liner":             "Beluga Liner",
    "beluga":                   "Beluga Liner",
    "dolphin":                  "Dolphin",
    "orca":                     "Orca",
    # ── Core Dynamics ─────────────────────────────────────────────────────────
    "viper":                    "Viper Mk III",
    "vipermkiii":               "Viper Mk III",
    "viper mk iii":             "Viper Mk III",
    "viper mk. iii":            "Viper Mk III",
    "vipermkiv":                "Viper Mk IV",
    "viper mk iv":              "Viper Mk IV",
    "viper mk. iv":             "Viper Mk IV",
    "vulture":                  "Vulture",
    "federation_dropship":      "Federal Dropship",
    "federaldropship":          "Federal Dropship",
    "federal dropship":         "Federal Dropship",
    "federation_dropship_mkii": "Federal Assault Ship",
    "federalassaultship":       "Federal Assault Ship",
    "federal assault ship":     "Federal Assault Ship",
    "federation_gunship":       "Federal Gunship",
    "federalgunship":           "Federal Gunship",
    "federal gunship":          "Federal Gunship",
    "federation_corvette":      "Federal Corvette",
    "federalcorvette":          "Federal Corvette",
    "federal corvette":         "Federal Corvette",
    # ── Kestrel Mk II (Core Dynamics, 2026) ──────────────────────────────────
    "smallcombat01_nx":         "Kestrel Mk II",
    "smallnx01":                "Kestrel Mk II",
    "small_nx01":               "Kestrel Mk II",
    "smallcombat01nx":          "Kestrel Mk II",
    "kestrel":                  "Kestrel Mk II",
    "kestrel_mkii":             "Kestrel Mk II",
    "kestrelmkii":              "Kestrel Mk II",
    "kestrel mkii":             "Kestrel Mk II",
    "kestrel mk ii":            "Kestrel Mk II",
    "kestrel mk. ii":           "Kestrel Mk II",
    # ── Gutamaya ─────────────────────────────────────────────────────────────
    "empire_eagle":             "Imperial Eagle",
    "imperialeagle":            "Imperial Eagle",
    "imperial eagle":           "Imperial Eagle",
    "empire_courier":           "Imperial Courier",
    "imperialcourier":          "Imperial Courier",
    "imperial courier":         "Imperial Courier",
    "empire_trader":            "Imperial Clipper",
    "imperialclipper":          "Imperial Clipper",
    "imperial clipper":         "Imperial Clipper",
    "empire_fighter":           "Imperial Fighter",
    "imperial_fighter":         "Imperial Fighter",
    "imperial fighter":         "Imperial Fighter",
    "cutter":                   "Imperial Cutter",
    "imperialcutter":           "Imperial Cutter",
    "imperial cutter":          "Imperial Cutter",
    # ── Corsair (Gutamaya, 2025) — NOT "Imperial Corsair" ────────────────────
    "empire_corsair":           "Corsair",
    "imperialcorsair":          "Corsair",
    "imperial corsair":         "Corsair",
    "corsair":                  "Corsair",
    # ── Alliance ──────────────────────────────────────────────────────────────
    "typex":                    "Alliance Chieftain",
    "alliancechieftain":        "Alliance Chieftain",
    "alliance chieftain":       "Alliance Chieftain",
    "typex_2":                  "Alliance Crusader",
    "alliancecrusader":         "Alliance Crusader",
    "alliance crusader":        "Alliance Crusader",
    "typex_3":                  "Alliance Challenger",
    "alliancechallenger":       "Alliance Challenger",
    "alliance challenger":      "Alliance Challenger",
    # ── Zorgon Peterson ───────────────────────────────────────────────────────
    "ferdelance":               "Fer-de-Lance",
    "fer-de-lance":             "Fer-de-Lance",
    "fer de lance":             "Fer-de-Lance",
    "keelback":                 "Keelback",
    "independant_trader":       "Keelback",
    # ── Panther Clipper variants (Zorgon Peterson) ───────────────────────────
    "clipper":                  "Panther Clipper",         # base variant (EDMC)
    "pantherclipper":           "Panther Clipper",
    "panther clipper":          "Panther Clipper",
    "panthermkii":              "Panther Clipper Mk II",
    "pantherclippermkii":       "Panther Clipper Mk II",
    "panther_clipper_mkii":     "Panther Clipper Mk II",
    "panther clipper mk ii":    "Panther Clipper Mk II",
    "panther clipper mkii":     "Panther Clipper Mk II",
    "panther clipper mk. ii":   "Panther Clipper Mk II",
    # ── SLF / fighters / misc ─────────────────────────────────────────────────
    # These entries cover cases where the SLF type string appears as a ship
    # type in journal context.  The canonical display names are per FIGHTER_TYPE_NAMES.
    "independent_fighter":      "Taipan Fighter",   # Faulcon DeLacy — Independent/Alliance
    "federation_fighter":       "F63 Condor",       # Core Dynamics — Federal
    "scout":                    "Taipan Fighter",   # EDMC alias
    "gdn_hybrid_fighter_v1":    "XG7 Trident",
    "gdn_hybrid_fighter_v2":    "XG8 Javelin",
    "gdn_hybrid_fighter_v3":    "XG9 Lance",
    "testbuggy":                "SRV",
    "scarab":                   "SRV",
}

# Matches Roman numeral tokens after "Mk " that were mangled by .title()
_MK_ROMAN_RE = _re.compile(r'\bMk\s+([IVXivx][IVXivx]*)\b')


def normalise_ship_name(raw: str | None) -> str | None:
    """Return the correctly-capitalised display name for a ship type string.

    Accepts both internal journal identifiers (e.g. ``"type8"``, ``"krait_mkii"``)
    and pre-localised strings the game sometimes sends (e.g. ``"Cobra Mk IV"``).

    Falls back to a title-cased string for completely unknown ships, with
    Roman numerals after "Mk" kept properly uppercase.

    Returns ``None`` if *raw* is ``None`` or empty.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    if key in SHIP_NAME_MAP:
        return SHIP_NAME_MAP[key]
    candidate = raw.replace("_", " ").strip().title()
    candidate = _MK_ROMAN_RE.sub(lambda m: "Mk " + m.group(1).upper(), candidate)
    return candidate


def resolve_fighter_name(fighter_type: str, loadout: str) -> str:
    """Return display name for a fighter given type + loadout key.

    Handles engineered grade variants (e.g. "df_g1") gracefully.
    Falls back to stripping grade suffix, then type name, then raw string.
    """
    ft = (fighter_type or "").lower().strip()
    lo = (loadout or "").lower().strip()
    key = (ft, lo)
    if key in FIGHTER_LOADOUT_NAMES:
        return FIGHTER_LOADOUT_NAMES[key]
    m = _re.match(r"^(.+)_(g\d+)$", lo, _re.IGNORECASE)
    if m:
        base_lo = m.group(1)
        grade   = m.group(2).upper()
        base_key = (ft, base_lo)
        if base_key in FIGHTER_LOADOUT_NAMES:
            return f"{FIGHTER_LOADOUT_NAMES[base_key]} {grade}"
    if ft in FIGHTER_TYPE_NAMES:
        return FIGHTER_TYPE_NAMES[ft]
    return ft.replace("_", " ").title() if ft else "SLF"

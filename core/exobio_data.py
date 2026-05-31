"""
core/exobio_data.py — Organic (exobiology) value data and helpers.

The verified species value table and genus clonal distances, shared by the
session exobiology tracker and the Exobiology window so both agree.

Value model (Odyssey):
  base value per species (table below)
  first logged (Codex first entry):  base × 5
  first footfall on the body:         + base × 4
"""

from __future__ import annotations

# ── Species value table — Codex key -> (display name, base credit value) ──────
SPECIES_VALUES: dict[str, tuple[str, int]] = {
    '$Codex_Ent_TubeABCD_02_Name;': ('Albidum Sinuous Tubers', 1514500),
    '$Codex_Ent_Aleoids_01_Name;': ('Aleoida Arcus', 7252500),
    '$Codex_Ent_Aleoids_02_Name;': ('Aleoida Coronamus', 6284600),
    '$Codex_Ent_Aleoids_05_Name;': ('Aleoida Gravis', 12934900),
    '$Codex_Ent_Aleoids_04_Name;': ('Aleoida Laminiae', 3385200),
    '$Codex_Ent_Aleoids_03_Name;': ('Aleoida Spica', 3385200),
    '$Codex_Ent_Vents_Name;': ('Amphora Plant', 1628800),
    '$Codex_Ent_SeedEFGH_01_Name;': ('Aureum Brain Tree', 1593700),
    '$Codex_Ent_Bacterial_04_Name;': ('Bacterium Acies', 1000000),
    '$Codex_Ent_Bacterial_06_Name;': ('Bacterium Alcyoneum', 1658500),
    '$Codex_Ent_Bacterial_01_Name;': ('Bacterium Aurasus', 1000000),
    '$Codex_Ent_Bacterial_10_Name;': ('Bacterium Bullaris', 1152500),
    '$Codex_Ent_Bacterial_12_Name;': ('Bacterium Cerbrus', 1689800),
    '$Codex_Ent_Bacterial_08_Name;': ('Bacterium Informem', 8418000),
    '$Codex_Ent_Bacterial_02_Name;': ('Bacterium Nebulus', 5289900),
    '$Codex_Ent_Bacterial_11_Name;': ('Bacterium Omentum', 4638900),
    '$Codex_Ent_Bacterial_03_Name;': ('Bacterium Scopulum', 4934500),
    '$Codex_Ent_Bacterial_07_Name;': ('Bacterium Tela', 1949000),
    '$Codex_Ent_Bacterial_13_Name;': ('Bacterium Verrata', 3897000),
    '$Codex_Ent_Bacterial_05_Name;': ('Bacterium Vesicula', 1000000),
    '$Codex_Ent_Bacterial_09_Name;': ('Bacterium Volu', 7774700),
    '$Codex_Ent_Cone_Name;': ('Bark Mound', 1471900),
    '$Codex_Ent_SphereEFGH_Name;': ('Blatteum Bioluminescent Anemone', 1499900),
    '$Codex_Ent_TubeEFGH_Name;': ('Blatteum Sinuous Tubers', 1514500),
    '$Codex_Ent_Cactoid_01_Name;': ('Cactoida Cortexum', 3667600),
    '$Codex_Ent_Cactoid_02_Name;': ('Cactoida Lapis', 2483600),
    '$Codex_Ent_Cactoid_05_Name;': ('Cactoida Peperatis', 2483600),
    '$Codex_Ent_Cactoid_04_Name;': ('Cactoida Pullulanta', 3667600),
    '$Codex_Ent_Cactoid_03_Name;': ('Cactoida Vermis', 16202800),
    '$Codex_Ent_TubeABCD_03_Name;': ('Caeruleum Sinuous Tubers', 1514500),
    '$Codex_Ent_Clypeus_01_Name;': ('Clypeus Lacrimam', 8418000),
    '$Codex_Ent_Clypeus_02_Name;': ('Clypeus Margaritus', 11873200),
    '$Codex_Ent_Clypeus_03_Name;': ('Clypeus Speculumi', 16202800),
    '$Codex_Ent_Conchas_02_Name;': ('Concha Aureolas', 7774700),
    '$Codex_Ent_Conchas_04_Name;': ('Concha Biconcavis', 16777215),
    '$Codex_Ent_Conchas_03_Name;': ('Concha Labiata', 2352400),
    '$Codex_Ent_Conchas_01_Name;': ('Concha Renibus', 4572400),
    '$Codex_Ent_SphereABCD_01_Name;': ('Croceum Anemone', 1499900),
    '$Codex_Ent_Ground_Struct_Ice_Name;': ('Crystalline Shards', 1628800),
    '$Codex_Ent_Electricae_01_Name;': ('Electricae Pluma', 6284600),
    '$Codex_Ent_Electricae_02_Name;': ('Electricae Radialem', 6284600),
    '$Codex_Ent_Fonticulus_02_Name;': ('Fonticulua Campestris', 1000000),
    '$Codex_Ent_Fonticulus_06_Name;': ('Fonticulua Digitos', 1804100),
    '$Codex_Ent_Fonticulus_05_Name;': ('Fonticulua Fluctus', 20000000),
    '$Codex_Ent_Fonticulus_04_Name;': ('Fonticulua Lapida', 3111000),
    '$Codex_Ent_Fonticulus_01_Name;': ('Fonticulua Segmentatus', 19010800),
    '$Codex_Ent_Fonticulus_03_Name;': ('Fonticulua Upupam', 5727600),
    '$Codex_Ent_Shrubs_02_Name;': ('Frutexa Acus', 7774700),
    '$Codex_Ent_Shrubs_07_Name;': ('Frutexa Collum', 1639800),
    '$Codex_Ent_Shrubs_05_Name;': ('Frutexa Fera', 1632500),
    '$Codex_Ent_Shrubs_01_Name;': ('Frutexa Flabellum', 1808900),
    '$Codex_Ent_Shrubs_04_Name;': ('Frutexa Flammasis', 10326000),
    '$Codex_Ent_Shrubs_03_Name;': ('Frutexa Metallicum', 1632500),
    '$Codex_Ent_Shrubs_06_Name;': ('Frutexa Sponsae', 5988000),
    '$Codex_Ent_Fumerolas_04_Name;': ('Fumerola Aquatis', 6284600),
    '$Codex_Ent_Fumerolas_01_Name;': ('Fumerola Carbosis', 6284600),
    '$Codex_Ent_Fumerolas_02_Name;': ('Fumerola Extremus', 16202800),
    '$Codex_Ent_Fumerolas_03_Name;': ('Fumerola Nitris', 7500900),
    '$Codex_Ent_Fungoids_03_Name;': ('Fungoida Bullarum', 3703200),
    '$Codex_Ent_Fungoids_04_Name;': ('Fungoida Gelata', 3330300),
    '$Codex_Ent_Fungoids_01_Name;': ('Fungoida Setisis', 1670100),
    '$Codex_Ent_Fungoids_02_Name;': ('Fungoida Stabitis', 2680300),
    '$Codex_Ent_SeedABCD_01_Name;': ('Gypseeum Brain Tree', 1593700),
    '$Codex_Ent_SeedEFGH_03_Name;': ('Lindigoticum Brain Tree', 1593700),
    '$Codex_Ent_TubeEFGH_01_Name;': ('Lindigoticum Sinuous Tubers', 1514500),
    '$Codex_Ent_SeedEFGH_Name;': ('Lividum Brain Tree', 1593700),
    '$Codex_Ent_Sphere_Name;': ('Luteolum Anemone', 1499900),
    '$Codex_Ent_Osseus_05_Name;': ('Osseus Cornibus', 1483000),
    '$Codex_Ent_Osseus_02_Name;': ('Osseus Discus', 12934900),
    '$Codex_Ent_Osseus_01_Name;': ('Osseus Fractus', 4027800),
    '$Codex_Ent_Osseus_06_Name;': ('Osseus Pellebantus', 9739000),
    '$Codex_Ent_Osseus_04_Name;': ('Osseus Pumice', 3156300),
    '$Codex_Ent_Osseus_03_Name;': ('Osseus Spiralis', 2404700),
    '$Codex_Ent_SeedABCD_02_Name;': ('Ostrinum Brain Tree', 1593700),
    '$Codex_Ent_SphereEFGH_02_Name;': ('Prasinum Bioluminescent Anemone', 1499900),
    '$Codex_Ent_TubeABCD_01_Name;': ('Prasinum Sinuous Tubers', 1514500),
    '$Codex_Ent_SphereABCD_02_Name;': ('Puniceum Anemone', 1499900),
    '$Codex_Ent_SeedEFGH_02_Name;': ('Puniceum Brain Tree', 1593700),
    '$Codex_Ent_Ingensradices_Unicus_Name;': ('Radicoida Unicus', 119037),
    '$Codex_Ent_Recepta_03_Name;': ('Recepta Conditivus', 14313700),
    '$Codex_Ent_Recepta_02_Name;': ('Recepta Deltahedronix', 16202800),
    '$Codex_Ent_Recepta_01_Name;': ('Recepta Umbrux', 12934900),
    '$Codex_Ent_SphereABCD_03_Name;': ('Roseum Anemone', 1499900),
    '$Codex_Ent_SphereEFGH_03_Name;': ('Roseum Bioluminescent Anemone', 1499900),
    '$Codex_Ent_Seed_Name;': ('Roseum Brain Tree', 1593700),
    '$Codex_Ent_Tube_Name;': ('Roseum Sinuous Tubers', 1514500),
    '$Codex_Ent_SphereEFGH_01_Name;': ('Rubeum Bioluminescent Anemone', 1499900),
    '$Codex_Ent_Stratum_04_Name;': ('Stratum Araneamus', 2448900),
    '$Codex_Ent_Stratum_06_Name;': ('Stratum Cucumisis', 16202800),
    '$Codex_Ent_Stratum_01_Name;': ('Stratum Excutitus', 2448900),
    '$Codex_Ent_Stratum_08_Name;': ('Stratum Frigus', 2637500),
    '$Codex_Ent_Stratum_03_Name;': ('Stratum Laminamus', 2788300),
    '$Codex_Ent_Stratum_05_Name;': ('Stratum Limaxus', 1362000),
    '$Codex_Ent_Stratum_02_Name;': ('Stratum Paleas', 1362000),
    '$Codex_Ent_Stratum_07_Name;': ('Stratum Tectonicas', 19010800),
    '$Codex_Ent_Tubus_03_Name;': ('Tubus Cavas', 11873200),
    '$Codex_Ent_Tubus_05_Name;': ('Tubus Compagibus', 7774700),
    '$Codex_Ent_Tubus_01_Name;': ('Tubus Conifer', 2415500),
    '$Codex_Ent_Tubus_04_Name;': ('Tubus Rosarium', 2637500),
    '$Codex_Ent_Tubus_02_Name;': ('Tubus Sororibus', 5727600),
    '$Codex_Ent_Tussocks_08_Name;': ('Tussock Albata', 3252500),
    '$Codex_Ent_Tussocks_15_Name;': ('Tussock Capillum', 7025800),
    '$Codex_Ent_Tussocks_11_Name;': ('Tussock Caputus', 3472400),
    '$Codex_Ent_Tussocks_05_Name;': ('Tussock Catena', 1766600),
    '$Codex_Ent_Tussocks_04_Name;': ('Tussock Cultro', 1766600),
    '$Codex_Ent_Tussocks_10_Name;': ('Tussock Divisa', 1766600),
    '$Codex_Ent_Tussocks_03_Name;': ('Tussock Ignis', 1849000),
    '$Codex_Ent_Tussocks_01_Name;': ('Tussock Pennata', 5853800),
    '$Codex_Ent_Tussocks_06_Name;': ('Tussock Pennatis', 1000000),
    '$Codex_Ent_Tussocks_09_Name;': ('Tussock Propagito', 1000000),
    '$Codex_Ent_Tussocks_07_Name;': ('Tussock Serrati', 4447100),
    '$Codex_Ent_Tussocks_13_Name;': ('Tussock Stigmasis', 19010800),
    '$Codex_Ent_Tussocks_12_Name;': ('Tussock Triticum', 7774700),
    '$Codex_Ent_Tussocks_02_Name;': ('Tussock Ventusa', 3227700),
    '$Codex_Ent_Tussocks_14_Name;': ('Tussock Virgam', 14313700),
    '$Codex_Ent_TubeEFGH_02_Name;': ('Violaceum Sinuous Tubers', 1514500),
    '$Codex_Ent_SeedABCD_03_Name;': ('Viride Brain Tree', 1593700),
    '$Codex_Ent_TubeEFGH_03_Name;': ('Viride Sinuous Tubers', 1514500),
}

# ── Minimum clonal distances by genus (metres) ──
_GENUS_CLONAL_DISTANCE: dict[str, int] = {
    "aleoida":     150,
    "bacterium":   500,
    "cactoida":    300,
    "clypeus":     150,
    "concha":      150,
    "electricae":  1000,
    "fonticulua":  500,
    "frutexa":     150,
    "fumerola":    100,
    "fungoida":    300,
    "osseus":      800,
    "recepta":     150,
    "stratum":     500,
    "tubus":       800,
    "tussock":     200,
}
_DEFAULT_CLONAL_DISTANCE = 100


# ── Value / distance helpers ─────────────────────────────────────────────────

_FIRST_DISCOVERY_MULT = 5
_FOOTFALL_MULT        = 4


def clonal_distance(species_key: str) -> int:
    """Minimum clonal distance (m) between samples of a species."""
    key_lower = (species_key or "").lower()
    for genus, dist in _GENUS_CLONAL_DISTANCE.items():
        if genus in key_lower:
            return dist
    return _DEFAULT_CLONAL_DISTANCE


def species_value(codex_key: str, was_logged: bool, footfall_bonus: bool) -> int:
    """Credit value of one species sample given its logged / footfall state."""
    entry = SPECIES_VALUES.get(codex_key)
    if not entry:
        return 0
    base  = entry[1]
    value = base * _FIRST_DISCOVERY_MULT if not was_logged else base
    if footfall_bonus:
        value += base * _FOOTFALL_MULT
    return value


# ── Lookups by display name (the DB stores localised names) ──────────────────

VALUE_BY_NAME = {disp: base for (disp, base) in SPECIES_VALUES.values()}


def species_base_by_name(display_name: str) -> int:
    """Base value for a species given its localised display name, or 0."""
    return VALUE_BY_NAME.get(display_name or "", 0)


def _build_genus_ranges():
    out: dict[str, tuple[int, int, int]] = {}
    for disp, base in SPECIES_VALUES.values():
        genus = disp.split()[0] if disp else ""
        if not genus:
            continue
        lo, hi, n = out.get(genus, (base, base, 0))
        out[genus] = (min(lo, base), max(hi, base), n + 1)
    return out


# genus (leading display word) -> (min base, max base, species count)
GENUS_RANGES = _build_genus_ranges()


def genus_value_range(genus_display: str):
    """(min, max) base value across a genus's species, or None if unknown.

    Matches the leading-word genus the game reports (e.g. 'Bacterium'); special
    multi-word names that don't match return None so the UI shows no figure
    rather than a wrong one.
    """
    r = GENUS_RANGES.get((genus_display or "").split()[0] if genus_display else "")
    return (r[0], r[1]) if r else None

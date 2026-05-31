"""
core/exobio_rules.py — Species spawn-condition catalog (our schema).

Per Codex species: display name, genus, credit value (from the verified value
table), and one or more condition rules describing where it can occur.  A body
satisfies a rule when its atmosphere, body type, gravity, temperature and
pressure all fall within the rule, and the volcanism requirement is met.

Rule keys: atm (allowed gases) | no_atm (requires none) | body (planet classes) |
g_min/g_max (G) | t_min/t_max (K) | p_min/p_max (atm) | volc (none|any|required) |
gated (extra location constraints — region/nebula/star/etc. — that this engine
does not fully evaluate; such rules are reported as location-gated).
"""

from __future__ import annotations

# 115 species across the predictable genera.
SPECIES_RULES: dict[str, dict] = {
    '$Codex_Ent_Aleoids_01_Name;': {
        "name": 'Aleoida Arcus', "genus": 'Aleoida', "value": 7252500,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 175.0, 't_max': 180.0, 'p_min': 0.0161, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Aleoids_02_Name;': {
        "name": 'Aleoida Coronamus', "genus": 'Aleoida', "value": 6284600,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 180.0, 't_max': 190.0, 'p_min': 0.025, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Aleoids_03_Name;': {
        "name": 'Aleoida Spica', "genus": 'Aleoida', "value": 3385200,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 170.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Aleoids_04_Name;': {
        "name": 'Aleoida Laminiae', "genus": 'Aleoida', "value": 3385200,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 152.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Aleoids_05_Name;': {
        "name": 'Aleoida Gravis', "genus": 'Aleoida', "value": 12934900,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 190.0, 't_max': 197.0, 'p_min': 0.054, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Bacterial_01_Name;': {
        "name": 'Bacterium Aurasus', "genus": 'Bacterium', "value": 1000000,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.039, 'g_max': 0.608, 't_min': 145.0, 't_max': 400.0},
        ],
    },
    '$Codex_Ent_Bacterial_02_Name;': {
        "name": 'Bacterium Nebulus', "genus": 'Bacterium', "value": 5289900,
        "rules": [
            {'atm': ['helium'], 'body': ['icy body'], 'g_min': 0.4, 'g_max': 0.55, 't_min': 20.0, 't_max': 21.0, 'p_min': 0.067},
            {'atm': ['helium'], 'body': ['rocky ice body'], 'g_min': 0.4, 'g_max': 0.7, 't_min': 20.0, 't_max': 21.0, 'p_min': 0.067},
        ],
    },
    '$Codex_Ent_Bacterial_03_Name;': {
        "name": 'Bacterium Scopulum', "genus": 'Bacterium', "value": 4934500,
        "rules": [
            {'atm': ['argon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.15, 'g_max': 0.26, 't_min': 56.0, 't_max': 150.0, 'volc': 'required'},
            {'atm': ['helium'], 'body': ['icy body'], 'g_min': 0.48, 'g_max': 0.51, 't_min': 20.0, 't_max': 21.0, 'p_min': 0.075, 'volc': 'required'},
            {'atm': ['methane'], 'body': ['icy body'], 'g_min': 0.025, 'g_max': 0.047, 't_min': 84.0, 't_max': 110.0, 'p_min': 0.03, 'volc': 'required'},
            {'atm': ['neon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.025, 'g_max': 0.61, 't_min': 20.0, 't_max': 65.0, 'p_max': 0.008, 'volc': 'required'},
            {'atm': ['neon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.025, 'g_max': 0.61, 't_min': 20.0, 't_max': 65.0, 'p_min': 0.005, 'volc': 'required'},
            {'atm': ['nitrogen'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.2, 'g_max': 0.3, 't_min': 60.0, 't_max': 70.0, 'volc': 'required'},
            {'atm': ['oxygen'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.27, 'g_max': 0.4, 't_min': 150.0, 't_max': 220.0, 'p_min': 0.01, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Bacterial_04_Name;': {
        "name": 'Bacterium Acies', "genus": 'Bacterium', "value": 1000000,
        "rules": [
            {'atm': ['neon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.255, 'g_max': 0.61, 't_min': 20.0, 't_max': 61.0, 'p_max': 0.01},
        ],
    },
    '$Codex_Ent_Bacterial_05_Name;': {
        "name": 'Bacterium Vesicula', "genus": 'Bacterium', "value": 1000000,
        "rules": [
            {'atm': ['argon'], 'g_min': 0.027, 'g_max': 0.51, 't_min': 50.0, 't_max': 245.0},
        ],
    },
    '$Codex_Ent_Bacterial_06_Name;': {
        "name": 'Bacterium Alcyoneum', "genus": 'Bacterium', "value": 1658500,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.04, 'g_max': 0.376, 't_min': 152.0, 't_max': 177.0, 'p_max': 0.0135},
        ],
    },
    '$Codex_Ent_Bacterial_07_Name;': {
        "name": 'Bacterium Tela', "genus": 'Bacterium', "value": 1949000,
        "rules": [
            {'atm': ['argon'], 'body': ['high metal content body', 'icy body', 'rocky ice body'], 'g_min': 0.045, 'g_max': 0.45, 't_min': 50.0, 'volc': 'any'},
            {'atm': ['argon'], 'g_min': 0.24, 'g_max': 0.45, 't_min': 50.0, 't_max': 150.0, 'p_max': 0.05, 'volc': 'any'},
            {'atm': ['ammonia'], 'g_min': 0.025, 'g_max': 0.23, 't_min': 165.0, 't_max': 177.0, 'p_min': 0.0025, 'p_max': 0.02, 'volc': 'any'},
            {'atm': ['carbon dioxide'], 'g_min': 0.45, 'g_max': 0.61, 't_min': 300.0, 'p_min': 0.006, 'volc': 'none'},
            {'atm': ['carbon dioxide'], 'g_min': 0.025, 'g_max': 0.61, 't_min': 167.0, 'p_min': 0.006, 'volc': 'any'},
            {'atm': ['helium'], 'body': ['icy body'], 'g_min': 0.025, 'g_max': 0.61, 't_min': 20.0, 't_max': 21.0, 'p_min': 0.067, 'volc': 'any'},
            {'atm': ['methane'], 'body': ['high metal content body', 'icy body', 'rocky body'], 'g_min': 0.026, 'g_max': 0.126, 't_min': 80.0, 't_max': 109.0, 'p_min': 0.012, 'volc': 'any'},
            {'atm': ['neon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.27, 'g_max': 0.61, 't_min': 20.0, 't_max': 95.0, 'p_max': 0.008, 'volc': 'any'},
            {'atm': ['neon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.27, 'g_max': 0.61, 't_min': 20.0, 't_max': 95.0, 'p_min': 0.003, 'volc': 'any'},
            {'atm': ['nitrogen'], 'g_min': 0.21, 'g_max': 0.35, 't_min': 55.0, 't_max': 80.0, 'volc': 'any'},
            {'atm': ['oxygen'], 'g_min': 0.23, 'g_max': 0.5, 't_min': 150.0, 't_max': 240.0, 'p_min': 0.01, 'volc': 'any'},
            {'atm': ['sulphur dioxide'], 'g_min': 0.18, 'g_max': 0.61, 't_min': 148.0, 't_max': 550.0, 'volc': 'any'},
            {'atm': ['sulphur dioxide'], 'g_min': 0.18, 'g_max': 0.61, 't_min': 300.0, 't_max': 550.0, 'volc': 'none'},
            {'atm': ['sulphur dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.5, 'g_max': 0.55, 't_min': 500.0, 't_max': 650.0, 'volc': 'any'},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.063, 'volc': 'none'},
            {'atm': ['water'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.315, 'g_max': 0.44, 't_min': 190.0, 't_max': 330.0, 'p_min': 0.01, 'volc': 'any'},
        ],
    },
    '$Codex_Ent_Bacterial_08_Name;': {
        "name": 'Bacterium Informem', "genus": 'Bacterium', "value": 8418000,
        "rules": [
            {'atm': ['nitrogen'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.05, 'g_max': 0.6, 't_min': 42.5, 't_max': 151.0, 'volc': 'none'},
            {'atm': ['nitrogen'], 'body': ['icy body'], 'g_min': 0.17, 'g_max': 0.63, 't_min': 50.0, 't_max': 90.0},
        ],
    },
    '$Codex_Ent_Bacterial_09_Name;': {
        "name": 'Bacterium Volu', "genus": 'Bacterium', "value": 7774700,
        "rules": [
            {'atm': ['oxygen'], 'g_min': 0.239, 'g_max': 0.61, 't_min': 143.5, 't_max': 246.0, 'p_min': 0.013},
        ],
    },
    '$Codex_Ent_Bacterial_10_Name;': {
        "name": 'Bacterium Bullaris', "genus": 'Bacterium', "value": 1152500,
        "rules": [
            {'atm': ['methane'], 'g_min': 0.0245, 'g_max': 0.35, 't_min': 67.0, 't_max': 109.0},
            {'atm': ['methane'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.44, 'g_max': 0.6, 't_min': 74.0, 't_max': 141.0, 'p_min': 0.01, 'p_max': 0.05, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Bacterial_11_Name;': {
        "name": 'Bacterium Omentum', "genus": 'Bacterium', "value": 4638900,
        "rules": [
            {'atm': ['argon'], 'body': ['icy body'], 'g_min': 0.045, 'g_max': 0.45, 't_min': 50.0, 'volc': 'required'},
            {'atm': ['argon'], 'body': ['icy body'], 'g_min': 0.23, 'g_max': 0.45, 't_min': 80.0, 't_max': 90.0, 'p_min': 0.01, 'volc': 'required'},
            {'atm': ['helium'], 'body': ['icy body'], 'g_min': 0.4, 'g_max': 0.51, 't_min': 20.0, 't_max': 21.0, 'p_min': 0.065, 'volc': 'required'},
            {'atm': ['methane'], 'body': ['icy body'], 'g_min': 0.0265, 'g_max': 0.0455, 't_min': 84.0, 't_max': 108.0, 'p_min': 0.035, 'volc': 'required'},
            {'atm': ['neon'], 'body': ['icy body'], 'g_min': 0.31, 'g_max': 0.6, 't_min': 20.0, 't_max': 61.0, 'p_max': 0.0065, 'volc': 'required'},
            {'atm': ['neon'], 'body': ['icy body'], 'g_min': 0.27, 'g_max': 0.61, 't_min': 20.0, 't_max': 93.0, 'p_min': 0.0027, 'volc': 'required'},
            {'atm': ['nitrogen'], 'body': ['icy body'], 'g_min': 0.2, 'g_max': 0.26, 't_min': 60.0, 't_max': 80.0, 'volc': 'required'},
            {'atm': ['water'], 'body': ['icy body'], 'g_min': 0.38, 'g_max': 0.45, 't_min': 190.0, 't_max': 330.0, 'p_min': 0.07, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Bacterial_12_Name;': {
        "name": 'Bacterium Cerbrus', "genus": 'Bacterium', "value": 1689800,
        "rules": [
            {'atm': ['sulphur dioxide'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.042, 'g_max': 0.605, 't_min': 132.0, 't_max': 500.0},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.064, 'volc': 'none'},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.064, 'volc': 'required'},
            {'atm': ['water'], 'body': ['rocky ice body'], 'g_min': 0.4, 'g_max': 0.5, 't_min': 190.0, 't_max': 330.0, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Bacterial_13_Name;': {
        "name": 'Bacterium Verrata', "genus": 'Bacterium', "value": 3897000,
        "rules": [
            {'atm': ['ammonia'], 'body': ['icy body', 'rocky body', 'rocky ice body'], 'g_min': 0.03, 'g_max': 0.09, 't_min': 160.0, 't_max': 180.0, 'p_max': 0.0135, 'volc': 'required'},
            {'atm': ['argon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.165, 'g_max': 0.33, 't_min': 57.5, 't_max': 145.0, 'volc': 'required'},
            {'atm': ['argon'], 'body': ['icy body'], 'g_min': 0.04, 'g_max': 0.08, 't_min': 80.0, 't_max': 90.0, 'p_max': 0.01, 'volc': 'required'},
            {'atm': ['carbon dioxide'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.25, 'g_max': 0.32, 't_min': 167.0, 't_max': 240.0, 'volc': 'required'},
            {'atm': ['helium'], 'body': ['icy body'], 'g_min': 0.49, 'g_max': 0.53, 't_min': 20.0, 't_max': 21.0, 'p_min': 0.065, 'volc': 'required'},
            {'atm': ['neon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.29, 'g_max': 0.61, 't_min': 20.0, 't_max': 51.0, 'p_max': 0.075, 'volc': 'required'},
            {'atm': ['neon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.43, 'g_max': 0.61, 't_min': 20.0, 't_max': 65.0, 'p_min': 0.005, 'volc': 'required'},
            {'atm': ['nitrogen'], 'body': ['icy body'], 'g_min': 0.205, 'g_max': 0.241, 't_min': 60.0, 't_max': 80.0, 'volc': 'required'},
            {'atm': ['oxygen'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.24, 'g_max': 0.35, 't_min': 154.0, 't_max': 220.0, 'p_min': 0.01, 'volc': 'required'},
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.054, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Cactoid_01_Name;': {
        "name": 'Cactoida Cortexum', "genus": 'Cactoida', "value": 3667600,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 180.0, 't_max': 197.0, 'p_min': 0.025, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Cactoid_02_Name;': {
        "name": 'Cactoida Lapis', "genus": 'Cactoida', "value": 2483600,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 160.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Cactoid_03_Name;': {
        "name": 'Cactoida Vermis', "genus": 'Cactoida', "value": 16202800,
        "rules": [
            {'atm': ['sulphur dioxide'], 'body': ['rocky body'], 'g_min': 0.265, 'g_max': 0.276, 't_min': 160.0, 't_max': 210.0, 'p_max': 0.005, 'volc': 'none'},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 'volc': 'none'},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Cactoid_04_Name;': {
        "name": 'Cactoida Pullulanta', "genus": 'Cactoida', "value": 3667600,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 180.0, 't_max': 197.0, 'p_min': 0.025, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Cactoid_05_Name;': {
        "name": 'Cactoida Peperatis', "genus": 'Cactoida', "value": 2483600,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 160.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Clypeus_01_Name;': {
        "name": 'Clypeus Lacrimam', "genus": 'Clypeus', "value": 8418000,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 190.0, 'p_min': 0.054, 'volc': 'none'},
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 'volc': 'none'},
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Clypeus_02_Name;': {
        "name": 'Clypeus Margaritus', "genus": 'Clypeus', "value": 11873200,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 190.0, 't_max': 197.0, 'p_min': 0.054, 'volc': 'none'},
            {'atm': ['water'], 'body': ['high metal content body'], 'g_min': 0.04, 'g_max': 0.276, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Clypeus_03_Name;': {
        "name": 'Clypeus Speculumi', "genus": 'Clypeus', "value": 16202800,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 190.0, 't_max': 197.0, 'p_min': 0.055, 'volc': 'none', 'gated': ['distance']},
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 'volc': 'none', 'gated': ['distance']},
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 'volc': 'required', 'gated': ['distance']},
        ],
    },
    '$Codex_Ent_Conchas_01_Name;': {
        "name": 'Concha Renibus', "genus": 'Concha', "value": 4572400,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.045, 't_min': 176.0, 't_max': 177.0, 'volc': 'required'},
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 180.0, 'p_min': 0.025, 'volc': 'none'},
            {'atm': ['methane'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.15, 't_min': 78.0, 't_max': 100.0, 'p_min': 0.01, 'volc': 'required'},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.65, 'volc': 'none'},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.65, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Conchas_02_Name;': {
        "name": 'Concha Aureolas', "genus": 'Concha', "value": 7774700,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 152.0, 't_max': 177.0, 'p_max': 0.0135},
        ],
    },
    '$Codex_Ent_Conchas_03_Name;': {
        "name": 'Concha Labiata', "genus": 'Concha', "value": 2352400,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 150.0, 't_max': 200.0, 'p_min': 0.002, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Conchas_04_Name;': {
        "name": 'Concha Biconcavis', "genus": 'Concha', "value": 16777215,
        "rules": [
            {'atm': ['nitrogen'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.053, 'g_max': 0.275, 't_min': 42.0, 't_max': 52.0, 'p_max': 0.0047, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Electricae_01_Name;': {
        "name": 'Electricae Pluma', "genus": 'Electricae', "value": 6284600,
        "rules": [
            {'atm': ['argon'], 'body': ['icy body'], 'g_min': 0.025, 'g_max': 0.276, 't_min': 50.0, 't_max': 150.0, 'gated': ['parent_star']},
            {'atm': ['neon'], 'body': ['icy body'], 'g_min': 0.26, 'g_max': 0.276, 't_min': 20.0, 't_max': 70.0, 'p_max': 0.005, 'gated': ['parent_star']},
        ],
    },
    '$Codex_Ent_Electricae_02_Name;': {
        "name": 'Electricae Radialem', "genus": 'Electricae', "value": 6284600,
        "rules": [
            {'atm': ['argon'], 'body': ['icy body'], 'g_min': 0.025, 'g_max': 0.276, 't_min': 50.0, 't_max': 150.0, 'gated': ['nebula']},
            {'atm': ['neon'], 'body': ['icy body'], 'g_min': 0.026, 'g_max': 0.276, 't_min': 20.0, 't_max': 70.0, 'p_max': 0.005, 'gated': ['nebula']},
        ],
    },
    '$Codex_Ent_Fonticulus_01_Name;': {
        "name": 'Fonticulua Segmentatus', "genus": 'Fonticulua', "value": 19010800,
        "rules": [
            {'atm': ['neon'], 'body': ['icy body'], 'g_min': 0.25, 'g_max': 0.276, 't_min': 50.0, 't_max': 75.0, 'p_max': 0.006, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Fonticulus_02_Name;': {
        "name": 'Fonticulua Campestris', "genus": 'Fonticulua', "value": 1000000,
        "rules": [
            {'atm': ['argon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.027, 'g_max': 0.276, 't_min': 50.0, 't_max': 150.0},
        ],
    },
    '$Codex_Ent_Fonticulus_03_Name;': {
        "name": 'Fonticulua Upupam', "genus": 'Fonticulua', "value": 5727600,
        "rules": [
            {'atm': ['argon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.209, 'g_max': 0.276, 't_min': 61.0, 't_max': 125.0, 'p_min': 0.0175},
        ],
    },
    '$Codex_Ent_Fonticulus_04_Name;': {
        "name": 'Fonticulua Lapida', "genus": 'Fonticulua', "value": 3111000,
        "rules": [
            {'atm': ['nitrogen'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.19, 'g_max': 0.276, 't_min': 50.0, 't_max': 81.0},
        ],
    },
    '$Codex_Ent_Fonticulus_05_Name;': {
        "name": 'Fonticulua Fluctus', "genus": 'Fonticulua', "value": 20000000,
        "rules": [
            {'atm': ['oxygen'], 'body': ['icy body'], 'g_min': 0.235, 'g_max': 0.276, 't_min': 143.0, 't_max': 200.0, 'p_min': 0.012},
        ],
    },
    '$Codex_Ent_Fonticulus_06_Name;': {
        "name": 'Fonticulua Digitos', "genus": 'Fonticulua', "value": 1804100,
        "rules": [
            {'atm': ['methane'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.025, 'g_max': 0.07, 't_min': 83.0, 't_max': 109.0, 'p_min': 0.03},
        ],
    },
    '$Codex_Ent_Fumerolas_01_Name;': {
        "name": 'Fumerola Carbosis', "genus": 'Fumerola', "value": 6284600,
        "rules": [
            {'atm': ['argon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.168, 'g_max': 0.276, 't_min': 57.0, 't_max': 150.0, 'volc': 'required'},
            {'atm': ['methane'], 'body': ['icy body'], 'g_min': 0.025, 'g_max': 0.047, 't_min': 84.0, 't_max': 110.0, 'p_min': 0.03, 'volc': 'required'},
            {'atm': ['neon'], 'body': ['icy body'], 'g_min': 0.26, 'g_max': 0.276, 't_min': 40.0, 't_max': 60.0, 'volc': 'required'},
            {'atm': ['nitrogen'], 'body': ['icy body'], 'g_min': 0.2, 'g_max': 0.276, 't_min': 57.0, 't_max': 70.0, 'volc': 'required'},
            {'atm': ['oxygen'], 'body': ['icy body'], 'g_min': 0.26, 'g_max': 0.276, 't_min': 160.0, 't_max': 180.0, 'volc': 'required'},
            {'atm': ['sulphur dioxide'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.185, 'g_max': 0.276, 't_min': 149.0, 't_max': 272.0, 'volc': 'required'},
            {'atm': ['ammonia', 'argon', 'carbon dioxide'], 'body': ['icy body'], 'g_max': 0.276, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Fumerolas_02_Name;': {
        "name": 'Fumerola Extremus', "genus": 'Fumerola', "value": 16202800,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.04, 'g_max': 0.09, 't_min': 161.0, 't_max': 177.0, 'p_max': 0.0135, 'volc': 'required'},
            {'atm': ['argon'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.07, 'g_max': 0.276, 't_min': 50.0, 't_max': 121.0, 'volc': 'required'},
            {'atm': ['methane'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.025, 'g_max': 0.127, 't_min': 77.0, 't_max': 109.0, 'p_min': 0.01, 'volc': 'required'},
            {'atm': ['sulphur dioxide'], 'body': ['rocky body', 'rocky ice body'], 'g_min': 0.07, 'g_max': 0.276, 't_min': 54.0, 't_max': 210.0, 'volc': 'required'},
            {'atm': ['carbon dioxide'], 'body': ['high metal content body'], 'g_min': 0.05, 'g_max': 0.276, 't_min': 500.0, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Fumerolas_03_Name;': {
        "name": 'Fumerola Nitris', "genus": 'Fumerola', "value": 7500900,
        "rules": [
            {'atm': ['neon'], 'body': ['icy body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 30.0, 't_max': 129.0, 'volc': 'required'},
            {'atm': ['argon', 'neon'], 'body': ['icy body'], 'g_min': 0.044, 'g_max': 0.276, 't_min': 50.0, 't_max': 141.0, 'volc': 'required'},
            {'atm': ['methane'], 'body': ['icy body'], 'g_min': 0.025, 'g_max': 0.1, 't_min': 83.0, 't_max': 109.0, 'volc': 'required'},
            {'atm': ['nitrogen'], 'body': ['icy body'], 'g_min': 0.21, 'g_max': 0.276, 't_min': 60.0, 't_max': 81.0, 'volc': 'required'},
            {'atm': ['oxygen'], 'body': ['icy body'], 'g_max': 0.276, 't_min': 150.0, 'volc': 'required'},
            {'atm': ['sulphur dioxide'], 'body': ['icy body'], 'g_min': 0.21, 'g_max': 0.276, 't_min': 160.0, 't_max': 250.0, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Fumerolas_04_Name;': {
        "name": 'Fumerola Aquatis', "genus": 'Fumerola', "value": 6284600,
        "rules": [
            {'atm': ['ammonia'], 'body': ['icy body', 'rocky body', 'rocky ice body'], 'g_min': 0.028, 'g_max': 0.276, 't_min': 161.0, 't_max': 177.0, 'p_min': 0.002, 'p_max': 0.02, 'volc': 'required'},
            {'atm': ['argon'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.166, 'g_max': 0.276, 't_min': 57.0, 't_max': 150.0, 'volc': 'required'},
            {'atm': ['carbon dioxide'], 'body': ['icy body'], 'g_min': 0.25, 'g_max': 0.276, 't_min': 160.0, 't_max': 180.0, 'p_min': 0.01, 'p_max': 0.03, 'volc': 'required'},
            {'atm': ['methane'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 80.0, 't_max': 100.0, 'p_min': 0.01, 'volc': 'required'},
            {'atm': ['neon'], 'body': ['icy body'], 'g_min': 0.26, 'g_max': 0.276, 't_min': 20.0, 't_max': 60.0, 'volc': 'required'},
            {'atm': ['nitrogen'], 'body': ['icy body'], 'g_min': 0.195, 'g_max': 0.245, 't_min': 56.0, 't_max': 80.0, 'volc': 'required'},
            {'atm': ['oxygen'], 'body': ['icy body'], 'g_min': 0.23, 'g_max': 0.276, 't_min': 153.0, 't_max': 190.0, 'p_min': 0.01, 'volc': 'required'},
            {'atm': ['sulphur dioxide'], 'body': ['icy body', 'rocky body', 'rocky ice body'], 'g_min': 0.18, 'g_max': 0.276, 't_min': 150.0, 't_max': 270.0, 'volc': 'required'},
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.06, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Fungoids_01_Name;': {
        "name": 'Fungoida Setisis', "genus": 'Fungoida', "value": 1670100,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 152.0, 't_max': 177.0, 'p_max': 0.0135},
            {'atm': ['methane'], 'body': ['rocky ice body'], 'g_min': 0.033, 'g_max': 0.276, 't_min': 68.0, 't_max': 109.0, 'volc': 'none'},
            {'atm': ['methane'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.033, 'g_max': 0.276, 't_min': 67.0, 't_max': 109.0},
        ],
    },
    '$Codex_Ent_Fungoids_02_Name;': {
        "name": 'Fungoida Stabitis', "genus": 'Fungoida', "value": 2680300,
        "rules": [
            {'atm': ['ammonia'], 'body': ['rocky body', 'rocky ice body'], 'g_min': 0.04, 'g_max': 0.045, 't_min': 172.0, 't_max': 177.0, 'volc': 'required', 'gated': ['regions']},
            {'atm': ['argon'], 'body': ['rocky ice body'], 'g_min': 0.2, 'g_max': 0.23, 't_min': 60.0, 't_max': 90.0, 'volc': 'required', 'gated': ['regions']},
            {'atm': ['argon'], 'body': ['icy body'], 'g_min': 0.3, 'g_max': 0.5, 't_min': 60.0, 't_max': 90.0, 'gated': ['regions']},
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.0405, 'g_max': 0.27, 't_min': 180.0, 'p_min': 0.025, 'volc': 'none', 'gated': ['regions']},
            {'atm': ['methane'], 'body': ['rocky body'], 'g_min': 0.043, 'g_max': 0.126, 't_min': 78.5, 't_max': 109.0, 'p_min': 0.012, 'volc': 'required', 'gated': ['regions']},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.039, 'g_max': 0.064, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Fungoids_03_Name;': {
        "name": 'Fungoida Bullarum', "genus": 'Fungoida', "value": 3703200,
        "rules": [
            {'atm': ['argon'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.058, 'g_max': 0.276, 't_min': 50.0, 't_max': 129.0, 'volc': 'none'},
            {'atm': ['nitrogen'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.155, 'g_max': 0.276, 't_min': 50.0, 't_max': 70.0, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Fungoids_04_Name;': {
        "name": 'Fungoida Gelata', "genus": 'Fungoida', "value": 3330300,
        "rules": [
            {'atm': ['argon'], 'body': ['rocky body', 'rocky ice body'], 'g_min': 0.041, 'g_max': 0.276, 't_min': 160.0, 't_max': 180.0, 'p_max': 0.0135, 'volc': 'required', 'gated': ['regions']},
            {'atm': ['ammonia'], 'body': ['rocky body', 'rocky ice body'], 'g_min': 0.042, 'g_max': 0.071, 't_min': 160.0, 't_max': 180.0, 'p_max': 0.0135, 'volc': 'required', 'gated': ['regions']},
            {'atm': ['ammonia'], 'body': ['high metal content body'], 'g_min': 0.042, 'g_max': 0.071, 't_min': 160.0, 't_max': 180.0, 'p_max': 0.0135, 'volc': 'required', 'gated': ['regions']},
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.041, 'g_max': 0.276, 't_min': 180.0, 'p_min': 0.025, 'volc': 'none', 'gated': ['regions']},
            {'atm': ['methane'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.044, 'g_max': 0.125, 't_min': 80.0, 't_max': 110.0, 'p_min': 0.01, 'volc': 'required', 'gated': ['regions']},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.039, 'g_max': 0.063, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Ground_Struct_Ice_Name;': {
        "name": 'Crystalline Shards', "genus": 'Crystalline', "value": 1628800,
        "rules": [
            {'atm': ['argon', 'carbon dioxide', 'helium', 'methane', 'neon'], 'g_max': 2.0, 't_max': 273.0, 'gated': ['bodies', 'distance', 'regions', 'star']},
        ],
    },
    '$Codex_Ent_Osseus_01_Name;': {
        "name": 'Osseus Fractus', "genus": 'Osseus', "value": 4027800,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 180.0, 'p_min': 0.025, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Osseus_02_Name;': {
        "name": 'Osseus Discus', "genus": 'Osseus', "value": 12934900,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.04, 'g_max': 0.088, 't_min': 161.0, 't_max': 177.0, 'p_max': 0.0135, 'volc': 'any'},
            {'atm': ['argon'], 'body': ['rocky ice body'], 'g_min': 0.2, 'g_max': 0.276, 't_min': 65.0, 't_max': 120.0, 'volc': 'any'},
            {'atm': ['carbon dioxide'], 'body': ['high metal content body'], 'g_min': 0.026, 'g_max': 0.276, 't_min': 500.0, 'volc': 'any'},
            {'atm': ['methane'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.127, 't_min': 80.0, 't_max': 110.0, 'p_min': 0.012, 'volc': 'any'},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.055},
        ],
    },
    '$Codex_Ent_Osseus_03_Name;': {
        "name": 'Osseus Spiralis', "genus": 'Osseus', "value": 2404700,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 160.0, 't_max': 177.0, 'p_max': 0.0135},
        ],
    },
    '$Codex_Ent_Osseus_04_Name;': {
        "name": 'Osseus Pumice', "genus": 'Osseus', "value": 3156300,
        "rules": [
            {'atm': ['argon'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.059, 'g_max': 0.276, 't_min': 50.0, 't_max': 135.0, 'volc': 'none'},
            {'atm': ['argon'], 'body': ['rocky ice body'], 'g_min': 0.059, 'g_max': 0.276, 't_min': 50.0, 't_max': 135.0, 'volc': 'required'},
            {'atm': ['argon'], 'body': ['rocky ice body'], 'g_min': 0.035, 'g_max': 0.276, 't_min': 60.0, 't_max': 80.5, 'p_min': 0.03, 'volc': 'none'},
            {'atm': ['methane'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.033, 'g_max': 0.276, 't_min': 67.0, 't_max': 109.0},
            {'atm': ['nitrogen'], 'body': ['high metal content body', 'rocky body', 'rocky ice body'], 'g_min': 0.05, 'g_max': 0.276, 't_min': 42.0, 't_max': 70.1, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Osseus_05_Name;': {
        "name": 'Osseus Cornibus', "genus": 'Osseus', "value": 1483000,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.0405, 'g_max': 0.276, 't_min': 180.0, 'p_min': 0.025, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Osseus_06_Name;': {
        "name": 'Osseus Pellebantus', "genus": 'Osseus', "value": 9739000,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.0405, 'g_max': 0.276, 't_min': 191.0, 'p_min': 0.057, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Recepta_01_Name;': {
        "name": 'Recepta Umbrux', "genus": 'Recepta', "value": 12934900,
        "rules": [
            {'atm': ['carbon dioxide'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 151.0, 't_max': 200.0, 'gated': ['atmosphere_component']},
            {'atm': ['oxygen'], 'body': ['icy body'], 'g_min': 0.23, 'g_max': 0.276, 't_min': 154.0, 't_max': 175.0, 'p_min': 0.01, 'volc': 'none', 'gated': ['atmosphere_component']},
            {'atm': ['oxygen'], 'body': ['icy body'], 'g_min': 0.23, 'g_max': 0.276, 't_min': 154.0, 't_max': 175.0, 'p_min': 0.01, 'volc': 'required', 'gated': ['atmosphere_component']},
            {'atm': ['sulphur dioxide'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 132.0, 't_max': 273.0, 'gated': ['atmosphere_component']},
        ],
    },
    '$Codex_Ent_Recepta_02_Name;': {
        "name": 'Recepta Deltahedronix', "genus": 'Recepta', "value": 16202800,
        "rules": [
            {'atm': ['carbon dioxide'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 150.0, 't_max': 195.0, 'volc': 'none', 'gated': ['atmosphere_component']},
            {'atm': ['carbon dioxide'], 'body': ['icy body', 'rocky ice body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 150.0, 't_max': 195.0, 'volc': 'required', 'gated': ['atmosphere_component']},
            {'atm': ['sulphur dioxide'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 132.0, 't_max': 272.0, 'gated': ['atmosphere_component']},
        ],
    },
    '$Codex_Ent_Recepta_03_Name;': {
        "name": 'Recepta Conditivus', "genus": 'Recepta', "value": 14313700,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'icy body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 150.0, 't_max': 195.0, 'volc': 'none', 'gated': ['atmosphere_component']},
            {'atm': ['oxygen'], 'body': ['icy body'], 'g_min': 0.23, 'g_max': 0.276, 't_min': 154.0, 't_max': 175.0, 'p_min': 0.01, 'volc': 'none', 'gated': ['atmosphere_component']},
            {'atm': ['oxygen'], 'body': ['icy body'], 'g_min': 0.23, 'g_max': 0.276, 't_min': 154.0, 't_max': 175.0, 'p_min': 0.01, 'volc': 'required', 'gated': ['atmosphere_component']},
            {'atm': ['sulphur dioxide'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 132.0, 't_max': 275.0, 'gated': ['atmosphere_component']},
        ],
    },
    '$Codex_Ent_SeedABCD_01_Name;': {
        "name": 'Gypseeum Brain Tree', "genus": 'Gypseeum', "value": 1593700,
        "rules": [
            {'body': ['rocky body'], 'g_max': 0.42, 't_min': 200.0, 't_max': 400.0, 'volc': 'required', 'gated': ['bodies', 'guardian', 'region']},
        ],
    },
    '$Codex_Ent_SeedABCD_02_Name;': {
        "name": 'Ostrinum Brain Tree', "genus": 'Ostrinum', "value": 1593700,
        "rules": [
            {'body': ['high metal content body', 'metal rich body', 'rocky body'], 'volc': 'required', 'gated': ['guardian', 'region']},
        ],
    },
    '$Codex_Ent_SeedABCD_03_Name;': {
        "name": 'Viride Brain Tree', "genus": 'Viride', "value": 1593700,
        "rules": [
            {'body': ['rocky ice body'], 'g_max': 0.4, 't_min': 100.0, 't_max': 270.0, 'volc': 'any', 'gated': ['bodies', 'guardian', 'region']},
        ],
    },
    '$Codex_Ent_SeedEFGH_01_Name;': {
        "name": 'Aureum Brain Tree', "genus": 'Aureum', "value": 1593700,
        "rules": [
            {'body': ['high metal content body', 'metal rich body'], 'g_max': 2.9, 't_min': 300.0, 't_max': 500.0, 'volc': 'required', 'gated': ['guardian', 'region']},
        ],
    },
    '$Codex_Ent_SeedEFGH_02_Name;': {
        "name": 'Puniceum Brain Tree', "genus": 'Puniceum', "value": 1593700,
        "rules": [
            {'body': ['high metal content body', 'metal rich body'], 'volc': 'any', 'gated': ['bodies', 'guardian', 'region']},
        ],
    },
    '$Codex_Ent_SeedEFGH_03_Name;': {
        "name": 'Lindigoticum Brain Tree', "genus": 'Lindigoticum', "value": 1593700,
        "rules": [
            {'body': ['high metal content body', 'rocky body'], 'g_max': 2.7, 't_min': 300.0, 't_max': 500.0, 'volc': 'required', 'gated': ['bodies', 'guardian', 'region']},
        ],
    },
    '$Codex_Ent_SeedEFGH_Name;': {
        "name": 'Lividum Brain Tree', "genus": 'Lividum', "value": 1593700,
        "rules": [
            {'body': ['rocky body'], 'g_max': 0.5, 't_min': 300.0, 't_max': 500.0, 'volc': 'required', 'gated': ['guardian', 'region']},
        ],
    },
    '$Codex_Ent_Seed_Name;': {
        "name": 'Roseum Brain Tree', "genus": 'Roseum', "value": 1593700,
        "rules": [
            {'t_min': 200.0, 't_max': 500.0, 'volc': 'any', 'gated': ['guardian', 'region']},
        ],
    },
    '$Codex_Ent_Shrubs_01_Name;': {
        "name": 'Frutexa Flabellum', "genus": 'Frutexa', "value": 1808900,
        "rules": [
            {'atm': ['ammonia'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 152.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Shrubs_02_Name;': {
        "name": 'Frutexa Acus', "genus": 'Frutexa', "value": 7774700,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.237, 't_min': 146.0, 't_max': 197.0, 'p_min': 0.0029, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Shrubs_03_Name;': {
        "name": 'Frutexa Metallicum', "genus": 'Frutexa', "value": 1632500,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 152.0, 't_max': 176.0, 'p_max': 0.01, 'volc': 'none'},
            {'atm': ['carbon dioxide'], 'body': ['high metal content body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 146.0, 't_max': 197.0, 'p_min': 0.002, 'volc': 'none'},
            {'atm': ['methane'], 'body': ['high metal content body'], 'g_min': 0.05, 'g_max': 0.1, 't_min': 100.0, 't_max': 300.0},
            {'atm': ['water'], 'body': ['high metal content body'], 'g_min': 0.04, 'g_max': 0.07, 't_max': 400.0, 'p_max': 0.07, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Shrubs_04_Name;': {
        "name": 'Frutexa Flammasis', "genus": 'Frutexa', "value": 10326000,
        "rules": [
            {'atm': ['ammonia'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 152.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Shrubs_05_Name;': {
        "name": 'Frutexa Fera', "genus": 'Frutexa', "value": 1632500,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 146.0, 't_max': 197.0, 'p_min': 0.003, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Shrubs_06_Name;': {
        "name": 'Frutexa Sponsae', "genus": 'Frutexa', "value": 5988000,
        "rules": [
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.056, 'volc': 'none'},
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.056, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Shrubs_07_Name;': {
        "name": 'Frutexa Collum', "genus": 'Frutexa', "value": 1639800,
        "rules": [
            {'atm': ['sulphur dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 132.0, 't_max': 215.0, 'p_max': 0.004},
            {'atm': ['sulphur dioxide'], 'body': ['high metal content body'], 'g_min': 0.265, 'g_max': 0.276, 't_min': 132.0, 't_max': 135.0, 'p_max': 0.004, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_SphereABCD_01_Name;': {
        "name": 'Croceum Anemone', "genus": 'Croceum', "value": 1499900,
        "rules": [
            {'body': ['rocky body'], 'g_min': 0.047, 'g_max': 0.37, 't_min': 200.0, 't_max': 440.0, 'volc': 'required', 'gated': ['regions', 'star']},
        ],
    },
    '$Codex_Ent_SphereABCD_02_Name;': {
        "name": 'Puniceum Anemone', "genus": 'Puniceum', "value": 1499900,
        "rules": [
            {'body': ['icy body', 'rocky ice body'], 'g_min': 0.17, 'g_max': 2.52, 't_min': 65.0, 't_max': 800.0, 'volc': 'none', 'gated': ['regions', 'star']},
            {'body': ['icy body', 'rocky ice body'], 'g_min': 0.17, 'g_max': 2.52, 't_min': 65.0, 't_max': 800.0, 'volc': 'required', 'gated': ['regions', 'star']},
        ],
    },
    '$Codex_Ent_SphereABCD_03_Name;': {
        "name": 'Roseum Anemone', "genus": 'Roseum', "value": 1499900,
        "rules": [
            {'body': ['rocky body'], 'g_min': 0.045, 'g_max': 0.37, 't_min': 200.0, 't_max': 440.0, 'volc': 'required', 'gated': ['regions', 'star']},
        ],
    },
    '$Codex_Ent_SphereEFGH_01_Name;': {
        "name": 'Rubeum Bioluminescent Anemone', "genus": 'Rubeum', "value": 1499900,
        "rules": [
            {'body': ['high metal content body', 'metal rich body'], 'g_min': 0.036, 'g_max': 4.61, 't_min': 160.0, 't_max': 1800.0, 'volc': 'any', 'gated': ['star']},
        ],
    },
    '$Codex_Ent_SphereEFGH_02_Name;': {
        "name": 'Prasinum Bioluminescent Anemone', "genus": 'Prasinum', "value": 1499900,
        "rules": [
            {'body': ['high metal content body', 'metal rich body', 'rocky body'], 'g_min': 0.036, 't_min': 110.0, 't_max': 3050.0, 'gated': ['star']},
        ],
    },
    '$Codex_Ent_SphereEFGH_03_Name;': {
        "name": 'Roseum Bioluminescent Anemone', "genus": 'Roseum', "value": 1499900,
        "rules": [
            {'body': ['high metal content body', 'metal rich body'], 'g_min': 0.036, 'g_max': 4.61, 't_min': 400.0, 'volc': 'any', 'gated': ['star']},
        ],
    },
    '$Codex_Ent_SphereEFGH_Name;': {
        "name": 'Blatteum Bioluminescent Anemone', "genus": 'Blatteum', "value": 1499900,
        "rules": [
            {'body': ['high metal content body', 'metal rich body'], 't_min': 220.0, 'volc': 'any', 'gated': ['regions', 'star']},
        ],
    },
    '$Codex_Ent_Sphere_Name;': {
        "name": 'Luteolum Anemone', "genus": 'Luteolum', "value": 1499900,
        "rules": [
            {'body': ['rocky body'], 'g_min': 0.044, 'g_max': 1.28, 't_min': 200.0, 't_max': 440.0, 'volc': 'required', 'gated': ['regions', 'star']},
        ],
    },
    '$Codex_Ent_Stratum_01_Name;': {
        "name": 'Stratum Excutitus', "genus": 'Stratum', "value": 2448900,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.48, 't_min': 165.0, 't_max': 190.0, 'p_min': 0.0035, 'volc': 'none', 'gated': ['regions']},
            {'atm': ['sulphur dioxide'], 'body': ['rocky body'], 'g_min': 0.27, 'g_max': 0.4, 't_min': 165.0, 't_max': 190.0, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Stratum_02_Name;': {
        "name": 'Stratum Paleas', "genus": 'Stratum', "value": 1362000,
        "rules": [
            {'atm': ['ammonia'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.35, 't_min': 165.0, 't_max': 177.0, 'p_max': 0.0135},
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.585, 't_min': 165.0, 't_max': 395.0, 'volc': 'none'},
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.43, 'g_max': 0.585, 't_min': 185.0, 't_max': 260.0, 'p_min': 0.015, 'volc': 'none'},
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.056, 'volc': 'none'},
            {'atm': ['water'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.056, 'p_min': 0.065, 'volc': 'required'},
            {'atm': ['oxygen'], 'body': ['rocky body'], 'g_min': 0.39, 'g_max': 0.59, 't_min': 165.0, 't_max': 250.0, 'p_min': 0.022},
        ],
    },
    '$Codex_Ent_Stratum_03_Name;': {
        "name": 'Stratum Laminamus', "genus": 'Stratum', "value": 2788300,
        "rules": [
            {'atm': ['ammonia'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.34, 't_min': 165.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Stratum_04_Name;': {
        "name": 'Stratum Araneamus', "genus": 'Stratum', "value": 2448900,
        "rules": [
            {'atm': ['sulphur dioxide'], 'body': ['rocky body'], 'g_min': 0.26, 'g_max': 0.57, 't_min': 165.0, 't_max': 373.0},
        ],
    },
    '$Codex_Ent_Stratum_05_Name;': {
        "name": 'Stratum Limaxus', "genus": 'Stratum', "value": 1362000,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.03, 'g_max': 0.4, 't_min': 165.0, 't_max': 190.0, 'p_min': 0.05, 'volc': 'none', 'gated': ['regions']},
            {'atm': ['sulphur dioxide'], 'body': ['rocky body'], 'g_min': 0.27, 'g_max': 0.4, 't_min': 165.0, 't_max': 190.0, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Stratum_06_Name;': {
        "name": 'Stratum Cucumisis', "genus": 'Stratum', "value": 16202800,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.6, 't_min': 191.0, 't_max': 371.0, 'volc': 'none', 'gated': ['regions']},
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.44, 'g_max': 0.56, 't_min': 210.0, 't_max': 246.0, 'p_min': 0.01, 'volc': 'none', 'gated': ['regions']},
            {'atm': ['oxygen'], 'body': ['rocky body'], 'g_min': 0.4, 'g_max': 0.6, 't_min': 200.0, 't_max': 250.0, 'p_min': 0.01, 'gated': ['regions']},
            {'atm': ['sulphur dioxide'], 'body': ['rocky body'], 'g_min': 0.26, 'g_max': 0.55, 't_min': 191.0, 't_max': 373.0, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Stratum_07_Name;': {
        "name": 'Stratum Tectonicas', "genus": 'Stratum', "value": 19010800,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body'], 'g_min': 0.045, 'g_max': 0.38, 't_min': 165.0, 't_max': 177.0},
            {'atm': ['argon'], 'body': ['high metal content body'], 'g_min': 0.485, 'g_max': 0.54, 't_min': 167.0, 't_max': 199.0, 'volc': 'none'},
            {'atm': ['carbon dioxide'], 'body': ['high metal content body'], 'g_min': 0.045, 'g_max': 0.61, 't_min': 165.0, 't_max': 430.0},
            {'atm': ['carbon dioxide'], 'body': ['high metal content body'], 'g_min': 0.035, 'g_max': 0.61, 't_min': 165.0, 't_max': 260.0},
            {'atm': ['oxygen'], 'body': ['high metal content body'], 'g_min': 0.4, 'g_max': 0.52, 't_min': 165.0, 't_max': 246.0},
            {'atm': ['sulphur dioxide'], 'body': ['high metal content body'], 'g_min': 0.29, 'g_max': 0.62, 't_min': 165.0, 't_max': 450.0},
            {'atm': ['water'], 'body': ['high metal content body'], 'g_min': 0.045, 'g_max': 0.063, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Stratum_08_Name;': {
        "name": 'Stratum Frigus', "genus": 'Stratum', "value": 2637500,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.043, 'g_max': 0.54, 't_min': 191.0, 't_max': 365.0, 'p_min': 0.001, 'volc': 'none', 'gated': ['regions']},
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.45, 'g_max': 0.56, 't_min': 200.0, 't_max': 250.0, 'p_min': 0.01, 'volc': 'none', 'gated': ['regions']},
            {'atm': ['sulphur dioxide'], 'body': ['rocky body'], 'g_min': 0.29, 'g_max': 0.52, 't_min': 191.0, 't_max': 369.0, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_TubeABCD_01_Name;': {
        "name": 'Prasinum Sinuous Tubers', "genus": 'Prasinum', "value": 1514500,
        "rules": [
            {'body': ['high metal content body', 'metal rich body', 'rocky body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'any', 'gated': ['tuber']},
            {'body': ['high metal content body', 'metal rich body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['tuber']},
            {'body': ['high metal content body', 'metal rich body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_TubeABCD_02_Name;': {
        "name": 'Albidum Sinuous Tubers', "genus": 'Albidum', "value": 1514500,
        "rules": [
            {'body': ['rocky body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['max_orbital_period', 'tuber']},
        ],
    },
    '$Codex_Ent_TubeABCD_03_Name;': {
        "name": 'Caeruleum Sinuous Tubers', "genus": 'Caeruleum', "value": 1514500,
        "rules": [
            {'body': ['rocky body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['max_orbital_period', 'tuber']},
            {'body': ['rocky body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_TubeEFGH_01_Name;': {
        "name": 'Lindigoticum Sinuous Tubers', "genus": 'Lindigoticum', "value": 1514500,
        "rules": [
            {'body': ['rocky body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['max_orbital_period', 'tuber']},
        ],
    },
    '$Codex_Ent_TubeEFGH_02_Name;': {
        "name": 'Violaceum Sinuous Tubers', "genus": 'Violaceum', "value": 1514500,
        "rules": [
            {'body': ['high metal content body', 'metal rich body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['tuber']},
        ],
    },
    '$Codex_Ent_TubeEFGH_03_Name;': {
        "name": 'Viride Sinuous Tubers', "genus": 'Viride', "value": 1514500,
        "rules": [
            {'body': ['high metal content body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['tuber']},
            {'body': ['rocky body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['max_orbital_period', 'tuber']},
        ],
    },
    '$Codex_Ent_TubeEFGH_Name;': {
        "name": 'Blatteum Sinuous Tubers', "genus": 'Blatteum', "value": 1514500,
        "rules": [
            {'body': ['high metal content body', 'metal rich body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['tuber']},
        ],
    },
    '$Codex_Ent_Tube_Name;': {
        "name": 'Roseum Sinuous Tubers', "genus": 'Roseum', "value": 1514500,
        "rules": [
            {'body': ['high metal content body'], 't_min': 200.0, 't_max': 500.0, 'volc': 'required', 'gated': ['tuber']},
        ],
    },
    '$Codex_Ent_Tubus_01_Name;': {
        "name": 'Tubus Conifer', "genus": 'Tubus', "value": 2415500,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.041, 'g_max': 0.153, 't_min': 160.0, 't_max': 197.0, 'p_min': 0.003, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tubus_02_Name;': {
        "name": 'Tubus Sororibus', "genus": 'Tubus', "value": 5727600,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body'], 'g_min': 0.045, 'g_max': 0.152, 't_min': 160.0, 't_max': 177.0, 'p_max': 0.0135},
            {'atm': ['carbon dioxide'], 'body': ['high metal content body'], 'g_min': 0.045, 'g_max': 0.152, 't_min': 160.0, 't_max': 195.0, 'volc': 'none'},
        ],
    },
    '$Codex_Ent_Tubus_03_Name;': {
        "name": 'Tubus Cavas', "genus": 'Tubus', "value": 11873200,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.152, 't_min': 160.0, 't_max': 197.0, 'p_min': 0.003, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tubus_04_Name;': {
        "name": 'Tubus Rosarium', "genus": 'Tubus', "value": 2637500,
        "rules": [
            {'atm': ['ammonia'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.153, 't_min': 160.0, 't_max': 177.0, 'p_max': 0.0135},
        ],
    },
    '$Codex_Ent_Tubus_05_Name;': {
        "name": 'Tubus Compagibus', "genus": 'Tubus', "value": 7774700,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['rocky body'], 'g_min': 0.04, 'g_max': 0.153, 't_min': 160.0, 't_max': 197.0, 'p_min': 0.003, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_01_Name;': {
        "name": 'Tussock Pennata', "genus": 'Tussock', "value": 5853800,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.09, 't_min': 146.0, 't_max': 154.0, 'p_min': 0.0029, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_02_Name;': {
        "name": 'Tussock Ventusa', "genus": 'Tussock', "value": 3227700,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.13, 't_min': 155.0, 't_max': 160.0, 'p_min': 0.0029, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_03_Name;': {
        "name": 'Tussock Ignis', "genus": 'Tussock', "value": 1849000,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.2, 't_min': 161.0, 't_max': 170.0, 'p_min': 0.0029, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_04_Name;': {
        "name": 'Tussock Cultro', "genus": 'Tussock', "value": 1766600,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 152.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_05_Name;': {
        "name": 'Tussock Catena', "genus": 'Tussock', "value": 1766600,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 152.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_06_Name;': {
        "name": 'Tussock Pennatis', "genus": 'Tussock', "value": 1000000,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 147.0, 't_max': 197.0, 'p_min': 0.0029, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_07_Name;': {
        "name": 'Tussock Serrati', "genus": 'Tussock', "value": 4447100,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.042, 'g_max': 0.23, 't_min': 171.0, 't_max': 174.0, 'p_min': 0.01, 'p_max': 0.071, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_08_Name;': {
        "name": 'Tussock Albata', "genus": 'Tussock', "value": 3252500,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.042, 'g_max': 0.276, 't_min': 175.0, 't_max': 180.0, 'p_min': 0.016, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_09_Name;': {
        "name": 'Tussock Propagito', "genus": 'Tussock', "value": 1000000,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 145.0, 't_max': 197.0, 'p_min': 0.0029, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_10_Name;': {
        "name": 'Tussock Divisa', "genus": 'Tussock', "value": 1766600,
        "rules": [
            {'atm': ['ammonia'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.042, 'g_max': 0.276, 't_min': 152.0, 't_max': 177.0, 'p_max': 0.0135, 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_11_Name;': {
        "name": 'Tussock Caputus', "genus": 'Tussock', "value": 3472400,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.041, 'g_max': 0.27, 't_min': 181.0, 't_max': 190.0, 'p_min': 0.0275, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_12_Name;': {
        "name": 'Tussock Triticum', "genus": 'Tussock', "value": 7774700,
        "rules": [
            {'atm': ['carbon dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 191.0, 't_max': 197.0, 'p_min': 0.058, 'volc': 'none', 'gated': ['regions']},
        ],
    },
    '$Codex_Ent_Tussocks_13_Name;': {
        "name": 'Tussock Stigmasis', "genus": 'Tussock', "value": 19010800,
        "rules": [
            {'atm': ['sulphur dioxide'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.276, 't_min': 132.0, 't_max': 180.0, 'p_max': 0.01},
        ],
    },
    '$Codex_Ent_Tussocks_14_Name;': {
        "name": 'Tussock Virgam', "genus": 'Tussock', "value": 14313700,
        "rules": [
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.065, 'volc': 'none'},
            {'atm': ['water'], 'body': ['high metal content body', 'rocky body'], 'g_min': 0.04, 'g_max': 0.065, 'volc': 'required'},
        ],
    },
    '$Codex_Ent_Tussocks_15_Name;': {
        "name": 'Tussock Capillum', "genus": 'Tussock', "value": 7025800,
        "rules": [
            {'atm': ['argon'], 'body': ['rocky ice body'], 'g_min': 0.22, 'g_max': 0.276, 't_min': 80.0, 't_max': 129.0},
            {'atm': ['methane'], 'body': ['rocky body', 'rocky ice body'], 'g_min': 0.033, 'g_max': 0.276, 't_min': 80.0, 't_max': 110.0},
        ],
    },
}

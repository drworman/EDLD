"""
components/exobiology.py — Exobiology session tracking.

Tracks organic samples in progress, held (analysed but unsold), and sold.
Shows estimated credit value of held samples including first-discovery and
footfall bonuses where applicable.

ScanOrganic stages: Log (1) → Sample (2) → Analyse (3 = complete).
Value bonuses:
  First discovery (WasLogged=False): 5× base value
  First footfall (body not previously visited): +4× base value on top

Additional tracking:
  - Per-body bio signal counts from FSSBodySignals and SAASignalsFound,
    correlated with ScanOrganic completions to show species completion per body
  - Count of distinct bodies where at least one species was completed
  - Minimum clonal distance for the current in-progress species

SellOrganicData gives realised credits.
"""

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.emit import fmt_credits

# ── Species value table ───────────────────────────────────────────────────────
# Codex species key → (display name, base credit value)
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

# ── Minimum clonal distances by genus (metres) ────────────────────────────────
# Required minimum distance between samples of the same species.
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


def _clonal_distance(species_key: str) -> int:
    """Return minimum clonal distance in metres for the given species codex key."""
    key_lower = (species_key or "").lower()
    for genus, dist in _GENUS_CLONAL_DISTANCE.items():
        if genus in key_lower:
            return dist
    return _DEFAULT_CLONAL_DISTANCE


_FIRST_DISCOVERY_MULT = 5
_FOOTFALL_MULT        = 4


def _species_value(codex_key: str, was_logged: bool, footfall_bonus: bool) -> int:
    entry = SPECIES_VALUES.get(codex_key)
    if not entry:
        return 0
    base  = entry[1]
    value = base * _FIRST_DISCOVERY_MULT if not was_logged else base
    if footfall_bonus:
        value += base * _FOOTFALL_MULT
    return value


def _body_key(system_address: int | None, body_id: int | None) -> tuple:
    return (system_address or 0, body_id or -1)


class ActivityExobiologyPlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME        = "exobiology"
    PLUGIN_DISPLAY     = "Exobiology Activity"
    PLUGIN_VERSION     = "2.0.0"
    PLUGIN_DESCRIPTION = "Tracks organic samples, bio signal counts, held value, and clonal distances."
    ACTIVITY_TAB_TITLE = "Exobiology"

    SUBSCRIBED_EVENTS = [
        "ScanOrganic",
        "SellOrganicData",
        "FSSBodySignals",
        "SAASignalsFound",
        "Location",
        "FSDJump",
        "Embark",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.samples_analysed: int  = 0
        self.credits_earned:   int  = 0
        self.held_value_est:   int  = 0
        self.species_tally:    dict = {}   # display name → count
        self._current_species: str  = ""
        self._current_stage:   int  = 0
        self._current_body_id: int | None = None
        self._current_sys_addr: int | None = None
        self.session_start_time     = None

        # Distinct bodies with at least one completed scan this session
        self.bodies_with_bio: set[tuple] = set()

        # Per-body bio signal counts:
        # key → {"bio_count": int, "completed": int, "genuses": list[str]}
        self._body_signals: dict[tuple, dict] = {}

    def on_session_reset(self) -> None:
        self._reset_counters()

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")
        gq      = self.core.gui_queue

        match ev:

            case "FSSBodySignals":
                sys_addr = event.get("SystemAddress")
                body_id  = event.get("BodyID")
                bk = _body_key(sys_addr, body_id)
                bio_count = 0
                for sig in event.get("Signals", []):
                    if "Biological" in sig.get("Type", ""):
                        bio_count = int(sig.get("Count", 0))
                        break
                if bio_count > 0:
                    entry = self._body_signals.setdefault(bk, {"bio_count": 0, "completed": 0, "genuses": []})
                    entry["bio_count"] = bio_count

            case "SAASignalsFound":
                sys_addr = event.get("SystemAddress")
                body_id  = event.get("BodyID")
                bk = _body_key(sys_addr, body_id)
                bio_count = 0
                for sig in event.get("Signals", []):
                    if "Biological" in sig.get("Type", ""):
                        bio_count = int(sig.get("Count", 0))
                        break
                genuses = [
                    g.get("Genus_Localised") or g.get("Genus", "")
                    for g in event.get("Genuses", [])
                ]
                if bio_count > 0 or genuses:
                    entry = self._body_signals.setdefault(bk, {"bio_count": 0, "completed": 0, "genuses": []})
                    if bio_count > 0:
                        entry["bio_count"] = max(entry.get("bio_count", 0), bio_count)
                    if genuses:
                        entry["genuses"] = genuses

            case "ScanOrganic":
                scan_type    = event.get("ScanType", "")
                species_key  = event.get("Species", "")
                body_id      = event.get("Body")
                sys_addr     = event.get("SystemAddress")
                stage = {"Log": 1, "Sample": 2, "Analyse": 3}.get(scan_type, 0)
                if not stage:
                    return

                self._current_species  = species_key
                self._current_stage    = stage
                self._current_body_id  = body_id
                self._current_sys_addr = sys_addr

                if stage == 3:
                    if self.session_start_time is None:
                        self.session_start_time = logtime
                    self.samples_analysed += 1
                    display = (
                        event.get("Species_Localised")
                        or SPECIES_VALUES.get(species_key, ("Unknown",))[0]
                    ).strip()
                    self.species_tally[display] = self.species_tally.get(display, 0) + 1
                    was_logged     = bool(event.get("WasLogged", True))
                    footfall_bonus = (event.get("WasFootfalled") is False)
                    self.held_value_est += _species_value(species_key, was_logged, footfall_bonus)

                    # Mark body as visited with bio life
                    bk = _body_key(sys_addr, body_id)
                    self.bodies_with_bio.add(bk)
                    entry = self._body_signals.setdefault(bk, {"bio_count": 0, "completed": 0, "genuses": []})
                    entry["completed"] = entry.get("completed", 0) + 1

                    self._current_species  = ""
                    self._current_stage    = 0
                    self._current_body_id  = None
                    self._current_sys_addr = None
                    if gq: gq.put(("stats_update", None))

            case "SellOrganicData":
                total = sum(
                    item.get("Value", 0)
                    for item in event.get("BioData", [])
                )
                self.credits_earned += total
                self.held_value_est  = max(0, self.held_value_est - total)
                if gq: gq.put(("stats_update", None))

            case "Location" | "FSDJump" | "Embark":
                # Jump/embark mid-scan discards the in-progress scan
                if self._current_stage < 3:
                    self._current_species  = ""
                    self._current_stage    = 0
                    self._current_body_id  = None
                    self._current_sys_addr = None

    def has_activity(self) -> bool:
        return self.samples_analysed > 0 or self.credits_earned > 0

    def get_summary_rows(self) -> list[dict]:
        rows = []
        if self.samples_analysed > 0 or self.credits_earned > 0:
            display_value = self.held_value_est if self.held_value_est > 0 else self.credits_earned
            value_rate = fmt_credits(display_value) if display_value else None
            rows.append({
                "label": "Samples",
                "value": str(self.samples_analysed),
                "rate":  f"{value_rate} credits" if value_rate else None,
            })
        if self.bodies_with_bio:
            rows.append({
                "label": "Bodies with bio",
                "value": str(len(self.bodies_with_bio)),
                "rate":  None,
            })
        return rows

    def get_tab_rows(self) -> list[dict]:
        rows = self.get_summary_rows()

        # In-progress scan
        if self._current_species:
            name  = SPECIES_VALUES.get(self._current_species, ("Scanning…",))[0]
            stage = {1: "Log", 2: "Sample", 3: "Analyse"}.get(self._current_stage, "")
            dist  = _clonal_distance(self._current_species)
            dist_str = f"{dist} m min. distance"
            rows.append({
                "label": f"  In progress ({stage})",
                "value": name,
                "rate":  dist_str,
            })
            # Show current body progress if known
            if self._current_body_id is not None:
                bk = _body_key(self._current_sys_addr, self._current_body_id)
                bsig = self._body_signals.get(bk)
                if bsig and bsig.get("bio_count", 0) > 0:
                    done  = bsig.get("completed", 0)
                    total = bsig["bio_count"]
                    rows.append({
                        "label": "  Body progress",
                        "value": f"{done}/{total} species",
                        "rate":  None,
                    })

        # Per-body signal summary for bodies with known bio counts
        visible_bodies = [
            (bk, info) for bk, info in self._body_signals.items()
            if info.get("bio_count", 0) > 0 or info.get("completed", 0) > 0
        ]
        if visible_bodies:
            rows.append({"label": "─── Bodies ───", "value": "", "rate": None})
            for bk, info in visible_bodies:
                done  = info.get("completed", 0)
                total = info.get("bio_count", 0) or done
                genuses = info.get("genuses", [])
                genus_str = ", ".join(g for g in genuses if g) if genuses else ""
                rows.append({
                    "label": f"  Body {bk[1]}",
                    "value": f"{done}/{total} species",
                    "rate":  genus_str or None,
                })

        # Completed species tally
        if self.species_tally:
            rows.append({"label": "─── Species ───", "value": "", "rate": None})
            for species, count in sorted(self.species_tally.items(), key=lambda x: -x[1]):
                rows.append({"label": f"  {species}", "value": str(count), "rate": None})

        return rows

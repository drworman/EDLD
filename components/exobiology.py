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

# Value table, clonal distances, and value math live in core/exobio_data.py
# (shared with the Exobiology window).  Imported under their original names.
from core.exobio_data import (
    SPECIES_VALUES,
    species_value   as _species_value,
    clonal_distance as _clonal_distance,
)


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

"""
components/journal_history.py — Background full-journal scanner.

Scans all journal files once at startup in a daemon thread, then exposes
aggregated career and historical data to other components and GUI blocks.

Results available via self.results dict after scan completes.  The
scan_done threading.Event is set when data is ready; GUI blocks should
call wait() or check is_set() before reading results.

Data produced:
────────────────────────────────────────────────────────────────────────
career          — exploration scanning career totals (mirrors catalog DB)
powerplay       — merit totals by system, back to earliest pledge found
exploration     — carto sold total, carto sold by system count, first
                  discovery count and value, DSS maps
exobiology      — samples by genus, total sold value, total by species
combat          — total bounties earned/redeemed, kill count
income          — totals by source type across all journals
────────────────────────────────────────────────────────────────────────

The career data complements the catalog SQLite store — it covers journals
prior to when the catalog plugin was first run.
"""

import json
import threading
from pathlib import Path
from core.plugin_loader import BasePlugin


def _terraformable(ts: str) -> bool:
    s = (ts or "").lower()
    return bool(s) and s not in ("", "not terraformable")


def _genus_from_species(key: str) -> str:
    """Extract a human-readable genus from a Codex species key."""
    k = (key or "").lower()
    for genus in (
        "aleoids", "bacterium", "bacterial", "cactoid", "clypeus", "conchas",
        "electricae", "fonticulus", "shrubs", "fumerolas", "fungoids",
        "osseus", "recepta", "stratum", "tube", "tussocks",
        "aleoida", "cactoida", "concha", "fumerola", "fungoida", "tubus",
        "tussock", "frutexa", "stratum",
    ):
        if genus in k:
            return genus.title()
    return "Unknown"


class JournalHistoryPlugin(BasePlugin):
    PLUGIN_NAME        = "journal_history"
    PLUGIN_DISPLAY     = "Journal History"
    PLUGIN_DESCRIPTION = "Background full-journal scan providing career and historical statistics."
    PLUGIN_VERSION     = "1.0.0"

    # This plugin does not subscribe to live events — it is query-only.
    SUBSCRIBED_EVENTS: list = []

    def on_load(self, core) -> None:
        super().on_load(core)
        self.scan_done = threading.Event()
        self.results:  dict = {}
        t = threading.Thread(
            target=self._scan, daemon=True, name="journal-history-scan"
        )
        t.start()

    def _scan(self) -> None:
        jdir = getattr(self.core, "journal_dir", None)
        if not jdir:
            self.scan_done.set()
            return

        journals = sorted(Path(jdir).glob("Journal*.log"))
        if not journals:
            self.scan_done.set()
            return

        # ── Accumulators ──────────────────────────────────────────────────────
        # Career / exploration
        bodies_scanned    = 0
        stars_scanned     = 0
        first_discoveries = 0
        first_mapped      = 0
        elw               = 0
        water_world       = 0
        ammonia_world     = 0
        terraformable     = 0
        neutron_star      = 0
        black_hole        = 0
        seen_bodies: set[tuple] = set()   # (system_address, body_id)

        # Cartography
        carto_sold_total  = 0
        carto_sold_events = 0
        carto_base_total  = 0
        carto_bonus_total = 0

        # Exobiology
        exobio_sold_total  = 0
        exobio_by_genus:    dict[str, int] = {}
        exobio_by_species:  dict[str, int] = {}   # localised name → count
        exobio_sample_count = 0

        # PowerPlay — scan all journals, sum all merits by system
        # Reset counters on PowerplayLeave/Defect so we only count current pledge
        pp_system_merits: dict[str, int] = {}
        pp_total_merits   = 0
        pp_active         = False   # True once we see a Powerplay/Join event
        pp_current_system = ""      # system at time of PowerplayMerits event

        # Combat / income
        bounties_earned   = 0
        bounties_redeemed = 0
        bonds_earned      = 0
        bonds_redeemed    = 0
        kill_count        = 0
        income_missions   = 0
        income_trade      = 0

        # Statistics — most recent event from game (authoritative career totals)
        latest_statistics: dict = {}
        latest_statistics_ts  = ""

        # Track current system for PP merit attribution
        current_system = ""

        for jpath in journals:
            try:
                lines = jpath.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue

            for line in lines:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue

                name = ev.get("event", "")

                # ── Location tracking ─────────────────────────────────────
                if name in ("FSDJump", "Location", "CarrierJump"):
                    current_system = ev.get("StarSystem", current_system)

                # ── Exploration ───────────────────────────────────────────
                elif name == "Scan":
                    scan_type = ev.get("ScanType", "")
                    if scan_type not in ("AutoScan", "Detailed", ""):
                        continue
                    sys_addr  = ev.get("SystemAddress")
                    body_id   = ev.get("BodyID")
                    bk        = (sys_addr, body_id)
                    if sys_addr is not None and body_id is not None:
                        if bk in seen_bodies:
                            continue
                        seen_bodies.add(bk)

                    planet_class = ev.get("PlanetClass", "")
                    star_type    = ev.get("StarType", "")
                    was_disc     = ev.get("WasDiscovered", True)

                    if planet_class:
                        bodies_scanned += 1
                        if not was_disc:
                            first_discoveries += 1
                        pc = planet_class.lower()
                        if pc == "earthlike body":
                            elw += 1
                        elif pc == "water world":
                            water_world += 1
                        elif pc == "ammonia world":
                            ammonia_world += 1
                        if _terraformable(ev.get("TerraformState", "")):
                            terraformable += 1

                    elif star_type:
                        stars_scanned += 1
                        if not was_disc:
                            first_discoveries += 1
                        st = star_type.lower()
                        if "neutron" in st:
                            neutron_star += 1
                        elif "black hole" in st or st == "h":
                            black_hole += 1

                elif name == "SAAScanComplete":
                    if not ev.get("WasMapped", True):
                        first_mapped += 1

                elif name in ("SellExplorationData", "MultiSellExplorationData"):
                    base  = ev.get("BaseValue", 0)
                    bonus = ev.get("Bonus", 0)
                    total = ev.get("TotalEarnings", 0) or (base + bonus)
                    carto_sold_total  += total
                    carto_base_total  += base
                    carto_bonus_total += bonus
                    carto_sold_events += 1

                # ── Exobiology ────────────────────────────────────────────
                elif name == "ScanOrganic":
                    if ev.get("ScanType") == "Analyse":
                        exobio_sample_count += 1
                        species_key    = ev.get("Species", "")
                        species_local  = ev.get("Species_Localised", "") or species_key
                        genus          = _genus_from_species(species_key)
                        exobio_by_genus[genus]         = exobio_by_genus.get(genus, 0) + 1
                        exobio_by_species[species_local] = exobio_by_species.get(species_local, 0) + 1

                elif name == "SellOrganicData":
                    for item in ev.get("BioData", []):
                        exobio_sold_total += int(item.get("Value", 0))

                # ── PowerPlay ─────────────────────────────────────────────
                elif name in ("Powerplay", "PowerplayJoin"):
                    pp_active = True
                    snap = ev.get("Merits", 0)
                    if snap and snap > pp_total_merits:
                        pp_total_merits = snap   # use login snapshot as floor

                elif name in ("PowerplayLeave", "PowerplayDefect"):
                    if name == "PowerplayLeave":
                        pp_active = False
                        pp_system_merits.clear()
                        pp_total_merits = 0

                elif name == "PowerplayMerits" and pp_active:
                    gained = ev.get("MeritsGained", 0)
                    total  = ev.get("TotalMerits")
                    if total is not None:
                        pp_total_merits = total   # authoritative running total from server
                    if gained > 0:
                        sys = current_system or "Unknown"
                        pp_system_merits[sys] = pp_system_merits.get(sys, 0) + gained

                # ── Combat / Income ───────────────────────────────────────
                elif name == "Bounty":
                    reward = ev.get("TotalReward", 0) or ev.get("Reward", 0)
                    bounties_earned += reward
                    kill_count      += 1

                elif name == "RedeemVoucher":
                    vtype  = ev.get("Type", "")
                    amount = ev.get("Amount", 0)
                    if vtype == "bounty":
                        bounties_redeemed += amount
                    elif vtype == "CombatBond":
                        bonds_redeemed += amount

                elif name == "FactionKillBond":
                    bonds_earned += ev.get("Reward", 0)

                elif name == "MissionCompleted":
                    income_missions += ev.get("Reward", 0)

                elif name == "MarketSell":
                    income_trade += ev.get("TotalSale", 0)

                elif name == "Statistics":
                    ts = ev.get("timestamp", "")
                    if ts > latest_statistics_ts:
                        latest_statistics_ts = ts
                        latest_statistics = ev

        # ── Publish results ───────────────────────────────────────────────────
        self.results = {
            "career": {
                "bodies_scanned":    bodies_scanned,
                "stars_scanned":     stars_scanned,
                "first_discoveries": first_discoveries,
                "first_mapped":      first_mapped,
                "elw":               elw,
                "water_world":       water_world,
                "ammonia_world":     ammonia_world,
                "terraformable":     terraformable,
                "neutron_star":      neutron_star,
                "black_hole":        black_hole,
            },
            "cartography": {
                "sold_total":    carto_sold_total,
                "sold_events":   carto_sold_events,
                "base_total":    carto_base_total,
                "bonus_total":   carto_bonus_total,
            },
            "exobiology": {
                "sample_count": exobio_sample_count,
                "sold_total":   exobio_sold_total,
                "by_genus":     dict(sorted(exobio_by_genus.items(),
                                            key=lambda x: -x[1])),
                "by_species":   dict(sorted(exobio_by_species.items(),
                                            key=lambda x: -x[1])),
            },
            "powerplay": {
                "total_merits":   pp_total_merits,
                "system_merits":  dict(sorted(pp_system_merits.items(),
                                              key=lambda x: -x[1])),
            },
            "combat": {
                "kill_count":        kill_count,
                "bounties_earned":   bounties_earned,
                "bounties_redeemed": bounties_redeemed,
                "bonds_earned":      bonds_earned,
                "bonds_redeemed":    bonds_redeemed,
            },
            "income": {
                "missions": income_missions,
                "trade":    income_trade,
            },
            "statistics": latest_statistics,
        }

        self.scan_done.set()

        # Notify GUI that career data is available
        gq = self.core.gui_queue
        if gq:
            gq.put(("career_update", None))

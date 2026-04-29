"""
components/holdings/plugin.py — At-risk holdings tracker.

Tracks vouchers, cartography, and exobiology that would be lost on death.
Rebuilds from all journals on every startup — the journal scan is fast
(~1-2 seconds on spinning rust, sub-second on NVMe) and always produces
a correct balance without relying on cached state that can drift.

Tracking:
  Bounty vouchers   — earned: Bounty; redeemed: RedeemVoucher(bounty)
  Combat bonds      — earned: FactionKillBond; redeemed: RedeemVoucher(CombatBond)
  Trade vouchers    — earned: TradeVoucher; redeemed: RedeemVoucher(trade)
  Cartography data  — per-system dict; matched by SystemName on sell
  Exobiology data   — per-sample list; matched by Species key on sell

Deduplication
─────────────
Vouchers: keyed by (timestamp, event, amount) composite — not timestamp alone.
Two Bounty events at the same second (common in multi-faction CZ kills) have
different reward amounts and must both count.

Cartography and exobiology: keyed by (system, body_id) and event timestamp
respectively, as before.

Broker percentage
─────────────────
RedeemVoucher.Amount is what the player received after broker cut.
We subtract Amount directly — not the inflated face value.  The full
voucher balance is consumed regardless of broker percentage; Amount
is the best available proxy for what was cleared from the in-game ledger.
"""

from core.plugin_loader import BasePlugin
import threading


# ── Exobiology species value table ────────────────────────────────────────────
_SPECIES_VALUE: dict[str, int] = {
    "$Codex_Ent_Aleoids_01_Name;": 7252500,
    "$Codex_Ent_Aleoids_02_Name;": 6284600,
    "$Codex_Ent_Aleoids_05_Name;": 12934900,
    "$Codex_Ent_Aleoids_04_Name;": 3385200,
    "$Codex_Ent_Aleoids_03_Name;": 3385200,
    "$Codex_Ent_Vents_Name;": 1628800,
    "$Codex_Ent_TubeABCD_01_Name;": 1514500,
    "$Codex_Ent_TubeABCD_02_Name;": 1514500,
    "$Codex_Ent_TubeABCD_03_Name;": 1514500,
    "$Codex_Ent_TubeABCD_04_Name;": 1514500,
    "$Codex_Ent_TubeABCD_05_Name;": 1514500,
    "$Codex_Ent_TubeABCD_06_Name;": 1514500,
    "$Codex_Ent_TubeABCD_07_Name;": 1514500,
    "$Codex_Ent_Cone_Name;": 1471900,
    "$Codex_Ent_Bacterial_01_Name;": 1000200,
    "$Codex_Ent_Bacterial_07_Name;": 1658500,
    "$Codex_Ent_Bacterial_12_Name;": 1000200,
    "$Codex_Ent_Bacterial_02_Name;": 1152500,
    "$Codex_Ent_Bacterial_03_Name;": 1689800,
    "$Codex_Ent_Bacterial_06_Name;": 8418000,
    "$Codex_Ent_Bacterial_04_Name;": 5289900,
    "$Codex_Ent_Bacterial_08_Name;": 4638900,
    "$Codex_Ent_Bacterial_05_Name;": 4934500,
    "$Codex_Ent_Bacterial_11_Name;": 1949000,
    "$Codex_Ent_Bacterial_10_Name;": 3897000,
    "$Codex_Ent_Bacterial_09_Name;": 1000200,
    "$Codex_Ent_Bacterial_13_Name;": 7774700,
    "$Codex_Ent_Cactoid_01_Name;": 3667600,
    "$Codex_Ent_Cactoid_05_Name;": 2483600,
    "$Codex_Ent_Cactoid_04_Name;": 2483600,
    "$Codex_Ent_Cactoid_02_Name;": 3667600,
    "$Codex_Ent_Cactoid_03_Name;": 16202800,
    "$Codex_Ent_Clypeus_01_Name;": 8418000,
    "$Codex_Ent_Clypeus_03_Name;": 11873200,
    "$Codex_Ent_Clypeus_02_Name;": 16202800,
    "$Codex_Ent_Conchas_01_Name;": 7774700,
    "$Codex_Ent_Conchas_04_Name;": 16777215,
    "$Codex_Ent_Conchas_02_Name;": 2352400,
    "$Codex_Ent_Conchas_03_Name;": 4572400,
    "$Codex_Ent_Electricae_01_Name;": 6284600,
    "$Codex_Ent_Electricae_02_Name;": 6284600,
    "$Codex_Ent_Fonticulus_06_Name;": 1000200,
    "$Codex_Ent_Fonticulus_04_Name;": 3111000,
    "$Codex_Ent_Fonticulus_05_Name;": 20000000,
    "$Codex_Ent_Fonticulus_03_Name;": 5727600,
    "$Codex_Ent_Fonticulus_01_Name;": 19010800,
    "$Codex_Ent_Fonticulus_02_Name;": 1000000,
    "$Codex_Ent_Shrubs_01_Name;": 7774700,
    "$Codex_Ent_Shrubs_05_Name;": 1639800,
    "$Codex_Ent_Shrubs_02_Name;": 1639800,
    "$Codex_Ent_Shrubs_07_Name;": 1639800,
    "$Codex_Ent_Shrubs_04_Name;": 10326000,
    "$Codex_Ent_Shrubs_06_Name;": 1639800,
    "$Codex_Ent_Shrubs_03_Name;": 5988900,
    "$Codex_Ent_Fumerolas_01_Name;": 6284600,
    "$Codex_Ent_Fumerolas_04_Name;": 6284600,
    "$Codex_Ent_Fumerolas_02_Name;": 16202800,
    "$Codex_Ent_Fumerolas_03_Name;": 7774700,
    "$Codex_Ent_Fungoids_03_Name;": 3703200,
    "$Codex_Ent_Fungoids_01_Name;": 3330300,
    "$Codex_Ent_Fungoids_04_Name;": 1670100,
    "$Codex_Ent_Fungoids_02_Name;": 2680300,
    "$Codex_Ent_Osseus_01_Name;": 1483000,
    "$Codex_Ent_Osseus_03_Name;": 12934900,
    "$Codex_Ent_Osseus_02_Name;": 4027800,
    "$Codex_Ent_Osseus_05_Name;": 9739000,
    "$Codex_Ent_Osseus_06_Name;": 3156300,
    "$Codex_Ent_Osseus_04_Name;": 2404700,
    "$Codex_Ent_Ingensradices_Unicus_Name;": 119037,
    "$Codex_Ent_Recepta_01_Name;": 14313700,
    "$Codex_Ent_Recepta_03_Name;": 16202800,
    "$Codex_Ent_Recepta_02_Name;": 12934900,
    "$Codex_Ent_Seed_Name;": 1593700,
    "$Codex_Ent_Shard_Name;": 1515200,
    "$Codex_Ent_Stratum_01_Name;": 2448900,
    "$Codex_Ent_Stratum_02_Name;": 1362000,
    "$Codex_Ent_Stratum_03_Name;": 2788300,
    "$Codex_Ent_Stratum_04_Name;": 2448900,
    "$Codex_Ent_Stratum_05_Name;": 1362000,
    "$Codex_Ent_Stratum_06_Name;": 16202800,
    "$Codex_Ent_Stratum_07_Name;": 19010800,
    "$Codex_Ent_Stratum_08_Name;": 2637500,
    "$Codex_Ent_Tube_01_Name;": 11873200,
    "$Codex_Ent_Tube_04_Name;": 7774700,
    "$Codex_Ent_Tube_02_Name;": 2415500,
    "$Codex_Ent_Tube_03_Name;": 2637500,
    "$Codex_Ent_Tube_05_Name;": 5853800,
    "$Codex_Ent_Tussocks_15_Name;": 3252500,
    "$Codex_Ent_Tussocks_06_Name;": 7025800,
    "$Codex_Ent_Tussocks_02_Name;": 3472400,
    "$Codex_Ent_Tussocks_11_Name;": 1766600,
    "$Codex_Ent_Tussocks_08_Name;": 1766600,
    "$Codex_Ent_Tussocks_10_Name;": 1766600,
    "$Codex_Ent_Tussocks_05_Name;": 1849000,
    "$Codex_Ent_Tussocks_04_Name;": 1766600,
    "$Codex_Ent_Tussocks_01_Name;": 1000200,
    "$Codex_Ent_Tussocks_07_Name;": 1000200,
    "$Codex_Ent_Tussocks_03_Name;": 1000200,
    "$Codex_Ent_Tussocks_09_Name;": 4447100,
    "$Codex_Ent_Tussocks_12_Name;": 19010800,
    "$Codex_Ent_Tussocks_13_Name;": 7774700,
    "$Codex_Ent_Tussocks_14_Name;": 3227700,
    "$Codex_Ent_Tussocks_16_Name;": 14313700,
}

_FIRST_DISC_MULT = 5
_FOOTFALL_MULT   = 4


def _exobio_value(species_key: str, was_logged: bool, footfall_bonus: bool) -> int:
    base = _SPECIES_VALUE.get(species_key, 0)
    if not base:
        return 0
    value = base * _FIRST_DISC_MULT if not was_logged else base
    if footfall_bonus:
        value += base * _FOOTFALL_MULT
    return value


# ── Cartography value formula ─────────────────────────────────────────────────
_PLANET_K: dict[str, int] = {
    "metal rich body":             52292,
    "ammonia world":              232619,
    "sudarsky class i gas giant":   3974,
    "sudarsky class ii gas giant": 23168,
    "high metal content body":     23168,
    "water world":                155581,
    "earthlike body":             155581,
}
_PLANET_K_DEFAULT = 720

_TERRA_K: dict[str, int] = {
    "high metal content body":  241607,
    "water world":              279088,
    "earthlike body":           279088,
    "rocky body":               223971,
}

_STAR_K: dict[str, int] = {
    "black hole":   54309,
    "neutron star": 54309,
    "white dwarf":  33737,
}
_STAR_K_DEFAULT = 2880

_FIRST_DISC_SCAN = 2.5
_MAP_MULT        = 3.3 * 1.3
_EFFICIENCY_MULT = 1.25


def _planet_base(planet_class: str, mass_em: float) -> int:
    k = _PLANET_K.get(planet_class.lower().strip(), _PLANET_K_DEFAULT)
    return round(k + (3 * k * (mass_em ** 0.199977) / 5.3))


def _terra_bonus(planet_class: str, mass_em: float) -> int:
    kt = _TERRA_K.get(planet_class.lower().strip(), 0)
    if not kt:
        return 0
    return round(kt + (3 * kt * (mass_em ** 0.199977) / 5.3))


def _star_value(star_type: str, solar_mass: float) -> int:
    st = star_type.lower()
    k  = next((v for key, v in _STAR_K.items() if key in st), _STAR_K_DEFAULT)
    return round(k + (solar_mass * k / 66.25))


def _scan_value(planet_class: str, mass_em: float, terraform_state: str,
                was_discovered: bool, was_mapped: bool,
                dss_mapped: bool, efficient: bool) -> int:
    terraformable = bool(
        terraform_state and
        terraform_state.lower() not in ("", "not terraformable")
    )
    base     = _planet_base(planet_class, mass_em)
    bonus    = _terra_bonus(planet_class, mass_em) if terraformable else 0
    scan_val = base + bonus
    value    = round(scan_val * _FIRST_DISC_SCAN) if not was_discovered else scan_val
    if dss_mapped:
        map_val = round(scan_val * _MAP_MULT)
        if efficient:
            map_val = round(map_val * _EFFICIENCY_MULT)
        value += map_val
    return value


def _voucher_key(ev: dict) -> tuple:
    """Composite dedup key: (timestamp, event, amount).

    Two Bounty events at the same second always have different reward amounts.
    Using the composite prevents same-second kills from being collapsed.
    """
    return (
        ev.get("timestamp", ""),
        ev.get("event", ""),
        ev.get("TotalReward") or ev.get("Reward") or ev.get("Amount") or 0,
    )


# ── Plugin ────────────────────────────────────────────────────────────────────

class HoldingsPlugin(BasePlugin):
    PLUGIN_NAME    = "holdings"
    PLUGIN_DISPLAY = "At-Risk Holdings"
    PLUGIN_DESCRIPTION = (
        "Tracks unredeemed vouchers, bonds, and unsold data "
        "that would be lost on ship destruction."
    )
    PLUGIN_VERSION = "2.0.0"

    SUBSCRIBED_EVENTS = [
        "Bounty",
        "FactionKillBond",
        "TradeVoucher",
        "RedeemVoucher",
        "Scan",
        "SAAScanComplete",
        "SellExplorationData",
        "MultiSellExplorationData",
        "ScanOrganic",
        "SellOrganicData",
        "Died",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        self._carto:   dict[str, int] = {}
        self._exobio:  list[dict]     = []
        self._pending: dict           = {}

        # Composite dedup key sets
        self._seen_vouchers: set[tuple] = set()   # (ts, event, amount)
        self._seen_bodies:   set[tuple] = set()   # (system, body_id)
        self._seen_exobio:   set[str]   = set()   # ScanOrganic timestamps

        # Always rebuild from journals in a background thread so startup is
        # non-blocking.  Live events are queued normally during the scan;
        # the dedup sets prevent double-counting when preload replays them.
        self._bootstrap_done = threading.Event()
        t = threading.Thread(target=self._bootstrap_all, daemon=True,
                             name="holdings-bootstrap")
        t.start()

    def _bootstrap_all(self) -> None:
        """Full journal scan: rebuild vouchers, cartography, and exobiology.

        Runs in a background thread on every startup.  Produces the canonical
        balance from the complete journal record.  Live events arriving during
        the scan are handled by on_event with dedup — they will be skipped
        when the scanner reaches the same timestamp/amount.
        """
        import json as _j
        from pathlib import Path as _P

        jdir = getattr(self.core, "journal_dir", None)
        if not jdir:
            self._bootstrap_done.set()
            return

        journals = sorted(_P(jdir).glob("Journal*.log"))
        if not journals:
            self._bootstrap_done.set()
            return

        bounties = 0
        bonds    = 0
        trade    = 0
        carto:  dict[str, int]  = {}
        exobio: list[dict]      = []
        pending: dict           = {}
        seen_v: set[tuple]      = set()   # voucher composite keys
        seen_b: set[tuple]      = set()   # (system, body_id)
        seen_x: set[str]        = set()   # exobio timestamps

        for jpath in journals:
            try:
                lines = jpath.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    ev = _j.loads(line)
                except ValueError:
                    continue

                name = ev.get("event", "")

                if name == "Died":
                    bounties = bonds = trade = 0
                    carto.clear()
                    exobio.clear()
                    pending.clear()
                    seen_v.clear()
                    seen_b.clear()
                    seen_x.clear()

                elif name == "Bounty":
                    key = _voucher_key(ev)
                    if key not in seen_v:
                        seen_v.add(key)
                        bounties += ev.get("TotalReward", 0) or ev.get("Reward", 0)

                elif name == "FactionKillBond":
                    key = _voucher_key(ev)
                    if key not in seen_v:
                        seen_v.add(key)
                        bonds += ev.get("Reward", 0)

                elif name == "TradeVoucher":
                    key = _voucher_key(ev)
                    if key not in seen_v:
                        seen_v.add(key)
                        trade += ev.get("Reward", 0)

                elif name == "RedeemVoucher":
                    key = _voucher_key(ev)
                    if key not in seen_v:
                        seen_v.add(key)
                        vtype  = ev.get("Type", "")
                        amount = ev.get("Amount", 0)
                        if vtype == "bounty":
                            bounties = max(0, bounties - amount)
                        elif vtype == "CombatBond":
                            bonds    = max(0, bonds    - amount)
                        elif vtype == "trade":
                            trade    = max(0, trade    - amount)

                elif name == "Scan":
                    scan_type = ev.get("ScanType", "")
                    if scan_type not in ("AutoScan", "Detailed", ""):
                        continue
                    system       = ev.get("StarSystem", "")
                    planet_class = ev.get("PlanetClass", "")
                    star_type    = ev.get("StarType", "")
                    body_id      = ev.get("BodyID")
                    if not system or (not planet_class and not star_type):
                        continue
                    body_key = (system, body_id)
                    if body_id is not None and body_key in seen_b:
                        continue
                    if planet_class:
                        mass_em = ev.get("MassEM", 1.0) or 1.0
                        val = _scan_value(
                            planet_class, mass_em,
                            ev.get("TerraformState", ""),
                            ev.get("WasDiscovered", True),
                            ev.get("WasMapped", True),
                            dss_mapped=False, efficient=False,
                        )
                        carto[system] = carto.get(system, 0) + val
                        if body_id is not None:
                            seen_b.add(body_key)
                            pending[body_id] = {
                                "system":          system,
                                "planet_class":    planet_class,
                                "mass_em":         mass_em,
                                "terraform_state": ev.get("TerraformState", ""),
                                "was_discovered":  ev.get("WasDiscovered", True),
                                "was_mapped":      ev.get("WasMapped", True),
                                "scan_value":      val,
                            }
                    elif star_type:
                        solar_mass = ev.get("StellarMass", 1.0) or 1.0
                        star_val   = _star_value(star_type, solar_mass)
                        if not ev.get("WasDiscovered", True):
                            star_val = round(star_val * _FIRST_DISC_SCAN)
                        carto[system] = carto.get(system, 0) + star_val
                        if body_id is not None:
                            seen_b.add(body_key)

                elif name == "SAAScanComplete":
                    body_id = ev.get("BodyID")
                    p       = pending.get(body_id)
                    if p:
                        target    = ev.get("EfficiencyTarget", 99)
                        used      = ev.get("ProbesUsed", 99)
                        full_val  = _scan_value(
                            p["planet_class"], p["mass_em"], p["terraform_state"],
                            p["was_discovered"], p["was_mapped"],
                            dss_mapped=True, efficient=(used <= target),
                        )
                        delta = full_val - p["scan_value"]
                        carto[p["system"]] = carto.get(p["system"], 0) + delta
                        del pending[body_id]

                elif name in ("SellExplorationData", "MultiSellExplorationData"):
                    if name == "SellExplorationData":
                        systems = [ev.get("System", "")]
                    else:
                        systems = [e.get("SystemName", "")
                                   for e in ev.get("Discovered", [])]
                    for sys in systems:
                        if sys and sys in carto:
                            del carto[sys]
                    sold = set(systems)
                    pending = {k: v for k, v in pending.items()
                               if v.get("system") not in sold}
                    seen_b = {b for b in seen_b if b[0] not in sold}

                elif name == "ScanOrganic":
                    if ev.get("ScanType") != "Analyse":
                        continue
                    ts = ev.get("timestamp", "")
                    if ts and ts in seen_x:
                        continue
                    species_key    = ev.get("Species", "")
                    was_logged     = bool(ev.get("WasLogged", True))
                    footfall_bonus = (ev.get("WasFootfalled") is False)
                    val = _exobio_value(species_key, was_logged, footfall_bonus)
                    exobio.append({"species": species_key, "value": val, "ts": ts})
                    if ts:
                        seen_x.add(ts)

                elif name == "SellOrganicData":
                    for item in ev.get("BioData", []):
                        species = item.get("Species", "")
                        for i, held in enumerate(exobio):
                            if held.get("species") == species:
                                ts = held.get("ts", "")
                                if ts:
                                    seen_x.discard(ts)
                                exobio.pop(i)
                                break

        # Publish results to state
        state = self.core.state
        state.holdings_bounties    = bounties
        state.holdings_bonds       = bonds
        state.holdings_trade       = trade
        state.holdings_cartography = sum(carto.values())
        state.holdings_exobiology  = sum(s["value"] for s in exobio)

        self._carto          = carto
        self._exobio         = exobio
        self._pending        = pending
        self._seen_vouchers  = seen_v
        self._seen_bodies    = seen_b
        self._seen_exobio    = seen_x

        self._bootstrap_done.set()
        self._notify()

    # ── State helpers ─────────────────────────────────────────────────────────

    def _update_carto_state(self) -> None:
        self.core.state.holdings_cartography = sum(self._carto.values())

    def _update_exobio_state(self) -> None:
        self.core.state.holdings_exobiology = sum(s["value"] for s in self._exobio)

    def _notify(self) -> None:
        gq = self.core.gui_queue
        if gq:
            gq.put(("holdings_update", None))

    def _current_system(self) -> str:
        return getattr(self.core.state, "pilot_system", "") or ""

    # ── Live event handling ───────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        # Don't process live events until bootstrap has published its results —
        # the dedup sets aren't ready yet.  Preload events arrive synchronously
        # before any live events, and bootstrap runs in a background thread
        # started before preload, so by the time preload completes the scan
        # is almost certainly done.  The wait() call is a safety net.
        if not self._bootstrap_done.is_set():
            self._bootstrap_done.wait(timeout=30)

        ev  = event.get("event")
        key = _voucher_key(event)

        match ev:

            # ── Voucher / bond accumulation ───────────────────────────────

            case "Bounty":
                if key in self._seen_vouchers:
                    return
                self._seen_vouchers.add(key)
                reward = event.get("TotalReward", 0) or event.get("Reward", 0)
                state.holdings_bounties += reward
                self._notify()

            case "FactionKillBond":
                if key in self._seen_vouchers:
                    return
                self._seen_vouchers.add(key)
                state.holdings_bonds += event.get("Reward", 0)
                self._notify()

            case "TradeVoucher":
                if key in self._seen_vouchers:
                    return
                self._seen_vouchers.add(key)
                state.holdings_trade += event.get("Reward", 0)
                self._notify()

            case "RedeemVoucher":
                if key in self._seen_vouchers:
                    return
                self._seen_vouchers.add(key)
                vtype  = event.get("Type", "")
                amount = event.get("Amount", 0)
                match vtype:
                    case "bounty":
                        state.holdings_bounties = max(0, state.holdings_bounties - amount)
                    case "CombatBond":
                        state.holdings_bonds = max(0, state.holdings_bonds - amount)
                    case "trade":
                        state.holdings_trade = max(0, state.holdings_trade - amount)
                self._notify()

            # ── Cartography ───────────────────────────────────────────────

            case "Scan":
                scan_type = event.get("ScanType", "")
                if scan_type not in ("AutoScan", "Detailed", ""):
                    return
                system = event.get("StarSystem", "") or self._current_system()
                if not system:
                    return
                planet_class    = event.get("PlanetClass", "")
                star_type       = event.get("StarType", "")
                was_discovered  = event.get("WasDiscovered", True)
                was_mapped      = event.get("WasMapped", True)
                terraform_state = event.get("TerraformState", "")
                body_id         = event.get("BodyID")

                if planet_class:
                    body_key = (system, body_id)
                    if body_id is not None and body_key in self._seen_bodies:
                        return
                    mass_em = event.get("MassEM", 1.0) or 1.0
                    val = _scan_value(planet_class, mass_em, terraform_state,
                                      was_discovered, was_mapped,
                                      dss_mapped=False, efficient=False)
                    self._carto[system] = self._carto.get(system, 0) + val
                    if body_id is not None:
                        self._seen_bodies.add(body_key)
                        self._pending[body_id] = {
                            "system":          system,
                            "planet_class":    planet_class,
                            "mass_em":         mass_em,
                            "terraform_state": terraform_state,
                            "was_discovered":  was_discovered,
                            "was_mapped":      was_mapped,
                            "scan_value":      val,
                        }
                    self._update_carto_state(); self._notify()

                elif star_type:
                    body_key = (system, body_id)
                    if body_id is not None and body_key in self._seen_bodies:
                        return
                    solar_mass = event.get("StellarMass", 1.0) or 1.0
                    star_val   = _star_value(star_type, solar_mass)
                    if not was_discovered:
                        star_val = round(star_val * _FIRST_DISC_SCAN)
                    self._carto[system] = self._carto.get(system, 0) + star_val
                    if body_id is not None:
                        self._seen_bodies.add(body_key)
                    self._update_carto_state(); self._notify()

            case "SAAScanComplete":
                body_id   = event.get("BodyID")
                target    = event.get("EfficiencyTarget", 99)
                used      = event.get("ProbesUsed", 99)
                efficient = (used <= target)
                pending   = self._pending.get(body_id)
                if pending:
                    system   = pending["system"]
                    full_val = _scan_value(
                        pending["planet_class"], pending["mass_em"],
                        pending["terraform_state"],
                        pending["was_discovered"], pending["was_mapped"],
                        dss_mapped=True, efficient=efficient,
                    )
                    delta = full_val - pending["scan_value"]
                    self._carto[system] = self._carto.get(system, 0) + delta
                    self._update_carto_state(); self._notify()

            case "SellExplorationData":
                system = event.get("System", "")
                if system and system in self._carto:
                    del self._carto[system]
                    self._pending = {
                        k: v for k, v in self._pending.items()
                        if v.get("system") != system
                    }
                    self._seen_bodies = {
                        b for b in self._seen_bodies if b[0] != system
                    }
                    self._update_carto_state(); self._notify()

            case "MultiSellExplorationData":
                sold    = {e.get("SystemName", "")
                           for e in event.get("Discovered", [])}
                changed = any(s in self._carto for s in sold)
                if changed:
                    for s in sold:
                        self._carto.pop(s, None)
                    self._pending = {
                        k: v for k, v in self._pending.items()
                        if v.get("system") not in sold
                    }
                    self._seen_bodies = {
                        b for b in self._seen_bodies if b[0] not in sold
                    }
                    self._update_carto_state(); self._notify()

            # ── Exobiology ────────────────────────────────────────────────

            case "ScanOrganic":
                if event.get("ScanType") != "Analyse":
                    return
                ts = event.get("timestamp", "")
                if ts and ts in self._seen_exobio:
                    return
                species_key    = event.get("Species", "")
                was_logged     = bool(event.get("WasLogged", True))
                footfall_bonus = (event.get("WasFootfalled") is False)
                val = _exobio_value(species_key, was_logged, footfall_bonus)
                self._exobio.append({"species": species_key, "value": val, "ts": ts})
                if ts:
                    self._seen_exobio.add(ts)
                self._update_exobio_state(); self._notify()

            case "SellOrganicData":
                for item in event.get("BioData", []):
                    species = item.get("Species", "")
                    for i, held in enumerate(self._exobio):
                        if held.get("species") == species:
                            ts = held.get("ts", "")
                            if ts:
                                self._seen_exobio.discard(ts)
                            self._exobio.pop(i)
                            break
                self._update_exobio_state(); self._notify()

            # ── Ship destruction ──────────────────────────────────────────

            case "Died":
                state.holdings_bounties = 0
                state.holdings_bonds    = 0
                state.holdings_trade    = 0
                self._carto.clear()
                self._exobio.clear()
                self._pending.clear()
                self._seen_bodies.clear()
                self._seen_exobio.clear()
                self._update_carto_state()
                self._update_exobio_state()
                self._notify()

    def total_at_risk(self) -> int:
        state = self.core.state
        return (
            state.holdings_bounties
            + state.holdings_bonds
            + state.holdings_trade
            + state.holdings_cartography
            + state.holdings_exobiology
        )

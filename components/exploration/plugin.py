"""
components/exploration/plugin.py — Exploration session tracking.

Tracks FSD jumps and distance, FSS/DSS scans, estimated unsold scan value
(accumulated from Scan events using Frontier's body value formula), realised
cartography sale value, notable body type counts (ELW, Water Worlds, etc.),
FSS completion progress, habitable zone for the current system's arrival star,
and active nav route progress.

Body value formula (from Frontier community research):
  Base = k + (3 * k * mass^0.199977 / 5.3)
  Terraformable bonus = k_terra + (3 * k_terra * mass^0.199977 / 5.3)
  Star = k + (solar_mass * k / 66.25)

Multipliers:
  First discovered:  2.5×
  Mapped (Odyssey):  3.3 × 1.3 = 4.29×
  First mapped:      same 4.29× on mapped component
  Efficiency bonus:  1.25× mapped value

Habitable zone formula (black-body approximation):
  dist_ls = sqrt(L / 4π) / (σ * T_hz^4)^0.5  — simplified to:
  d = r * (T_star / T_hz)^2 / LS
  where r = stellar radius (m), T_star = surface temp (K), T_hz = target temp (K)

Tab title: Exploration
"""

import math

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.emit import fmt_credits

# ── Planet k-factors ──────────────────────────────────────────────────────────
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

_FIRST_DISC_MULT   = 2.5
_MAP_MULT          = 3.3 * 1.3
_EFFICIENCY_MULT   = 1.25

# ── Notable body categories ───────────────────────────────────────────────────
# Each entry: (display label, predicate)
_NOTABLE_PLANET_CLASSES = {
    "earthlike body":        "Earth-Like World",
    "water world":           "Water World",
    "ammonia world":         "Ammonia World",
}

_NOTABLE_STAR_TYPES = {
    "n":  "Neutron Star",
    "h":  "Black Hole",
}

# Habitable zone black-body target temperatures (K) for ELW / Water / Ammonia
_HZ_TARGETS: list[tuple[str, float, float]] = [
    # (label, T_inner, T_outer)  — higher T = closer to star
    ("ELW",    315.0, 223.0),
    ("Water",  307.0, 156.0),
    ("Ammonia",193.0, 117.0),
]
_LS = 300_000_000.0   # 1 ls in metres


def _planet_base(planet_class: str, mass_em: float) -> int:
    pc = planet_class.lower().strip()
    k  = _PLANET_K.get(pc, _PLANET_K_DEFAULT)
    return round(k + (3 * k * (mass_em ** 0.199977) / 5.3))


def _terra_bonus(planet_class: str, mass_em: float) -> int:
    pc = planet_class.lower().strip()
    kt = _TERRA_K.get(pc, 0)
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
    terraformable = bool(terraform_state and terraform_state.lower()
                         not in ("", "not terraformable"))
    base  = _planet_base(planet_class, mass_em)
    bonus = _terra_bonus(planet_class, mass_em) if terraformable else 0
    scan_val = base + bonus
    value = round(scan_val * _FIRST_DISC_MULT) if not was_discovered else scan_val
    if dss_mapped:
        map_val = round(scan_val * _MAP_MULT)
        if not was_mapped:
            map_val = round(map_val)
        if efficient:
            map_val = round(map_val * _EFFICIENCY_MULT)
        value += map_val
    return value


def _hz_dist_ls(radius_m: float, t_star: float, t_hz: float) -> float:
    """Distance in ls for the habitable-zone boundary at temperature t_hz."""
    if t_hz <= 0:
        return 0.0
    return radius_m * (t_star / t_hz) ** 2 / _LS


class ActivityExplorationPlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME        = "exploration"
    PLUGIN_DISPLAY     = "Exploration Activity"
    PLUGIN_VERSION     = "2.0.0"
    PLUGIN_DESCRIPTION = "Tracks jumps, scans, notable bodies, FSS completion, hab zone, and nav route."
    ACTIVITY_TAB_TITLE = "Exploration"

    SUBSCRIBED_EVENTS = [
        "FSDJump",
        "Scan",
        "SAAScanComplete",
        "FSSDiscoveryScan",
        "FSSAllBodiesFound",
        "SellExplorationData",
        "MultiSellExplorationData",
        "NavRouteClear",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.jumps:               int   = 0
        self.distance_ly:         float = 0.0
        self.bodies_fss_scanned:  int   = 0
        self.bodies_dss_mapped:   int   = 0
        self.first_discoveries:   int   = 0
        self.first_mapped:        int   = 0
        self.unsold_value_est:    int   = 0
        self.cartography_base:    int   = 0
        self.cartography_bonus:   int   = 0
        self.session_start_time         = None

        # Notable body counters: label → count
        self.notable_bodies: dict[str, int] = {}

        # FSS completion tracking
        self.systems_honked:        int  = 0
        self.systems_fully_scanned: int  = 0
        self._honked_systems:       set  = set()   # SystemAddress values seen

        # Current system habitable zone (set on arrival star Scan)
        # List of (label, near_ls, far_ls) or None
        self.current_hz: list[tuple[str, float, float]] | None = None
        self.current_hz_system: str | None = None

        # Pending DSS data: body_id → scan info dict
        self._pending_scans: dict = {}

    def on_session_reset(self) -> None:
        self._reset_counters()

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")
        gq      = self.core.gui_queue

        match ev:

            case "FSDJump":
                if self.session_start_time is None:
                    self.session_start_time = logtime
                self.jumps       += 1
                self.distance_ly += event.get("JumpDist", 0.0)
                # Clear hab zone — new system, not yet scanned
                self.current_hz = None
                self.current_hz_system = event.get("StarSystem")
                if gq: gq.put(("stats_update", None))

            case "Scan":
                scan_type = event.get("ScanType", "")
                if scan_type not in ("AutoScan", "Detailed", ""):
                    return

                if self.session_start_time is None:
                    self.session_start_time = logtime

                planet_class    = event.get("PlanetClass", "")
                star_type       = event.get("StarType", "")
                was_discovered  = event.get("WasDiscovered", True)
                was_mapped      = event.get("WasMapped", True)
                terraform_state = event.get("TerraformState", "")
                body_id         = event.get("BodyID")
                dist_from_arr   = event.get("DistanceFromArrivalLS", 999.0) or 999.0

                if planet_class:
                    mass_em = event.get("MassEM", 1.0) or 1.0
                    self.bodies_fss_scanned += 1
                    if not was_discovered:
                        self.first_discoveries += 1

                    val = _scan_value(planet_class, mass_em, terraform_state,
                                      was_discovered, was_mapped,
                                      dss_mapped=False, efficient=False)
                    self.unsold_value_est += val

                    if body_id is not None:
                        self._pending_scans[body_id] = {
                            "planet_class":    planet_class,
                            "mass_em":         mass_em,
                            "terraform_state": terraform_state,
                            "was_discovered":  was_discovered,
                            "was_mapped":      was_mapped,
                            "scan_value":      val,
                        }

                    # Notable planet types
                    pc_lower = planet_class.lower().strip()
                    label = _NOTABLE_PLANET_CLASSES.get(pc_lower)
                    if label:
                        self.notable_bodies[label] = self.notable_bodies.get(label, 0) + 1
                    elif terraform_state and terraform_state.lower() not in ("", "not terraformable"):
                        self.notable_bodies["Terraformable"] = self.notable_bodies.get("Terraformable", 0) + 1

                elif star_type:
                    solar_mass = event.get("StellarMass", 1.0) or 1.0
                    star_val   = _star_value(star_type, solar_mass)
                    if not was_discovered:
                        star_val = round(star_val * _FIRST_DISC_MULT)
                        self.first_discoveries += 1
                    self.unsold_value_est += star_val

                    # Notable star types
                    st_lower = star_type.lower().strip()
                    label = _NOTABLE_STAR_TYPES.get(st_lower)
                    if label:
                        self.notable_bodies[label] = self.notable_bodies.get(label, 0) + 1

                    # Habitable zone for arrival star
                    if dist_from_arr < 0.01:
                        radius = event.get("Radius", 0.0) or 0.0
                        t_star = event.get("SurfaceTemperature", 0.0) or 0.0
                        if radius > 0 and t_star > 0:
                            hz = []
                            for (lbl, t_inner, t_outer) in _HZ_TARGETS:
                                near = _hz_dist_ls(radius, t_star, t_inner)
                                far  = _hz_dist_ls(radius, t_star, t_outer)
                                if far > 0:
                                    hz.append((lbl, near, far))
                            self.current_hz = hz if hz else None
                            self.current_hz_system = event.get("StarSystem") or self.current_hz_system

            case "SAAScanComplete":
                body_id   = event.get("BodyID")
                target    = event.get("EfficiencyTarget", 99)
                used      = event.get("ProbesUsed", 99)
                efficient = (used <= target)
                self.bodies_dss_mapped += 1
                pending = self._pending_scans.get(body_id)
                if pending:
                    full_val = _scan_value(
                        pending["planet_class"], pending["mass_em"],
                        pending["terraform_state"],
                        pending["was_discovered"], pending["was_mapped"],
                        dss_mapped=True, efficient=efficient,
                    )
                    self.unsold_value_est += full_val - pending["scan_value"]
                    if not pending["was_mapped"]:
                        self.first_mapped += 1

            case "FSSDiscoveryScan":
                sys_addr = event.get("SystemAddress")
                if sys_addr and sys_addr not in self._honked_systems:
                    self._honked_systems.add(sys_addr)
                    self.systems_honked += 1

            case "FSSAllBodiesFound":
                self.systems_fully_scanned += 1

            case "SellExplorationData":
                base  = event.get("BaseValue", 0)
                bonus = event.get("Bonus", 0)
                total = event.get("TotalEarnings", 0) or (base + bonus)
                self.cartography_base  += base
                self.cartography_bonus += bonus
                self.unsold_value_est   = max(0, self.unsold_value_est - total)
                if gq: gq.put(("stats_update", None))

            case "MultiSellExplorationData":
                base  = event.get("BaseValue", 0)
                bonus = event.get("Bonus", 0)
                total = event.get("TotalEarnings", 0) or (base + bonus)
                self.cartography_base  += base
                self.cartography_bonus += bonus
                self.unsold_value_est   = max(0, self.unsold_value_est - total)
                if gq: gq.put(("stats_update", None))

            case "NavRouteClear":
                # Route was cancelled; state.nav_route will be empty
                if gq: gq.put(("stats_update", None))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _nav_route_info(self) -> tuple[int, float] | None:
        """
        Return (remaining_jumps, total_distance_ly) from state.nav_route,
        or None if no route is plotted.
        """
        route = getattr(self.core.state, "nav_route", [])
        if not route or len(route) < 2:
            return None
        # route is a list of waypoints; remaining = all entries after current position
        # state.pilot_system gives current system
        pilot = getattr(self.core.state, "pilot_system", None)
        if pilot:
            # Find first waypoint past current system
            waypoints = [w for w in route if w.get("StarSystem") != pilot]
        else:
            waypoints = list(route)
        remaining = len(waypoints)
        if remaining == 0:
            return None
        # Approximate total plotted distance by summing consecutive jump distances
        # (we don't have per-hop distances, so just report hop count and next dest)
        return (remaining, 0.0)

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return self.jumps > 0 or self.bodies_fss_scanned > 0

    def get_summary_rows(self) -> list[dict]:
        rows = []
        if self.jumps > 0:
            rows.append({
                "label": "Distance",
                "value": f"{self.jumps} jumps",
                "rate":  f"{self.distance_ly:,.0f} ly",
            })
        if self.bodies_fss_scanned > 0:
            carto_rate = fmt_credits(self.unsold_value_est) if self.unsold_value_est > 0 else None
            rows.append({
                "label": "Bodies scanned",
                "value": str(self.bodies_fss_scanned),
                "rate":  carto_rate,
            })
        total_sold = self.cartography_base + self.cartography_bonus
        if total_sold > 0:
            rows.append({
                "label": "Cartography sold",
                "value": fmt_credits(total_sold),
                "rate":  None,
            })
        return rows

    def get_tab_rows(self) -> list[dict]:
        rows = self.get_summary_rows()

        # DSS / discovery milestones
        if self.bodies_dss_mapped > 0:
            rows.append({"label": "DSS mapped",        "value": str(self.bodies_dss_mapped),  "rate": None})
        if self.first_discoveries > 0:
            rows.append({"label": "First discoveries", "value": str(self.first_discoveries),  "rate": None})
        if self.first_mapped > 0:
            rows.append({"label": "First mapped",      "value": str(self.first_mapped),       "rate": None})
        if self.cartography_bonus > 0:
            rows.append({"label": "  Discovery bonus", "value": fmt_credits(self.cartography_bonus), "rate": None})

        # FSS completion
        if self.systems_honked > 0:
            fully = self.systems_fully_scanned
            label = f"{self.systems_honked} honked"
            if fully > 0:
                label += f", {fully} fully scanned"
            rows.append({"label": "Systems (FSS)", "value": label, "rate": None})

        # Notable bodies
        if self.notable_bodies:
            rows.append({"label": "─── Notable bodies ───", "value": "", "rate": None})
            order = ["Earth-Like World", "Water World", "Ammonia World",
                     "Terraformable", "Neutron Star", "Black Hole"]
            for lbl in order:
                n = self.notable_bodies.get(lbl, 0)
                if n:
                    rows.append({"label": f"  {lbl}", "value": str(n), "rate": None})
            # Any unlisted notable types
            for lbl, n in self.notable_bodies.items():
                if lbl not in order and n > 0:
                    rows.append({"label": f"  {lbl}", "value": str(n), "rate": None})

        # Habitable zone
        if self.current_hz:
            rows.append({"label": "─── Habitable zone ───", "value": "", "rate": None})
            for (lbl, near, far) in self.current_hz:
                if near < 0.5:
                    near_str = f"{near:.2f} ls"
                else:
                    near_str = f"{near:.0f} ls"
                if far < 0.5:
                    far_str = f"{far:.2f} ls"
                else:
                    far_str = f"{far:.0f} ls"
                rows.append({
                    "label": f"  {lbl}",
                    "value": f"{near_str} – {far_str}",
                    "rate":  None,
                })

        # Nav route progress
        nav_info = self._nav_route_info()
        if nav_info:
            remaining, _ = nav_info
            route = getattr(self.core.state, "nav_route", [])
            pilot = getattr(self.core.state, "pilot_system", None)
            next_dest = None
            for wp in route:
                if wp.get("StarSystem") != pilot:
                    next_dest = wp.get("StarSystem")
                    break
            rows.append({"label": "─── Nav Route ───", "value": "", "rate": None})
            rows.append({
                "label": "  Remaining jumps",
                "value": str(remaining),
                "rate":  None,
            })
            if next_dest:
                rows.append({
                    "label": "  Next",
                    "value": next_dest,
                    "rate":  None,
                })

        return rows

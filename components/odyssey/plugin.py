"""
components/odyssey/plugin.py — Odyssey on-foot and surface session tracking.

Tracks meaningful Odyssey activities: planet surface deployments, SRV
deployments, settlement/engineer/guardian site approaches, taxi journeys,
on-foot material collection, and suit loadout used.

Event mapping:
  Disembark          — on-foot deployment (planet or station); suit type captured
  Embark             — back to ship; clears on-foot state
  LaunchSRV          — SRV deployment
  DockSRV            — SRV recalled
  SuitLoadout        — current suit name on Disembark
  ApproachSettlement — categorised as engineer / guardian / regular
  BookTaxi           — taxi booked (cost tracked)
  TakeTaxi           — taxi ride taken
  MaterialCollected  — raw / manufactured / encoded material collected on-foot

Tab title: Odyssey
"""

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.emit import fmt_credits


def _is_engineer(station_gov: str) -> bool:
    return "$government_engineer" in (station_gov or "").lower()


def _is_guardian(name: str) -> bool:
    return (name or "").startswith("$Ancient_")


def _suit_display(raw: str) -> str:
    """Return a clean suit display name from the internal suit name."""
    s = (raw or "").lower()
    if "dominator"   in s: return "Dominator"
    if "maverick"    in s: return "Maverick"
    if "exploration" in s: return "Artemis"
    return (raw or "").replace("_", " ").title()


class ActivityOdysseyPlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME        = "odyssey"
    PLUGIN_DISPLAY     = "Odyssey Activity"
    PLUGIN_VERSION     = "2.0.0"
    PLUGIN_DESCRIPTION = "Tracks on-foot deployments, SRV use, settlements, taxis, and materials."
    ACTIVITY_TAB_TITLE = "Odyssey"

    SUBSCRIBED_EVENTS = [
        "Disembark",
        "Embark",
        "LaunchSRV",
        "DockSRV",
        "SuitLoadout",
        "ApproachSettlement",
        "BookTaxi",
        "TakeTaxi",
        "MaterialCollected",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._reset_counters()

    def _reset_counters(self) -> None:
        # On-foot
        self.surface_deployments: int   = 0   # Disembark on planet, not taxi/SRV
        self.station_deployments: int   = 0   # Disembark at station
        self.current_suit:        str   = ""  # display name of current suit
        # SRV
        self.srv_deployments:     int   = 0
        # Settlements
        self.settlements_visited: int   = 0
        self.engineer_visits:     int   = 0
        self.guardian_sites:      int   = 0
        # Taxi
        self.taxi_journeys:       int   = 0
        self.taxi_cost:           int   = 0
        # Materials
        self.materials_collected: dict  = {}  # category → count
        self.session_start_time         = None

    def on_session_reset(self) -> None:
        self._reset_counters()

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")
        gq      = self.core.gui_queue

        match ev:

            case "SuitLoadout":
                self.current_suit = _suit_display(
                    event.get("SuitName_Localised") or event.get("SuitName", "")
                )

            case "Disembark":
                if event.get("Taxi") or event.get("SRV"):
                    return
                if self.session_start_time is None:
                    self.session_start_time = logtime
                if event.get("OnPlanet"):
                    self.surface_deployments += 1
                else:
                    self.station_deployments += 1
                if gq: gq.put(("stats_update", None))

            case "Embark":
                # Clear suit when back aboard ship (not SRV/taxi re-embark)
                if not event.get("SRV") and not event.get("Taxi"):
                    self.current_suit = ""

            case "LaunchSRV":
                if event.get("PlayerControlled", True):
                    if self.session_start_time is None:
                        self.session_start_time = logtime
                    self.srv_deployments += 1
                    if gq: gq.put(("stats_update", None))

            case "DockSRV":
                pass   # counted on launch; dock is just the close of the loop

            case "ApproachSettlement":
                name = event.get("Name", "")
                gov  = event.get("StationGovernment", "")
                if self.session_start_time is None:
                    self.session_start_time = logtime
                if _is_guardian(name):
                    self.guardian_sites += 1
                elif _is_engineer(gov):
                    self.engineer_visits += 1
                else:
                    self.settlements_visited += 1
                if gq: gq.put(("stats_update", None))

            case "BookTaxi":
                cost = int(event.get("Cost", 0))
                self.taxi_cost += cost

            case "TakeTaxi":
                if self.session_start_time is None:
                    self.session_start_time = logtime
                self.taxi_journeys += 1
                if gq: gq.put(("stats_update", None))

            case "MaterialCollected":
                cat   = event.get("Category", "Unknown").replace("$MICRORESOURCE_CATEGORY_", "").title()
                count = int(event.get("Count", 1))
                self.materials_collected[cat] = self.materials_collected.get(cat, 0) + count

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return (
            self.surface_deployments > 0
            or self.station_deployments > 0
            or self.srv_deployments > 0
            or self.settlements_visited > 0
            or self.engineer_visits > 0
            or self.guardian_sites > 0
            or self.taxi_journeys > 0
        )

    def get_summary_rows(self) -> list[dict]:
        rows = []
        if self.surface_deployments > 0:
            suit = f"  [{self.current_suit}]" if self.current_suit else ""
            rows.append({
                "label": "Surface deployments",
                "value": str(self.surface_deployments),
                "rate":  suit.strip() or None,
            })
        if self.srv_deployments > 0:
            rows.append({
                "label": "SRV deployments",
                "value": str(self.srv_deployments),
                "rate":  None,
            })
        if self.settlements_visited > 0:
            rows.append({
                "label": "Settlements",
                "value": str(self.settlements_visited),
                "rate":  None,
            })
        return rows

    def get_tab_rows(self) -> list[dict]:
        rows = self.get_summary_rows()
        if self.station_deployments > 0:
            rows.append({"label": "Station deployments", "value": str(self.station_deployments), "rate": None})
        if self.engineer_visits > 0:
            rows.append({"label": "Engineer visits",     "value": str(self.engineer_visits),     "rate": None})
        if self.guardian_sites > 0:
            rows.append({"label": "Guardian sites",      "value": str(self.guardian_sites),      "rate": None})
        if self.taxi_journeys > 0:
            cost_str = fmt_credits(self.taxi_cost) if self.taxi_cost > 0 else None
            rows.append({"label": "Taxi journeys", "value": str(self.taxi_journeys), "rate": cost_str})
        if self.materials_collected:
            rows.append({"label": "─── Materials ───", "value": "", "rate": None})
            for cat, count in sorted(self.materials_collected.items(), key=lambda x: -x[1]):
                rows.append({"label": f"  {cat}", "value": str(count), "rate": None})
        return rows

"""
components/income/plugin.py — Session income tracking.

Aggregates all realised credit income across activity types into a single
session total with a credits-per-hour rate. Complements activity-specific
plugins by providing a unified view of total session earnings.

Income sources:
  RedeemVoucher            — bounties, combat bonds, trade vouchers (face value)
  MissionCompleted         — mission reward
  SellExplorationData      — cartography
  MultiSellExplorationData — cartography (batch)
  SellOrganicData          — exobiology
  MarketSell               — commodity sale gross proceeds

CarrierBankTransfer is excluded — moving money between accounts is not income.

Tab title: Income
"""

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.emit import fmt_credits


class ActivityIncomePlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME         = "income"
    PLUGIN_DISPLAY      = "Income Activity"
    PLUGIN_VERSION      = "1.0.0"
    PLUGIN_DESCRIPTION  = "Tracks total session credit income and credits-per-hour rate."
    ACTIVITY_TAB_TITLE  = "Income"

    SUBSCRIBED_EVENTS = [
        "RedeemVoucher",
        "MissionCompleted",
        "SellExplorationData",
        "MultiSellExplorationData",
        "SellOrganicData",
        "MarketSell",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.total_income:    int  = 0
        self.by_source:       dict = {}   # source label → int
        self.session_start_time    = None

    def on_session_reset(self) -> None:
        self._reset_counters()

    def _add(self, logtime, amount: int, label: str) -> None:
        if amount <= 0:
            return
        if self.session_start_time is None:
            self.session_start_time = logtime
        self.total_income += amount
        self.by_source[label] = self.by_source.get(label, 0) + amount
        gq = self.core.gui_queue
        if gq:
            gq.put(("stats_update", None))

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")

        match ev:

            case "RedeemVoucher":
                vtype  = event.get("Type", "")
                amount = int(event.get("Amount", 0))
                pct    = float(event.get("BrokerPercentage", 0.0))
                # Amount is post-broker; recover face value
                face   = round(amount / (1.0 - pct / 100.0)) if pct else amount
                label  = {
                    "bounty":     "Bounties",
                    "CombatBond": "Combat bonds",
                    "trade":      "Trade vouchers",
                }.get(vtype, "Vouchers")
                self._add(logtime, face, label)

            case "MissionCompleted":
                self._add(logtime, int(event.get("Reward", 0)), "Missions")

            case "SellExplorationData" | "MultiSellExplorationData":
                self._add(logtime, int(event.get("TotalEarnings", 0)), "Cartography")

            case "SellOrganicData":
                total = sum(
                    int(item.get("Value", 0))
                    for item in event.get("BioData", [])
                )
                self._add(logtime, total, "Exobiology")

            case "MarketSell":
                self._add(logtime, int(event.get("TotalSale", 0)), "Trade")

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return self.total_income > 0

    def _cph(self) -> str | None:
        dur = self._duration_seconds()
        if dur < 60 or self.total_income <= 0:
            return None
        cph = self.total_income / (dur / 3600.0)
        return f"{fmt_credits(round(cph))}/hr"

    def get_summary_rows(self) -> list[dict]:
        if not self.total_income:
            return []
        return [{
            "label": "Session income",
            "value": fmt_credits(self.total_income),
            "rate":  self._cph(),
        }]

    def get_tab_rows(self) -> list[dict]:
        rows = self.get_summary_rows()
        if self.by_source:
            rows.append({"label": "─── By source ───", "value": "", "rate": None})
            for label, amount in sorted(
                self.by_source.items(), key=lambda x: -x[1]
            ):
                rows.append({
                    "label": f"  {label}",
                    "value": fmt_credits(amount),
                    "rate":  None,
                })
        return rows

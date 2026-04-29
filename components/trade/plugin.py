"""
components/trade/plugin.py — Trade session tracking.

Tracks market sales and purchases, separating mined cargo from
bought-and-resold commerce using MiningRefined records.

Registers with Session Stats as an activity provider.
Tab title: Trade
"""

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.emit import fmt_credits, rate_per_hour


class ActivityTradePlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME         = "trade"
    PLUGIN_DISPLAY      = "Trade Activity"
    PLUGIN_VERSION      = "1.0.0"
    PLUGIN_DESCRIPTION  = "Tracks trade profit, differentiating mined cargo from commerce."
    ACTIVITY_TAB_TITLE  = "Trade"

    SUBSCRIBED_EVENTS = [
        "MarketSell",
        "MarketBuy",
        "MiningRefined",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.trade_profit:      int  = 0   # profit from bought-and-resold goods
        self.mined_income:      int  = 0   # proceeds from selling mined cargo
        self.total_sold_units:  int  = 0
        self.commodity_profit:  dict = {}  # name → profit int
        self.commodity_mined:   set  = set()  # names of commodities we refined this session
        self.session_start_time = None

    def on_session_reset(self) -> None:
        self._reset_counters()

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")

        match ev:

            case "MiningRefined":
                # Record which commodity types were mined so we can
                # categorise subsequent MarketSell events correctly.
                commodity = (
                    event.get("Type_Localised") or event.get("Type", "Unknown")
                ).strip()
                self.commodity_mined.add(commodity.lower())

            case "MarketSell":
                if self.session_start_time is None:
                    self.session_start_time = logtime
                commodity = (
                    event.get("Type_Localised") or event.get("Type", "Unknown")
                ).strip()
                count     = event.get("Count", 1)
                sell_price = event.get("SellPrice", 0)
                avg_cost   = event.get("AvgPricePaid", 0)
                profit     = (sell_price - avg_cost) * count
                stolen_tax = event.get("StolenGoods", False)

                # Determine if this is mined cargo or traded cargo.
                # Heuristic: if we refined this commodity type this session,
                # and avg_cost == 0 (mined = no purchase cost), classify as mined.
                is_mined = (
                    commodity.lower() in self.commodity_mined and avg_cost == 0
                )

                if is_mined:
                    self.mined_income += sell_price * count
                else:
                    self.trade_profit += profit
                    name = commodity
                    self.commodity_profit[name] = (
                        self.commodity_profit.get(name, 0) + profit
                    )

                self.total_sold_units += count
                gq = self.core.gui_queue
                if gq: gq.put(("stats_update", None))

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return self.trade_profit != 0 or self.mined_income > 0

    def get_summary_rows(self) -> list[dict]:
        dur  = self._duration_seconds()
        rows = []
        if self.trade_profit != 0:
            rate = (f"{fmt_credits(rate_per_hour(dur / self.trade_profit, 2))} /hr"
                    if dur and self.trade_profit > 0 else "—")
            rows.append({"label": "Trade profit",
                         "value": fmt_credits(self.trade_profit),
                         "rate":  rate})
        if self.mined_income > 0:
            rows.append({"label": "Mining income",
                         "value": fmt_credits(self.mined_income),
                         "rate":  None})
        return rows

    def get_tab_rows(self) -> list[dict]:
        rows = self.get_summary_rows()
        if self.commodity_profit:
            rows.append({"label": "─── By commodity ───", "value": "", "rate": None})
            for name, profit in sorted(
                self.commodity_profit.items(), key=lambda x: -x[1]
            ):
                rows.append({
                    "label": f"  {name}",
                    "value": fmt_credits(profit),
                    "rate":  None,
                })
        return rows

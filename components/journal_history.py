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
        # Accurate FSS / DSS counts.  The in-game Statistics fields
        # Planets_Scanned_To_Level_2 / _Level_3 are unreliable — they
        # frequently report identical values and don't match what the
        # commander has actually done.  Counting unique bodies from the
        # journal's Scan (FSS detail scan) and SAAScanComplete (DSS map)
        # events is the trustworthy source.
        fss_planet_bodies: set = set()   # unique (system, body) FSS-detailed
        dss_mapped_bodies: set = set()   # unique (system, body) DSS-mapped
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
        exobio_by_genus:    dict[str, int] = {}   # genus → sample count
        exobio_by_species:  dict[str, int] = {}   # localised name → count
        exobio_sample_count = 0
        # Credit accounting from SellOrganicData — the BioData payload carries
        # a per-entry Value (base) and Bonus (first-logged / first-discovery
        # premium).  Tracked separately so the Exobiology tab can show a
        # genus-level credit breakdown plus the first-discovery bonus total.
        exobio_value_by_genus: dict[str, int] = {}   # genus → credits sold
        exobio_first_bonus     = 0                   # Σ first-discovery bonuses

        # PowerPlay — scan all journals, sum all merits by system
        # Reset counters on PowerplayLeave/Defect so we only count current pledge
        pp_system_merits: dict[str, int] = {}
        pp_total_merits   = 0
        pp_active         = False   # True once we see a Powerplay/Join event
        pp_current_system = ""      # system at time of PowerplayMerits event
        # Merits-by-activity: the journal's PowerplayMerits event records
        # MeritsGained but not *what* earned them.  We attribute each grant
        # to whichever activity dominated the recently-preceding events —
        # a heuristic, but a defensible one (the activity that produced the
        # merits is almost always the last thing the commander did).
        pp_merits_by_activity: dict[str, int] = {
            "Combat": 0, "Trade": 0, "Exploration": 0,
            "Missions": 0, "Other": 0,
        }
        # Sliding window of recent activity classifications (most recent last).
        pp_recent_activity: list[str] = []

        # Fleet carrier — most recent CarrierStats snapshot.  Authoritative
        # for capacity / current jump range / fuel, and lets the Navigation
        # block auto-fill the carrier route form.
        latest_carrier_stats: dict = {}
        latest_carrier_ts    = ""

        # Combat / income
        bounties_earned   = 0
        bounties_redeemed = 0
        bonds_earned      = 0
        bonds_redeemed    = 0
        kill_count        = 0
        income_missions   = 0
        income_trade      = 0

        # ── Comprehensive money-flow tracking ─────────────────────────────────
        # The in-game Statistics fields are unreliable for several income/
        # spending categories (Trading.Goods_Sold is stuck at 0 for many
        # commanders; Bank_Account fields don't capture carrier-bank flows
        # at all).  Counting from journal events is the only accurate path.
        #
        # finance_in[k]  / finance_out[k]  = lifetime credits in/out for
        # category k.  Categories are kept human-readable because they're
        # surfaced verbatim in the Earnings & Spending tab.
        finance_in:  dict[str, int] = {}
        finance_out: dict[str, int] = {}
        def _fin_in(cat: str, v) -> None:
            try: vi = int(v) if v is not None else 0
            except (TypeError, ValueError): vi = 0
            if vi:
                finance_in[cat] = finance_in.get(cat, 0) + vi
        def _fin_out(cat: str, v) -> None:
            try: vi = int(v) if v is not None else 0
            except (TypeError, ValueError): vi = 0
            if vi:
                finance_out[cat] = finance_out.get(cat, 0) + vi

        # Carrier bank — transfers between the commander and their carrier
        # are neutral for net worth (money moves between pockets) but the
        # user needs them visible to understand where their "missing"
        # credits went.  Plus the latest CarrierFinance snapshot gives the
        # current carrier balance / reserve / available.
        cbank_deposits    = 0
        cbank_withdrawals = 0
        latest_cfinance: dict = {}
        latest_cfinance_ts   = ""

        # Trade accuracy — Statistics.Trading.Goods_Sold is unreliable, so
        # count tonnes / revenue / profit from MarketSell events directly.
        market_sell_count   = 0
        market_sell_revenue = 0
        market_sell_profit  = 0

        # Latest LoadGame.Credits — the commander's personal liquid wallet
        # (does NOT include carrier bank).  Useful for net-worth breakdown.
        latest_credits      = 0
        latest_credits_ts   = ""

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

                # ── Activity classification for PowerPlay attribution ─────
                # Maintain a short rolling window of "what was the commander
                # doing".  Each PowerplayMerits grant is later attributed to
                # the dominant activity in this window.
                _act = None
                if name in ("Bounty", "FactionKillBond", "ShipTargeted",
                            "CommitCrime", "Died", "PVPKill", "Interdiction"):
                    _act = "Combat"
                elif name in ("MarketSell", "MarketBuy", "PowerplayCollect",
                              "PowerplayDeliver", "BuyTradeData", "SellDrones"):
                    _act = "Trade"
                elif name in ("Scan", "SellExplorationData",
                              "MultiSellExplorationData", "SAAScanComplete",
                              "FSSDiscoveryScan", "FSSAllBodiesFound",
                              "ScanOrganic", "SellOrganicData"):
                    _act = "Exploration"
                elif name in ("MissionCompleted", "MissionAccepted",
                              "MissionRedirected"):
                    _act = "Missions"
                elif name in ("DatalinkScan", "DataScanned", "USSDrop"):
                    _act = "Other"
                if _act is not None:
                    pp_recent_activity.append(_act)
                    if len(pp_recent_activity) > 12:
                        pp_recent_activity.pop(0)

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
                        # An FSS detail scan of a planet body — record the
                        # unique (system, body) so the Explore tab can show
                        # an accurate FSS-scanned count.
                        if sys_addr is not None and body_id is not None:
                            fss_planet_bodies.add(bk)
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
                    # Every SAAScanComplete is one DSS map completion.
                    sys_addr = ev.get("SystemAddress")
                    body_id  = ev.get("BodyID")
                    if sys_addr is not None and body_id is not None:
                        dss_mapped_bodies.add((sys_addr, body_id))
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
                    _fin_in("Exploration: cartographic data", total)

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
                        base  = int(item.get("Value", 0))
                        bonus = int(item.get("Bonus", 0))
                        exobio_sold_total  += base + bonus
                        exobio_first_bonus += bonus
                        _fin_in("Exobiology: organic data", base + bonus)
                        # Genus label: prefer the localised payload, else
                        # derive from the species key.
                        genus = (item.get("Genus_Localised")
                                 or _genus_from_species(item.get("Species", ""))
                                 or "Unknown")
                        exobio_value_by_genus[genus] = (
                            exobio_value_by_genus.get(genus, 0) + base + bonus
                        )

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
                        # Attribute to the activity that dominated the recent
                        # window.  Ties and empty windows fall to "Other".
                        if pp_recent_activity:
                            counts: dict[str, int] = {}
                            for a in pp_recent_activity:
                                counts[a] = counts.get(a, 0) + 1
                            dominant = max(counts, key=counts.get)
                        else:
                            dominant = "Other"
                        pp_merits_by_activity[dominant] = (
                            pp_merits_by_activity.get(dominant, 0) + gained
                        )

                # ── Combat / Income ───────────────────────────────────────
                elif name == "Bounty":
                    reward = ev.get("TotalReward", 0) or ev.get("Reward", 0)
                    bounties_earned += reward
                    kill_count      += 1
                    _fin_in("Combat: bounty vouchers (issued)", reward)

                elif name == "RedeemVoucher":
                    vtype  = ev.get("Type", "")
                    amount = ev.get("Amount", 0)
                    if vtype == "bounty":
                        bounties_redeemed += amount
                        _fin_in("Combat: bounty vouchers (redeemed)", amount)
                    elif vtype == "CombatBond":
                        bonds_redeemed += amount
                        _fin_in("Combat: combat bonds (redeemed)", amount)
                    elif vtype == "settlement":
                        _fin_in("Combat: settlement vouchers", amount)
                    elif vtype == "scannable":
                        _fin_in("Combat: scan data vouchers", amount)
                    elif vtype == "trade":
                        _fin_in("Trade: trade vouchers", amount)
                    else:
                        _fin_in(f"Vouchers redeemed ({vtype or 'other'})",
                                amount)

                elif name == "FactionKillBond":
                    bonds_earned += ev.get("Reward", 0)
                    _fin_in("Combat: combat bonds (issued)", ev.get("Reward"))

                elif name == "MissionCompleted":
                    rwd = ev.get("Reward", 0)
                    income_missions += rwd
                    _fin_in("Missions: rewards", rwd)
                    # Donation missions also carry a Donation field (the
                    # credits the commander handed over).  Journal ships
                    # it as a string — coerce safely.
                    don = ev.get("Donation")
                    if don:
                        _fin_out("Missions: donations", don)

                elif name == "MarketSell":
                    ts_amt = ev.get("TotalSale", 0)
                    cnt    = ev.get("Count", 0)
                    avg    = ev.get("AvgPricePaid", 0)
                    income_trade += ts_amt
                    market_sell_count   += cnt
                    market_sell_revenue += ts_amt
                    market_sell_profit  += ts_amt - cnt * avg
                    _fin_in("Trade: market sells (revenue)", ts_amt)

                elif name == "MarketBuy":
                    _fin_out("Trade: market buys",          ev.get("TotalCost"))

                elif name == "SearchAndRescue":
                    _fin_in("Search & rescue: items handed in",
                            ev.get("Reward"))

                elif name == "SellMicroResources":
                    _fin_in("Odyssey: micro-resources sold",
                            ev.get("Price"))

                elif name == "CommunityGoalReward":
                    _fin_in("Community goal rewards", ev.get("Reward"))

                # ── Sales (modules / ships / drones) — INCOMING ───────────
                elif name == "ShipyardSell":
                    _fin_in("Ships sold", ev.get("ShipPrice"))
                elif name == "ModuleSell":
                    _fin_in("Modules sold (at station)", ev.get("SellPrice"))
                elif name == "ModuleSellRemote":
                    _fin_in("Modules sold (remote)", ev.get("SellPrice"))
                elif name == "SellDrones":
                    _fin_in("Limpets sold", ev.get("TotalSale"))

                # ── Purchases — OUTGOING ───────────────────────────────────
                elif name == "ShipyardBuy":
                    _fin_out("Ships bought", ev.get("ShipPrice"))
                elif name == "ShipyardTransfer":
                    _fin_out("Ship transfer fees", ev.get("TransferPrice"))
                elif name == "ModuleBuy":
                    _fin_out("Outfitting: modules bought",
                             ev.get("BuyPrice"))
                elif name == "ModuleBuyAndStore":
                    _fin_out("Outfitting: modules bought (stored)",
                             ev.get("BuyPrice"))
                elif name == "BuyAmmo":
                    _fin_out("Operations: ammo", ev.get("Cost"))
                elif name == "RefuelAll":
                    _fin_out("Operations: fuel", ev.get("Cost"))
                elif name == "Repair":
                    _fin_out("Operations: repairs", ev.get("Cost"))
                elif name == "RepairAll":
                    _fin_out("Operations: repairs", ev.get("Cost"))
                elif name == "RestockVehicle":
                    _fin_out("Operations: SRV restock", ev.get("Cost"))
                elif name == "BuyDrones":
                    _fin_out("Operations: limpets bought",
                             ev.get("TotalCost"))
                elif name == "BuySuit":
                    _fin_out("Odyssey: suits", ev.get("Price"))
                elif name == "BuyWeapon":
                    _fin_out("Odyssey: weapons", ev.get("Price"))

                # ── Fines / rebuys — OUTGOING ──────────────────────────────
                elif name == "PayBounties":
                    _fin_out("Fines: bounty fines",      ev.get("Amount"))
                elif name == "PayFines":
                    _fin_out("Fines: fines paid",        ev.get("Amount"))
                elif name == "PayLegacyFines":
                    _fin_out("Fines: legacy fines",      ev.get("Amount"))
                elif name == "Resurrect":
                    _fin_out("Insurance rebuys",         ev.get("Cost"))
                elif name == "Donate":
                    _fin_out("Donations",                ev.get("Amount"))

                # ── Carrier-related — purchase + ongoing costs ─────────────
                elif name == "CarrierBuy":
                    _fin_out("Carrier: purchase", ev.get("Price"))
                elif name == "NpcCrewPaidWage":
                    _fin_out("Carrier: NPC crew wages", ev.get("Amount"))
                elif name == "CarrierTradeOrder":
                    # A buy/sell order placed on the carrier market.  The
                    # cost only materialises if the order is filled —
                    # surface it as a NOTE rather than a hard "Out"
                    # category, because not all orders fill.
                    po = ev.get("PurchaseOrder")
                    pr = ev.get("Price")
                    if po and pr:
                        _fin_out("Carrier: pending buy-order commitments",
                                 int(po) * int(pr))
                elif name == "CarrierDepositFuel":
                    # When commander buys tritium from a market to refuel
                    # the carrier — the tritium itself was paid for via
                    # the preceding MarketBuy event (already counted).
                    # CarrierDepositFuel.Cost (if present) is any service
                    # surcharge, normally 0.
                    _fin_out("Carrier: tritium service fees",
                             ev.get("Cost"))

                # ── Carrier bank transfers — neutral but tracked ───────────
                elif name == "CarrierBankTransfer":
                    cbank_deposits    += int(ev.get("Deposit",  0) or 0)
                    cbank_withdrawals += int(ev.get("Withdraw", 0) or 0)

                elif name == "CarrierFinance":
                    ts = ev.get("timestamp", "")
                    if ts > latest_cfinance_ts:
                        latest_cfinance_ts = ts
                        latest_cfinance    = ev

                # ── Liquid credits snapshot (LoadGame) ─────────────────────
                elif name == "LoadGame":
                    ts = ev.get("timestamp", "")
                    if ts > latest_credits_ts:
                        latest_credits_ts = ts
                        latest_credits    = int(ev.get("Credits", 0) or 0)

                elif name == "Statistics":
                    ts = ev.get("timestamp", "")
                    if ts > latest_statistics_ts:
                        latest_statistics_ts = ts
                        latest_statistics = ev

                elif name == "CarrierStats":
                    ts = ev.get("timestamp", "")
                    if ts > latest_carrier_ts:
                        latest_carrier_ts    = ts
                        latest_carrier_stats = ev

        # ── Publish results ───────────────────────────────────────────────────
        self.results = {
            "career": {
                "bodies_scanned":    bodies_scanned,
                "stars_scanned":     stars_scanned,
                "first_discoveries": first_discoveries,
                "first_mapped":      first_mapped,
                # Accurate journal-derived FSS/DSS counts (the Statistics
                # Planets_Scanned_To_Level_2/3 fields are unreliable).
                "fss_scanned":       len(fss_planet_bodies),
                "dss_mapped":        len(dss_mapped_bodies),
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
                "first_bonus":  exobio_first_bonus,
                "by_genus":     dict(sorted(exobio_by_genus.items(),
                                            key=lambda x: -x[1])),
                "by_genus_value": dict(sorted(exobio_value_by_genus.items(),
                                              key=lambda x: -x[1])),
                "by_species":   dict(sorted(exobio_by_species.items(),
                                            key=lambda x: -x[1])),
            },
            "powerplay": {
                "total_merits":   pp_total_merits,
                "system_merits":  dict(sorted(pp_system_merits.items(),
                                              key=lambda x: -x[1])),
                "by_activity":    dict(sorted(pp_merits_by_activity.items(),
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
            # Comprehensive money-flow ledger derived from journal events.
            # The "in" / "out" dicts each map a human-readable category
            # label to lifetime credits.  Sorted by amount so the Earnings
            # & Spending tab renders them in priority order.  market_sell
            # carries the accurate goods-sold trio (Statistics.Trading's
            # Goods_Sold field is unreliable).
            "finance": {
                "in":  dict(sorted(finance_in.items(),  key=lambda x: -x[1])),
                "out": dict(sorted(finance_out.items(), key=lambda x: -x[1])),
                "market_sell": {
                    "count":   market_sell_count,
                    "revenue": market_sell_revenue,
                    "profit":  market_sell_profit,
                },
                # Combat voucher reconciliation — issued vs. redeemed often
                # differ because vouchers can sit unclaimed for ages.
                "vouchers": {
                    "bounty_issued":   bounties_earned,
                    "bounty_redeemed": bounties_redeemed,
                    "bonds_issued":    bonds_earned,
                    "bonds_redeemed":  bonds_redeemed,
                },
                # Liquid credits = the commander's personal wallet from
                # the most recent LoadGame.  Distinct from carrier bank.
                "liquid_credits": latest_credits,
            },
            "carrier": {
                # Most recent CarrierStats snapshot, or {} if the commander
                # has no fleet carrier.  SpaceUsage.TotalCapacity is the
                # figure Spansh wants for carrier route planning.
                "stats":         latest_carrier_stats,
                "callsign":      latest_carrier_stats.get("Callsign", ""),
                "name":          latest_carrier_stats.get("Name", ""),
                "type":          latest_carrier_stats.get("CarrierType", ""),
                "fuel_level":    latest_carrier_stats.get("FuelLevel", 0),
                "jump_range":    latest_carrier_stats.get("JumpRangeCurr", 0),
                "total_capacity": (latest_carrier_stats.get("SpaceUsage", {})
                                   .get("TotalCapacity", 0)),
                # Carrier bank: latest balance snapshot + lifetime flow.
                # Balance is from CarrierFinance (the authoritative event
                # for current values); deposits/withdrawals are from
                # CarrierBankTransfer over the journal lifetime.
                "bank_balance":   latest_cfinance.get("CarrierBalance", 0),
                "bank_reserve":   latest_cfinance.get("ReserveBalance", 0),
                "bank_available": latest_cfinance.get("AvailableBalance", 0),
                "bank_deposits":     cbank_deposits,
                "bank_withdrawals":  cbank_withdrawals,
            },
            "statistics": latest_statistics,
        }

        self.scan_done.set()

        # Notify GUI that career data is available
        gq = self.core.gui_queue
        if gq:
            gq.put(("career_update", None))

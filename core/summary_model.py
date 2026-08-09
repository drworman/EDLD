"""
core/summary_model.py — Shared summary model for the Session window and the
Career block's Summary tab.

Purpose
-------
Two windows present the same picture of the commander's activity at two
different scopes:

    Session window            → the current session (reset with Ctrl+R)
    Career block, Summary tab → the whole career (lifetime)

They are meant to show *the same things*, so the only honest way to build
them is from one model.  This module owns that model: it emits an ordered
list of sections with identical titles and identical meaning for both
scopes, and the two Textual blocks are thin renderers over the result.
Adding a row to a section therefore lands in both windows at once, and the
two views cannot drift apart as either side is maintained.

This module is deliberately UI-agnostic — it imports nothing from ``tui``
and returns plain dicts.  Any front end can render it.

Data shape
----------
``session_sections(core)`` and ``career_sections(core)`` both return::

    [
      {"title": "Combat",
       "rows": [{"label": str, "value": str, "rate": str|None, "kind": str},
                ...]},
      ...
    ]

``kind`` is ``"kv"`` for an ordinary key/value row or ``"sub"`` for a
sub-heading inside a section (activity providers emit these as
``"─── Notable bodies ───"`` divider rows; they are normalised here so the
renderer never has to know about the dash convention).

Sections with no data are omitted entirely, so an empty section never
occupies a row.  A section that only one scope can populate — Fleet
carrier has no session-scoped counterpart, for instance — simply does not
appear on the other side.

Sources
-------
Session scope reads the registered ActivityProviderMixin components via
``core.session_providers`` and calls ``get_tab_rows()``, which is
materially richer than ``get_summary_rows()``: notable bodies and
habitable zones from Exploration, the in-progress scan and clonal distance
from Exobiology, per-commodity profit from Trade, limpet efficiency and
per-commodity yield from Mining, per-system merits from PowerPlay.

Career scope reads the ``journal_history`` component's lifetime scan
results plus the most recent in-game ``Statistics`` event, and live wealth
figures from state (maintained by the Assets component from CAPI, LoadGame
and CarrierFinance — fresher than a one-shot journal scan).

Journal-derived figures are preferred over Statistics wherever the two
disagree: Statistics fields such as ``Trading.Goods_Sold`` and
``Exploration.Planets_Scanned_To_Level_2`` sit at zero or stale for many
commanders, while journal events are authoritative.
"""

from __future__ import annotations


# ── Section order ─────────────────────────────────────────────────────────────
# Both scopes emit sections in this order.  Keeping one tuple as the single
# source of ordering is what makes the two windows read identically.

SECTION_ORDER = (
    "Overview",
    "Combat",
    "Exploration",
    "Exobiology",
    "Mining",
    "Trade",
    "Missions",
    "On foot",
    "PowerPlay",
    "Fleet carrier",
    "Credits",
)

# Activity provider tab title → section title.  The providers were named
# before this model existed; this table maps their vocabulary onto ours so
# the session scope lands in the same sections as the career scope.
PROVIDER_SECTION = {
    "Combat":      "Combat",
    "Exploration": "Exploration",
    "Exobiology":  "Exobiology",
    "Mining":      "Mining",
    "Trade":       "Trade",
    "Missions":    "Missions",
    "Odyssey":     "On foot",
    "PowerPlay":   "PowerPlay",
    "Income":      "Credits",
}


# ── Formatting ────────────────────────────────────────────────────────────────
# Local copies rather than imports from tui.block_base: core must not depend
# on the UI layer.  Output matches the Career block's existing tabs so the
# expanded Summary tab reads consistently against them.

def _credits(n) -> str:
    if not n:
        return "—"
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B cr"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M cr"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K cr"
    return f"{v} cr"


def _num(n) -> str:
    if not n:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _dist(n) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M ly"
    if v >= 1_000:
        return f"{v:,.0f} ly"
    return f"{v:.2f} ly"


def _hours(seconds) -> str:
    """Format a large playtime figure in hours (Statistics.Time_Played)."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if s <= 0:
        return "—"
    return f"{s / 3600:,.0f} h"


def _duration(seconds) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "—"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02}:{sec:02}"
    return f"{m}:{sec:02}"


# ── Row helpers ───────────────────────────────────────────────────────────────

def _since(iso_ts) -> str | None:
    """Render how long ago an ISO timestamp was, e.g. "32d ago".

    Used for the PowerPlay pledge date, where the useful question is "how
    long have I been with this power", not the calendar date.
    """
    if not iso_ts:
        return None
    try:
        from datetime import datetime, timezone
        when = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - when).days
    except Exception:
        return None
    if days < 0:
        return None
    if days == 0:
        return "today"
    if days == 1:
        return "1d ago"
    return f"{days}d ago"


def _row(label: str, value: str, rate: str | None = None) -> dict:
    return {"label": label, "value": value, "rate": rate, "kind": "kv"}


def _sub(label: str) -> dict:
    return {"label": label, "value": "", "rate": None, "kind": "sub"}


def _clean_sub(label: str) -> str:
    """Turn a provider divider label into a plain sub-heading.

    Providers emit dividers as ``"─── Notable bodies ───"``.  Strip the box
    drawing so the renderer can style sub-headings however it likes.
    """
    return label.strip().strip("─").strip() or "—"


def _live(rows: list) -> bool:
    """True when a section has at least one real key/value row."""
    return any(r["kind"] == "kv" for r in rows)


def _pack(sections: dict) -> list[dict]:
    """Emit sections in SECTION_ORDER, dropping any that carry no data."""
    out: list[dict] = []
    for title in SECTION_ORDER:
        rows = sections.get(title) or []
        if _live(rows):
            out.append({"title": title, "rows": rows})
    return out


# ── Session scope ─────────────────────────────────────────────────────────────

def session_sections(core) -> list[dict]:
    """Build the current-session view.

    Every registered activity provider contributes its full tab rows to the
    section its ACTIVITY_TAB_TITLE maps to, so the Session window shows
    everything the per-activity views would — not the condensed summary
    rows the Career block used to inline.
    """
    sections: dict[str, list] = {t: [] for t in SECTION_ORDER}

    plugin = core._plugins.get("session_stats")
    dur_s  = 0.0
    if plugin is not None:
        try:
            dur_s = plugin.session_duration_seconds() or 0.0
        except Exception:
            dur_s = 0.0

    # ── Overview — duration and the headline credit figure ────────────────
    overview: list = []
    if dur_s > 0:
        overview.append(_row("Duration", _duration(dur_s)))

    income = core._plugins.get("income")
    total_income = 0
    if income is not None:
        total_income = getattr(income, "total_income", 0) or 0
    if total_income:
        overview.append(_row("Income", _credits(total_income)))
        if dur_s >= 60:
            cph = total_income / (dur_s / 3600.0)
            overview.append(_row("Income rate", f"{_credits(round(cph))}/hr"))

    state = getattr(core, "state", None)
    if state is not None:
        ship = (getattr(state, "ship_name", None)
                or (getattr(state, "assets_current_ship", None) or {}).get("type_display"))
        if ship:
            overview.append(_row("Ship", str(ship)))
    sections["Overview"] = overview

    # ── Per-activity sections ─────────────────────────────────────────────
    for p in getattr(core, "session_providers", []):
        title = getattr(p, "ACTIVITY_TAB_TITLE", "")
        target = PROVIDER_SECTION.get(title)
        if target is None:
            continue
        try:
            if not p.has_activity():
                continue
            raw = p.get_tab_rows()
        except Exception:
            continue
        rows: list = []
        for r in raw or []:
            label = (r.get("label") or "").strip()
            value = r.get("value") or ""
            rate  = r.get("rate")
            if not label and not value:
                continue
            if label.startswith("─"):
                rows.append(_sub(_clean_sub(label)))
                continue
            rows.append(_row(label, value or "—", rate))
        if _live(rows):
            sections[target].extend(rows)

    return _pack(sections)


# ── Career scope ──────────────────────────────────────────────────────────────

def career_sections(core) -> list[dict]:
    """Build the lifetime view.

    Returns an empty list when the journal_history lifetime scan has not
    finished, so the caller can show a scan-in-progress placeholder.
    """
    hist = core._plugins.get("journal_history")
    if hist is None or not hist.scan_done.is_set():
        return []

    state = getattr(core, "state", None)
    r     = hist.results

    stats   = r.get("statistics", {}) or {}
    bank    = stats.get("Bank_Account", {}) or {}
    expl_s  = stats.get("Exploration",  {}) or {}
    exo_s   = stats.get("Exobiology",   {}) or {}
    cmb_s   = stats.get("Combat",       {}) or {}
    mine_s  = stats.get("Mining",       {}) or {}
    trd_s   = stats.get("Trading",      {}) or {}
    smg_s   = stats.get("Smuggling",    {}) or {}
    sar_s   = stats.get("Search_And_Rescue", {}) or {}
    crew_s  = stats.get("Crew",         {}) or {}
    pass_s  = stats.get("Passengers",   {}) or {}
    fc_s    = stats.get("FLEETCARRIER", {}) or {}

    career  = r.get("career",      {}) or {}
    combat  = r.get("combat",      {}) or {}
    carto   = r.get("cartography", {}) or {}
    exobio  = r.get("exobiology",  {}) or {}
    finance = r.get("finance",     {}) or {}
    carrier = r.get("carrier",     {}) or {}
    pp      = r.get("powerplay",   {}) or {}

    sections: dict[str, list] = {t: [] for t in SECTION_ORDER}

    # ── Overview — live wealth breakdown + career scale ───────────────────
    rows: list = []
    net_worth, liquid, cbank = _wealth(state, finance, carrier, bank)
    if net_worth:
        rows.append(_row("Net worth", _credits(net_worth)))
    if liquid:
        rows.append(_row("  Liquid credits", _credits(liquid)))
    if cbank:
        rows.append(_row("  Carrier bank", _credits(cbank)))
    if bank.get("Owned_Ship_Count"):
        rows.append(_row("Ships owned", _num(bank.get("Owned_Ship_Count"))))
    if expl_s.get("Time_Played"):
        rows.append(_row("Time played", _hours(expl_s.get("Time_Played"))))
    if expl_s.get("Greatest_Distance_From_Start"):
        rows.append(_row("Furthest from start",
                         _dist(expl_s.get("Greatest_Distance_From_Start"))))
    sections["Overview"] = rows

    # ── Combat ────────────────────────────────────────────────────────────
    rows = []
    kills = cmb_s.get("Bounties_Claimed", 0) or combat.get("kill_count", 0)
    if kills:
        rows.append(_row("Kills", _num(kills)))
    bounty = cmb_s.get("Bounty_Hunting_Profit") or combat.get("bounties_earned")
    if bounty:
        rows.append(_row("Bounties earned", _credits(bounty)))
    bonds = cmb_s.get("Combat_Bond_Profits") or combat.get("bonds_earned")
    if bonds:
        rows.append(_row("Combat bonds", _credits(bonds)))
    if cmb_s.get("Assassinations"):
        rows.append(_row("Assassinations", _num(cmb_s.get("Assassinations"))))
    if cmb_s.get("Highest_Single_Reward"):
        rows.append(_row("Highest single reward",
                         _credits(cmb_s.get("Highest_Single_Reward"))))
    if cmb_s.get("ConflictZone_Total"):
        wins = cmb_s.get("ConflictZone_Total_Wins", 0)
        rows.append(_row("Conflict zones",
                         _num(cmb_s.get("ConflictZone_Total")),
                         f"{wins:,} won" if wins else None))
    if bank.get("Insurance_Claims"):
        rows.append(_row("Deaths", _num(bank.get("Insurance_Claims"))))
    if bank.get("Spent_On_Insurance"):
        rows.append(_row("Rebuy costs", _credits(bank.get("Spent_On_Insurance"))))

    # Unredeemed vouchers — these often sit unclaimed for a long time and
    # are the one combat figure worth acting on.
    vouchers = finance.get("vouchers", {}) or {}
    pend_b = max((vouchers.get("bounty_issued", 0)
                  - vouchers.get("bounty_redeemed", 0)), 0)
    pend_k = max((vouchers.get("bonds_issued", 0)
                  - vouchers.get("bonds_redeemed", 0)), 0)
    if pend_b:
        rows.append(_row("Bounties unredeemed", _credits(pend_b)))
    if pend_k:
        rows.append(_row("Bonds unredeemed", _credits(pend_k)))
    sections["Combat"] = rows

    # ── Exploration ───────────────────────────────────────────────────────
    # Journal-derived FSS/DSS counts win: the Statistics
    # Planets_Scanned_To_Level_2/3 fields are unreliable.
    fss = career.get("fss_scanned") or expl_s.get("Planets_Scanned_To_Level_2")
    dss = career.get("dss_mapped")  or expl_s.get("Planets_Scanned_To_Level_3")
    rows = []
    if expl_s.get("Systems_Visited"):
        rows.append(_row("Systems visited", _num(expl_s.get("Systems_Visited"))))
    if expl_s.get("Total_Hyperspace_Jumps"):
        rows.append(_row("Hyperspace jumps",
                         _num(expl_s.get("Total_Hyperspace_Jumps")),
                         _dist(expl_s.get("Total_Hyperspace_Distance"))))
    if fss:
        rows.append(_row("Planets FSS-scanned", _num(fss)))
    if dss:
        rows.append(_row("Planets DSS-mapped", _num(dss)))
    if career.get("first_discoveries"):
        rows.append(_row("First discoveries", _num(career.get("first_discoveries"))))
    if career.get("first_mapped"):
        rows.append(_row("First mapped", _num(career.get("first_mapped"))))
    if expl_s.get("Efficient_Scans"):
        rows.append(_row("Efficient scans", _num(expl_s.get("Efficient_Scans"))))
    carto_total = expl_s.get("Exploration_Profits") or carto.get("sold_total")
    if carto_total:
        rows.append(_row("Cartography sold", _credits(carto_total)))
    if expl_s.get("Highest_Payout"):
        rows.append(_row("Highest payout", _credits(expl_s.get("Highest_Payout"))))

    notable = [
        ("elw",           "Earth-likes"),
        ("water_world",   "Water worlds"),
        ("ammonia_world", "Ammonia worlds"),
        ("terraformable", "Terraformables"),
        ("neutron_star",  "Neutron stars"),
        ("black_hole",    "Black holes"),
    ]
    found = [(lbl, career.get(key)) for key, lbl in notable if career.get(key)]
    if found:
        rows.append(_sub("Notable bodies"))
        for lbl, n in found:
            rows.append(_row(f"  {lbl}", _num(n)))
    sections["Exploration"] = rows

    # ── Exobiology ────────────────────────────────────────────────────────
    rows = []
    samples = exo_s.get("Organic_Data") or exobio.get("sample_count")
    if samples:
        rows.append(_row("Samples analysed", _num(samples)))
    if exo_s.get("Organic_Species_Encountered"):
        rows.append(_row("Species encountered",
                         _num(exo_s.get("Organic_Species_Encountered"))))
    if exo_s.get("Organic_Genus_Encountered"):
        rows.append(_row("Genera encountered",
                         _num(exo_s.get("Organic_Genus_Encountered"))))
    if exo_s.get("Organic_Systems"):
        rows.append(_row("Systems", _num(exo_s.get("Organic_Systems")),
                         (f"{exo_s.get('Organic_Planets'):,} planets"
                          if exo_s.get("Organic_Planets") else None)))
    sold = exo_s.get("Organic_Data_Profits") or exobio.get("sold_total")
    if sold:
        rows.append(_row("Total sold", _credits(sold)))
    if exo_s.get("First_Logged"):
        rows.append(_row("First-logged", _num(exo_s.get("First_Logged")),
                         (_credits(exo_s.get("First_Logged_Profits"))
                          if exo_s.get("First_Logged_Profits") else None)))
    by_genus = exobio.get("by_genus_value", {}) or exobio.get("by_genus", {}) or {}
    top_genus = [(g, v) for g, v in by_genus.items() if v][:5]
    if top_genus:
        rows.append(_sub("Top genera by value"))
        for genus, val in top_genus:
            rows.append(_row(f"  {genus}", _credits(val)))
    sections["Exobiology"] = rows

    # ── Mining ────────────────────────────────────────────────────────────
    rows = []
    qty    = mine_s.get("Quantity_Mined", 0)
    mats   = mine_s.get("Materials_Collected", 0)
    profit = mine_s.get("Mining_Profits", 0)
    if qty:
        rows.append(_row("Tonnes refined", f"{qty:,} t"))
    if mats:
        rows.append(_row("Materials collected", _num(mats)))
    if profit:
        rows.append(_row("Mining profit", _credits(profit),
                         (f"{_credits(profit / qty)}/t" if qty else None)))
    sections["Mining"] = rows

    # ── Trade ─────────────────────────────────────────────────────────────
    # Journal-derived figures win — Statistics.Trading.Goods_Sold sits at 0
    # for many commanders despite thousands of tonnes sold.
    ms        = finance.get("market_sell", {}) or {}
    j_count   = ms.get("count",   0)
    j_revenue = ms.get("revenue", 0)
    j_profit  = ms.get("profit",  0)
    market_profit = max(trd_s.get("Market_Profits", 0), j_profit)
    resources     = max(trd_s.get("Resources_Traded", 0), j_count)

    rows = []
    if trd_s.get("Markets_Traded_With"):
        rows.append(_row("Markets visited", _num(trd_s.get("Markets_Traded_With"))))
    if resources:
        rows.append(_row("Tonnes sold", f"{resources:,} t"))
    if j_revenue:
        rows.append(_row("Gross revenue", _credits(j_revenue)))
    if market_profit:
        rows.append(_row("Net profit", _credits(market_profit),
                         (f"{_credits(market_profit / resources)}/t"
                          if resources else None)))
    if trd_s.get("Highest_Single_Transaction"):
        rows.append(_row("Largest transaction",
                         _credits(trd_s.get("Highest_Single_Transaction"))))
    if smg_s.get("Black_Markets_Profits"):
        rows.append(_row("Smuggling profit",
                         _credits(smg_s.get("Black_Markets_Profits"))))
    if sar_s.get("SearchRescue_Profit"):
        rows.append(_row("Search & rescue",
                         _credits(sar_s.get("SearchRescue_Profit")),
                         (f"{sar_s.get('SearchRescue_Count'):,} handins"
                          if sar_s.get("SearchRescue_Count") else None)))
    sections["Trade"] = rows

    # ── Missions ──────────────────────────────────────────────────────────
    # Statistics carries no mission counters, so the journal ledger is the
    # only lifetime source here.
    rows = []
    f_in  = finance.get("in",  {}) or {}
    f_out = finance.get("out", {}) or {}
    m_rewards = f_in.get("Missions: rewards", 0)
    m_donate  = f_out.get("Missions: donations", 0)
    if m_rewards:
        rows.append(_row("Mission rewards", _credits(m_rewards)))
    if m_donate:
        rows.append(_row("Donations paid", _credits(m_donate)))
    if pass_s.get("Passengers_Missions_Delivered"):
        rows.append(_row("Passengers delivered",
                         _num(pass_s.get("Passengers_Missions_Delivered"))))
    if pass_s.get("Passengers_Missions_VIP"):
        rows.append(_row("VIP passengers",
                         _num(pass_s.get("Passengers_Missions_VIP"))))
    if f_in.get("Community goal rewards"):
        rows.append(_row("Community goals",
                         _credits(f_in.get("Community goal rewards"))))
    sections["Missions"] = rows

    # ── On foot ───────────────────────────────────────────────────────────
    rows = []
    if expl_s.get("OnFoot_Distance_Travelled"):
        rows.append(_row("On-foot distance",
                         f"{int(expl_s.get('OnFoot_Distance_Travelled')):,} m"))
    if expl_s.get("First_Footfalls"):
        rows.append(_row("First footfalls", _num(expl_s.get("First_Footfalls"))))
    if expl_s.get("Planet_Footfalls"):
        rows.append(_row("Planet footfalls", _num(expl_s.get("Planet_Footfalls"))))
    if expl_s.get("Settlements_Visited"):
        rows.append(_row("Settlements visited",
                         _num(expl_s.get("Settlements_Visited"))))
    if cmb_s.get("OnFoot_Combat_Bonds_Profits"):
        rows.append(_row("On-foot bonds",
                         _credits(cmb_s.get("OnFoot_Combat_Bonds_Profits"))))
    if bank.get("Suits_Owned"):
        rows.append(_row("Suits owned", _num(bank.get("Suits_Owned")),
                         (f"{bank.get('Weapons_Owned'):,} weapons"
                          if bank.get("Weapons_Owned") else None)))
    sections["On foot"] = rows

    # ── PowerPlay ─────────────────────────────────────────────────────────
    # ── PowerPlay ─────────────────────────────────────────────────────────
    # Everything here is scoped to the current pledge.  Merits earned under a
    # former allegiance are not carried over — they bought standing with a
    # power the commander has left.  Two distinct measures remain, and are
    # labelled for what they each count: the server's TotalMerits resets every
    # cycle, while the journal tally runs from the pledge date.
    rows = []
    live_merits = getattr(state, "pp_merits_total", None) if state else None
    cycle_total = live_merits or pp.get("total_merits", 0)
    pp_power    = ((getattr(state, "pp_power", None) if state else None)
                   or pp.get("power") or "")
    pp_rank     = getattr(state, "pp_rank", None) if state else None
    if pp_power:
        rows.append(_row("Pledged to", pp_power, _since(pp.get("pledged_since"))))
    if pp_rank is not None:
        rows.append(_row("Rank", str(pp_rank)))
    if cycle_total:
        rows.append(_row("Merits this cycle", _num(cycle_total)))

    by_act   = pp.get("by_activity", {}) or {}
    earned   = [(a, m) for a, m in by_act.items() if m]
    pledge   = pp.get("pledge_merits", 0) or sum(m for _, m in earned)
    if pledge:
        rows.append(_row("Merits this pledge", _num(pledge)))
    if earned:
        rows.append(_sub("Merits by activity"))
        for act, m in earned[:5]:
            pct = f"{m / pledge * 100:.0f}%" if pledge else None
            rows.append(_row(f"  {act}", _num(m), pct))
    sections["PowerPlay"] = rows

    # ── Fleet carrier ─────────────────────────────────────────────────────
    rows = []
    cstats = carrier.get("stats", {}) or {}
    if carrier.get("name") or carrier.get("callsign"):
        rows.append(_row(carrier.get("name") or "Carrier",
                         carrier.get("callsign") or "—"))
    usage = cstats.get("SpaceUsage", {}) or {}
    if usage:
        used = usage.get("TotalCapacity", 0) - usage.get("FreeSpace", 0)
        rows.append(_row("Capacity used",
                         f"{used:,} / {usage.get('TotalCapacity', 0):,} t"))
    if carrier.get("fuel_level"):
        rows.append(_row("Tritium on board", f"{int(carrier.get('fuel_level')):,} t"))
    if cbank:
        rows.append(_row("Bank balance", _credits(cbank)))
    jumps    = fc_s.get("FLEETCARRIER_TOTAL_JUMPS") or 0
    distance = fc_s.get("FLEETCARRIER_DISTANCE_TRAVELLED") or 0
    if jumps:
        rows.append(_row("Total jumps", _num(jumps),
                         _dist(distance) if distance else None))
    services = ((fc_s.get("FLEETCARRIER_REFUEL_TOTAL")  or 0)
                + (fc_s.get("FLEETCARRIER_REARM_TOTAL")   or 0)
                + (fc_s.get("FLEETCARRIER_REPAIRS_TOTAL") or 0))
    if services:
        rows.append(_row("Services rendered", _num(services)))
    if fc_s.get("FLEETCARRIER_TRADEPROFIT_TOTAL"):
        rows.append(_row("Carrier trade profit",
                         _credits(fc_s.get("FLEETCARRIER_TRADEPROFIT_TOTAL"))))
    sections["Fleet carrier"] = rows

    # ── Credits ───────────────────────────────────────────────────────────
    # Top earning and spending categories from the journal ledger, mirroring
    # the session scope's income-by-source breakdown.
    rows = []
    total_in  = sum(f_in.values())
    total_out = sum(f_out.values())
    if f_in:
        rows.append(_sub("Top earnings"))
        for k, v in [(k, v) for k, v in f_in.items() if v][:5]:
            pct = f"{v / total_in * 100:.0f}%" if total_in else None
            rows.append(_row(f"  {k}", _credits(v), pct))
        rows.append(_row("Total earnings", _credits(total_in)))
    if f_out:
        rows.append(_sub("Top spending"))
        for k, v in [(k, v) for k, v in f_out.items() if v][:5]:
            pct = f"{v / total_out * 100:.0f}%" if total_out else None
            rows.append(_row(f"  {k}", _credits(v), pct))
        rows.append(_row("Total spending", _credits(total_out)))
    if crew_s.get("NpcCrew_TotalWages"):
        rows.append(_row("Ship crew wages",
                         _credits(crew_s.get("NpcCrew_TotalWages")),
                         (f"{crew_s.get('NpcCrew_Hired'):,} hired"
                          if crew_s.get("NpcCrew_Hired") else None)))
    sections["Credits"] = rows

    return _pack(sections)


# ── Wealth ────────────────────────────────────────────────────────────────────

def _wealth(state, finance, carrier_scan, bank) -> tuple[int, int, int]:
    """Return ``(net_worth, liquid, carrier_bank)``.

    Liquid credits, ship and module values, and the carrier bank balance are
    all maintained on live state by the Assets component (CAPI + LoadGame +
    Commander + CarrierFinance), so they are fresher than the one-shot
    journal scan.  ``Statistics.Current_Wealth`` acts as the floor: if the
    computed sum is larger — credits earned since the last Statistics event
    fired — the computed sum wins.
    """
    if state is None:
        return (bank.get("Current_Wealth", 0) or 0,
                finance.get("liquid_credits", 0) or 0,
                carrier_scan.get("bank_balance", 0) or 0)

    live_bal = getattr(state, "assets_balance", None)
    liquid   = int(live_bal) if live_bal is not None else (
               finance.get("liquid_credits", 0) or 0)

    cur            = getattr(state, "assets_current_ship", None) or {}
    stored_ships   = getattr(state, "assets_stored_ships",   []) or []
    stored_modules = getattr(state, "assets_stored_modules", []) or []
    cur_id    = cur.get("ship_id")
    all_ships = ([cur] if cur else []) + [
        s for s in stored_ships
        if isinstance(s, dict) and s.get("ship_id") != cur_id
    ]
    ships_val = sum(s.get("value", 0) for s in all_ships if s)
    mods_val  = sum(m.get("value", 0) for m in stored_modules
                    if isinstance(m, dict))

    live_carrier = getattr(state, "assets_carrier", None) or {}
    cbank = (live_carrier.get("balance")
             or carrier_scan.get("bank_balance", 0)
             or 0)

    risk = 0
    for attr in ("holdings_bounties", "holdings_bonds",
                 "holdings_trade",    "holdings_cartography",
                 "holdings_exobiology"):
        risk += getattr(state, attr, 0) or 0

    stat_wealth = bank.get("Current_Wealth", 0) or 0
    computed    = liquid + ships_val + mods_val + cbank + risk
    return (max(stat_wealth, computed), liquid, cbank)

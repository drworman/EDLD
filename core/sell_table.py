"""
core/sell_table.py — "what is worth selling here", as one table.

The commodity catalogue (core.commodity_ledger) knows what every commodity is
worth on average across the galaxy; Market.json knows what the station
underfoot will actually pay for it.  This module resolves which of those two
is the right answer right now and renders the result as a single two-column
table: the commodity's display name, and its price, highest first.

One model, three surfaces.  ``sell_table()`` builds the table from state, and
``render_markdown()`` / ``render_html()`` turn it into the files written
beside the catalogue.  The TUI and GUI popups render the same dict, so the
files and the popups cannot disagree about what a commodity is worth.

Which market is quoted
----------------------
The mode comes from ``cargo_price_context()``, the same resolver the Cargo
panel prices its manifest against, so the popup and the panel always name the
same market:

  * a Spansh target market, when one is set and loaded;
  * otherwise the station underfoot, from Market.json;
  * otherwise the galactic average, from the catalogue.

NPC prices only
---------------
A commodity with no galactic average is not one NPCs trade.  Stations list
such commodities anyway and quote a sell price for them, but no NPC will pay
it — the price is whatever players set on carriers.  Those rows are dropped,
so the table only ever offers prices that can actually be collected.  Which
commodities those are is read from the catalogue, not from the market in
hand, so the judgement improves as more markets are seen.

Carriers
--------
Fleet and squadron carriers are excluded at every point.  Their markets are
player-run, mobile, and change without notice, so a carrier is never treated
as the focused station — the table falls through to whatever was quoting
before it, exactly as if the commander had not docked at all.  The test is a
substring rather than a fixed list of station types, because Frontier's
``FleetCarrier`` and Spansh's ``Drake-Class Carrier`` are two spellings of the
same thing and a squadron carrier will be a third.
"""

from __future__ import annotations

import html as _html

from core.ui_helpers import cargo_price_context
from data.mining import is_mineable

#: What the table calls itself when it is quoting nothing in particular.
GALACTIC_LABEL = "Galactic Average"


def is_carrier(station_type: str) -> bool:
    """True for any flavour of carrier, however the source spells it.

    Frontier writes ``FleetCarrier`` in Market.json; Spansh writes
    ``Drake-Class Carrier``; a squadron carrier will be something else again.
    Nothing else in the game has "carrier" in its station type, so the
    substring is both sufficient and forward-compatible.
    """
    return "carrier" in (station_type or "").lower()


# ── Model ─────────────────────────────────────────────────────────────────────

def sell_table(state, ledger_rows: dict | None = None) -> dict:
    """Resolve the sell table for the current moment.

    ``ledger_rows`` is the commodity catalogue keyed on canonical name, used
    for the galactic-average fallback because it is the only source that
    carries a display name alongside the price.

    Returns ``{"mode", "source_label", "rows"}`` where each row is
    ``{"name", "price"}`` and rows are ordered by price, highest first.
    """
    ctx = cargo_price_context(state)
    mode = ctx["mode"]
    label = ctx["source_label"]
    comms: dict = {}

    if mode == "target":
        target = getattr(state, "cargo_target_market", {}) or {}
        if is_carrier(target.get("station_type", "")):
            mode = "galactic"
        else:
            comms = ctx["tgt_comms"]
    elif mode == "station":
        # cargo_market_info is already carrier-free — the Market.json reader
        # declines to record one — so an empty market here means either a
        # carrier underfoot or nowhere docked.  Either way there is no focused
        # station and the galactic average is the honest answer.
        comms = ctx["gal_comms"]
        if not comms:
            mode = "galactic"

    if mode == "galactic":
        label = GALACTIC_LABEL
        rows = _rows_from_ledger(ledger_rows or {})
    else:
        rows = _rows_from_market(comms, _non_npc_names(ledger_rows or {}))

    # Highest price first; ties broken by name so the order is stable between
    # writes and the file does not churn.
    rows.sort(key=lambda r: (-r["price"], r["name"].lower()))
    return {"mode": mode, "source_label": label, "rows": rows}


def _squash(name: str) -> str:
    """Reduce a display name to something two sources can agree on.

    Market.json says "Titan Maw Deep Tissue Sample" and so does Spansh, but
    spacing and punctuation are not dependable across sources, and the
    internal symbol is no help at all — Frontier's is
    ``thargoidtissuesampletype10a``.
    """
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _non_npc_names(ledger_rows: dict) -> set[str]:
    """Squashed names of commodities no NPC market has ever priced.

    A commodity with no galactic average is not one NPCs trade: its only
    price is whatever a player set on a carrier, and a station listing it
    reports that price without being willing to pay it.  The Titan Maw
    tissue samples are the standing example — they list at 476,000 cr and
    there is no NPC anywhere who will buy one.

    Derived from the catalogue rather than from the market in hand so the
    judgement improves with every market seen: a commodity that shows a
    real average anywhere drops out of this set everywhere.  An empty
    catalogue yields an empty set, so nothing is excluded on a guess.
    """
    return {
        _squash(row.get("name_localised") or key)
        for key, row in (ledger_rows or {}).items()
        if _int(row.get("mean_price", 0)) <= 0
    }


def _rows_from_market(comms: dict, non_npc: set[str] | None = None) -> list[dict]:
    """Rows from a station's own market — what it will pay, per tonne."""
    non_npc = non_npc or set()
    rows = []
    for key, c in (comms or {}).items():
        price = _int(c.get("sell_price", 0))
        if price <= 0:
            continue
        name = c.get("name_local") or _pretty(key)
        if _squash(name) in non_npc or _squash(key) in non_npc:
            continue
        rows.append({
            "name":     name,
            "price":    price,
            "mineable": is_mineable(name, c.get("category", ""))
                        or is_mineable(key, c.get("category_local", "")),
        })
    return rows


def _rows_from_ledger(ledger_rows: dict) -> list[dict]:
    """Rows from the commodity catalogue — the galactic average.

    A zero here is the absence of a galactic average rather than a commodity
    worth nothing (Thargoid tissue samples carry one), and a row with no
    price answers no question this table is asked, so it is left out.
    """
    rows = []
    for key, r in (ledger_rows or {}).items():
        price = _int(r.get("mean_price", 0))
        if price <= 0:
            continue
        name = r.get("name_localised") or _pretty(key)
        rows.append({
            "name":     name,
            "price":    price,
            "mineable": is_mineable(name, r.get("category", ""))
                        or is_mineable(key),
        })
    return rows


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pretty(key: str) -> str:
    return str(key).replace("_", " ").title()


def _credits(n: int) -> str:
    return f"{int(n):,} cr"


# ── Renderers ─────────────────────────────────────────────────────────────────

def render_markdown(table: dict) -> str:
    """The table as GitHub-flavoured Markdown."""
    label = table.get("source_label") or GALACTIC_LABEL
    lines = [f"# {label}", "", "| Commodity | Sell |", "| --- | ---: |"]
    for row in table.get("rows", []):
        # Escape the cell separator; nothing else in a commodity name can
        # break a Markdown table.
        name = str(row["name"]).replace("|", "\\|")
        lines.append(f"| {name} | {_credits(row['price'])} |")
    if not table.get("rows"):
        lines.append("| _no prices available_ | |")
    lines.append("")
    return "\n".join(lines)


#: Self-contained so the file opens correctly from anywhere — no stylesheet to
#: ship alongside it, and no assumption about the reader's browser theme.
_HTML_CSS = """\
:root { color-scheme: light dark; }
body { font: 15px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       margin: 2rem auto; max-width: 42rem; padding: 0 1rem; }
h1 { font-size: 1.25rem; font-weight: 600; margin: 0 0 1rem; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: .35rem .6rem; border-bottom: 1px solid rgba(128,128,128,.3); }
th { text-align: left; font-weight: 600; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody tr:hover { background: rgba(128,128,128,.12); }
"""


def render_html(table: dict) -> str:
    """The table as a standalone HTML document."""
    label = table.get("source_label") or GALACTIC_LABEL
    esc = _html.escape
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>EDLD — {esc(label)}</title>",
        f"<style>{_HTML_CSS}</style></head><body>",
        f"<h1>{esc(label)}</h1>",
        '<table><thead><tr><th>Commodity</th><th class="num">Sell</th></tr>'
        "</thead><tbody>",
    ]
    for row in table.get("rows", []):
        parts.append(
            f'<tr><td>{esc(str(row["name"]))}</td>'
            f'<td class="num">{esc(_credits(row["price"]))}</td></tr>'
        )
    if not table.get("rows"):
        parts.append('<tr><td colspan="2">No prices available.</td></tr>')
    parts.append("</tbody></table></body></html>")
    return "\n".join(parts) + "\n"


def mineable_rows(table: dict) -> list[dict]:
    """Just the rows a mining laser can produce, in the same order."""
    return [r for r in table.get("rows", []) if r.get("mineable")]


def render_columns(table: dict, mineable_only: bool = False) -> list[tuple[str, str]]:
    """The table as (name, price) string pairs, for the TUI and GUI popups.

    Returned rather than formatted into one string so each front end can lay
    the two columns out in its own widgets, which is what keeps the price
    column aligned in both.
    """
    rows = mineable_rows(table) if mineable_only else table.get("rows", [])
    return [(str(r["name"]), _credits(r["price"])) for r in rows]

"""
data/mining.py — which commodities can be mined.

Frontier publishes no "mineable" flag.  Market.json says what a commodity is
and what it costs; nothing in it says whether a mining laser can produce one.
So the answer has to be stated here, and the useful thing is that it is nearly
all category:

  * everything in **Minerals** is mined.  That is what the category is for —
    every one of the 39 entries is either a laser yield, a sub-surface
    deposit, or a core motherlode;
  * a **named ten Metals**, which are the refinery outputs.  The rest of the
    category — Aluminium, Steel, Titanium, the rare-goods entries — is
    manufactured or traded, never dug up;
  * a **named four Chemicals**: the three ices and the tritium that fuels
    carriers.

Evidence
--------
The named metals and chemicals are exactly those appearing in `MiningRefined`
and `ProspectedAsteroid` events across a real 210-journal capture — Cobalt,
Copper, Gold, Osmium, Palladium, Platinum, Praseodymium, Samarium, Silver and
Thorium refined; Tritium, Water, Liquid Oxygen and Hydrogen Peroxide
prospected.  Nothing outside Minerals turned up beyond those fourteen.

The category rule is what makes the table cheap to keep: a mineral added in a
future update is mined the day it ships, without an edit here.  Only a new
mineable *metal* or *chemical* would need one, and those are rare — the ten
metals have not changed since the refinery was introduced.
"""

from __future__ import annotations

#: Categories mined in their entirety, by canonical (lowercased, unwrapped)
#: category symbol.
MINEABLE_CATEGORIES: frozenset[str] = frozenset({"minerals"})

#: Metals a refinery produces.  The rest of the Metals category is traded.
MINEABLE_METALS: frozenset[str] = frozenset({
    "cobalt", "copper", "gold", "osmium", "palladium",
    "platinum", "praseodymium", "samarium", "silver", "thorium",
})

#: Chemicals taken from ice rings, plus the tritium carriers run on.
MINEABLE_CHEMICALS: frozenset[str] = frozenset({
    "hydrogenperoxide", "liquidoxygen", "tritium", "water",
})

#: Every named exception to the category rule, squashed for comparison.
MINEABLE_NAMES: frozenset[str] = MINEABLE_METALS | MINEABLE_CHEMICALS


def _squash(text: str) -> str:
    """Lowercase and strip everything that is not a letter or digit.

    "Liquid oxygen", "liquid_oxygen" and "LiquidOxygen" are one commodity
    spelled three ways across Market.json, the journals, and Spansh.
    """
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


#: Frontier wraps the category as ``$MARKET_category_minerals;``; other
#: sources send the bare display name.  Squashing alone is not enough — it
#: would leave ``marketcategoryminerals``, which matches nothing.
_CATEGORY_WRAPPER = "marketcategory"


def _category_key(category: str) -> str:
    """Reduce a category to its bare symbol, whichever form it arrives in."""
    key = _squash(category)
    if key.startswith(_CATEGORY_WRAPPER):
        key = key[len(_CATEGORY_WRAPPER):]
    return key


def is_mineable(name: str = "", category: str = "") -> bool:
    """True when a mining laser, sub-surface charge, or core can produce this.

    Either argument may be absent — a source that reports only a name still
    resolves the fourteen named commodities, and a source that reports only a
    category still resolves the minerals.
    """
    if _category_key(category) in MINEABLE_CATEGORIES:
        return True
    return _squash(name) in MINEABLE_NAMES

"""
data/ranks.py — Elite Dangerous pilot rank name tables.

Each list maps rank integer index to the display string shown in-game.
Indices 0–8 are the standard progression; indices 9–13 are Elite tiers I–V.

CAPI_RANK_SKILLS ties each rank domain to its CAPI /profile key, display
label, and name table for use across the bridge and TUI layers.
"""
from __future__ import annotations

RANK_NAMES: list[str] = [
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]

RANK_NAMES_TRADE: list[str] = [
    "Penniless", "Mostly Penniless", "Peddler", "Dealer", "Merchant",
    "Broker", "Entrepreneur", "Tycoon", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]

RANK_NAMES_EXPLORE: list[str] = [
    "Aimless", "Mostly Aimless", "Scout", "Surveyor", "Trailblazer",
    "Pathfinder", "Ranger", "Pioneer", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]

RANK_NAMES_CQC: list[str] = [
    "Helpless", "Mostly Helpless", "Amateur", "Semi-Professional",
    "Professional", "Champion", "Hero", "Legend", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]

RANK_NAMES_SOLDIER: list[str] = [   # Mercenary
    "Defenceless", "Mostly Defenceless", "Rookie", "Soldier",
    "Gunslinger", "Warrior", "Gladiator", "Deadeye", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]

RANK_NAMES_EXOBIO: list[str] = [
    "Directionless", "Mostly Directionless", "Compiler", "Collector",
    "Cataloguer", "Taxonomist", "Ecologist", "Geneticist", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]

RANK_NAMES_FEDERATION: list[str] = [
    "None",
    "Recruit", "Cadet", "Midshipman", "Petty Officer", "Chief Petty Officer",
    "Warrant Officer", "Ensign", "Lieutenant", "Lieutenant Commander",
    "Post Commander", "Post Captain", "Rear Admiral", "Vice Admiral", "Admiral",
]

RANK_NAMES_EMPIRE: list[str] = [
    "None",
    "Outsider", "Serf", "Master", "Squire", "Knight",
    "Lord", "Baron", "Viscount", "Count", "Earl",
    "Marquis", "Duke", "Prince", "King",
]

# (CAPI /profile key (lowercase), display label, rank name table)
CAPI_RANK_SKILLS: list[tuple[str, str, list[str]]] = [
    ("combat",       "Combat",       RANK_NAMES),
    ("explore",      "Explorer",     RANK_NAMES_EXPLORE),
    ("trade",        "Trade",        RANK_NAMES_TRADE),
    ("cqc",          "CQC",          RANK_NAMES_CQC),
    ("soldier",      "Mercenary",    RANK_NAMES_SOLDIER),
    ("exobiologist", "Exobiologist", RANK_NAMES_EXOBIO),
    ("federation",   "Federation",   RANK_NAMES_FEDERATION),
    ("empire",       "Empire",       RANK_NAMES_EMPIRE),
]

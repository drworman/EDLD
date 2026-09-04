"""
data/ — Static reference data for Elite Dangerous in-game definitions.

Kept separate from functional code so these tables can be updated without
touching any plugin or UI logic.

Modules
-------
ships       Ship type → display name, fighter type/loadout names, normalise helpers
modules     Module internal → display name, class/rating/mount/size maps, normalise helper
ranks       Rank name tables (combat, trade, explore, …) and CAPI skill manifest
engineering Engineering blueprint → display name, experimental effect → display name
status_flags  Status.json Flags / Flags2 / GuiFocus bit constants
"""

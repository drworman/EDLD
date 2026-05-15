"""
gui/blocks — EDLD dashboard block widgets.

Each block subclasses gui.block_base.BlockWidget and owns its own
build() and refresh() logic.  EdmdWindow instantiates all blocks and
calls build() once then refresh() on every relevant gui_queue message.
"""

from gui.blocks.commander     import CommanderBlock
from gui.blocks.crew_slf      import CrewSlfBlock
from gui.blocks.missions      import MissionsBlock
from gui.blocks.alerts        import AlertsBlock
from gui.blocks.cargo         import CargoBlock
from gui.blocks.engineering   import EngineeringBlock
from gui.blocks.assets        import AssetsBlock
from gui.blocks.colonisation  import ColonisationBlock
from gui.blocks.career        import CareerBlock
from gui.blocks.navigation    import NavigationBlock

__all__ = [
    "CommanderBlock",
    "CrewSlfBlock",
    "MissionsBlock",
    "AlertsBlock",
    "CargoBlock",
    "EngineeringBlock",
    "AssetsBlock",
    "ColonisationBlock",
    "CareerBlock",
    "NavigationBlock",
]

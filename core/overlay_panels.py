"""
core/overlay_panels.py — What the overlay shows, and where.

The overlay is not a second dashboard. EDLD already is one, on a second screen,
and reproducing it over the game would be both unreadable and pointless. The
overlay carries the *subset that matters while you cannot look away* — the
numbers a commander would otherwise alt-tab for, and the ones a streamer would
want on camera.

Ownership
---------
Panels belong to the components that own the data. The cargo component knows
what is in the hold and when that is worth showing; the exobiology component
knows whether this body has anything to scan. A component contributes by
implementing::

    OVERLAY_PANELS = ("cargo", "cargo_srv")        # ids it can produce

    def overlay_panel(self, panel_id: str, ctx: PanelContext) -> Panel | None:
        ...                                        # None means "not now"

Returning None is the component's own relevance test, and it is the only thing
that decides whether a panel is eligible in ``auto`` mode. Nothing here knows
what a bio signal is or how full a hold has to be to be interesting.

Zones
-----
Three fixed anchors across the top of the screen: left, centre, right. Each
holds a vertical stack. The commander assigns panels to zones and orders them
within a zone; there is no free placement, no drag, and no overflow rule,
because a stack too tall to fit is visible the moment it happens and the fix is
to move a panel. Zones are anchors rather than boxes — a stack is as tall as
what is in it, and nothing can wander into the middle of the viewport.

Hidden panels
-------------
When a panel in ``auto`` mode is not currently eligible, the stack either
closes up or holds the space. Both are defensible and neither is right for
everyone, so it is :data:`HIDE_MODES` and the commander picks:

``collapse``  the stack closes up. Denser, no wasted screen, but the panels
              below move when one appears or goes, and something that moves is
              something you have to re-find rather than glance at.
``reserve``   the space is held. Every panel stays where it was put, at the
              cost of gaps. Steadier to read, and the better default for
              anyone with the overlay on camera.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, NamedTuple, Optional

#: Where a panel can be placed.
#:
#: "left", "centre" and "right" are the three columns of the top bar and keep
#: those names deliberately: renaming them to "top-left" and so on would have
#: silently unplaced every panel in every existing config, since an unknown
#: zone is reported and skipped.
#:
#: "dock-left" and "dock-right" are separate windows against the side edges of
#: the screen, each a single stacked column.
ZONES = ("left", "centre", "right", "dock-left", "dock-right")

#: Which window each zone is drawn in. The top bar holds three columns; each
#: dock is its own window so it can be sized and positioned independently, and
#: so a commander with nothing docked pays for no extra window at all.
ZONE_WINDOW = {
    "left":       "top",
    "centre":     "top",
    "right":      "top",
    "dock-left":  "dock-left",
    "dock-right": "dock-right",
}

WINDOWS = ("top", "dock-left", "dock-right")

#: Positions a panel can take within its zone. A closed vocabulary, so it is a
#: picker rather than a number field. Two panels given the same position fall
#: back to panel id, which is stable and alphabetical — deliberately boring,
#: because the alternative is a reorder that silently renumbers panels the
#: commander did not touch.
POSITIONS = tuple(str(n) for n in range(1, 10))
MODES = ("on", "off", "auto")
HIDE_MODES = ("collapse", "reserve")

#: Vertical space one line of panel text occupies, before scaling.
#:
#: Derived from the body size rather than fixed: a commander who raises the
#: font and finds the rows overlapping has been given a setting that breaks
#: the layout, which is worse than not offering it.
LINE_HEIGHT = 17


def line_height(body_size: int = 13) -> int:
    return max(12, int(round(body_size * 1.3)))

#: Gap between the last line of one panel and the title of the next.
PANEL_GAP = 12

#: Config section for the overlay's layout.  Panel placement lives in
#: ``Panels``, a table of ``panel_id = {Zone, Mode, Order}``, so adding a panel
#: never needs a schema change here.
CFG_DEFAULTS = {
    "HideMode": "reserve",
    "TitleSize": 12,
    "BodySize": 13,
    "TitleColour": "#7aa2d2",
    "LabelColour": "#9aa4b2",
    "ValueColour": "#cfd6e4",
}


class PanelContext(NamedTuple):
    """Everything a component needs to decide whether its panel applies now.

    Assembled once per frame from Status.json and MonitorState, so every panel
    in a frame sees the same instant. A panel that read state directly could
    answer from a position half a second newer than the one its neighbour used,
    and the overlay would disagree with itself.
    """
    in_srv:       bool = False
    on_foot:      bool = False
    in_ship:      bool = False
    docked:       bool = False
    landed:       bool = False
    supercruise:  bool = False
    in_taxi:      bool = False
    hardpoints:   bool = False
    has_latlong:  bool = False
    latitude:     Optional[float] = None
    longitude:    Optional[float] = None
    heading:      Optional[float] = None
    body_radius:  Optional[float] = None
    body_name:    str = ""
    system_name:  str = ""
    suit_name:    str = ""


@dataclass
class Panel:
    """One block of text the overlay can draw.

    ``rows`` are ``(label, value)``. A row with an empty label is a full-width
    line; a row with an empty value is a heading. The panel does not know where
    it will be drawn or how wide the zone is — that is the layout's business,
    and keeping it that way is what lets the same panel sit in any zone.
    """
    id:     str
    title:  str = ""
    rows:   list[tuple[str, str]] = field(default_factory=list)
    accent: str = ""          # optional colour override for the title

    #: Set by the layout so height matches the configured body size.
    line_h: int = LINE_HEIGHT

    @property
    def height(self) -> int:
        lines = len(self.rows) + (1 if self.title else 0)
        return lines * self.line_h

    def is_empty(self) -> bool:
        return not self.rows and not self.title


@dataclass
class PanelPlacement:
    """Where the commander wants a panel, and whether it is allowed to show."""
    panel_id: str
    zone:     str = "left"
    mode:     str = "auto"
    order:    int = 100

    def valid(self) -> bool:
        return self.zone in ZONES and self.mode in MODES


#: Flat config key prefixes, one per placement field.
#:
#: Not a nested ``Panels.<id>.Zone`` table, though that reads better. The
#: preferences writer stores a pending ``(section, key)`` pair by assigning
#: ``target[key] = value`` — the key is written literally, so a dotted key
#: becomes a flat string key containing dots rather than a nested table, and
#: nothing ever reads it back. Panel placement could be changed in either front
#: end, saved without error, and have no effect whatsoever.
#:
#: Flat keys survive that writer unchanged. A hand-written ``Panels`` table is
#: still honoured, for anyone who prefers editing TOML.
KEY_ZONE  = "PanelZone_"
KEY_MODE  = "PanelMode_"
KEY_ORDER = "PanelOrder_"
KEY_SCOPE = "PanelScope_"

#: How much of an activity's figures a panel shows. Only offered for panels
#: that actually have both halves.
SCOPES = ("session", "career", "both")
SCOPE_CHOICES: list[tuple[str, str]] = [
    ("Session", "session"),
    ("Career", "career"),
    ("Career (Session: )", "both"),
]


def placement_keys(panel_id: str) -> dict[str, str]:
    """Config keys for one panel's placement."""
    return {"zone":  f"{KEY_ZONE}{panel_id}",
            "mode":  f"{KEY_MODE}{panel_id}",
            "order": f"{KEY_ORDER}{panel_id}",
            "scope": f"{KEY_SCOPE}{panel_id}"}


def placements_from_config(cfg: dict, log=None) -> list[PanelPlacement]:
    """Read placements, dropping nonsense loudly.

    Two sources, flat keys winning: a ``Panels`` table for hand-edited configs,
    and the flat ``PanelZone_<id>`` / ``PanelMode_<id>`` / ``PanelOrder_<id>``
    keys the preferences screens write.

    An invalid zone or mode is reported and skipped rather than coerced to a
    default, because a typo that silently relocates a panel is worse than one
    that says so.
    """
    merged: dict[str, dict] = {}

    for panel_id, spec in (cfg.get("Panels") or {}).items():
        if not isinstance(spec, dict):
            if log:
                log(f"overlay: panel {panel_id!r} is not a table; ignored")
            continue
        merged[panel_id] = {"Zone": spec.get("Zone", "left"),
                            "Mode": spec.get("Mode", "auto"),
                            "Order": spec.get("Order", 100)}

    for key, value in cfg.items():
        for prefix, field_name in ((KEY_ZONE, "Zone"), (KEY_MODE, "Mode"),
                                   (KEY_ORDER, "Order")):
            if isinstance(key, str) and key.startswith(prefix):
                panel_id = key[len(prefix):]
                if panel_id:
                    merged.setdefault(panel_id, {})[field_name] = value

    out: list[PanelPlacement] = []
    for panel_id, spec in merged.items():
        try:
            order = int(spec.get("Order", 100) or 100)
        except (TypeError, ValueError):
            order = 100
        p = PanelPlacement(panel_id=panel_id,
                           zone=str(spec.get("Zone", "left")).lower(),
                           mode=str(spec.get("Mode", "auto")).lower(),
                           order=order)
        if not p.valid():
            if log:
                log(f"overlay: panel {panel_id!r} has zone={p.zone!r} "
                    f"mode={p.mode!r}; expected one of {ZONES} / {MODES}. Ignored.")
            continue
        out.append(p)

    # Ties break on panel id so the stack is stable frame to frame. A sort
    # that fell back on dict order would reshuffle the overlay on restart.
    out.sort(key=lambda p: (p.order, p.panel_id))
    return out


class ResolvedSlot(NamedTuple):
    """One position in a zone's stack after eligibility has been decided."""
    placement: PanelPlacement
    panel:     Optional[Panel]     # None means the slot is empty this frame
    height:    int                 # space it occupies, 0 when collapsed away


def resolve_zone(placements: Iterable[PanelPlacement],
                 panels: dict[str, Optional[Panel]],
                 hide_mode: str = "reserve",
                 reserve_heights: Optional[dict[str, int]] = None,
                 ) -> list[ResolvedSlot]:
    """Decide what occupies a zone's stack this frame.

    ``panels`` maps panel id to the panel its component produced, or None if
    the component said it does not apply now. ``mode`` overrides that: ``on``
    shows it whenever the component produced anything at all, ``off`` never
    shows it, ``auto`` defers to the component.

    In ``reserve`` mode a hidden panel keeps the height it last had, which is
    why ``reserve_heights`` is carried between frames — reserving nothing would
    make the stack jump the first time a panel appeared, which is the exact
    thing reserving is for.
    """
    reserve_heights = reserve_heights or {}
    slots: list[ResolvedSlot] = []
    for p in placements:
        panel = panels.get(p.panel_id)
        if p.mode == "off":
            continue                      # never drawn, never reserved
        if panel is not None and panel.is_empty():
            panel = None
        show = panel is not None
        if p.mode == "on" and panel is None:
            show = False                  # nothing to draw is nothing to draw
        if show:
            slots.append(ResolvedSlot(p, panel, panel.height))
        elif hide_mode == "reserve":
            slots.append(ResolvedSlot(p, None, reserve_heights.get(p.panel_id, 0)))
        # collapse: contribute nothing at all
    return slots


def zone_x(zone: str, width: int, margin: int = 16) -> tuple[int, str]:
    """Anchor x and text alignment for a zone within its own window.

    A dock is a single column filling its window, so it anchors at the margin
    and reads left-to-right like the top bar's left column — a right-hand dock
    right-aligned against a narrow window would put its text hard against the
    screen edge, which is where it is least readable.
    """
    if zone in ("left", "dock-left", "dock-right"):
        return margin, "left"
    if zone == "right":
        return width - margin, "right"
    return width // 2, "centre"


def layout(placements: Iterable[PanelPlacement],
           panels: dict[str, Optional[Panel]],
           width: int, *,
           window: str = "top",
           hide_mode: str = "reserve",
           reserve_heights: Optional[dict[str, int]] = None,
           top: int = 0,
           pad_x: int = 16,
           pad_y: int = 8,
           colours: Optional[dict] = None,
           ) -> tuple[list[dict], dict[str, int]]:
    """Turn panels into overlay text elements.

    Returns ``(elements, heights)`` — the drawable frame, and the height each
    panel actually occupied, to be fed back as ``reserve_heights`` next frame.
    """
    from core.overlay import text

    colours = {**CFG_DEFAULTS, **(colours or {})}
    lh = line_height(int(colours.get("BodySize", 13)))
    for p in panels.values():
        if p is not None:
            p.line_h = lh
    zones = [z for z in ZONES if ZONE_WINDOW.get(z) == window]
    by_zone: dict[str, list[PanelPlacement]] = {z: [] for z in zones}
    for p in placements:
        if p.zone in by_zone:
            by_zone[p.zone].append(p)

    elements: list[dict] = []
    heights: dict[str, int] = {}

    for zone, zone_placements in by_zone.items():
        x, align = zone_x(zone, width, pad_x)
        y = top + pad_y
        for slot in resolve_zone(zone_placements, panels, hide_mode,
                                 reserve_heights):
            heights[slot.placement.panel_id] = slot.height
            if slot.panel is None:
                y += slot.height + (PANEL_GAP if slot.height else 0)
                continue
            panel = slot.panel
            if panel.title:
                el = text(f"{panel.id}.title", x, y, panel.title,
                          colour=panel.accent or colours["TitleColour"],
                          size=int(colours.get("TitleSize", 12)), weight="bold")
                el["align"] = align
                elements.append(el)
                y += lh
            for label, value in panel.rows:
                body = f"{label}  {value}".strip() if label else str(value)
                el = text(f"{panel.id}.{label or value}", x, y, body,
                          colour=colours["ValueColour"] if not label
                                 else colours["LabelColour"],
                          size=int(colours.get("BodySize", 13)))
                el["align"] = align
                elements.append(el)
                y += lh
            y += PANEL_GAP

    return elements, heights


def collect(components: Iterable, ctx: PanelContext,
            wanted: Iterable[str], log=None) -> dict[str, Optional[Panel]]:
    """Ask every component for the panels the commander has placed.

    Only ids that are actually placed are requested, so a component's panel
    costs nothing while it is switched off. A component that raises is reported
    and skipped — one broken panel must not blank the overlay.
    """
    wanted = set(wanted)
    out: dict[str, Optional[Panel]] = {}
    for comp in components:
        ids = getattr(comp, "OVERLAY_PANELS", ()) or ()
        fn = getattr(comp, "overlay_panel", None)
        if not ids or not callable(fn):
            continue
        for panel_id in ids:
            if panel_id not in wanted:
                continue
            try:
                out[panel_id] = fn(panel_id, ctx)
            except Exception as exc:
                out[panel_id] = None
                if log:
                    log(f"overlay panel {panel_id!r} from "
                        f"{getattr(comp, 'PLUGIN_NAME', comp)!r} failed: "
                        f"{type(exc).__name__}: {exc}")
    return out


def context_from(position, state=None) -> PanelContext:
    """Build a frame's context from a Status.json position and MonitorState."""
    if position is None:
        return PanelContext()
    return PanelContext(
        in_srv      = bool(position.in_srv),
        has_latlong = True,
        latitude    = position.latitude,
        longitude   = position.longitude,
        heading     = position.heading,
        body_radius = position.radius_m,
        body_name   = position.body_name,
        on_foot     = bool(getattr(state, "on_foot", False)) if state else False,
        docked      = bool(getattr(state, "docked", False)) if state else False,
        landed      = bool(getattr(state, "landed", False)) if state else False,
        supercruise = bool(getattr(state, "supercruise", False)) if state else False,
        system_name = str(getattr(state, "star_system", "") or "") if state else "",
        suit_name   = str(getattr(state, "suit_name", "") or "") if state else "",
    )

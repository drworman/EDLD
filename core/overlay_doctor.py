"""
core/overlay_doctor.py — Why is there no overlay?

Every layer of the overlay is individually tested and the whole thing still
does not appear, which means the fault is in the joins: config that is written
but not read, panels that exist but are not placed, placements that parse but
resolve to nothing, a renderer that starts and is handed an empty frame. From
outside, all of those look identical — no overlay.

This walks the chain and reports each link. Run it with::

    python edld.py --overlay-doctor

It reads the same config the running app reads, through the same code, and
prints what each stage produced. No guessing, and nothing inferred from a
screenshot.
"""

from __future__ import annotations

import json
from typing import Any


def _line(label: str, value: Any) -> str:
    return f"  {label:<26} {value}"


def run(cfg, plugins=None) -> int:
    """Walk the overlay chain and print what each stage sees.

    ``cfg`` is the live ConfigManager, so this reads exactly what the running
    app reads — same file, same profile, same resolution order. A doctor that
    built its own view of the config could disagree with the app and would then
    be diagnosing itself.
    """
    from core.overlay import CFG_DEFAULTS as WINDOW_DEFAULTS
    from core import overlay_panels as op

    out: list[str] = ["EDLD overlay doctor", ""]

    wcfg = cfg.load_setting("Overlay", WINDOW_DEFAULTS, False)
    lcfg = cfg.load_setting("OverlayPanels", dict(op.CFG_DEFAULTS), False,
                            include_extra=True)
    profile = cfg.config_profile
    path = cfg.config_path

    out.append("CONFIG")
    out.append(_line("file", path))
    out.append(_line("profile", profile or "(none)"))
    out.append(_line("Overlay.Enabled", wcfg.get("Enabled")))
    out.append(_line("Overlay.Anchor", wcfg.get("Anchor")))
    out.append(_line("Overlay.Width", wcfg.get("Width")))
    out.append(_line("Overlay.Opacity", wcfg.get("Opacity")))
    out.append(_line("OverlayPanels.HideMode", lcfg.get("HideMode")))

    placement_keys = {k: v for k, v in lcfg.items()
                      if isinstance(k, str) and k.startswith(
                          (op.KEY_ZONE, op.KEY_MODE, op.KEY_ORDER))}
    out.append(_line("placement keys found", len(placement_keys)))
    for k in sorted(placement_keys):
        out.append(_line(f"  {k}", placement_keys[k]))
    if "Panels" in lcfg:
        out.append(_line("Panels table", json.dumps(lcfg["Panels"])[:120]))
    out.append("")

    # 2. placements
    notes: list[str] = []
    placements = op.placements_from_config(lcfg, log=notes.append)
    out.append("PLACEMENTS")
    if not placements:
        out.append("  none — every panel is unplaced, so nothing can draw")
    for p in placements:
        out.append(_line(p.panel_id, f"zone={p.zone} mode={p.mode} order={p.order}"))
    for n in notes:
        out.append(f"  ! {n}")
    active = [p for p in placements if p.mode != "off"]
    out.append(_line("not switched off", len(active)))
    out.append("")

    # 3. what the components can offer
    out.append("PANELS OFFERED BY COMPONENTS")
    plugins = list(plugins or [])
    if not plugins:
        out.append("  (none loaded in this context)")
    offered: set[str] = set()
    for comp in plugins:
        ids = tuple(getattr(comp, "OVERLAY_PANELS", ()) or ())
        if ids:
            offered.update(ids)
            out.append(_line(getattr(comp, "PLUGIN_NAME", "?"), ", ".join(ids)))
    if plugins:
        unplaced = sorted(offered - {p.panel_id for p in placements})
        if unplaced:
            out.append(_line("offered but unplaced", ", ".join(unplaced)))
        missing = sorted({p.panel_id for p in placements} - offered)
        if missing:
            out.append(_line("placed but no component", ", ".join(missing)))
    out.append("")

    # 4. position, which gates every context-aware panel
    from core.surface_survey import POSITIONS
    import time as _t
    pos = POSITIONS.latest()
    out.append("POSITION")
    if pos is None:
        out.append("  no Status.json sample yet — context-aware panels cannot apply")
    else:
        age = _t.time() - pos.ts
        out.append(_line("age", f"{age:.1f}s"))
        out.append(_line("in SRV", pos.in_srv))
        out.append(_line("body", pos.body_name or "(none)"))
    out.append("")

    # 5. the verdict, in the order the chain fails
    out.append("VERDICT")
    if not wcfg.get("Enabled"):
        out.append("  Overlay.Enabled is false — nothing will start.")
    elif not placements:
        out.append("  No panel placements in config. Set a panel's mode in "
                   "Preferences > Overlay, then Apply & Save.")
    elif not active:
        out.append("  Every placed panel is mode=off. Set at least one to "
                   "'on' or 'auto'.")
    elif plugins and not offered:
        out.append("  No component offers a panel — the components did not "
                   "load. This is a plugin loading problem, not an overlay one.")
    else:
        out.append("  Config and placement look sound. If nothing is drawn, "
                   "the panels in 'auto' are deciding they do not apply; try "
                   "one on 'on'. Run --overlay-probe for renderer capability.")

    print("\n".join(out))
    return 0

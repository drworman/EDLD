# EDLD Roadmap

Last updated: 20260906

---

## Recently shipped

**Cross-platform desktop interface** (20260811) — a PySide6 window rendering
the same dashboard as the terminal interface, with prebuilt binaries for Linux,
Windows and macOS. This is what prompted the rename from ED Linux Dash to ED
Live Dashboard. See the changelog for the full entry.

Worth noting for anyone picking up work here: both front ends are rendered from
one layout model and one set of components, so a new dashboard window should be
added to both rather than to whichever is convenient. `core/summary_model.py`
and `core/palette.py` exist for the same reason.

**Window consolidation** (20260905–06) — windows that duplicated each other's
rows were folded into the window they belonged with, and the size classes cut
from three to two. The set is now seven windows in seven slots, so everything
is on screen at once and rearranging swaps two windows rather than hiding one.

Assets became tabs on Commander, Exobiology nested under the body it describes
in Exploration, Cargo and Engineering became tabs on Ship, missions and
colonisation became the Objectives window, Session became Career's first tab,
and Crew / SLF merged with Alerts. Hull, shields and fuel live on Commander's
Info tab, which is the default view and therefore the one place they cost
nothing to reach.

No data was dropped. A `windows.json` from before this release describes a
window set and a slot grid that no longer exist, so it is replaced with the
current defaults and rewritten once, on the next launch.

**Spansh fleet-carrier routing** (20260905) — carrier routing works. The endpoint and parameter names had been correct all
along; the two list-shaped parameters were being sent as JSON strings where
Spansh's form parser expects repeated bare keys — jQuery's `traditional`
serialisation — so a job was accepted with `HTTP 202` and then had no
destination to route to. Routes come back with full per-jump fuel planning:
tritium burned, tank level on arrival, restock stops and amounts, and which
systems have a market or a pristine icy ring to mine.

---

## Deferred

### Exploration / Exobiology module split
Exploration and Exobiology now render as one window — the biology for a body
sits nested under that body's exploration row — but their shared body-data
layer (`core/explo_*`) still mixes Exploration logic
(scan / mapping / discovery) with Exobiology logic (flora status, waypoints,
clonal distance, one-sample-in-progress reset) as a legacy of their shared
origin. A future refactor will split these into distinct modules so the two
concerns are cleanly separated. The tables are interlinked via shared
systems/bodies, so the approach is a module split rather than a separate
database. Deferred — no target release. Background in
[EXPLORATION_EXOBIOLOGY_PLAN.md](EXPLORATION_EXOBIOLOGY_PLAN.md).


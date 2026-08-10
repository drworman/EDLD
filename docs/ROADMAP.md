# EDLD Roadmap

Last updated: 20260613

---

## Deferred

### Exploration / Exobiology module split
The Exploration and Exobiology dashboard windows and their shared body-data
layer (`core/explo_*`) have shipped. That layer still mixes Exploration logic
(scan / mapping / discovery) with Exobiology logic (flora status, waypoints,
clonal distance, one-sample-in-progress reset) as a legacy of their shared
origin. A future refactor will split these into distinct modules so the two
concerns are cleanly separated. The tables are interlinked via shared
systems/bodies, so the approach is a module split rather than a separate
database. Deferred — no target release. Background in
[EXPLORATION_EXOBIOLOGY_PLAN.md](EXPLORATION_EXOBIOLOGY_PLAN.md).

### Spansh Fleet-Carrier Routing  ⚠ unfinished — deferred, no target release
The carrier route planner in the Navigation block is non-functional —
Spansh's `/api/fleetcarrier/*` endpoints respond `HTTP 202` to the
POST but the resulting job UUID doesn't resolve at any of the
documented results paths (`/api/results/<id>`, `/api/fleetcarrier/results/<id>`,
`/api/fleet-carrier/results/<id>`, `/api/fleetcarrier/route/<id>`).
The form scaffolding remains in place but inputs and the plot button
are disabled, with an explanatory banner in the tab. FSD and Neutron
routing are unaffected.

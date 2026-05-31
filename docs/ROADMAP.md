# EDLD Roadmap

Last updated: 20260530

---

## Planned

### Exploration & Exobiology windows
Two new dashboard windows plus a shared body data layer and a user-configurable
window layout system. Full multi-session plan in
[EXPLORATION_EXOBIOLOGY_PLAN.md](EXPLORATION_EXOBIOLOGY_PLAN.md).

---

## Active / In Progress

### Spansh Fleet-Carrier Routing  ⚠ unfinished — disabled in 20260515
The carrier route planner in the Navigation block is non-functional —
Spansh's `/api/fleetcarrier/*` endpoints respond `HTTP 202` to the
POST but the resulting job UUID doesn't resolve at any of the
documented results paths (`/api/results/<id>`, `/api/fleetcarrier/results/<id>`,
`/api/fleet-carrier/results/<id>`, `/api/fleetcarrier/route/<id>`).
The form scaffolding remains in place but inputs and the plot button
are disabled, with an explanatory banner in the tab.  FSD and Neutron
routing are unaffected.

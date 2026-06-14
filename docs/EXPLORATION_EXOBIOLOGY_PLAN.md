# EDLD — Exploration & Exobiology Plan

**Scope:** Two new dashboard windows (Exploration, Exobiology), a shared body
data layer fed from the commander's full journal history, and a layout system
that lets the user choose which windows are shown and where. Multi-session
effort; this document is the running plan and is updated as workstreams land.

**How to use this document:** Each workstream below has a checklist. The data
model, size-class model, and default-layout tables are the canonical
references — update them in the same commit as the code they describe.

---

## Guiding constraints

These hold for every line of code and documentation produced under this plan.

1. **Independent implementation.** Every algorithm, data table, and schema in
   EDLD is written from first principles against the game's journal format and
   publicly known formulae. No code is carried over from any external project.
2. **MIT throughout.** EDLD remains MIT-licensed. Nothing in the tree creates a
   dependency on, or derivative relationship with, any third-party tool.
3. **No external attribution anywhere in the realm.** Code, comments,
   docstrings, docs, config, and UI strings name no outside tool, author, or
   codebase. In-game terminology (e.g. the *Pioneer Supplies* carrier tax, the
   *Pioneer* exploration rank) and the game publisher / journal spec are not
   attribution and are retained.
4. **No overlay.** Neither window renders an in-game overlay. Any datum that
   would otherwise be surfaced only via an overlay is instead presented inside
   the relevant EDLD box (see Workstream D, navigation aids).
5. **Process rules** (unchanged): complete files only, destination table on
   every delivery, Python syntax-validated before delivery, only files modified
   that turn are shipped, and release notes are produced only on explicit
   request.

---

## Workstream 0 — Attribution scrub

Remove residual references to external journal-tooling codebases from existing
comments and docs, keeping all technical content. Affected files are
comment/doc edits only; no behaviour changes. In-game terms and journal-spec
references are retained.

- [ ] README setup-guide wording
- [ ] EDSM component comments
- [ ] Inara component comment
- [ ] Module-name table sourcing comments
- [ ] Ship-name table sourcing comments
- [ ] Status-flag table sourcing comment
- [ ] Re-grep the tree to confirm zero external-codebase mentions remain

---

## Workstream A — Layout foundation

Make the dashboard composition data-driven in both UIs and let the user assign
windows to positions, so the new windows can replace existing ones without
breaking the layout. No visible change ships until Workstreams C/D flip the
defaults.

### Size classes

Blocks are grouped into interchangeable size classes. A position only accepts
blocks of its own class, which is what prevents layout breakage.

| Class       | Members (current + planned)                                   | Std width | Std height |
|-------------|---------------------------------------------------------------|-----------|------------|
| `panel`     | Assets, Engineering, Career, Cargo, Exploration, Exobiology   | 11 / 10   | ~38 rows   |
| `stack`     | Massacre Missions, Navigation, Colonisation                   | 11 / 10   | ~28 rows   |
| `compact`   | Alerts, Crew/SLF                                              | 10        | ~17 rows   |
| `anchor`    | Commander                                                     | 10        | 32 rows    |

Standardised heights are chosen close to today's values so the visible layout
barely shifts. Left and right columns are both 11 units wide, so `panel`/`stack`
blocks swap freely across them; the centre column is 10 units, so its positions
are mutually compatible. Navigation's internal vertical padding is trimmed as
part of fitting it to the `stack` height.

### Position model

- Positions are addressed in spreadsheet notation: column letter (A = left,
  B = centre, C = right) + row index within the column (A1, A2, B3, …).
- Each position carries a size class. Its Preferences > Display selector lists
  only the blocks of that class, plus "(empty)".
- Selecting a block already shown elsewhere moves it; positions left empty close
  up so the column reflows without gaps.

### Tasks

- [ ] Define size classes + per-block class membership in one shared module.
- [ ] TUI: replace the hard-coded `compose()` columns and static per-block CSS
      heights with composition from the same assignment map.
- [ ] Preferences > Display tab (both UIs): per-position class-filtered
      selector, "reset to defaults", live apply without restart where feasible.
- [ ] Persist assignments per commander; migrate existing `layout.json` files.
- [ ] Verify: disabling/enabling any block, in any position, never produces an
      overlapping or zero-size widget in either UI.

---

## Workstream B — Body data layer (build first, per sequencing)

A shared, normalised store of system/body facts plus per-commander scan status,
populated from the full journal archive and kept current during play.

### Storage

- **Engine:** standard-library `sqlite3`, thin hand-written data-access layer.
  No ORM dependency.
- **Location:** one shared galaxy database at the EDLD data root (system and
  body facts are universal); commander-scoped rows for discovery/scan/map state.
- **Migrations:** integer schema version in a `meta` table; forward migrations
  run at startup; version checked before the windows read from it.

### Proposed schema (refined as we build)

| Table             | Purpose                                                              |
|-------------------|---------------------------------------------------------------------|
| `meta`            | schema version, last-import bookmarks                               |
| `journals`        | processed journal filenames (incremental import bookmark)          |
| `commanders`      | id ↔ FID/name, for status segmentation                              |
| `systems`         | name, coords, region, body/non-body counts, population             |
| `system_status`   | per-commander honked / fully-scanned / fully-mapped                 |
| `stars`           | type, subclass, luminosity, mass, distance, rings                   |
| `star_status`     | per-commander discovered / was-discovered / scan-state              |
| `planets`         | class, atmosphere, volcanism, gravity, temp, pressure, radius, materials, terraform state, bio/geo signal counts, rings |
| `planet_status`   | per-commander discovered / mapped / footfall / efficient / scan-state |
| `planet_gas`      | per-planet atmospheric composition                                  |
| `planet_signals`  | per-planet detected biological / geological signal genera          |
| `flora`           | per-planet genus / species / colour                                 |
| `flora_status`    | per-commander sample count / logged / waypoints                     |
| `non_bodies`      | belts, clusters, barycentres                                        |

### Population

- First run / catch-up: reuse the existing startup preload and lifetime journal
  scan to walk the archive once, recording each processed journal in `journals`
  so subsequent launches are incremental.
- Live: the Exploration and Exobiology components write through to the DB as
  scan/map/sample events arrive during play.
- Manual: a "rebuild from journals" action for recovery.

### Tasks

- [ ] DAL module + schema + migration runner.
- [ ] Incremental journal-import walker on top of the preload.
- [ ] Live write-through from the two feature components.
- [ ] Optional external-data enrichment hook (deferred; design only for now).

---

## Workstream C — Exploration window

Replaces Assets in the default layout; Assets ships view-disabled by default.

### Component

Extend the existing exploration provider so it also writes body/value data to
the data layer and exposes a system/body view for the new blocks. Body value
math (base, terraform-bonus range, first-discovery, mapped + efficiency bonus,
honk contribution) already exists in the tree and is reused.

### Window contents (no overlay)

- System header: honk / fully-scanned / fully-mapped / first-footfall markers.
- Main-star value including the honk bonus contributed by all bodies.
- High-value mappable highlights with terraformable / previously-scanned /
  previously-mapped markers and a configurable value threshold.
- Bodies-with-biological-signals callouts.
- Detailed per-body list: type, current value, max-if-mapped value, honk
  contribution, scan/map/footfall status (with "previously done" marker).
- System totals: current value and max-if-fully-mapped value.
- First-fully-scanned / first-fully-mapped system bonuses.

### Tasks

- [ ] Component write-through + system/body accessor for blocks.
- [ ] TUI block (`tui/blocks/exploration.py`) + composition entry + CSS height.
- [ ] Default layout: Exploration into the Assets position; Assets view off.

---

## Workstream D — Exobiology window

Replaces Engineering in the default layout; Engineering ships view-disabled by
default.

### Prediction engine

Independent species-prediction module built from the game's biological criteria
(body class, atmosphere, gravity, temperature, volcanism, parent-star class,
galactic region, nebula proximity). Produces the candidate genera/species and
value ranges for a planet's signals, narrowing to detected genera after mapping
and to the final species as samples are taken.

### Window contents (no overlay)

- System body tracker: shorthand body type + signal counts; gravity warnings
  (high ≥ 1 G, extreme ≥ 2.7 G / non-walkable).
- Per-planet candidate genera/species with value ranges; optional full variant
  breakdown.
- Post-DSS narrowing to detected genera/species.
- Live sample progress (1/3, 2/3, complete) and final per-species value.
- Required sample distance and current minimum distance to the previous sample.
- **Overlay-relocated navigation aids:** nearest-waypoint distance, compass
  heading, and turn-to-heading indicator shown inside the box (the on-foot radar
  graphic is dropped; its useful data is presented numerically here).
- Codex novelty markers: not-yet-logged-in-region and never-seen indicators.
- System totals: analysed value and possible first-find value.

### Tasks

- [ ] Prediction module + value-range calculator.
- [ ] Component write-through (signals, samples, waypoints) + accessors.
- [ ] TUI block (`tui/blocks/exobiology.py`) + composition entry + CSS height.
- [ ] Default layout: Exobiology into the Engineering position; Engineering off.

---

## Workstream E — Parity audit & polish

- [ ] Walk the target feature set end-to-end against live play; close gaps.
- [ ] Confirm every former overlay-only datum has a box home.
- [ ] Performance pass on full-archive import and large-system rendering.
- [ ] `docs/CONFIGURATION.md` entries for the new windows and Display tab.

---

## Default layout — before / after

**Before (current):**

| Column        | Positions (top → bottom)              |
|---------------|---------------------------------------|
| A (left)      | Assets · Engineering · Colonisation   |
| B (centre)    | Commander · Crew/SLF · Alerts · Cargo |
| C (right)     | Massacre Missions · Navigation · Career |

**After (Exploration + Exobiology default-on, Assets + Engineering default-off):**

| Column        | Positions (top → bottom)               |
|---------------|----------------------------------------|
| A (left)      | Exploration · Exobiology · Colonisation |
| B (centre)    | Commander · Crew/SLF · Alerts · Cargo  |
| C (right)     | Massacre Missions · Navigation · Career |

Assets and Engineering remain fully available and one selection away in
Preferences > Display; they are only hidden by default.

---

## Sequencing

1. **This plan.**
2. **Data layer** (Workstream B) — schema, DAL, migrations, journal import.
3. **Layout foundation** (Workstream A) — size classes, positions, Display tab.
4. **Exploration window** (Workstream C) + default flip.
5. **Exobiology window** (Workstream D) + default flip.
6. **Parity audit & polish** (Workstream E).

Workstream 0 (attribution scrub) is independent and runs as soon as approved.

---

## Decisions log

- Data layer is an independent MIT implementation; `sqlite3` (no ORM).
- No external attribution anywhere in the realm; in-game terms and the journal
  spec are retained.
- Neither window renders an overlay; overlay-only data is relocated into boxes.
- Existing TUI layout changes are held to the minimum needed to standardise box
  sizes for interchangeability.

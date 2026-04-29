# EDLD Reports

Reports are accessed from the **Reports** menu in the menu bar. Each report scans
your entire journal history — all `.log` files in your configured journal directory —
and computes statistics across every session recorded there. They are generated
on demand and are not updated in real time.

---

## Career Overview

A lifetime summary of your combat career across all journal files.

- Total kills, total bounties earned, overall kill rate
- All-time top session (kills and bounties)
- Total powerplay merits earned

---

## Bounty Breakdown

Kills and credit earnings broken down by target ship class.

Useful for evaluating which ship types contribute most to session value and
for identifying what the traffic at your hunting grounds looks like over time.

---

## Session History

A chronological per-session table covering every recorded play session.

| Column | Description |
|--------|-------------|
| Date | Session start date |
| Duration | Time from first to last event |
| Kills | Total kills that session |
| Bounties | Total credits earned |
| Kill rate | Kills per hour |

Sessions with zero kills (menu-only, travel, etc.) are omitted.

---

## Top Hunting Grounds

The systems and venues where you have accumulated the most kills across your
journal history.

### Systems

Ranked by total kills recorded in that star system, regardless of whether you
were docked at the time.

### Venues

Ranked by kills recorded while docked at or based from a specific location.
Each venue shows a **Type** column classifying what kind of location it is:

| Type | What it means |
|------|---------------|
| Your fleet carrier | A personal Drake-class carrier you own (identified via `CarrierStats` events) |
| Your squadron carrier | A Javelin-class carrier your squadron owns and you manage |
| Squadron carrier | A Javelin-class carrier you docked on but do not manage |
| Fleet carrier | A Drake-class carrier with no ownership data in your journals |
| Stronghold Carrier | A faction-controlled capital vessel (`StationMegaShip`) |
| Megaship | An NPC megaship |
| Surface installation | Planetary outpost, crater port, or on-foot settlement |
| Asteroid base | Asteroid-embedded station |
| Station / Outpost | Standard orbital station of any class |

For fleet and squadron carriers you have ownership data for, the venue name is
shown as `CALLSIGN (Name)` — for example `BZZ-89N (Vectura)`. The callsign is
permanent; the name reflects the most recently seen value across your journals,
so a renamed carrier will show its current name in future reports automatically.

---

## NPC Rogues' Gallery

A named-pilot hall of records sourced from `Bounty` events across all journals.

### Repeat Offenders

Pilots who appear more than once in your kill record, ranked by kill count.
Because the game reuses NPC names, a high count may represent multiple
different pilots sharing the same procedurally generated name rather than a
single pilot repeatedly respawning.

### Pilots Destroyed (A–Z)

Alphabetical list of every uniquely named NPC pilot you have killed. Excludes
authority vessel pilots (identified by the `$ShipName_Police*` prefix in the
journal), who are tallied separately.

### Pilots Who Killed You

Named pilots recorded in `Died.Killers[]` events — the pilots responsible for
destroying your ship.

### Law Enforcement Interactions

A three-row summary of your interactions with authority vessels:

| Row | Source |
|-----|--------|
| Cargo scans | `Scanned` events with `ScanType = Cargo` |
| Times you destroyed an authority vessel | `Bounty` events where the pilot name begins `$ShipName_Police*` |
| Times authority vessels destroyed you | `Died.Killers[]` entries with `$ShipName_Police*` names |

### Player vs Player

Kills and deaths involving other commanders, sourced from `PVPKill` and
`Died.Killers[]` events where the killer is identified as a player.

---

## Data Sources

All reports read journal files directly from `JournalFolder` as configured in
`config.toml`. Profile-aware: if a profile is active, the profile's
`JournalFolder` is used.

Reports do not write to or modify journal files. Running a report has no effect
on EDLD's live monitoring state.

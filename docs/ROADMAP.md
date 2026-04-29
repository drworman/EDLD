# EDLD Roadmap

Last updated: 20260416

---

## Active / In Progress

*(Nothing currently blocked — see Near-term for next priorities.)*

---

## Released in 20260416

### Data Package Consolidation  ✅ shipped
All inline reference maps (ship names, module types, rank names, engineering
blueprints, status flags) consolidated into a new top-level `data/` package.
Module name normalisation hardpoint size bug fixed.

### Colonisation: Raven Colonial Integration  ✅ shipped
The colonisation plugin is completely rewritten as an integration with
[Raven Colonial](https://ravencolonial.com). Configure an API key via
Preferences to sync supply needs and contributions in real time. Local tracking
works without an API key. Feature remains experimental.

### Two-UI Standardisation Pass  ✅ shipped
GTK4 and TUI blocks audited and aligned — Career detail tabs,
Colonisation resource layout, Crew/SLF row order, Session Stats duration row,
cargo alpha sort, mission stack height row, and colonisation total alignment.

### Commander Block Bug Fixes  ✅ shipped
- Shields key label no longer overwritten with "Hull" on every refresh
- Home system distance now displays immediately on login

### Carrier Cargo Value  ✅ shipped
Fleet carrier cargo galactic-average value now populates correctly in the
Assets block and net worth calculation.

### GitHub Actions: Node.js 24  ✅ shipped
All workflow actions updated to Node.js 24 native versions; deprecation
warnings eliminated.

---

## Released in 20260325

### At-Risk Holdings Tracker  ✅ shipped
Persistent cross-session tracker for bounties, combat bonds, trade vouchers, cartography, and exobiology. Survives session resets. Zeroed on death.

### Assets Block: Wallet Redesign  ✅ shipped
Fleet, Fleet Carrier, At Risk, and Net Worth sections inline. Dynamic tab counts. Credit balance from Status.json polling.

### Commander Block: SRV and On-Foot State  ✅ shipped
Header and vitals reflect vehicle — ship, SRV, or on-foot. Suit name and loadout shown on foot.

### EDDN: Schema Compliance and FC Market  ✅ shipped
Preload guard, NavRoute, fcmaterials_capi/1, commodity/outfitting schema fixes, blackmarket removed.

---

## Released in 20260327

### Session Summaries: Fixed and Redesigned  ✅ shipped
Summaries now fire reliably at :00, :15, :30, and :45 of every hour regardless of activity type (exploration, trade, missions, combat — all covered). The trigger runs on every processed journal event so it fires even during active play when the journal is written continuously. The old combat-only timer is removed.

Output is reformatted with aligned columns: values right-justify to a shared column and the `|` delimiter lines up across all rows. Duration is a header row. Each activity section appears only when it has data.

### Session Summaries: Condensed Activity Rows  ✅ shipped
- **Exploration:** Distance and jump count combined into one row; bodies scanned shows unsold cartography estimate as the rate field
- **Missions:** Completed count and credits combined into one row
- **Exobiology:** Samples and held/sold value combined into one row
- **Mining:** Tonnes refined with galactic average value estimate as the rate field

### Update Notifier: Release-Only  ✅ shipped
The update check now only notifies when a newer release tag exists on GitHub. Post-release commits on `main` no longer trigger a notification. Version comparison handles lettered patch releases correctly (20260325a < 20260325b < 20260326).

### Assets Block: Module and Credit Updates  ✅ shipped
Credits update live from `Status.json` (updated every ~500ms by the game) instead of waiting for a CAPI poll. Ship value now correctly includes `ModulesValue` from `Loadout`. `ModuleRetrieve`, `ModuleStore`, `ModuleBuy`, `ModuleSell`, `ModuleSwap`, and `ShipyardSwap` subscribed so tab counts refresh immediately.

### Cargo Block: Station Restore on Startup  ✅ shipped
The target station now restores correctly from the saved market ID on startup rather than running a fuzzy name search that could match a different station with the same name.

### Holdings Tracker: Voucher Bootstrap  ✅ shipped
On first run (no prior `holdings.json`), the tracker scans journal history from the most recent `Died` event forward to reconstruct unredeemed voucher balances. Previously earned bounties and bonds that predated EDLD were invisible until cashed out.

### Holdings Tracker: Dedup Fixes  ✅ shipped
Cartography and exobiology dedup sets persist across restarts via JSON-safe serialisation, preventing double-counting on preload replay.

### NPC Crew / SLF: Bootstrap and Display Fixes  ✅ shipped
- `bootstrap_fighter_bay` pre-scan ensures the fighter bay flag is set before dependent bootstraps run
- SLF variant bootstrap skips `RestockVehicle` events with no `Loadout` field (Frontier omits it when only one variant is stocked), scanning further back to find the specific variant
- Same fix applied in `_bootstrap_type_from_journals`

---

## Released in 20260328

### JetBrains Mono: Bundled Default Font  ✅ shipped
Bundled in `fonts/`, copied to `~/.local/share/EDLD/fonts/` on first launch and registered
with PangoCairo per-process. No system font directories touched. Falls back to system
monospace if files are absent.

### Font Preferences  ✅ shipped
Font Family dropdown (monospace-only, from Pango font map) and Font Size spinner (10–24 px)
in Settings → Appearance. Both saved to `config.toml [GUI]`, require restart.

### CSS Theme Template: Community Contribution  ✅ shipped
`themes/custom-template.css` overhauled with full inline documentation.
Contributed by [Maldor](https://github.com/Maldor) via [PR #2](https://github.com/drworman/EDLD/pull/2).

### Session Stats: Pipe Alignment Fixed  ✅ shipped
Summary tab now uses a single shared `Gtk.Grid` across all sections so `|`
delimiters align globally regardless of value widths across Combat, Exploration,
Missions, etc.

### Assets Block: Sold Ships Now Removed Immediately  ✅ shipped
`ShipyardSell` subscribed — sold ship removed from cache and display without waiting
for `StoredShips`. `_ship_loadout_cache` also pruned against `StoredShips` on startup
when CAPI is unavailable.

### Assets Block: Decommissioned Carrier Removed  ✅ shipped
`CarrierDecommission` subscribed — `assets_carrier` cleared immediately.

---

## Near-term

### Context-aware Commander block
The Commander block shows fixed rows regardless of vehicle. Rows should adapt:

- **On foot:** Fuel → Battery (suit), Shields/Hull → Suit Shield/Health
- **SRV:** Fuel → SRV Fuel, Shields/Hull → SRV Hull
- **Fighter:** Already partially handled (header shows `[In Fighter]`)

Data sources: Status.json Flags bits, Odyssey journal events, `VehicleSwitch`.

---

## Planned Blocks

### Mining Block
Real-time mining session display: prospected asteroids with yield distribution, refined commodities with value estimate, session efficiency.

### ExoBiology Block
Per-body scan progress with species names and estimated values, unanalysed sample indicators, session earnings.

### Combat Zone Block
Active CZ tracking separate from Session Stats: faction, intensity, bonds and rate for the current zone.

---

## Deferred / Parked

### Profile Switcher GUI
Selector in menu bar, create-new-profile dialog, restart with `-p PROFILENAME`.

### Squadron Carrier Support
Fleet carriers owned by a squadron are not tracked — journal coverage is incomplete.

### Web UI / HTTP Dashboard
Built-in HTTP server with SSE for browser-based remote monitoring. Deferred until GTK GUI reaches stable feature set. See extended design notes in git history.

---

## Known Limitations / Technical Debt

- Stored ship loadouts are only as current as the last time each ship was boarded
- Carrier finance field paths have multiple fallbacks but have not been confirmed across all carrier types — use `--trace` if values are missing
- GTK progressbar warning on close (`GtkGizmo min width -2`) — intentionally set aside
- Block collapse state is not persisted across restarts
- SLF shield state is not tracked — not exposed via journal or Status.json
- Minor faction reputation reflects only the current system; absent between sessions
- On-foot health not shown (requires Status.json field not currently polled)

**Pending docs:** Document CAPI vs. journal tradeoffs for the fleet roster in `docs/CONFIGURATION.md` — what is and isn't available when CAPI is disabled.

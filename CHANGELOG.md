# EDLD CHANGELOG

Last updated: 20260811

---

## Released in 20260811

The headline change is that EDLD is cross-platform again, with a desktop
interface alongside the terminal one and prebuilt binaries for Linux, Windows
and macOS.  Because the project no longer runs only on Linux, it has been
renamed.

### Renamed: ED Linux Dash is now ED Live Dashboard

"Linux" in the name had become wrong.  The acronym, the GitHub repository, the
data directory at `~/.local/share/EDLD/` and every config key are unchanged,
so there is nothing to migrate — existing installs pick the new name up and
carry on with the same config, the same per-commander data and the same window
layout.

### New: desktop interface (`--gui`)

A PySide6 desktop window rendering the same dashboard as the terminal
interface.  It is built from the same layout model and the same components, so
the two show the same windows in the same positions with the same data;
Preferences → Display drives both.

All fourteen windows are present — Career, Session, Ship Health, Commander,
Crew/SLF, Alerts, Cargo, Missions, Navigation, Colonisation, Exploration,
Exobiology, Assets and Engineering — along with the preferences dialog, the
home-location and target-market search pickers, the update notice and the
session-management controls.  Columns are draggable splitters, initially sized
from the layout model's own proportions.  Window controls are the platform's
own: minimise, maximise, snap, tiling and the close button all behave as the
desktop expects, on all three operating systems.

All eight themes render in both front ends, custom themes included; the
palettes moved to `core/palette.py` so a theme added once appears in both.

The terminal dashboard remains the default.  Nothing about it changed.

### New: `--tui`, `--gui` and `--terminal`

The three interfaces now have flags of their own.  `--mode textual|terminal|gui`
still works and means the same thing; passing both a flag and a conflicting
`--mode` is an error rather than a silent resolution.  `UI.Mode` in
`config.toml` accepts `gui` as well.

Two diagnostic flags are new:

- `--version` prints the version and exits before touching config, journals or
  components, so it answers on a machine that has never run Elite Dangerous.
- `--selftest` imports both front ends and reports on each.  A packaged build
  can start cleanly and still be missing a lazily-imported module that only
  fails when the dashboard is drawn; this turns that into something the
  release workflow can catch on every platform.

### New: cross-platform binaries

The release workflow builds single-file binaries for Linux, Windows and macOS
alongside the source tarball, with optional code signing and macOS notarisation
that skip cleanly when the secrets are absent.  Windows and macOS users no
longer need a Python install.

Pushing a version tag now publishes the release itself: notes are taken from
this changelog, artefacts and checksums are attached, and a version suffix such
as `-rc1` marks it a prerelease.  A manual dry run builds everything without
publishing.

Every artefact is smoke-tested before publication.  This is not ceremony — a
binary that cannot load its own components starts perfectly and shows an empty
dashboard, which is indistinguishable from a working build until you notice no
data ever arrives.

### Fixed: HTTPS failed in every packaged build

A frozen binary carries its own OpenSSL, compiled with the *build* machine's
certificate paths baked in.  Those paths do not exist on most target machines,
so certificate verification failed for everything and every network feature
stopped working at once — CAPI returned no profile, which is why the Commander
window lost its squadron line and its ranks, and EDDN, EDSM, EDAstro, Inara and
Spansh all went quiet.

Nothing crashed, which is what made it hard to spot: each failure was a single
unremarkable warning line and none of them said "none of this is going to
work".

Binaries now ship a CA bundle and point OpenSSL at it before anything opens a
connection, leaving a deliberately-set `SSL_CERT_FILE` alone.  Startup records
one line saying where verification will look, so the next report of "uploads
stopped" is answered outright.

### Fixed: components did not load in a packaged build

`core/plugin_loader.py` discovers components by globbing `components/*.py` and
loads each by file path, which gives every component its own module namespace
and a sandboxed `open()`.  In a one-file build the sources live in the compiled
archive rather than on disk, so the glob matched nothing and the dashboard came
up with every window permanently empty.

The component sources now ship as bundled data as well as compiled code, and
the loader looks under the extraction directory when frozen.  The loading
mechanism, including the sandbox, is unchanged.

### Fixed: the terminal dashboard would not start in a packaged build

`textual.widgets` resolves its widgets lazily through a module-level
`__getattr__` that imports by a name built at runtime.  Static analysis cannot
see through that, so the build bundled only the widgets something imported
directly and dropped the rest; `--tui` then died at startup with
`No module named 'textual.widgets._tab_pane'`.  All of Textual is now collected
explicitly.

### Fixed: a dashboard that failed to start said nothing

`--tui` and `--gui` route stdout and stderr to `/dev/null` before components
load, so terminal noise cannot corrupt the display.  Correct, but it also meant
an exception during dashboard startup vanished: the process exited non-zero
with no message anywhere, including the diagnostic log.

Both launch paths now record a failure in the diagnostic log and on the real
stderr, and `EDLD_KEEP_STDERR=1` leaves both streams attached for cases the log
cannot reach.

On Windows a startup crash was worse still: the windowed build rendered the
traceback in a modal dialog and waited for a click, so a crash presented as a
hang.  That dialog is disabled.

### Fixed: missing psutil stopped EDLD from starting

`core/journal.py` imported psutil at module scope, although the only use is one
fallback process-name scan already wrapped in `try`/`except`.  Since psutil is
documented as a distro-package install, a source install legitimately might not
have it — and then EDLD would not start at all.  The import is now guarded in
both `core/journal.py` and the session-management component, which reports the
reason instead of disappearing.  Binaries bundle psutil, so nothing is lost
there.

### Fixed: bracketed text was dropped from display strings

The dashboard blocks build their display strings with console markup, and the
desktop front end translates that markup into rich text.  Any bracketed token
that named no known tag was discarded — silently eating squadron tags rendering
as `[SOL]` and faction names of the form `[XYZ] Corporation`.  Unrecognised
bracketed tokens are now passed through as literal text.

### Changed: Crew / SLF header

A fighter's model and its variant are one designation — `GU-97 (Gelid G)` — and
they now appear together, on the right of the header row, in both front ends.
Previously the model sat on the header row and the variant was parked at the
end of the combat-rank line, so neither line read as a complete answer to what
the crew was flying.  The combat-rank line now shows only the rank.

### Licensing

The desktop interface adds Qt, so the project now carries an LGPL v3 obligation
alongside its own MIT licence.  `docs/LICENSING.md` sets out how each condition
of LGPLv3 section 4 is met, `THIRD-PARTY-NOTICES.md` lists every dependency,
and the GPL and LGPL texts ship in `licenses/` inside every binary and every
release archive.  `docs/BUILDING.md` covers building from source and relinking
against your own Qt.

Qt is never statically linked and UPX stays disabled; both matter for the above
and both are enforced in `packaging/`.

The disclaimers and trademark notice have moved out of `LICENSE` and into the
README, so the file is now the MIT text alone and GitHub detects the licence
correctly again.

### Support links

The desktop window carries a "Support EDLD Development" strip along the bottom
with Patreon, Ko-fi and PayPal icons, and the same links appear in Help →
About.  The destinations are read from `.github/FUNDING.yml` at runtime rather
than hard-coded, so there is one place to change them.  The strip can be hidden
from the View menu.

---

## Released in 20260809

### Session Summary: New window
Current-session activity has moved out of the Career block's Summary tab
into a Panel-classed window of its own.  Sharing one tab meant the session
view and the career view were each squeezed into half the height; both now
get a full window.

The new window also shows considerably more.  Where the Career tab inlined
each activity component's condensed summary rows, the Session window
renders their full detail: notable bodies and habitable zones from
Exploration, the in-progress scan with clonal distance from Exobiology,
per-commodity profit from Trade, limpet efficiency and per-commodity yield
from Mining, and per-system merits from PowerPlay.  Ctrl+R resets it as
before, and the window now repaints immediately on reset rather than
waiting for the next journal event.

### Career: Summary tab rebuilt
The Summary tab showed three wealth rows and little else — not much of a
career summary.  It now pulls the headline figures from every other tab
into one place: wealth and career scale, combat, exploration, exobiology,
mining, trade, missions, on-foot, PowerPlay, fleet carrier, and the top
earning and spending categories from the lifetime ledger.

Both windows are built from one shared model
(`core/summary_model.py`), which emits the same sections in the same order
for both scopes.  They are meant to show the same things — one scoped to
the current session, the other to the whole career — so they are generated
from a single source rather than two renderers that would drift apart as
either side is maintained.

Two smaller reporting errors surfaced while building it.  Zero-valued
entries no longer occupy a row rendering as an em dash.  And ship NPC crew
wages from Statistics are now labelled distinctly from the fleet carrier's
own crew upkeep, which appears separately in the spending ledger under a
near-identical name.

### PowerPlay: merits are now scoped to the current pledge
The lifetime scan accumulated merits across every allegiance the commander
had ever held.  A commander who has swapped powers a few times saw a merit
total belonging to nobody in particular — merits earned for a power they
had long since left, summed together with the current one.  Those merits
bought standing with a power that no longer counts them; carrying them
forward tells you nothing about where you stand now.

Every PowerPlay counter — merit total, merits by activity, and merits by
system — is now cleared at each pledge boundary, so what the Career block
reports belongs to the current allegiance alone.  The intended behaviour
was described in a comment on the old code but only partly implemented:
`PowerplayLeave` cleared the system tally and total while leaving the
by-activity breakdown intact, and `PowerplayDefect` — the very case that
matters most — was matched but then did nothing at all.

Boundaries are now taken from `PowerplayJoin`, `PowerplayDefect` and
`PowerplayLeave`, and additionally from any observed change of power on a
`Powerplay` login snapshot or a `PowerplayMerits` grant, which recovers the
case where the pledge event itself falls outside the scanned journal range.
Where no Join event is available, `Powerplay.TimePledged` is used to date
the pledge.

The Career block's PowerPlay tab and the Summary tab now both show the
power pledged to and how long ago, merits earned this cycle (the server's
figure, which resets weekly), and merits earned since the pledge began —
labelled separately, because they count different things.

### Ship Health: New window
A new Panel-classed window for neutron hoppers, who need to know before
each leg whether anything wants repairing.  Hull sits in the first row and
shields in the second, then a rule, then every fitted module sorted by
power priority and — within each priority group — by health ascending, so
whatever most needs an AFM unit pointed at it floats to the top of its
group and cannot hide in the middle of a thirty-row list.  The Modules
header carries a count of anything below full health.

Per-module condition is tracked by a new `ship_health` component.  Nothing
else in EDLD carried it: `ModulesInfo.json` has `Priority` but no `Health`
at all, and the Assets component parses `Loadout` for value and engineering
rather than condition.  `Loadout` is the only source carrying both fields
together, so it provides the baseline and `AfmuRepairs`, `Repair`,
`RepairAll`, `RebootRepair` and `HullDamage` are applied incrementally on
top.  The component seeds itself from the most recent `Loadout` on disk at
startup, so the window has content before the first one of the session
fires.

Power priority is displayed 1-based to match the in-game power distribution
panel; the journal reports it 0-based.  Paint jobs, decals, nameplates,
ship kits, engine and weapon colours and voice packs are filtered out — all
report priority 1 and full health forever, and would otherwise pad the
first priority group with a dozen rows that can never need repair.

### Display
Both new windows are Panel class, so either can be assigned to any Panel
position from Preferences > Display.  The position layout itself is
unchanged — the left and right columns hold three Panel windows each, which
is what fits on screen at a readable height.  There are now eleven Panel
windows for seven positions, so placing Session or Ship Health means
choosing what it replaces, as it already did for the other windows.

---

## Released in 20260614

### Session Management: New
EDLD can now automatically quit Elite Dangerous when a condition you
configure is met — an optional safeguard that is off by default.  It is
hard-gated to Solo mode and will never act in Open or Private Group:
force-quitting in a shared mode is combat-logging under Frontier's rules,
so the gate is enforced at the moment of termination and even a manual
activation is refused outside Solo.

Triggers cover a destroyed ship-launched fighter, low hull, and low
main-tank fuel — a percentage threshold, optionally combined with
estimated burn-time remaining, and suppressed while in supercruise and
for a short grace period after exiting it.  A separate idle trigger quits
after a configurable number of minutes without an NPC kill while dropped
in a Resource Extraction Site of any tier; the RES requirement keeps it
from firing during ordinary idle time, since AFK kill-farming happens
nowhere else.

Termination runs locally by default, or on another machine over SSH for a
remote monitoring setup.  Press Ctrl+K to arm or disarm it at runtime —
the header shows ✕ when armed and □ when idle.  Settings live in a new
`[SessionMgmt]` section: a master `Enabled` switch plus per-trigger keys,
all scopable per profile like any other setting.  A new Session Management
guide and a configuration-reference section document every key.

### Configuration
Configuration now resolves through a single profile → global → default
path for every section.  The older profile-only lookup that some advanced
keys relied on has been retired, so any setting — including the new
Session Management keys — can be defined globally and overridden per
profile in the usual way.

---

## Released in 20260613

### GTK4 UI Discontinued
The GTK4 graphical interface has been removed.  EDLD now ships a single
interface — the Textual TUI dashboard — with a plain scrolling terminal
mode (`--mode terminal`) still available.  `--mode textual` is the default,
and any existing config carrying `Mode = "gtk4"` is treated as `textual`
automatically.  All GTK4 code, bundled fonts, theme stylesheets, and the
PyGObject / GTK4 dependencies are gone; `requirements.txt`, `install.sh`,
and the documentation no longer reference them.

### Dashboard Layout
The default arrangement is now Career / Cargo / Missions on the left,
Commander / Crew / Alerts / Exploration in the centre, and Navigation /
Colonisation / Exobiology on the right.  Every interchangeable window is a
single Panel size class — the former Tall class is gone — so any window can
occupy any non-fixed position.  Commander, Crew, and Alerts remain fixed:
Commander spans one Panel and Crew + Alerts together span one Panel, so the
rows line up across all three columns.

### Cargo
The manifest's quantity and credit columns are fixed-width, so the `|`
separator lands in the same column on every row.  The station · system
label in the title bar now uses a middle dot instead of a pipe so it no
longer collides with the body columns.

### cAPI OAuth
Frontier cAPI authentication now uses a fixed-port loopback redirect
(`http://127.0.0.1:28473/callback`, per RFC 8252) with CSRF state
validation, replacing the previous hosted callback page.

### Inara
Community-goal contributions are now submitted to Inara — the bare
`CommunityGoal` journal event is handled and the event field names were
corrected — so goal progress is reflected on your Inara profile.

---

## Released in 20260531

### Exploration Window: New
A dedicated Exploration block — selectable in any layout position and on
by default — summarises every body the commander has scanned in the
current system.  For each body it shows the current scan value and the
full mapping value (the credits still on the table from a DSS map plus
the efficiency bonus), alongside markers for high-value bodies (`★`),
terraformable worlds (`T`), biological signal counts (`◆N`), mapped
status (`✓`), first discovery (`FD`), and first footfall (`FF`).

First discovery and first mapped come straight from the journal's
`WasDiscovered` / `WasMapped` flags, so they are authoritative; first
footfall is inferred from an undiscovered, landable body.  The header
tallies bodies scanned, the worth-mapping count, bodies with biology,
and how many are still undiscovered or awaiting a first footfall, plus
the running value-now / value-max for the system.  Available in both
GTK4 and the TUI.

### Exobiology Window: New
A dedicated Exobiology block tracks biological signals and sampling
progress per body and — the headline feature — predicts what is likely
to be present *before* a surface scan, so a commander can judge whether
a body is worth landing on.

- **Pre-landing prediction.** From a body's atmosphere, planet class,
  gravity, surface temperature, pressure, and volcanism, the block lists
  the genera that can occur and an estimated credit range for the signal
  count, with a `✦ first footfall ×9` flag on untouched bodies.  Species
  that need a location condition the dashboard cannot verify (region,
  nebula proximity, a specific star, an atmosphere component) are
  surfaced but marked *conditional*.
- **Post-DSS narrowing.** Once a surface scan reveals the genera, those
  become authoritative and the estimate narrows to them.
- **Sampling progress.** Each logged or in-progress species shows its
  stage (`1/3` → `✓`), value, and the genus clonal-distance requirement.

### On-Foot Clonal-Distance Aid
While on foot, the Exobiology block focuses the body you are standing on
(floated to the top and marked `▸`) and, for each species you are part
way through sampling, shows a live aid: a compass arrow toward your
nearest previous sample, the distance to it, the clonal-distance
requirement, and whether you have moved far enough yet (`clear ✓` /
`too close — move away`).  Sample positions are recorded from live
surface coordinates as you scan, and distances are computed as
great-circle arcs on the body's actual radius.  Live position is read
from `Status.json` on a throttled refresh while on foot.

### Species Prediction Engine
Prediction is driven by a species-level condition catalog
(`core/exobio_rules.py`, 115 species) written from first principles
against the game's body data, paired with a matcher
(`core/exobio_predict.py`) that tests each species' tolerated
atmospheres, body classes, gravity, temperature, pressure, and volcanism
against a body, plus a verified per-species value table.  Body pressure
is converted from pascals to atmospheres for the comparison, and any
property a body has not yet exposed never excludes a candidate.

### Configurable Window Layout
A shared, UI-agnostic layout model (`core/layout_model.py`) now defines
which blocks appear and where, across three columns, for both UIs from a
single source.  A new **Display** tab in Preferences (GTK4 and TUI) lets
you assign a block to each position — class-filtered so panel, tall, and
compact slots only offer blocks that fit — with the choice persisted per
commander.  The default layout now leads with Exploration and Exobiology;
Assets and Engineering remain fully available and can be re-enabled from
the Display tab.

### Shared Body Data Layer
Both windows read from a shared SQLite store of systems, bodies, signals,
and flora, fed from the commander's journal history and kept current
during play, with per-commander sampling status and recorded sample
waypoints.

---

## Released in 20260515

### Reports Feature: Removed
Reports menu, viewer, and registry have been removed entirely across all
UIs.  Nothing in the codebase invoked the report flow at runtime and the
feature wasn't in use — deleting it sheds ~1,700 lines and simplifies
the menu surface.  Removed: `core/reports.py`, `gui/reports_viewer.py`,
`tui/reports.py`, the Reports menu entry in the GTK4 menubar, the
`r → Reports` keybinding in the TUI, and `docs/REPORTS.md`.

### Career Block: Financial Ledger Rewrite
The Career block now carries a proper journal-derived earnings and
spending ledger.  In-game Statistics fields like `Trading.Goods_Sold`,
`Trading.Data_Sold`, and `Trading.Assets_Sold` sit at zero for many
commanders even after hundreds of tonnes sold, so journal events are
now the authoritative source for trade activity and credit flows.

The new ledger covers 27 credit-moving event types — `Bounty`,
`RedeemVoucher` (typed: bounty / combat bond / settlement / scannable /
trade), `FactionKillBond`, `MissionCompleted` (rewards and donations),
`MarketSell` (revenue + profit), `MarketBuy`, `MultiSellExplorationData`,
`SellOrganicData`, `SearchAndRescue`, `SellMicroResources`,
`CommunityGoalReward`, `ShipyardBuy/Sell/Transfer`, `ModuleBuy/Sell/
BuyAndStore/SellRemote`, `BuyAmmo/RefuelAll/Repair/RepairAll/RestockVehicle/
BuyDrones`, `BuySuit/BuyWeapon`, `PayBounties/PayFines/PayLegacyFines`,
`Resurrect`, `Donate`, `CarrierBuy`, `NpcCrewPaidWage`,
`CarrierTradeOrder`, `CarrierDepositFuel`, `CarrierBankTransfer`,
`CarrierFinance`, and `LoadGame.Credits`.

Tab structure (both GTK4 and TUI):
- **Summary**: live wealth breakdown — Net worth, Liquid credits,
  Carrier bank — sourced from `state.assets_balance`,
  `state.assets_carrier.balance`, and computed from ship/module values
  with `Statistics.Bank_Account.Current_Wealth` as a floor.
- **Combat**: kills, bounties, bonds, plus a Voucher status section
  showing issued vs redeemed and the unredeemed pending balance.
- **Explore**: journal-derived FSS and DSS counts, first-discovery
  counts, notable body counters (ELW, water world, ammonia, neutron,
  black hole, terraformable).
- **Exobio**: per-genus credits breakdown alongside Statistics totals.
- **Mining**: tonnage refined, profit, per-tonne yield.
- **Trade**: journal-derived `tonnes sold`, gross revenue, net profit,
  largest transaction, profit per tonne — no longer trusts the broken
  `Statistics.Trading.Goods_Sold` field.
- **Credits**: lifetime earnings (every income category with %),
  lifetime spending (every spending category with %), carrier-bank
  flow (current balance + reserve + available + lifetime deposits/
  withdrawals), and voucher reconciliation.
- **Carrier**: identity, capacity, fuel, jump range, full bank section,
  lifetime travel, and services rendered.
- **PPlay**: merits by activity attribution and by-system top 20.

### Live State for Wealth Display
Liquid credits and Net worth now read from `state.assets_balance` and
the live state pieces maintained by the Assets plugin (CAPI snapshots +
`LoadGame` + `Commander` + `CarrierFinance` events).  The previous
implementation used `LoadGame.Credits` from the journal scan, which can
be stale by many millions when the most recent journal is hours old.
Net worth is now `max(Statistics.Bank_Account.Current_Wealth,
liquid + ships + modules + carrier_bank + at-risk_holdings)` — the
Statistics figure is the floor, not the ceiling, so credits earned
since the last `Statistics` event aren't hidden.

### Inara Uploader: Default-Enabled + Diagnostic Logging
The Inara plugin's `PLUGIN_DEFAULT_ENABLED` was `False`, which meant
that even with `[Inara] Enabled = true` in `config.toml` the plugin
loader's `plugin_states.json` gate kept it from instantiating unless
the user had also toggled it on in the Installed Plugins dialog.
Switched to `True` matching the other integration plugins (EDDN, EDSM,
EDAstro) — the `cfg["Enabled"]` check inside `on_load` is still the
final gate, so setting `Enabled = false` in config continues to
suppress uploads.

All 12 `print()` calls in `components/inara.py` migrated to
`debug.info()` / `debug.log()`.  Bare `print()` in GTK4 mode goes to
`/dev/null` after the fork-early restructure, which silently hid every
Inara error — including the API-key-rejected case that previously
looked like "nothing's happening at all".  Added sender-thread
lifecycle logging (entry banner with queue file path, per-minute
heartbeat with push count + batch size, per-batch POST log with event
count + commander, per-batch acceptance log with HTTP status and
`header_status`).

### EDSM Routing: User-Agent Header
The EDSM-based FSD router and carrier id64 resolver were returning
`HTTP 403 Forbidden` because the helper sent no `User-Agent` header.
EDSM blocks the default `Python-urllib/X.Y` UA.  Helper now sends
`User-Agent: EDLD/1.0 (+routing helper)`, matching the pattern used by
the rest of the codebase (EDDN, EDAstro, EDSM uploader).

### Carrier Routing: Marked UNFINISHED  ⚠ disabled
The Spansh fleet-carrier API integration was reverse-engineered from
sample JSON responses but result-endpoint discovery remains unresolved.
POSTs to `/api/fleetcarrier/route` return `HTTP 202` but the returned
job UUID doesn't surface at any documented results path.  Switched the
primary POST endpoint to `/api/fleetcarrier/search` and expanded the
polling candidate list to include both
hyphenated (`/api/fleet-carrier/results/<id>`) and no-hyphen variants,
but live testing still failed.  The carrier tab now displays an
UNFINISHED banner, all inputs and the plot button are disabled, and
the tab label is suffixed with `⚠` in both GTK4 and TUI.  FSD and
Neutron routing remain fully functional.

### Mission Stack: Renamed for Clarity
"Mission Stack" → "Massacre Mission Stack" everywhere — the block only
tracks massacre missions and the old name was misleading commanders
who expected courier / passenger / data deliveries to appear there.
GTK4 `gui/blocks/missions.py`, TUI `tui/blocks/missions.py`, GUI app
plugin registry, and Career block cross-references all updated.

### Journal History: Comprehensive Money-Flow Tracking
`components/journal_history.py` now publishes a `finance` section in
its results with `in` and `out` dicts (sorted by amount, descending),
a `market_sell` trio (count / revenue / profit), `vouchers` issued vs
redeemed, and `liquid_credits` from the latest `LoadGame`.  The
`carrier` section gained `bank_balance`, `bank_reserve`,
`bank_available`, `bank_deposits`, and `bank_withdrawals` from
`CarrierFinance` and `CarrierBankTransfer` events.  Frontier ships
`MissionAccepted.Donation` and `MissionCompleted.Donation` as JSON
strings — the new accumulators coerce safely with `_fin_in` / `_fin_out`
helpers.

### Spansh Routing: FSD + Neutron Confirmed Working
The Spansh route API behaviour was reverse-engineered from real
session responses.  `HTTP 202` from the route POST means accepted, not
failed (the previous code treated it as an error).  Neutron routing
correctly distinguishes total waypoints (`total_jumps` for galaxy-map
plotting) from actual jumps (sum of per-waypoint `jumps` fields) —
validated end-to-end on a 129-waypoint / 165-jump Skogulumari → Colonia
plot.  The FSD tab now uses the EDSM system database for genuine
jump-by-jump routing (Spansh's `/api/route` is fundamentally a neutron
router and never made sense for vanilla-FSD plotting).

### Plugin Loader: Storage Layout Flattened
Per-plugin data moved from `<cmdr>/plugins/<X>/data.json` to
`<cmdr>/data/<X>.json` with sidecar files at `<cmdr>/data/<X>.<purpose>.{json,jsonl}`.
Cleaner layout, single directory per commander, simpler debugging.  A
one-shot migration runs at startup and moves any legacy files
automatically.

### Debug Log: File-Based Diagnostic Channel
New `core/debug.py` module providing `debug.info()` / `debug.log()`
sinks that write to `<data_dir>/logs/error[_<profile>]_<YYYYMMDD>.log`.
Necessary because GTK4 mode forks early and dups `stdout` / `stderr`
to `/dev/null` on the child, which silently discarded every `print()`.
Plugins migrated incrementally — Inara is fully migrated; others are
following.

### Session Stats Block: Removed
The standalone Session Stats block in both UIs has been deleted, its
content folded into the Career block's Summary tab.  Activity rows
from registered session providers now appear under a "Current session"
section in the Summary tab.  Reset is still on `Ctrl+R` (TUI) or the
↺ button (GTK4) — both call `session_stats.on_new_session(0)`.

### TUI/GTK4 Parity Pass
TUI Career block fully rewritten to mirror the GTK4 9-tab structure
with the financial ledger, voucher reconciliation, and live-state
wealth display.  TUI Missions block renamed to `MASSACRE MISSION
STACK`.  TUI app docstring refreshed.  Default block layout sync'd
(no more `session_stats` or `session_mgmt` entries).

---

## Released in 20260506

Fixes for CAPI and some initial math for total assets calculation.

---

## Released in 20260429

Initial fork from the previous drworman/EDMD (project has been abandoned)

# EDLD CHANGELOG

Last updated: 20260909

---

## Released in 20260909

### Fixed: the SRV's cargo was priced from a different market than the ship's

Per-unit value is a property of the commodity and the chosen price source.  It
does not depend on which vessel the tonne is sitting in, but the Cargo tab said
otherwise: the ship's manifest resolved the target station's sell price, or the
docked station's, falling back to galactic average, while the SRV's manifest
only ever read `cargo_mean_prices`.  Docked at Metz Enterprise in Ega, 33 tonnes
of osmium in the Rhino read 44,051 a tonne against the same ore's 264,306 in the
ship's hold, a sixfold difference on identical cargo.

It was invisible for three reasons.  Both figures are plausible on their own,
and nothing in the panel invites comparing them.  The panel prints one
price-source label above both sections, so the SRV rows appeared to come from
the market named in the header when they never did.  And the error is not a
consistent offset that could be eyeballed — sell price runs several hundred per
cent over galactic average on osmium, painite and ruby, and forty to sixty per
cent under it on alexandrite, low temperature diamonds and the other high-value
gems, so the SRV read high on some cargo and low on other cargo in the same
hold.

The sorts diverged with the prices.  Freight is ordered cheapest per tonne first
so that a full hold answers the question of what to jettison, but the ship
ordered on the resolved price and the SRV on galactic average, which are
different orderings of the same manifest.  The SRV section also had no limpet
handling at all, so limpets sorted in with freight and headed the jettison list
at around a hundred credits a tonne — the exact placement the ship's manifest
was changed to avoid.

Pricing, limpet separation and ordering now live in `core.ui_helpers`, in
`cargo_price_context()` and `cargo_manifest()`.  One context is built per
repaint and every hold in that repaint is valued against it, so the two
manifests cannot answer the same question differently.  Both front ends call
the same functions; neither prices anything locally any more.

The two expressions sat eighty lines apart in one method, duplicated across the
TUI and the GUI, which is why the front ends agreed with each other and both
disagreed with themselves.  A structural test now asserts the shape rather than
the output — one price context per panel, one manifest call per hold, no price
arithmetic left in either block — because a test that only exercises
`cargo_manifest()` would not notice a future edit that open-codes a lookup in a
renderer again.


### Fixed: the SRV totals line was assembled by string surgery

It rendered a manifest row with a price of zero and then replaced the
formatted zero back out to blank the column, which produced the right output
only for as long as the credit formatter's output stayed exactly nine
characters wide.  Both totals lines — the ship's and the SRV's — are now built
by `cargo_totals_cols()` alongside the manifest's own `cargo_cols()`, from one
set of column widths, so the separators cannot drift apart.

`_fmt_cr` and `_cargo_cols` moved to `core.ui_helpers` with them.  They were
byte-identical copies in the TUI and the GUI, which is the arrangement that let
the two price paths diverge in the first place.  Both names remain importable
from either block module.

### Changed: the SRV totals line shows capacity where it is known

It read "Carrying 41 t" while the ship's read "62/256 t", so there was no way
to tell from the panel how much room was left.  It now reads "41/72 t" in the
same columns.

The game never reports a surface vehicle's cargo capacity.  `LaunchSRV` gives
only a loadout name, a `Cargo` event for a surface vehicle carries a count and
nothing else, and `Status.json` reports current tonnage with no capacity beside
it — so the denominator comes from a table in `data/ships.py`, keyed by vehicle
and consulted through `srv_cargo_capacity()`.

Only established figures are listed: the Rhino at 72 tonnes, read off the
in-game panels, the Scarab at 4 and the Scorpion at 2.  Third-party references
giving the Rhino 24 tonnes are wrong, and provably so from the journals — real
SRV cargo counts run smoothly past 24 to a high-water mark of 68, which a 24 t
denominator would have displayed as a hold 283% full.  A vehicle with no
confirmed figure falls back to plain tonnage rather than a denominator that
might be wrong, because a wrong one reads as a full hold while there is still
room, or the reverse.  Adding one is a single line, and the totals line picks
it up with no other change.


## Released in 20260907

### Fixed: the ship's cargo vanished after resuming in an SRV

Resume a save while already in a surface vehicle and the new journal contains
no `Loadout` and no ship `Cargo` event at all — only SRV ones.  A real capture
of that session ran to 282 events without either.  Since only the current
journal is replayed, EDLD had no capacity and no manifest, so the Cargo tab
rendered an empty Ship section with a dash for its totals.

Capacity and hold are now recovered by replaying the recent journals forward.
No single event holds the hold: ship cargo events are often count-only — the
newest in a real capture read "71" with no inventory — and the contents are
frequently the product of transfers made afterwards, which had brought it to
110.  Reading one event found an older, emptied snapshot and reported nothing
aboard.

The last cargo event carrying an inventory is the baseline and every transfer
after it is applied.  Sales and jettisons emit their own cargo event, which
resets the baseline, so they need no special handling.  The journals win over
the persisted copy, so a save written while the hold was not yet known cannot
stick.

### Fixed: resuming in an SRV renamed the commander's ship

`LoadGame` reports the *vehicle* in that case — `"Ship": "MEV_Rhino"`,
`"Ship_Localised": "SRV Rhino"`, with `ShipName` and `ShipIdent` blank — and
taking it at face value replaced the ship's identity everywhere it is named.

It also reset `vessel_mode` to "ship" while the commander was plainly in an
SRV, and no `LaunchSRV` follows a resume to correct it.  A surface vehicle
reported here now sets the SRV state and leaves the ship's identity alone.


### Fixed: the ship's and the SRV's holds are told apart

Three faults kept the two confused, all of them surfacing now that the Rhino
carries a refinery and can hold cargo of its own:

- **Cargo.json was read as the ship's regardless of whose it was.**  The game
  rewrites that file for whichever hold last changed, so while the commander
  is in an SRV it holds the SRV's manifest.  It is now only applied to the
  hold it actually describes.
- **LoadGame emptied the ship's hold.**  Resuming does not unload anything,
  and no `Vessel: Ship` cargo event necessarily follows — resume straight
  into an SRV and only SRV events arrive, so the ship's cargo was lost for
  the rest of the session with nothing to restore it.
- **The SRV's manifest froze.**  Most SRV cargo events carry a count and no
  inventory, so the listing stuck at whatever the last event with one said.
  The count-only events now take the manifest from Cargo.json, which is the
  SRV's while the commander is aboard.

The Cargo tab lists both holds under their own headings, each with its own
totals, so a full ship and a full SRV read at a glance.

### Fixed: ore refined in an SRV was counted twice

The Rhino carries a refinery, and what it refines goes into the SRV's hold,
not the ship's.  `MiningRefined` credited the ship's manifest regardless, so
the ore was counted once when it was refined and again when `CargoTransfer`
moved it across — a hold showing 20 t in game read 40 t in EDLD.

Refining is credited to the ship only when the ship is the hold being filled.
The vessel the game last reported cargo for decides that, rather than the
commander's tracked vessel mode: `LoadGame` resets that mode to "ship", and
resuming a save while already in an SRV emits no `LaunchSRV` to correct it, so
a mode-based check silently stopped working after any reload — 60 t aboard
read 84 after another 24 refines.  The SRV's own `Cargo` events keep arriving
the whole time it is being filled, which makes them the dependable signal.


## Released in 20260906

### Changed: the desktop window opens at the terminal's proportions

Column widths lived twice — as literals in the terminal stylesheet, and not at
all in the desktop window, which handed the job to a pair of nested
QSplitters.  Qt sized those from widget size hints, so the desktop dashboard
opened with columns bearing no relation to the terminal's, and one stray drag
left it permanently lopsided with no way back.

`COLUMN_WIDTH_PCT` in the layout model is now the single definition, read by
both front ends.  The desktop columns are fixed proportional layouts rather
than splitters, measured at 34.0 / 32.0 / 34.0 percent against a model of
34 / 32 / 34.

Which window occupies which slot is still changed through
Preferences > Display; the geometry itself is not draggable, matching the
terminal.


### Fixed: session boundaries were never detected

A play session ends when the commander stops playing, and the journal records
that three different ways: a `Shutdown`, a `Music` event with `MainMenu`, or —
when the client crashed and wrote neither — simply the last event in the file.
A `LoadGame` more than fifteen minutes later starts a new session.

The check only ever looked at the journal being replayed.  Elite opens a new
journal on every launch, so the closing marker is always in an earlier file:
across a 269-journal capture a `LoadGame` never once followed a `Shutdown`
within the same file, and the comparison could not fire.  Every restart
therefore inherited the previous session's clock.

The marker is now recovered from the preceding journal before the replay
begins, covering all three cases, and an exit to the main menu closes the
session live as a `Shutdown` does.  Validated against 242 real journal
transitions.

### Fixed: the session clock was saved from the wrong variable

Two clocks existed: the `session_stats` plugin's, which the display reads, and
`state.session_start_time`.  Persistence wrote a module global that is only
ever populated by a previous *load*, so the stored value was stale or null.

Worse, the save was unreachable — `state.sessionend()` cleared
`state.session_start_time` on the line immediately above the `if` that guarded
on it.  The clock is now read before it is cleared, and the plugin's value is
what gets written.

### Changed: the dashboard is drawn before the journal is replayed

Preload fires thousands of events in a few seconds, and each one triggered a
repaint, so startup flickered through months of history before settling.
Repaints are held while the replay runs and done once when it finishes.


### Fixed: Commander and Crew windows stopped rendering partway down

`_fmt_health` lives in the Ship window, and the hull row that uses it was
moved to Commander without it.  The module imports cleanly and only fails when
the row is drawn — and because blocks swallow refresh errors, the window
simply stopped updating at that point.  Mode and Shields, set before the hull
row, populated; Hull, Fuel, Home System, Current System, Location, Power and
PP Rank, all set after it, stayed blank.

Three more of the same kind were found by scanning for it:

- `gui/blocks/commander.py` — the same missing `_fmt_health`.
- `gui/blocks/status.py` — `PP_RANK_NAMES` and `TextRow`, lost when Crew / SLF
  merged with Alerts, so the crew rank line raised.
- `gui/blocks/ship_info.py` — a whole colonisation renderer left behind when
  colonisation moved to Objectives, calling a helper the module no longer had.

Two were older than this release and had never worked: `ClickableHdr`, which
the Qt colonisation view has called since before these merges and which was
never defined anywhere, and `_build_loadout_from_capi_modules`, referenced by
the CAPI stored-ships path and likewise never written.  Both are implemented.

`tests/test_layout_windows.py` now parses every module under `tui/`, `gui/`,
`core/`, `components/` and `data/` and fails on any helper or class name used
but never defined.  Compiling and importing cleanly is not enough to catch
this; only calling the code was, and nothing called these paths.

### Fixed: repaint routing lost seven plugin mappings

`_PLUGIN_TO_BLOCK` had been reduced to six entries — `crew_slf`, `alerts`,
`cargo`, `engineering`, `ship_health`, `assets` and `colonisation` were deleted
rather than retargeted when their windows merged.  An unmapped name falls back
to repainting every block, so nothing looked broken; the dashboard just
repainted wholesale on every crew wage payment.  That fallback is exactly what
hid the omission.

`_all_block_ids()` had drifted the same way, naming a window that no longer
exists and repeating two others.  It is derived from the id map again.

A layout release.  The window set had accumulated more panels than a screen
holds, several of them near-empty most of the time, and three size classes to
arrange them in.  This reduces the set by merging windows with their natural
neighbours and reduces the classes to two, which makes far more of the layout
interchangeable.

### Changed: two size classes, and columns that mirror

Every window is now either **Large** or **Centre**, and every column adds up
to the same height so rows line up across all three:

    left / right   PANEL  + PANEL                   = 50 + 50      = 100
    centre         CENTRE + CENTRE + CENTRE         = 33 + 33 + 33 = 100

The right column mirrors the left: two large windows apiece, four such
positions in total, and any large window may occupy any of them.  The centre
column is three equal windows, freely interchangeable.  Preferences > Display
already filtered its options by class and now offers five large windows for
the four large slots and three centre windows for the three centre slots.

``COMPACT`` and ``ANCHOR`` are retained as aliases of ``CENTRE`` so a
``windows.json`` written against the previous three-class scheme still loads.

### Changed: Crew / SLF and Alerts merged

They are almost never busy at the same time — crew and fighter status is a
short fixed set of rows, empty unless a fighter is deployed or crew is hired,
and alerts are empty until something fires — so they share one window instead
of each holding a slot.  No tabs: an alert that needs a tab change to see is
an alert you miss.  Crew above, alerts flowing beneath.

This is what makes the centre column three equal windows rather than a tall
pair with a short pair wedged between them.

### Changed: the Ship window

Ship Health became **Ship**, because the ship rather than its health is the
subject.  One header line — name, ident and type — over three tabs:

    Cargo         the hold, leading because it changes constantly
    Modules       every fitted module, worst-first within each power group
    Engineering   the material store by grade

Cargo and Engineering had windows of their own; both are about the vessel's
contents and neither filled a slot on its own.

### Changed: a new Objectives window

Work with an end state, as distinct from the running totals in Session and
the ship's contents:

    Missions      the massacre stack, then every other mission held
    Colonisation  construction sites and their outstanding requirements

Missions came out of Session and Colonisation out of Cargo.  Neither belonged
where it was: a mission stack is not a session statistic, and a depot's
shopping list is not the hold.

### Changed: ship condition is back in Commander

Shields, hull and fuel return to the Commander window's Info tab, under
Powerplay rank and separated by a rule.  Info is the default view, so that is
the one place they cost nothing to reach.  They are no longer duplicated in
the Ship window.

"Set Home" now reads "Set Home System", and the carrier tabs are "Carrier" and
"S. Carrier".  Both appear only when the commander actually owns a carrier of
that class — an empty tab implying one they do not own is worse than no tab.

### Changed: every window fits on screen at once

Objectives moved to the centre column and Session merged into Career as its
first tab, leaving seven windows for seven slots.  Rearranging now swaps two
windows rather than hiding one.

Session and lifetime figures are the same question over two spans of time, so
they share one tab bar — Session, then Summary, Combat, Explore and the rest —
rather than two slots.  An Operations tab and a Career statistics panel are
planned once there is data to build them from.

### Changed: saved layouts are migrated once

A `windows.json` from before this release names windows that no longer exist —
Cargo, Engineering, Alerts, Crew / SLF and Session were all folded into other
windows — and the slot grid changed shape with them.  Salvaging what survived
would leave a half-populated grid, so a pre-version-2 file is replaced with the
current defaults and rewritten once.  A read-only home does not stop the
dashboard drawing.

### Changed: seams between sections that share a window

Crew / Alerts now carries an "Alerts" heading and a rule between the two
halves.  Sharing a window without a visible seam meant an alert read as
another crew row.

The Ship window's Cargo tab is likewise headed "Ship", and gains an "SRV"
section while a surface vehicle is out.

### Changed: the Session view stops repeating activity detail

Each provider fed its **full tab rows** into the Session view, which is a
different question from what the session produced.  A breakdown of the body
you are mining and a line per commodity describe the *place*; they belong in
the window that is about the place.  That is how ring hotspots, planetary
site counts and a row per refined commodity ended up in a session summary.

Providers now supply ``get_session_rows()`` for this view, falling back to
their condensed summary rows.  Removed from it:

- **Cargo currently held** — a state of the hold, not something the session
  produced, and already on the Ship window.
- **Ring and planetary sites** — the place, not the session.
- **The ship in use** — named in the Ship window's header and in Commander.
- **A line per refined commodity** — now one Refined total, with a count of
  how many kinds when there is more than one.
- **A line per raw material category** — now one Raw materials total.
- **Limpet stock and yield distribution** — states of the hold and of the
  ring rather than session output.  Both stay on the Mining tab, where the
  question is "how is this run going" and running dry ends it.

The Mining tab keeps every bit of that detail; only the Session view is
narrower.

### Changed: income is accounted for once, in its own section

The session total appeared twice in the Overview and again as a Credits row,
while the streams that make it up were scattered across the sections of
whichever activity produced them — and mined ore was filed under Trade, so a
mining session read as a trade run.

There is now one Income section, last because it tallies everything above it:
every earning stream largest-first, then Total earned and the hourly rate.
Mined sales are told apart from trade by `AvgPricePaid` — ore was never
bought, so it has no average paid price.

Only **redeemed** vouchers count.  Bounties accrued from `Bounty` events are
money earned that is still lost on death, so counting them as session income
counts credits that are not the commander's yet.  Bounties, combat bonds and
trade vouchers are all recorded when cashed in.

### Changed: further Session view corrections

- **Mining** — the commodity-kinds count and materials-collected total both
  proved uninteresting and are gone; Refined and Prospected remain.
- **Exploration** — "Distance" reported a jump count with light-years in the
  rate column, and its value repeated its own unit: now "Jumps  14  |  812 ly".
- **On foot** — surface deployment counting removed, same objection as the SRV
  counter.  Settlements visited and raw materials remain.
- **Exobiology** — "Bodies with bio" describes where you were rather than what
  you produced; Samples remains.
- **Missions** — "Failed" appears only when something failed, rather than
  standing at a permanent zero.

Every one of these stays in full on the activity's own window.

### Removed: SRV deployment counting

How many times a vehicle was deployed says nothing about what a session
produced.  Losing one would, and that already arrives as ``SRVDestroyed``.
The counter, its row and its ``LaunchSRV``/``DockSRV`` subscriptions are gone.

### Changed: the cargo manifest is sorted for jettisoning

Freight is ordered by value per unit, cheapest first.  With a full hold the
question is what to throw out, and that is answered by whatever is worth least
per tonne — which was previously buried in the middle of an alphabetical list.
Prices follow the chosen source: the target station's when one is set,
galactic average otherwise.

Each row now carries three columns — units, price per unit, line value — at
fixed widths so the separators line up down the manifest and under the totals.

Limpets are consumables, not freight: never sold, and their count is what says
whether the run can continue.  They sit below a blank line, immediately above
the totals, and are excluded from the value sort — at around 100 cr a tonne
they would otherwise permanently head the jettison list.

### Fixed: SRV cargo was applied to the ship's hold

``Cargo`` fires for the SRV as well, and those events name only a count —
never an inventory.  Untangled from the ship's, an SRV event with a count
above zero sent the hold off to re-read ``Cargo.json``, and an SRV ``Count: 0``
emptied the ship's manifest outright.  In a real journal that is 149 SRV
events against 12,815 for the ship, so it fired rarely and looked like cargo
mysteriously vanishing.

SRV tonnage is tracked separately and shown in its own section.  The journal
gives no inventory for it, so tonnage is all that section can show.

### Fixed: module names read like internal ids

The module list showed "Largecargorack", "Panthermkii Cockpit", "Mkii
Passengercabin" and "0 Point Defence (Turret)".  Three separate causes:

- Modules with no mapping fell through to title-casing their raw id.  The
  ones a real 299-module capture turns up are now named — cargo racks,
  passenger cabins, fighter hangars, vehicle hangars, limpet controllers,
  abrasion blasters, cargo bay doors.
- Utility mounts carry no size in game, so prefixing the size digit produced
  "0 Point Defence".  The prefix is dropped for them, and utility mounts whose
  id omits the mount type entirely — `hpt_chafflauncher_tiny` — are handled
  rather than falling through.
- Cosmetics ride in the same Loadout list as real modules.  The filter matched
  id prefixes, so anything whose id begins with the ship rather than the item
  type got through: ship kits, bumpers, spoilers, cockpit skins.  Matching on
  substrings catches them whatever the ship prefix.  A real 51-entry loadout
  now yields 39 modules and filters 12 decorations.

### Fixed: the SRV that called itself Testbuggy

Surface vehicles carry Frontier's internal development names in the journal,
and they are not guessable: ``testbuggy`` is the Scarab and has been since
2015.  The fallback title-cased the raw id, so "Testbuggy" reached the screen.
All four are now mapped — Scarab, Scorpion, Nomad and Rhino — with the
journal's own localised field preferred wherever it supplies one.

---

### Added: a guard against window-registry drift

Windows are declared in four places that have to stay in step — the layout
model's class registry and display names, the slot grid, and each front end's
DOM-id and block-class maps.  Every merge in this release left one of those
behind at least once, and every such failure is silent: the window simply
never appears, or never refreshes.

`tests/test_layout_windows.py` derives what must line up from the registries
themselves.  Adding a window without wiring it now fails four tests
immediately rather than going missing on someone's dashboard.  It also checks
that every column sums to a full height, that every window has a slot of its
class, that Preferences > Display offers only class-matching windows, and that
every repaint target names a live DOM id.

## Released in 20260905

A consolidation release.  Several windows had grown to restate one another —
the same body listed twice for its value and its flora, hull and shields shown
in two places, a mission stack sitting apart from the session it belongs to —
and the dashboard was paying grid space for the duplication.  This release
folds each of those into the window it belonged with, and fixes the routing
and carrier bugs found along the way.

### Fixed: routing worked in the desktop window and never in the terminal

FSD and Neutron plots ran to completion and then vanished.  Both routers were
returning results the whole time; the worker thread died on its own last line
marshalling the result back onto the event loop.  `call_from_thread` is defined
on `App`, not on `Widget`, so calling it on the block raised `AttributeError`
in a daemon thread — silently — leaving the status label on "Plotting…"
indefinitely.  The desktop window was unaffected because Qt marshals through a
signal instead.  `tui/search_modal.py` had been using the correct
`self.app.call_from_thread` form all along, which is why the Cargo target
search worked and this did not.

`tests/test_tui_thread_marshalling.py` scans every module under `tui/` for
App-only methods called on `self`, so this class of bug is caught for windows
that do not exist yet, and separately pins the premise that `App` has the
method and `Widget` does not.

### Fixed: fleet-carrier routing

Carrier plots were accepted with `HTTP 202` and then never resolved.  The
endpoint and every parameter name had been correct all along.  Spansh's own
front end submits through jQuery with `traditional: true`, which serialises a
list as repeated bare keys — `destination_systems=6681123623626` — where EDLD
was sending a JSON string.  The job was queued with a destination list that
parsed to nothing.  `refuel_destinations` had the same problem in reverse: an
empty array is omitted entirely under that serialisation, not sent as an empty
value.

Carrier routes now come back with the fuel planning that makes them worth
having: tritium burned per jump, tank level on arrival, restock stops and
amounts, and which systems have a market or a pristine icy ring to mine.  The
Carrier tab has a real form in both interfaces, prefilled from live carrier
state.

Expectations in `tests/test_spansh_carrier_params.py` are derived from a
completed job saved from the site rather than restated by hand, so a future
list-shaped parameter fails the test instead of being quietly JSON-encoded onto
the wire.

### Fixed: squadron carriers overwrote fleet carriers

`CarrierStats` reports both kinds of carrier through the same event,
distinguished by `CarrierType`, and both were being written to the same state
field.  Whichever event arrived last won, and the other carrier disappeared
from the display.  They are now tracked separately, with `CarrierID` recorded
so `CarrierDecommission` can tell which one was sold.

### Fixed: the Assets carrier tab read keys nothing produced

Four of its ten rows could never populate.  Reserve read `reserve_balance`
where the parsers write `reserve`; Upkeep read `coreCost`, which no parser has
ever written; and both cargo rows read a `capacity` sub-dict that is read
*from* the CAPI payload but never written *into* the carrier state.  Meanwhile
twenty-one parsed fields had nowhere to appear.

Three separate parsers populate that state and they did not agree on key names,
so the tab's content depended on whether CAPI had polled recently.  They now
share a vocabulary, and `core/ui_helpers.py` holds the single description of
what the tab shows so the two interfaces cannot drift.  A test extracts every
key the display reads and every key the parsers write, and fails if the display
reads something nobody produces.

### Changed: windows folded into the window they belonged with

| Was | Now |
|-----|-----|
| Assets | Wallet / Ships / Modules / Fleet Carrier / Squadron Carrier tabs on **Commander** |
| Exobiology | nested under each body's row in **Exploration** |
| Massacre Mission Stack | the Missions tab in **Session** |
| Colonisation | the Colonisation tab in **Cargo** |

Exobiology is the clearest case: every body carrying biological signals was
listed twice, once for its cartographic value and again for its flora.  The
biology now sits indented beneath the body it belongs to, so a body's full
story is in one place.  Cargo and Colonisation are the same activity from
opposite ends — what you are carrying against what the depot still needs — and
Cargo collapses to a couple of rows on a hauling run, which is exactly when a
construction site is live.

Hull, shields and fuel were shown in both Commander and Ship Health.  They now
live only in Ship Health, which is also where the ship names itself: its name
and ident head the window, with the hull type on a second row.  Commander's
header is the commander alone.

No data was dropped in any of this.  A `windows.json` written before the merges
still loads: names that no longer exist are dropped, and any window whose saved
slot has since gone — column A went from three positions to two — is rehomed
into the first free slot of its class rather than being silently lost.

### Added: every mission type on the board

Mission tracking only ever covered massacres, because that is all the stack
view needed.  The Session window's Missions tab now shows the massacre stack
summarised by source faction as before, followed by every other mission the
commander holds, grouped by type and dropping off as each is completed, failed
or abandoned.

The massacre-specific bookkeeping moved out of the event match into a method of
its own so the general handler can record every mission first and then delegate,
rather than one `case` shadowing the other.

### Added: mining session context

Tonnage and rate figures said nothing about where they were earned — 180 t is
excellent in a depleted ring and mediocre in a pristine one.  Mining now
captures the ring's reserve level, its class and its hotspots, alongside the
two numbers that actually end a run: limpets remaining and how full the hold
is.  Raw materials collected while mining are recorded too.  Reserve level was
not captured anywhere in the codebase before this.

### Changed: Discord launch message and periodic summary

The periodic summary had no commander, no ship and no location, so a reader had
numbers with no idea where they came from — and despite income being tracked,
it never appeared.  Both are fixed.  Values wider than the numeric columns no
longer set the column width, which had been right-shifting every figure in the
block.

The launch embed leads with who and where, then reports credits, cargo, fuel
and the fleet carrier, all of which were tracked and none of which were shown.
A carrier parked twenty thousand light years away is easy to forget about.

### Fixed: `--trace` wrote the Discord webhook in cleartext

The trace header dumps the effective config on every launch, and those logs get
attached to bug reports.  A webhook URL is a bearer credential.  Credential-
shaped keys are now redacted by substring match — `webhook`, `token`, `secret`,
`password`, `apikey`, `auth`, `credential` — reporting whether a value is set
without the value itself, which is the only thing that dump was answering.

**If you have shared a `--trace` log, rotate your webhook.**  The redaction
only protects logs written from here on.

### Fixed: a new window could silently never refresh

`_all_block_ids()` in the terminal interface was a hand-maintained list.  A
window absent from it rendered its placeholder rows forever, which is exactly
what happened during development of this release.  It is now derived from the
window registry.

### Added: carrier jump notifications

A scheduled jump locks a carrier down for about fifteen minutes — nothing can
dock, and anyone aboard is going wherever it goes — so all three transitions
now notify: scheduled (with carrier name, ident, destination and countdown),
cancelled, and arrived.  Fleet and squadron carriers are tracked separately and
can have jumps in flight at the same time.  They go out through the alerts
component, so each lands in the Alerts window and is emitted to the terminal
and Discord at its own configurable level — `CarrierJumpScheduled`,
`CarrierJumpCancelled` and `CarrierJumpComplete` under `[LogLevels]`.

The events are thinner than they look.  A jump request names the destination
and departure time but not the carrier; a cancellation names neither, so the
pending jump recorded at request time is the only record of where it was going.
Completion arrives as `CarrierLocation` when the commander is elsewhere and
`CarrierJump` when aboard — and when aboard, both fire about a minute apart.
`CarrierLocation` is also a periodic status event, outnumbering real arrivals
roughly two to one in a real journal, so an arrival is only recognised when it
names the destination that was requested and the departure time has passed.
Replaying a 269-journal capture accounts for every request exactly: 178
scheduled resolve to 170 completed, 3 cancelled, 4 re-targeted and 1 still
pending at the end of the logs.

### Fixed: riding a carrier through a jump blanked its system

The `CarrierJump` handler read `SystemName`, which that event does not carry —
it names the arrival system in `StarSystem`.  Every jump the commander rode
along with set the carrier's recorded system to a dash.

### Fixed: a departure time nobody could read

The carrier jump notification ended with `— departs 05:19`, taken straight
from the journal's UTC timestamp regardless of the `UseUTC` setting.  For
anyone not on UTC it was neither their wall clock nor a duration.  It now
follows `UseUTC` like every other time EDLD prints, is bracketed rather than
dash-separated so it cannot be misread as part of the countdown, and is
labelled when it is UTC.

### Changed: config files gain new settings automatically

Every release that adds a setting left existing configs without it.  Nothing
broke — resolution falls back to the default — but the warned sections printed
a line per missing key on every launch, and a key absent from the file is one
the user cannot discover or edit.

New defaults are now appended to the existing `config.toml` on startup, in
place and by line so the comments in a hand-edited file survive.  Only
additions, only at the top level, and never keys whose default is empty:
credentials and paths are the user's to supply, and writing `ApiKey = ""` into
their file is noise.  Profile sections are untouched.

`example.config.toml` had drifted — missing keys and two whole sections — and
the config generated for a fresh install omitted `[CAPI]`, `[Colonisation]`
and `[SessionMgmt]` entirely.  Both are current, and a test now derives what
must be present from the defaults themselves, so the next setting added fails
there rather than in someone's log.

### Changed: the Session summary no longer repeats the route

Remaining jumps and next destination were duplicated into the Session window
from Exploration.  The Navigation window owns the route, including the
follower's next-system readout in its footer.

### Fixed: a finished route outlived the trip

Arriving at the last waypoint of an EDLD-plotted route left it stored, so
jumping onward reported being off a route that had already been completed.
Reaching the final destination now retires the route.  The game's
`NavRoute.json` is left alone — that one is the game's to manage.

### Fixed: mining recorded surface points of interest as hotspots

A surface scan returns two unrelated families of signal through one event.
Bare commodity names — Painite, Monazite, Low Temperature Diamonds — are
mining hotspots.  Everything spelled as a `$SAA_SignalType_*` token is a
surface point-of-interest category, and `$PlanetaryMiningLocation_Name` marks
the body itself.  All of them were being counted, which put rows like
"Human  3 hotspots" and "Planetary Mining Location  28 hotspots" in the mining
panel next to the real ones.

Only commodities are counted now, localised names are preferred where the
journal supplies one, and case is normalised — the same commodity appears as
both `Tritium` and `tritium` across a real journal.

### Added: ring and planetary mining sites, listed separately

Planetary mining locations are new, and a ring and a planetary surface are
different kinds of place — one has hotspots you fly into, the other has sites
you land at.  They now get a heading each, with every mineable body scanned
this session listed under the right one and the body you are currently at
marked:

    ─── Ring sites ───
      Ega 3 A Ring          Common · Rocky
        Serendibite         2 hotspots
        Musgravite          2 hotspots
    ─── Planetary sites ───
      Ega 3 a               20 sites
    ▸ Ega 3 d               28 sites
      Ogmar A 1             13 sites

The journal records how many surface sites a body has and nothing about what
any individual one holds — that detail exists only on the in-game surface map.
Checked against every body carrying a planetary mining location across a
269-journal capture: the count is all there is.

Dropping into a ring hotspot from supercruise now marks which one is being
worked, which overlapping hotspots make ambiguous from the ring's signal list
alone.

Bodies scanned but with nothing to mine are omitted.

### Changed: the mining section is headed by the body, not "Ring"

Mining happens at planetary locations as well as in rings, so a section headed
"Ring" with the body demoted to a row inside it was wrong for half the cases.
The body is now the heading, with reserve level, ring class where there is one,
and hotspots beneath it.

### Changed: smaller things

- Engineering no longer prints a totals row above every material grade.
- Navigation's Carrier tab lost its "unfinished" banner.
- The README badge row is down from ten to six.
- `example.layout.json` was on a schema the loader has not read for some time
  and named windows that no longer exist; it now matches `windows.json` and the
  shipped default.

---

## Released in 20260901

A structural release.  The body-data layer that feeds the Exploration and
Exobiology windows had grown as one undifferentiated block, and a bug that had
been sitting in it for some time turned out to be a direct consequence of that
shape rather than a slip in any one place.  Splitting the layer along the seam
the two domains actually have is most of this release; the bug is fixed, and a
test now derives what used to be maintained by hand.

### Changed: the body-data layer is split by domain

`core/explo_db.py` and `core/explo_ingest.py` each did two jobs.  They carried
Exploration — what a body is, what scanning and mapping it recorded — alongside
Exobiology — what grows on it, what the commander has sampled, where.  The two
share a database because flora rows hang off planets, and that shared storage
had quietly become shared code as well, so that neither domain could be read,
changed or reasoned about without the other in view.

The database module is now three.  `core/bodies_db.py` owns what neither domain
owns alone: the connection, the schema and its migrations, the corrupt-file
quarantine, the generic upsert and status helpers, and the tables both sides
share — commanders, systems, journals, and `planet_signals`.  `core/explo_db.py`
keeps stars, planets, rings and non-bodies.  A new `core/exobio_db.py` takes
flora, sample status and waypoints.  The two domain modules are mixins that
`bodies_db` composes into a single class over a single connection: the split is
by concern, not by storage, and no migration is involved.

`planet_signals` stays in the shared module deliberately.  One `FSSBodySignals`
event carries biological, geological and human signals together, so the table
has one writer and two readers and belongs to neither side.  Trying to divide it
is where a tidy split would have turned ugly.

Ingestion divides the same way.  `core/body_ingest.py` holds the dispatcher and
the context both domains need — the current commander, the current system — and
routes each event to `core/explo_ingest.py` for scanning and mapping or to a new
`core/exobio_ingest.py` for sampling and footfall.  The field-reading helpers
they share moved to `core/journal_fields.py`, which imports nothing, so neither
domain module has to import the other or the dispatcher that imports them both.

Nothing about what is stored changed.  Replaying an identical event stream
through the old and new code produces databases that match row for row across
all sixteen tables, and view output that matches exactly.

### Fixed: the Exobiology window ignored the scan that fills a body in

A body reaches the Exobiology window through its biological signals, and
`FSSBodySignals` arrives with nothing but a name and a count.  Everything the
window estimates from — whether the body is landable, its gravity, atmosphere
and temperature — is written by the `Scan`, and `landable` gates the genus
prediction outright.  A body known only from its signals therefore shows no
predicted genera and no value at all.

`Scan` was in the Exploration window's repaint list but not the Exobiology
window's, so scanning such a body repainted one window and not the other.  The
Exobiology window kept showing the stub's empty estimate until some later
sampling event or a jump happened to repaint it.

In practice the two events are usually written together and both land before
the next repaint, which is why this survived: the common path is correct by
accident, and the stale window only appears when the two fall either side of a
poll — during an archive replay, or catching up after the app has been closed.
It was never a wrong number, only an absent one, and it always healed itself
eventually.  It is nonetheless the window showing less than it knows.

### New: the repaint lists are derived rather than remembered

The bug above was not a typo.  Two lists of journal events lived in the
component that dispatches repaints, several files away from the views whose
data they governed, and nothing anywhere connected one to the other.  Adding a
field to a view could not fail to update the list, because there was no link to
fail.

Each view module now declares its own `REPAINT_EVENTS` beside the code that
reads the data, and the component imports those declarations instead of keeping
its own copies.  `tests/test_repaint_events.py` then checks the declarations
against reality rather than restating them: for every event the ingestor
handles, it builds each view over a fresh database, ingests the event, and
builds the view again.  If the output changed, that event must be in that
window's list.  That is the invariant itself, checked mechanically.  Removing
`Scan` from the Exobiology list makes the test fail with the symptom named.

The test also fails when a new handler is added to either ingest module without
a scenario covering it, so the check cannot quietly stop covering the code it
was written for.

### Changed: fewer release artefacts

A release attached a detached signature beside every archive, which came to
twelve files for four downloads.  Only the checksum manifest is signed now.  It
lists every artefact by digest and is itself signed, so a single signature check
still authenticates the whole release — a signature beside each file asserted
nothing the signed manifest did not already assert transitively.  The checksum
job no longer re-uploads the archives it only needed to read, either.  Four
archives, a manifest and one signature replace the previous twelve.

---

## Released in 20260830

A maintenance release about failure that does not announce itself.  The
Exploration and Exobiology windows had been coming up empty on some installs
with nothing anywhere to say why, and tracing that turned up a handful of
places where a real fault rendered as an ordinary quiet session.  Two
integration errors and a build-tooling gap are fixed alongside.

### Fixed: a corrupt body database left Exploration and Exobiology empty forever

A damaged `explo.db` — SQLite reporting `database disk image is malformed` —
failed every read and every write, so both windows fell back to their
empty-state text and the journal-history import completed `0/168 journals` on
every launch.  Nothing recovered on its own: the same file was reopened next
time and failed the same way, and the only way out was deleting it by hand.

Every row in that database derives from the journal archive and nothing else,
which makes the file a cache rather than a record.  It is now treated as one.
A corruption error on open or on migration moves the file aside as
`explo.db.corrupt-<timestamp>` — renamed rather than deleted, because a corrupt
SQLite file is often still partly readable and keeping it costs nothing — and a
fresh database is rebuilt from the archive on the same run.

The check has to cover opening as well as migrating: `_open()` issues
`PRAGMA journal_mode=WAL`, and on a truncated or overwritten file that is where
SQLite refuses first.  Corruption is matched on the error text, because SQLite
raises the same `DatabaseError` class for an ordinary query error, which must
not trigger a rebuild.

### Fixed: a component that failed to load disappeared without trace

`--tui` and `--gui` detach stdout before components load, so the loader's
warning about a component that raised during `on_load` went to `/dev/null`.
The component was then simply absent: its events were never dispatched and
every window reading it showed its empty-state placeholder, which looks exactly
like a session in which nothing has happened yet.

Load failures are now recorded, written to the diagnostic log with a traceback,
echoed to the real stderr, and raised as a dashboard alert naming the
components affected.

### Fixed: the body-data windows reported every fault as "nothing scanned yet"

Exploration and Exobiology reduced a missing view to the same sentence
regardless of cause, so a component that never loaded, a database that could
not be opened and a genuinely unvisited system were indistinguishable on
screen.  All four windows — both front ends — now distinguish them, and a fault
reads as a fault:

    Body data unavailable: body database unavailable — DatabaseError: …

`components/explo_sync.py` no longer swallows ingest errors in a bare
`except: pass`; it counts them, logs the first, and reports the reason.  A
database that cannot be opened at all no longer takes the whole component down
with it — it stays loaded carrying the reason, which is more useful than
vanishing.

### Fixed: the journal monitor could die mid-session in silence

Two independent faults with the same symptom: a dashboard still on screen,
still refreshing hull, shields, fuel and credit balance from `Status.json`,
while every journal-driven window sat frozen.

The first was an unguarded timestamp parse in the component-dispatch path of
`handle_event`.  A single journal line whose timestamp `fromisoformat` could
not read aborted the preload loop, unwound through `monitor_journal` into
`run_monitor`, and killed the thread.  A bad timestamp is now traced and
treated as absent.

The second was `run_monitor`'s own error handling calling `sys.exit(1)`, which
in a daemon thread raises `SystemExit` in that thread and nowhere else.  Losing
the monitor now sets a flag on the shared state, writes the traceback to the
diagnostic log and the real stderr, and raises a persistent alert reading
`Journal monitor stopped — …. Restart EDLD.`  The exit is kept only on the main
thread, which is the terminal-mode path.

### Changed: alerts distinguish faults from events

The alerts deque is cleared on every context reset — `LoadGame`, `Docked`,
`FSDJump` — which during preload wiped anything raised at startup before it
could be seen.  Subsystem faults now live in a list of their own: they ignore
preload, they do not fade, and they clear only on an explicit Ctrl+L.

### Fixed: EDDN discarded the last scan of every system left

The game finishes writing a body scan for the system being left up to a few
seconds *after* the `FSDJump` line:

    20:33:52  FSDJump  Colonia    SystemAddress=3238296097059
    20:33:54  Scan     Ogmar B    SystemAddress=84180519395914

The scan is valid, it just arrives late.  Augmenting it from the tracked
location would have filed an Ogmar body under Colonia's coordinates, so
dropping it was the safe thing to do — but the data was recoverable all along,
because the system it belongs to is the one just left and its `StarPos` was
known a moment earlier.

The component now keeps one level of location history and augments a late event
from it.  A `SystemAddress` matching neither the current system nor the
previous one is still dropped.  This was not rare: a single evening's journal
carried fourteen such scans, all of them discarded.

### Fixed: Inara rejected every wealth snapshot

The `Statistics` handler sent `setCommanderCredits` carrying only
`commanderAssets`.  That field is not sufficient on its own — Inara answers
`400: No credits value provided.` and the wealth figure is lost with it.
`Statistics` carries no credit balance of its own, so the most recently
observed one is used, in practice the `LoadGame` from seconds earlier, which is
the balance the snapshot was taken against.  With no credits anchor yet seen
the wealth is cached and carried forward to the next push that has one, rather
than sent as an event that cannot succeed.

### Fixed: release signing steps never ran

`if: runner.os == 'Windows' && env.CERT != ''` sat next to a step-level `env`
block defining `CERT` from a secret.  A step's own `env` is not visible to that
step's `if`, and the `secrets` context is not available in a step `if` at all,
so the condition was always false and both the Windows signing and the macOS
signing-and-notarisation steps were skipped unconditionally — including on runs
where the certificates were configured.  The certificates are hoisted to
job-level `env`, which is visible to a step `if`, so skipping only when a
secret is genuinely absent now works as documented.

### New: build the release artefacts locally

`scripts/build_local.sh` runs what the release workflow runs, on your own
machine: the preflight on the checkout, `pyinstaller packaging/edld.spec`, both
smoke tests, the archive carrying the licence texts, and the SHA-256 file.
Artefacts land in `out/` named exactly as the released ones are.

    scripts/build_local.sh                 # build, test, package
    scripts/build_local.sh --no-package    # build and test only
    scripts/build_local.sh --dir           # directory layout instead of onefile
    scripts/build_local.sh --sign          # sign, using SIGNING_KEY

It detects platform and architecture, falls back to `xvfb-run` when there is no
display, and warns when `packaging/edld.spec` or `packaging/build_common.py` is
git-ignored — the trap that bites only in CI, because the file is present
locally.  PyInstaller does not cross-compile, so a full set still needs three
machines.

Beyond convenience this is a diagnostic: if a local build passes and CI does
not, the difference is the runner rather than the tree.

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

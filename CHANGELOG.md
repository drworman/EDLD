# EDLD CHANGELOG

Last updated: 20260926

---

## Unreleased

### Fixed: installing into a blank spreadsheet built no dashboard

Pasting `Loader.gs` into a new spreadsheet and running Install produced a bare
`Deposits` tab beside Google's empty `Sheet1`, and nothing else. The upgrade
steps only ever adjusted tabs a sheet already had, on the assumption that every
sheet began as an import of `Mining_Dashboard.xlsx` — which the loader made
unnecessary and nobody would think to do first.

Upgrade now builds whichever of Dashboard, Settings, Queries and Themes a sheet
is missing (`sheets/Template.gs`, sheet layout v2), orders them, hides Queries
and Themes, and removes Google's empty default tab once there are real ones —
only an empty tab with that kind of name, and only when something was built.
A tab that exists is never rewritten. So a blank spreadsheet, a sheet that only
ever had the receiver, and one started from the xlsx all end up the same, and a
sheet already on layout v1 gains its tabs on its next Upgrade. **Repair
dashboard formulas** rebuilds a tab that has been deleted.

The content is not written twice. `build_bundle.py` reads the template's
constants out of `build_dashboard.py` — which now keeps every label, hint,
placeholder, preset and formula as a named literal — into the bundle as
`TEMPLATE`, and `tests/test_sheets_template.py` builds the tabs in a sheet and
compares them with the xlsx cell for cell. That comparison found one fault
before it shipped: a role description beginning with an apostrophe lost it,
because Sheets reads a leading `'` as its "this is text" marker. Template text
now goes through the same escaping as deposit values.

Settings!D1, the release line, is refreshed on every install unless the owner
has put their own text there. The manifest lists each layout step by name, so
Upgrade's confirmation says what it will do before it fetches anything.

`tests/gas_fake.js` now refuses any read it does not implement. It used to
answer them with a placeholder, which let a test pass against code that never
saw the value it asked for.

### Fixed: a sheet could only upgrade from a tagged release

Upgrade fetched the sheet code from the git tag the manifest named, so it
worked only once a release had been tagged — and trying it first meant
publishing one. On `dev` the manifest named `20260924-dev`, a tag that did not
exist, and Upgrade stopped with HTTP 404. The manifest itself was also stale:
the version file had moved to `20260926-dev` without a rebuild.

A sheet now follows a branch. It reads `sheets/release.json` from that branch
and the bundle from beside it; the manifest names the bundle by file name
only, and the loader accepts nothing else, so it cannot be pointed at another
address. Sheets follow `main`, which makes merging to `main` the sheet release.
**ED Dashboard → Update from branch…** switches a sheet to `dev` — or any
branch — to try sheet code before it is merged or tagged. No tag or GitHub
Release is involved at any point.

"Up to date" is now decided by the bundle's hash rather than its version, since
a development branch keeps one version across many commits. The confirmation
shows short hashes when versions tie, says which branch the code comes from,
and warns when stepping back to code that expects an older layout. A branch
with no sheet release says so and suggests another branch instead of reporting
a 404. A hash mismatch — usually GitHub's raw-file cache still serving the
previous copy for a few minutes after a push — says to wait and retry.
**About** shows the branch, the installed hash and where it came from.

`Loader.gs` changed; it has not been on `main`, so no sheet outside testing is
affected, but a sheet that installed the earlier one needs it pasted again.

### Fixed: a manual release run on a branch failed every smoke test

Running the release workflow by hand on `dev` built all three binaries and then
failed each one's smoke test: the workflow's `VERSION` is the ref name, which on
a branch is the branch — `dev` — while the binary correctly reported the
version file. The binaries and checksums jobs now take the version from the
verify job, which reads the version file, so a dry run on any branch builds,
tests and names its artefacts correctly and publishes nothing.
`tests/test_release_workflow.py` pins it.

### Added: a stale sheet bundle stops a release

`sheets/build_bundle.py` builds the sheet bundle and its manifest with the
standard library alone; `build_dashboard.py` now calls it. Its `--check` runs
in the release workflow's verify job and in `scripts/build_local.sh`, so a
version bump without a rebuild fails in seconds, naming the command to run,
instead of shipping a manifest for another version.

---

## Released in 20260926-dev

### Added: a survey sheet upgrades itself, from its own menu

Upgrading a shared sheet meant pasting new script files into Apps Script,
redeploying, and hoping nothing was missed — for every sheet, every release.
Now the owner pastes one file, `sheets/Loader.gs`, once. After that, upgrading
EDLD and then running **ED Dashboard → Upgrade…** in the sheet is the whole
job.

Upgrade reads `sheets/release.json` from `main`, shows the owner the version and
what will change, and on their say-so fetches the sheet code from that
release's tag, checks its SHA-256 against the manifest, copies `Deposits` to a
hidden backup tab, installs the code and runs the sheet's upgrade steps. Steps
are recorded as they complete, so an interrupted upgrade resumes; running it
on an up-to-date sheet says so and changes nothing. Deposits are only ever
added to, Settings values are left alone, EDLD's writes wait on the same lock
while it runs, and the web app's URL and token do not change.

The code cannot replace its own files: the Apps Script API that would allow it
is off in the hidden Cloud project every sheet script gets, and turning it on
is a Cloud console visit per owner — exactly what the sheet promises nobody
needs. So `Loader.gs` never changes. It holds the entry points Google calls and
runs the real code, which Upgrade stores in the script's properties and the
loader re-checks against its hash every time it loads it. Code is fetched only
from `raw.githubusercontent.com` and only at the address the manifest names. A
release that needs a newer loader says so and stops.

The token moves out of the code, which an upgrade replaces, into the script's
properties: **ED Dashboard → Set sheet token…** sets or changes it, and
revoking a commander no longer needs a redeploy. **About** shows what is
installed, and **Test connection** in EDLD names the release a sheet runs and,
when it is too old, says to run Upgrade.

A sheet set up before this needs one last manual pass — copy the token, paste
`Loader.gs` over the old files, run Upgrade, redeploy once — described in
`sheets/README.md`. Existing deposits, the URL and the token all carry over.

`build_dashboard.py` now also writes `sheets/edld_sheet.js`, the bundle the
loader installs (`Code.gs`, `Dashboard.gs` and the new `Upgrade.gs`), and
`sheets/release.json`; both are committed and must be rebuilt after bumping
`version`, which the tests enforce. `tests/test_sheets_loader.py` runs the real
loader and bundle under Node against a stand-in for Google's services
(`tests/gas_fake.js`), taking an old template sheet through a full upgrade and
checking every refusal.

### Added: notes on a surface deposit

The deposit window (**Ctrl+D**) has a **Notes** box at the bottom, several
lines tall in both interfaces, for anything the next commander should know
about a site — the way in, a hazard, what else is on the ridge. It opens
holding the current note, so clearing it removes the note: the one field in the
form where an empty box means nothing rather than leave-it-alone. Notes are
limited to 1000 characters and stored as plain text.

Notes are shared on the survey sheet and read back from it. They do not merge
like the fields around them, which are observations and follow the freshest
sighting. A note is somebody's writing, so it carries its own timestamp,
`notes_updated`, and the most recently written note wins — a blank one
included, which is how a note is withdrawn. Following `last_confirmed` instead
would have let anyone who drove onto a site re-send a copy they imported weeks
ago and put back text its author had since changed.

The sheet gains `notes` and `notes_updated` columns, and the dashboard template
a wrapped **Notes** column at the end of its table. Anything Sheets would run
as a formula — text starting with `=`, `+`, `-` or `@` — is now stored as
text, in every column, so a note cannot execute in a reader's copy of the sheet.

An existing sheet gets the columns, the Notes column and everything else here
from **ED Dashboard → Upgrade…** — see the next entry. An old script accepts
writes and drops the fields it has no column for, so **Test connection** now
compares the script's column count with EDLD's and says so instead of
reporting success.

The survey store moves to schema version 2, adding the columns; existing
deposits are kept and nothing is re-queued for publishing.

### Changed: depletion is a date, never an amount

Amount and density describe what a site holds when it is full. "Depleted" was
an amount, which meant working a site out overwrote the High it had held, and
somebody had to remember to put it back once the site refilled. It is gone from
the Amount list. The depletion date is now the whole of how a worked-out site
is recorded, shown and shared: **Mark depleted** stamps today, the form's date
records an earlier day, and neither touches the amount.

A store that has `Depleted` as an amount keeps the fact as a dated log line —
its last confirmation, if nothing already dated it — and the amount becomes
blank. The sheet stops serving `Depleted`, clears it from a row the next time
the row is written, and **Repair dashboard formulas** clears it from a template
sheet at once. The overlay no longer has a colour for it.

How long a site takes to refill is not yet known. `REPLENISH_DAYS` in
`core/mining_db.py` is `None` and `replenishes_on()` answers nothing until it
is; setting it will turn every depletion date already recorded into a refresh
date.

On the sheet the latest depletion date now wins, whoever sent it. It was
following `last_confirmed`, so a commander confirming a site could replace a
newer date with an older one. The date is also written as text: Sheets parsed a
bare day into a date in the spreadsheet's timezone and handed back a timestamp
that could land on a different day.

### Changed: amount and density change only when corrected

A later sighting could overwrite an assessment. The sheet replaced amount and
density whenever a report carried a newer `last_confirmed`, and every drive-by
of a site republishes it — so a commander who had imported "High" weeks ago
could put it back over somebody's correction just by parking on the rock.

Amount and both densities now fill blanks and otherwise change only when a
commander corrects them in the form. A correction stamps `assessment_updated`,
and on the sheet and on import only a newer stamp replaces a value that is
already there. The sheet gains an `assessment_updated` column.

### Fixed: a carrier jump test that passed only on machines set to UTC

`test_schedule_reports_name_ident_destination_and_countdown` expected the
departure clock in UTC, but the notification prints it in local time unless
`UseUTC` is set, which is the intended behaviour. On any machine not set to UTC
the suite reported a failure in code that was working correctly. It went
unnoticed because every place the suite had been run, the GitHub runners
included, runs on UTC. The test now converts the departure the same way the
notification does, and a second test covers `UseUTC`, the case the old
assertion had been checking without meaning to.

### Added: edit a radio station from the Radio tab

A **✎** now sits between **+** and **−** beside the station list, in both
interfaces. It opens the selected station's name and stream address for
editing, with the same checks as adding a station, and writes the change with
the same line-by-line editor, so nothing else in `config.toml` moves. Until now
the only way to correct a mistyped address was to delete the station and add
it again, which gave it a new Id and lost it as the remembered station, or to
edit the file by hand. The station keeps its Id. The change is saved where the
station already lives, the loaded profile when it defines the station and
`[Radio]` otherwise, and the form says which, because writing a profile's
station globally would change nothing and writing a global one into the profile
would quietly fork it for that profile alone. Editing the station that is
playing retunes it to the new address rather than leaving it stopped, and a
new name shows under On air at once; On air previously showed the name the
stream was started with, which would have gone stale after a rename.

### Fixed: the overlay froze on its last frame after Apply & Save

The overlay draws from the same state as both dashboards, yet it could sit on
screen reading SRV 22/72 while the Ship window beside it read 45/72, with the
income rate behind as well. Nothing was wrong with the numbers; the overlay had
simply stopped updating. Reloading the config after Apply & Save built a new
renderer client and dropped the old one without stopping it, so the old
renderer stayed on screen showing whatever it was last sent, while every later
frame went to the new client, which had never been started and so refused
them. From then on the overlay was a snapshot of the moment the button was
pressed, drifting further from the dashboard with every event. It was
invisible because the only record was a TRACE line reading `sent=False` twice a
second, which says nothing unless you already know to look for it. A
layout-only change now keeps the running renderer, a change to the window
settings stops the old renderer before starting its replacement, and switching
the overlay off takes it off the screen. A renderer that goes away for any
reason is now reported once at INFO and restarted after a short pause, rather
than being abandoned in silence. Two smaller faults went with it: the overlay
only noticed config changes if it had been enabled when EDLD started, so
switching it on in Preferences did nothing until the next launch, and
unplacing every panel left the last frame up indefinitely.

### Fixed: release verification could not find the public key

`scripts/verify_release.sh` and `docs/SIGNING.md` both said the release public
key was committed to the repository as `signing_key.pub`, and the script sent
anyone without it to a download link for that file. It was never committed —
`.gitignore` excludes `*.pub` — so the link was a 404 and nobody outside could
check a release signature at all. The key is now in the repository at
`signing/id_ed25519_signing.pub`, and the script and the documentation point
there. The script also checks the key's fingerprint before using it, and
refuses a key file that is not the release key, since a key file downloaded
beside a manifest can be swapped as easily as the manifest can. The
fingerprint is published in `docs/SIGNING.md`.

### Fixed: profile credentials were written in full to every trace log

The `--trace` header redacts credentials, but it only looked at the key sitting
directly beside each value. A profile holds its overrides as nested tables, so
in `[EDP1]` the key beside the EDSM API key is `EDSM`, not `ApiKey`, and the
whole table was written out as it stood. Every profile-level EDSM, Inara and
Colonisation API key, the Surface Survey token and the Discord webhook URL went
into every trace log, while the top-level copies of the same settings a few
lines above were correctly redacted, which is what made the leak easy to miss
when reading the file. Redaction now walks nested tables to any depth, and a
table whose own name is credential-shaped is hidden whole. The tests only ever
exercised flat sections, which is why they passed; they now use the shape of a
real profile.

### Fixed: `--terminal` never read Status.json, and lost every live surface refine

The Status.json poller was started by the two dashboards and not by terminal
mode, so a terminal session never saw live fuel, balance or shield changes.
Worse, the poller is also what records surface positions, and surface-mining
deposits are joined against those positions; with none recorded, every live
refine was treated as a ring refine and discarded. Nothing was logged, because
a ring refine is the ordinary case. Terminal mode now starts the poller too.

### Fixed: `--terminal` held every dashboard redraw request in memory

The journal reader, the Status.json poller and the components post redraw
requests to a queue in every mode, but only the dashboards ever read it. In
terminal mode the queue grew for as long as EDLD ran, which is precisely the
mode people leave running through day-long AFK sessions. Terminal mode now
empties it.

### Added: a Radio tab in the Crew / Alerts window

Radio Sidewinder, Hutton Orbital Radio and Radio Skvortsov can now be played
from inside EDLD, in both the terminal dashboard and the desktop window: a
station list, Play/Stop, volume down and up, mute, and the song title where the
station sends one. Nothing plays until Play is pressed. The last station chosen
is selected again at the next launch but not started, and volume, mute and
that station are kept in `radio.json` in the data directory rather than in
`config.toml`, so turning the volume down never rewrites a hand-commented
config.

Stations live in a new `[Radio]` section as two keys each, `Name_<Id>` and
`Url_<Id>`. Profiles add, rename, repoint or hide stations with the usual
dotted keys, and an empty URL is how a default is hidden, since deleted default
keys are put back at startup like any other. The flat layout is not a style
choice: `config_to_toml`, which Preferences saves with, writes only scalars
under bare keys, so an array of stations would have been flattened to a string
and a station name with a space in it could not have been a key. Either would
have lost every added station the first time anyone pressed Apply & Save.
`[Radio]` is also now a standard section, without which migration and backfill
would have treated it as a profile. The list follows hot-reload, and a station
hidden or repointed while it plays is stopped. `docs/CONFIGURATION.md`
documents all of it.

Playback is `core/radio.py`, one player shared by both front ends, with
miniaudio (MIT) doing the decoding and output, so there is no player to install.
It plays MP3, Ogg Vorbis and FLAC, and follows `.m3u` and `.pls` addresses. All
three default stations are MP3. miniaudio's own Icecast client was not used: it
connects twice, and its second connection is given no SSL context, so in a
frozen build HTTPS would have failed in a background thread after the first
connection had reported success, after which its reader waits for data forever.
That is a station that says it is playing and makes no sound. The reader here
makes one connection and returns end-of-stream when it stops, and every way a
station can fail arrives in the tab as a message instead: AAC, AAC+, Opus and
HLS streams by name, a web page where a stream was expected, an HTTP error, an
unreachable host, a rejected certificate, a stall, a dropped connection, data
that will not decode, and no audio device. miniaudio falls back to a null
device that accepts audio and plays nothing when a machine has no output; that
is refused as "no audio output device found". A `[Radio]` entry that cannot be
used is listed under Config in the tab rather than left out without comment.

The window's own rule was that an alert needing a tab change is an alert
missed, so any new alert brings the Crew / Alerts tab back to the front while
the radio carries on. Alerts already standing when the window opens do not.

Both tabs draw the same view from one `RadioController`, and a test checks
their controls match. Everything the terminal tab shows is passed as plain
text rather than markup: song titles come from the station, and a problem line
quoting `[Radio]` lost the word entirely when Textual read it as a tag, while
one containing `[/b]` would have raised.

`tests/test_radio.py` drives the real decoder and the real audio callback
against a local Icecast-style server through miniaudio's null backend, which
consumes samples in real time without a sound card, and covers each failure
above.

miniaudio is bundled in all three binaries, so the radio works without
installing anything. Playback is otherwise only exercised by pressing Play, so
a binary missing miniaudio's compiled half would have shipped looking fine;
`--selftest`, which the release workflow runs against each platform's binary,
now decodes a short embedded MP3 through the same reader and decoder a station
uses, needing neither a network nor a sound card.

### Added: add and delete radio stations from the Radio tab

A **+** and **−** beside the station list, in both interfaces. **+** opens a
form for a name, a stream address, and where to keep it — Global (preselected)
or the profile loaded now, which is disabled when there is none. **−** deletes
the selected station after a confirmation that says exactly what will change,
and stops it first if it is playing. A default station is hidden by blanking
its address rather than deleted, since deleted default lines come back at the
next launch. The new station is selected but not started. The logic lives in
`RadioController`, shared by both forms, so validation messages, the Id made
from the name, and what a delete touches are identical in each.

Both write `config.toml` through a new `edit_config_keys()` rather than
`ConfigManager.save()`, which regenerates the file from parsed values and would
have thrown away every comment in a file most people copied from the commented
example — as the side effect of adding a radio station. The new editor works
line by line like the defaults backfill: a key is replaced where it stands with
its alignment kept, a new one goes at the end of its table, a profile's keys go
under `[EDP1.Radio]` if the file has that table and as dotted lines under
`[EDP1]` otherwise. Line editing cannot see all of TOML, so the result is
parsed and compared with the intended document before anything is written, and
anything else is refused with the file left byte-for-byte as it was; the write
itself goes through a temporary file and keeps the file's permissions, since
it can hold credentials. That check caught a real case while this was being
built: deleting the last dotted `Radio.*` key removes the table outright,
which the comparison now treats the same as an emptied `[EDP1.Radio]`.

After a write the config is re-read at once through a new
`ConfigManager.reload_now()`. Waiting for hot-reload would not do: it compares
modification times, and two edits inside the filesystem's timestamp resolution
look like one.

The desktop theme gained a radio-button style. These are the first radio
buttons in the desktop window, and without one the platform draws the
indicator in the window colour, so the unchecked choice was invisible.

### Added: a dashboard template for the shared survey sheet

`sheets/Mining_Dashboard.xlsx` is a starting spreadsheet for squadrons that
publish their survey: import it into Google Drive, save it as a Google Sheet,
and bind `Code.gs` to it as before. It arrives with an empty `Deposits` tab
carrying the header row, so the receiver writes straight into it, and with
placeholders on the Settings tab for the squadron and the commander who
maintains it, from which the dashboard takes its title.

The Dashboard tab is the read side for people who open the sheet rather than
run EDLD. Choose a system, a commodity or both, and a table of matching
deposits appears — body, gravity, mining site, amount, density, rigs and when
it was worked out. Rows alternate in colour, High amounts and densities are
highlighted and Low ones dimmed, and depleted deposits are struck through.
Deposits flagged as test data are left out, as they are from EDLD's own reads.

The table sorts by any column, from Sort By and Order beside the filters or by
clicking a header, and the sorted header carries ▲ or ▼. Amount and Density
sort by rank — Depleted, Low, Medium, High — rather than alphabetically. The
sort is done inside the table's formula: the table is one `FILTER` expression,
and Sheets cannot reorder a formula's output in place, so Data → Sort range
over it either fails or is undone at the next recalculation.

It is styled after the game's HUD, with five colour presets — Classic HUD,
Federation, Empire, Alliance and Thargoid — and a Custom set of twelve hex
codes on the Settings tab, plus a choice of title and body font. Sheets cannot
colour a cell from a formula, so something has to turn those codes into
formatting: that is `sheets/Dashboard.gs`, a second script beside `Code.gs` in
the same project, which re-applies the theme whenever Settings changes and
adds the click-to-sort. Without it the template shows Classic HUD and sorts
from the dropdowns only.

An xlsx cell cannot hold `FILTER`, `LET` or an array literal over ranges, so
the template stores those formulas in the wrapper Google's own xlsx export
uses, which Sheets unwraps on import. **ED Dashboard → Repair dashboard
formulas** rewrites them if an import ever does not. Both the template and the
repair take the formula text from `FORMULAS` in `Dashboard.gs`, so they cannot
disagree.

`sheets/build_dashboard.py` generates the template, stamping it with the
`version` file's datestamp. The table picks `Deposits` columns by letter, so
it depends on `COLUMNS` in `Code.gs` the way `core/sheets_publish.py` does, and
nothing would raise if they drifted; the dashboard would show the wrong field.
`tests/test_sheets_dashboard.py` checks every letter against `COLUMNS`, the
sort rank against `AMOUNT_LEVELS` and `DENSITY_LEVELS` in `core/mining_db.py`,
the script's fallback palette against the template's, and that the committed
template is what the build produces now. openpyxl, which the build and the
last check use, is in `requirements-dev.txt`; it is never bundled.

### Fixed: the binaries carried none of their dependencies' licence texts

Textual, Rich, discord-webhook, requests, psutil and a dozen packages beneath
them are MIT, BSD or Apache 2.0. Permissive, but each sets one condition: its
copyright and licence text accompany every copy, plus the NOTICE file for
Apache. A binary is a copy of every package inside it, and PyInstaller bundles
the code while leaving the package metadata, where those texts live, behind.
`licenses/` held only the GPL and LGPL texts for Qt, so every release so far
has shipped the rest without them.

The build now copies each bundled package's licence files from the build
environment's own metadata into `licenses/third-party/<package>-<version>/`,
following `requirements.txt` and everything it pulls in, so the texts always
match the versions actually shipped and a new dependency cannot be forgotten.
A bundled package with no licence file stops the build. `--selftest` fails a
frozen binary that carries none, and `tests/test_dependencies.py` checks the
collector finds one for every bundled package.

### Changed: the requirements files match what EDLD imports

`requirements.txt` declared cryptography, which nothing imports. It was listed
in the notices as "Frontier CAPI token storage", which was never true: CAPI
tokens are stored as plain JSON in the commander's data directory. It is gone
from the requirements, `install.sh`, and the install commands and tables in
`README.md` and `INSTALL.md`. Rich, which the terminal blocks import directly,
is now declared rather than assumed to arrive with Textual.

`requirements-dev.txt` declared Pillow for `scripts/generate_icons.py`, which
does not exist; the icons are committed. It is gone. pytest and pyflakes, which
the tests need, are added, and so is PyPA's `packaging`, which the licence
collector uses. `tests/test_dependencies.py` compares both files with the
imports in both directions: an undeclared import fails, and so does a declared
package nothing imports.

### Fixed: `scripts/build_local.sh --dir` failed before building

It passed `-D` to PyInstaller alongside `packaging/edld.spec`, and PyInstaller
refuses layout options when given a spec file, so the directory build exited
with a usage error every time. The spec now chooses the layout from
`EDLD_ONEDIR=1`, which the script sets, and the script finds the executable
inside `dist/EDLD/` where that layout puts it. The build's preflight also
checks for miniaudio now.

### Fixed: a CAPI token file that failed to save said nothing

`_save_tokens` swallowed any error. A refreshed token that could not be written
worked for the rest of that run and then demanded a new Frontier login at the
next launch, with nothing recorded to say why. Failures to save or read the
token file are now written to the debug log, as the exception only; no token
content is logged.

### Fixed: the desktop Crew / Alerts window stopped updating with crew hired

`gui/blocks/status.py` called `fmt_crew_active` without importing it, so every
redraw raised as soon as hired crew had a hire date. The Active and Paid rows
never filled in, and because alerts are drawn after crew, the window's alert
feed stopped updating too. The terminal window has its own copy of the helper
and was unaffected.

### Fixed: accepting a massacre mission never refreshed the dashboard

`_on_massacre_accepted` read `settings`, a local of the event handler it was
lifted out of, to check for a full stack. Every live acceptance raised there,
after the "Accepted massacre mission" line and before the "Stack full" notice
and the dashboard repaint, so a full stack was never announced and the
Objectives window only caught up at the next unrelated event.

### Fixed: a window that failed to redraw said nothing

Both front ends guard each window's redraw so one fault cannot take the
dashboard down, and both guards were `except Exception: pass`. That is why the
two faults above went unnoticed. A redraw fault is now written to the debug log
with its traceback and shown as a standing fault in the Alerts feed, once per
window and fault since redraws run many times a second.

`tests/test_undefined_names.py` runs pyflakes over the whole tree and fails on
any undefined name, and would have caught both. It skips where pyflakes is not
installed.

---

## Released in 20260922

### Fixed: Ctrl+D closed EDLD instead of opening the deposit window

Textual validates a Select's value when the widget mounts, not when it is
constructed. The deposit form passed `None` for a choice field with nothing
selected, which raised `InvalidSelectValueError` inside a mount handler — and
an unhandled exception there takes the whole application down. So a bad default
on one field presented as EDLD vanishing on a keypress rather than as a broken
control.

Every field is blank on a new deposit, which made it certain the first time
anyone pressed Ctrl+D on unrecorded ground. Nothing was written to the
diagnostic log, because Textual tears the app down before the exception hook
runs; the log simply stops mid-frame.

The value is now omitted entirely when there is nothing to select. Not `None`,
and not the blank sentinel either: that has moved between Textual releases — it
is `Select.NULL` in some and `Select.BLANK` in others, and in at least one
version `BLANK` is a plain `False` that the validator then rejects. Leaving the
argument off uses whichever default a given release considers blank, across the
range `requirements.txt` allows.

`tests/test_deposit_screen.py` mounts the screen in a headless app rather than
constructing it, for the new-deposit case, the fully-populated case, a
partially-filled one, and each choice field blank on its own. Building the
widget was never going to catch this; only mounting it does. The desktop
dialog was checked for the same fault and does not have it — an unknown value
there falls back to the blank entry.

Chasing the same failure further found a second way in that the first fix did
not close. Any stored choice value that is not exactly an option crashes
identically — `high`, `Very High`, `vhigh` — and one can reach the store:
`import_deposits` wrote sheet values verbatim, and a sheet is a document people
edit by hand, so another commander's cell would have taken the window down on
whoever opened it next rather than on whoever typed it. The widget now matches
case-insensitively and drops anything unrecognised, and the import normalises
amount and density to the vocabulary, discarding what it cannot place: a wrong
value is worse than a blank one a later sighting can fill in.

### Fixed: a surface scan moved the commander to the scanned body

Scanning two bodies back to back while parked in an SRV on the first filed
every later refine against the second. Three deposits landed on a body that had
never been approached, carrying the coordinates of the one underneath — a
Deuterium site on top of a valid Low Temp. Diamond one.

`_on_saa_signals` set the tracked body to whatever it had just scanned. A
surface scan is about a body you may be nowhere near; they are done from orbit,
often several in a row. It records the census for the scanned body now and
leaves the commander where they are. Where that is comes from `ApproachBody`,
`Location`, `Touchdown` and `SupercruiseExit` — events about the ship rather
than about a telescope.

A second guard backs it up: Status.json names the body underneath, and a refine
is refused when that disagrees with the tracked identity. A deposit written
during a disagreement carries the right coordinates under the wrong body, which
is precisely what happened, and no amount of care in one code path prevents
another from drifting.

### Added: deleting a deposit, from the site

For a row that should never have existed — a wrong commodity, a position filed
under the wrong body. A site that is merely empty should be marked Depleted
instead: that is information the next commander wants, and deleting it invites
them to rediscover it.

Restricted to standing at the deposit, like every other action in the survey,
and for a stronger reason than convenience. A deposit on the shared sheet is
somewhere other commanders will fly to, so being able to remove one from a list
would make a stray click into somebody else's wasted trip.

It propagates. Only rows that actually reached the sheet cost a request, and a
sheet that cannot be reached does not stop the local removal — otherwise a row
known to be bad survives on the machine that knows it is bad. Deletion sticks
because imported deposits are stamped as published and never re-sent: the only
copy that could put it back belongs to whoever recorded it, and that is the
commander doing the deleting.

### Added: the depletion date is shared

`depleted_on` is a published column now, read back on import like everything
else. It lives in its own table rather than on the deposit row, so the publish
query fetches it — otherwise it was recorded locally and dropped on the way
out, which is the half of the feature that matters least.

It is the one fact about a deposit that any commander can contribute and every
commander needs: a site somebody emptied last week is a wasted trip, and only
the person who found it empty knows.

The most recent date wins on a merge, unlike every other field where local
observation does. Sites reset and are worked out again, so the freshest
sighting of an empty one describes the current state; an older date would keep
asserting a depletion that has since been undone.

A sheet created before this column keeps its old header, and the script only
writes a header when the sheet is empty — so an existing squadron sheet would
have silently dropped every value past its last column. It is widened in place
instead. Columns are only ever appended, never reordered, so existing data
stays where it is.

### Changed: the deposit window records when a site was worked out

The **Advertised** field is gone. It held the density the body's signals
promised, which on reflection is the density of the fresh deposit — the same
measurement Density already records, so it was two controls for one number.

**Depleted on** takes its place: a date, validated, refused if it is in the
future. A button reading "Mark Depleted" would have been the same redundancy
in a different shape, because choosing Depleted in the Amount list already
stamps today.

Amount and the date divide the work instead of overlapping. Amount says whether
a site is worked out; the date says when. Supplying a date records a site
worked out last week and implies Depleted whether or not Amount was touched.

The date lives in its own table rather than on the deposit row, so the window
fetches it — without that a site already known to be worked out would have
shown the field blank, and saving would have silently re-stamped it with today.
That date is what a reset-period calculation gets built on, so it is worth
being the day it happened rather than the day somebody noticed.

The `density_claimed` column stays in the store and on the sheet: rows imported
from other commanders may carry it, and dropping the field a form offers is not
a reason to discard data already collected.

### Fixed: saving a deposit with a signal number raised TypeError

The form offered a Signal # field and `annotate_deposit()` had no such
parameter, so filling it in and pressing Save failed — after everything else
had been typed. Nothing checks that pairing at import time; the form builds its
controls from one list and the store declares its parameters in another, and
the two had drifted.

`signal_no` is accepted now, and a test asserts every field the form can
produce is one the store takes, so the next field added to either side cannot
quietly fail on the one that matters.

### Fixed: the deposit window filled the terminal

Three of the style classes it asked for did not exist, so it had no width, no
border and no centring — and it inherited the preferences row rules, which size
the label column at 45%. Inside the preferences container that is the house
style; in a window spanning the whole terminal it put every label a thousand
pixels from its control.

It has its own container rule now: a fixed, centred, bordered box with a
narrower label column. A test asserts every class and id the window uses is
styled somewhere, because an unstyled name fails silently and only looks wrong.

### Fixed: Ctrl+D just after a refine offered to add a deposit already on its way

A refine queues its deposit and does not write it until the confirm interval
has passed, so pressing Ctrl+D moments after mining the first unit described
unrecorded ground and invited a second row for the same rock. The pending queue
is flushed before the window is filled, so it now opens on the deposit that is
actually there.

---

## Released in 20260916

### Added: keybinds and a window for adding and editing a deposit

**Ctrl+D** opens a form for the deposit underfoot. **Ctrl+G** pushes everything
pending to the shared sheet. Both are bound identically in the TUI and the GUI,
and the GUI also carries them on a Survey menu.

One binding covers adding and editing, because the commander does not know
which they are doing until EDLD has looked at where they are standing.
`form_for_here()` resolves that by proximity — the same rule every other action
in the survey uses — and returns either blanks and a "New deposit" heading or
the stored values and an "Editing" one.

Typed values reach a sheet other people read, so validation is a module of its
own with tests rather than a few `strip()` calls in a dialog. A malformed row
on a shared sheet is not a local mistake: it is a row somebody else fetches,
fails to parse, and blames on their own install. Amount and density are matched
case-insensitively against Frontier's vocabularies, rigs and signal numbers are
range-checked, and a hand-typed commodity canonicalises to the journal's own
spelling so it deduplicates against a captured one.

An empty field means leave it alone rather than set it to nothing — editing the
amount must not silently blank the density recorded last week. A rejected form
stays open with the reason on it rather than discarding what was typed.

The commodity cannot be changed on an existing deposit. It is part of the
deposit's identity, and altering it would leave the id pointing at something
else on every sheet that already has the row.

Both windows build their controls from one field list and submit through one
component method, so neither can drift from the other on what a deposit has or
on what counts as valid.

### Added: published deposits carry the body's facts

A deposit was reaching the sheet with five of its twenty-three columns empty —
coordinates and a commodity, but no planet class, gravity, atmosphere or
volcanism, which is what tells a squadron whether a site is drivable. The
survey only learned those from a `Scan` in the current session, and a body
scanned months ago produces none.

EDLD already had all of it. `explo.db` holds a planets table with exactly those
columns, from the same scans; it was simply never asked. The body record is
filled from the catalogue before a deposit is written, blanks only, so a live
`Scan` still wins.

### Added: a deposit can be flagged as test data

The config switch flags everything recorded from now on and cannot reach the
one row that was a mistake. **Flag as test** and **Unflag** act on the deposit
underfoot, resolved by position like every other action there. Flagged rows
stay in the local store and are held back from the sheet, so a bad row is
retired without deleting the evidence.

### Changed: the overlay is released on Linux and experimental elsewhere

X11 with a compositor is tested and supported. Windows and macOS are untested
and stay experimental — `--overlay-probe` turns a report from either into a
capability line. Wayland remains unsupported for protocol reasons rather than
effort ones.

The compositor is documented as a dependency rather than a nicety: without one
there is no alpha channel to composite into. EDLD falls back to an opaque panel
so the text stays readable, but transparency needs picom or equivalent running.

### Fixed: published deposits had no system name

The first real row to reach a shared sheet named the body and left the system
column empty — `Ega 3 a` with no `Ega`. A row that names the rock but not the
system is one nobody else can use.

The system name was only ever written to the body record by the `Scan` handler.
A body scanned in an earlier session produces no `Scan` in this one, so the
record was created by the signal census or by the deposit flush, both of which
knew the body name and not the system. It is carried into every path that
touches a body now, from whatever event last said where we were — and
`FSDJump` was added to the subscriptions because in a session that starts in
supercruise it is often the only event that says.

### Added: the survey reads back, not just up

The sheet was write-only. EDLD published deposits and never fetched any, which
made the in-game compass point exclusively at sites the commander had already
found — which the game's own HUD is already showing them, with a marker and a
distance. That is not a feature; the shared half was the feature, and it did
not exist.

On arriving at a body, EDLD asks the sheet what is known about it and merges
the answer into the local store. The compass then points at deposits nobody
running this has ever seen.

Scoped to one body rather than pulling the sheet down, because that is the
question being asked, and once per body per session — arriving, leaving and
coming back should not spend three requests to learn the same thing. There is a
**Fetch this body** button for when it should.

Imported rows are stamped as already published, so a deposit that came down
never goes back up. Without that every commander would re-publish every other
commander's finds on their next flush and the sheet would spend its write quota
echoing itself.

Local observation wins. An imported row only fills fields the local row does not
have, and only advances `last_confirmed` if the sheet's is newer: what the
commander saw with their own eyes is better evidence than what a stranger wrote
down last month. A deposit you found worked out stays Depleted however rich
somebody else remembers it.

A sheet that cannot be reached is recorded and carried on from — it is a reason
to have fewer deposits on the compass, not a reason to stop surveying.

`sheets/Code.gs` gains the read endpoint. It reads the used range once and
filters in memory rather than a `getRange` per row, which is the difference
between answering instantly and timing out once a squadron sheet has a few
thousand rows in it. Test rows are never served.

### Fixed: a finished run of refines was never written

Four tonnes of silver refined with EDLD running, and no deposit, no error, and
not one log line.

`_flush_pending()` ran only at the end of `_on_refined`. A run of refines
collapses into a single pending entry that is not ready to be written until
`_CONFIRM_INTERVAL_S` has passed — so the last refine queued the deposit, found
it too young to write, and nothing ever ran again to try. The code had
succeeded at every step up to the final one and then had no reason to execute.
The silence was the worst part: every diagnostic added for this feature reports
a failure, and this was not one.

The flush is on a clock now, alongside the proximity check, and that tick runs
whether or not proximity confirmation is switched on — the flush is not
optional.

A collapsed run also advances `refine_count` by how many refines there were
rather than by one, so a deposit worked for an hour and one touched once are
distinguishable.

### Fixed: SRV cargo had no denominator

The overlay read a `srv_cargo_capacity` state field that does not exist, so it
showed "SRV 4" while the dashboard three feet away showed "4/72". The journal
never reports a surface vehicle's capacity; it comes from the same table the
dashboard uses, and is still omitted rather than guessed at for a vehicle that
is not in it.

### Added: a reachable way to record the deposit you are standing on

Preferences → Survey → **Record a deposit**: commodity, amount, density, and a
button. EDLD takes the position from the game; those three are on the HUD and
in no journal event, so they are the only things it has to ask for. There is a
**Mark depleted** button beside it.

`record_here()` and `mark_depleted_here()` have existed and been tested since
they were written, and nothing could call them. That was the whole gap between
a commander parked on a Helium-3 deposit and a survey with a row in it.

Component buttons now receive the screen's live widget values. Not the
pending-change map: a field typed into but not yet saved is exactly the one an
action like "record what I am standing on" needs, and nothing has been applied
at that point. These are not settings and are deliberately not stored — they
describe one rock, once.

### Fixed: a hand-typed commodity did not match the journal's spelling

The journal writes `$helium3_name;`; a commander types `Helium-3`. Those
canonicalised to `helium3` and `helium-3`, so the same rock recorded by hand and
then refined would have become two deposits. Canonicalisation now drops
everything that is not a letter or a digit.

### Changed: overlay windows grow to their content

`Height` and `DockHeight` were settings, which meant a stack taller than the
number was silently clipped — with no way to tell a panel that was missing from
one that was merely cut off. Career figures made the stacks taller and the
generous number became the wrong one. Both settings are gone; each window sizes
itself to the frame it is handed.

Only the height moves. Width stays a setting because it is a real choice: it
decides where a centred zone centres and where a right zone right-aligns, and
resizing it underneath the commander would move text they had placed.

### Changed: the overlay is the Streamer Stats Overlay

It is not a second dashboard and has stopped pretending to be one. EDLD already
is a dashboard and is better at it — a second screen has room for everything and
you can look at it whenever you like. The overlay carries the subset you cannot
look away for, and the subset someone else is looking at. The name says which.

`docs/STREAMER_STATS_OVERLAY.md` is new and is the first documentation the
feature has had: panels, placement, the career/session choice, spacing, type
and colour, where it will not run, and the three diagnostic commands. Indexed
from the README, and the preferences page and plugin name use the full name.

The "No overlay" decision in `docs/EXPLORATION_EXOBIOLOGY_PLAN.md` is marked
superseded rather than rewritten. Its reasoning still stands for the
exploration and exobiology windows, which put every datum in a box rather than
relying on an overlay to carry it; the overlay was added later for a different
purpose, and pretending the earlier decision had said so would lose why those
windows are built the way they are.

### Changed: the overlay's text shadow is derived from the text

It was a flat black copy offset by one pixel, which is the obvious choice and
wrong twice over. Against a tinted palette flat black reads as a separate
colour — a black fringe on Elite orange looks like a printing error — and it
does nothing at all for the light theme's dark ink, where the shadow has to be
*lighter* than the text to separate it from the background.

The shadow now keeps the ink's hue and moves its lightness to the far end,
with saturation pulled down so it reads as depth rather than as a second colour
in the palette.

The lightness threshold is deliberately low rather than at the midpoint. What
matters is not whether the ink is light in the abstract but whether it is
lighter than what is behind it, and what is behind it is the game —
overwhelmingly dark. A midpoint threshold gave the muted amber label colour a
near-white shadow, which against a starfield would have been the brightest
thing on screen.

`ShadowOffset` (0-2 px, 0 disables) and `ShadowStrength` are settings in both
front ends. The offset is capped at two because past that it stops reading as
depth and starts reading as a second, blurry copy of the text.

The derivation is a pure function taking and returning a hex string, so the
colour it picks for every palette can be checked without a display.

### Added: each overlay panel chooses career, session, or both

A per-panel setting alongside zone, position and mode: Session, Career, or
Career (Session: ). The third puts the career figure first with the session in
parentheses, because a commander who wants both wants to know what today added
to the total rather than to read two numbers and do the subtraction.

Career rows come from `core.summary_model.career_sections`, matched to an
activity by its tab title, so nothing needed wiring up per component — only
Odyssey and Income name a section that differs from their tab, and they declare
it. An activity with no matching section has no career figures, and the picker
is simply not offered for it: a dropdown choosing between career and session
where only one of them exists is a control that does nothing.

Scope is set on the component just before it is asked for its panel, rather
than passed through the collector, so a component that overrides
`overlay_panel()` — cargo, the survey compass, powerplay — is unaffected and
takes no argument it has no use for.

`Career` also survives a quiet session, which `Session` by definition does not:
a career figure is true whether or not anything happened today, so a panel set
to Career is drawn from the first frame.

### Added: a PowerPlay overlay panel

The power's name as the header, the commander's rank beneath it, and nothing
else. An unpledged commander gets no panel at all — not an empty one, not one
reading "None". PowerPlay is opt-in, and an overlay line whose only content is
that a feature is switched off is worse than the space it takes.

It overrides the activity mixin's default rather than using it. That default
would have reported session merits, and only once some had been earned;
allegiance and rank are true the moment you undock and are what a pledged
commander would actually want on screen.

### Fixed: nothing reachable controlled the overlay's distance from the screen edge

`OffsetY` set the gap between the monitor's top edge and the overlay window,
defaulted to 40, and was exposed in neither front end. The setting that *was*
exposed, labelled "Padding Y", moved text around inside a window of fixed size.
So the obvious question — what moves the overlay down the screen — had no
answer anyone could reach, and the control that looked like the answer was not
it.

Two layers now, named for what they are:

    Margin   monitor edge  →  window edge   (moves the whole overlay)
    Pad      window edge   →  first glyph   (breathing room in the box)

Both are settings in both front ends. `OffsetX` and `OffsetY` are still read as
a fallback, so an existing config keeps the position it had. The docks use the
same margin as the top bar, so the three windows line up.

### Changed: overlay panel content

Credits moved from the commander panel to income. It is a number about money
and belongs beside the rate that is changing it — a commander watching what
they are earning wants to see what they have. Income now reads as a balance and
a session line with its rate.

The vessel panel is the ship's name and ident as its header, then what you are
currently in when that is not the ship, then the type and the value. Hull and
shields are gone: they are live status the game already shows on the HUD in a
form that cannot be missed, and repeating them spent two lines of a very small
display telling the commander something they were already looking at.

The header stays the ship whether you are sitting in it, driving an SRV or on
foot, so it does not move around; what you are in is the first row.

### Changed: the overlay options list is alphabetical

It was grouped by zone and then position, so the page read like the screen —
but that meant a row jumped the moment its zone changed, and the setting you had
just edited moved somewhere else in the list.

### Added: Apply & Save redraws the overlay

The overlay watches config.toml's modification time and reloads when it
changes. Watched rather than hooked, because both front ends write the same
file and neither had anything to notify a component with; it also means a
hand-edited config takes effect the same way. Reserved panel heights are
dropped on reload, since they describe the layout that has just been replaced
and would otherwise hold gaps open for panels that had been moved or switched
off.

### Fixed: the commander name was read from one journal file only

Elite writes a new journal the moment it launches and does not emit `Commander`
or `LoadGame` until a commander is actually loaded in. Start the game and leave
it at the main menu, start EDLD, and the newest journal is a `Fileheader` and a
couple of `Music` events — so the name lookup, which read that file and only
that file, found nothing.

It is not a missing label. `pilot_name` is what config profile auto-detection
keys on, what EDSM and Inara wait for before sending anything, and what the
overlay's commander panel needs before it will draw. One unscanned file left
all of them idle: `Position check skipped — journal preload did not populate
commander name within 30 s`, `Deferring send — commander name not yet known`,
and an overlay that reported an empty frame every half second because its only
enabled panel had nothing to show.

The FID lookup twelve lines below has always known this — its comment says the
current journal may hold only a Fileheader and that prior journals are reliable
— and the name lookup simply never had the same treatment. Both now share one
scanner that walks backwards through journals, newest first, and takes the
first file that has the field.

### Changed: the commander panel's header is the commander

`CMDR <name>` is the title, with squadron, balance and location beneath it. A
`COMMANDER` heading directly above `CMDR Merrick Calbruin` spent a line of a
very small display saying the same thing twice.

### Added: docked overlay windows down the left and right edges

Two more zones, `dock-left` and `dock-right`, each a window against its screen
edge holding a single stacked column with the same 1-9 positions the top bar
already had. The top bar keeps its three columns and its zone names —
renaming `left` to `top-left` would have silently unplaced every panel in every
existing config, since an unknown zone is reported and skipped.

Each dock is a separate window so it can be sized and placed on its own, and
because a frame sent an empty element list hides its window: a commander who
docks nothing never sees them. Dock width, top offset and height are settings.

Both docks lay their text out left-to-right. Right-aligning the right-hand dock
against a narrow window would press the text into the screen edge, which is
where it is least readable.

### Changed: the overlay does not start where it cannot work

Terminal mode has no window for an overlay to sit beside, a secondary instance
is not the machine the game is running on, and a headless session has no
display at all. None of those are a setting a commander got wrong, so the
component checks before it reads any config and says which one applied.

`CoreAPI` now carries `ui_mode`, because a component cannot ask which front end
is running unless something tells it.

### Fixed: the GUI Overlay tab compressed itself into overlapping rows

The panel grid sat in its own scroll area with a stretch factor, inside a tab
of fixed height. That scroll took the vertical space the form rows above it
needed, so each was squeezed below its own minimum and the WINDOW and TYPE
sections drew on top of one another, with the footnote landing across the grid.

Twenty-odd settings will not fit in that tab whatever the arrangement, so the
page scrolls as one instead: a single scroll area around the whole thing, the
grid back in the normal flow, and a trailing stretch so the last widget does
not absorb the slack.

### Added: EDLD ships its overlay fonts

JetBrains Mono and Euro Caps live in `fonts/`, which is in `DATA_FILES` so
frozen builds carry it. The renderer registers everything it finds there with
Qt at startup, then does the same for `<data>/fonts/` — so the shipped faces
work out of the box and a commander can still drop their own in without
touching fontconfig or needing root. When frozen, the shipped directory is
found under `sys._MEIPASS`.

JetBrains Mono is SIL OFL 1.1; `fonts/OFL.txt` sits beside it because the
licence requires the text to travel with the font. Euro Caps is freeware. Both
are recorded in THIRD-PARTY-NOTICES.md.

### Added: an Elite Dangerous colour theme, and themes for the overlay

`elite-orange` — the cockpit HUD's own orange, `#ff7100` on near-black. It is
deliberately not one of the "EDLD Default" family: those are EDLD's identity,
this one matches the game so an overlay sitting on top of it does not look like
a different program. It is the overlay's default.

The overlay takes a colour theme rather than three colours. The picker offers
every palette in `core/palette.py` plus Custom, and the title, label and value
colours are derived from each palette's accent, dim and foreground — so a theme
added to `palette.py` reaches the overlay with nothing else edited.

A theme overrides what is drawn, never what is stored. Switching back to Custom
restores whatever the commander had set, rather than whatever the last theme
happened to leave behind.

### Added: fonts are discovered, not hardcoded

Every `.ttf` and `.otf` in `<data>/fonts/` is registered with Qt at renderer
startup, so Elite's own faces work by dropping the files in — no fontconfig, no
root, no system install. The renderer reports which families it registered and
the preferences page shows them as the font field's placeholder.

Deliberately not a hardcoded list of Elite font names. The set of faces on
offer is not something this code can know, and a name guessed wrong is a
setting that silently does nothing.

### Fixed: the first row of every overlay panel was clipped

`drawText` takes a *baseline*; the layout works in tops. Passing a top as a
baseline puts the whole ascent of the first line above the requested y, so it
was drawn above the window and cut off — however far the window was padded from
the screen edge, because the padding was never what was wrong.

### Changed: padding is the commander's, and there is none inside the box

The layout began at a hardcoded eight pixels in and sixteen across. Those are
now `PadX` and `PadY`, the panel stack starts at zero, and the offset from the
monitor edge is the only spacing anyone has to reason about.

### Added: font family, sizes and colours

Any locally installed family by name, blank for the default. Title and body
sizes, and the three colours the panels already used — title, label, value —
are settings rather than constants.

Line height is derived from the body size rather than fixed. A commander who
raises the font and finds the rows overlapping each other has been handed a
setting that breaks the layout, which is worse than not offering one.

### Changed: SHIP is now VESSEL, and says what you are actually in

Titled for the current vehicle: SRV with the SRV's type, ON FOOT with the suit,
VESSEL otherwise, and what you are in is listed first. "SHIP" while sitting in
an SRV is the small wrongness that makes a reader stop trusting the rest of the
panel, and the frame's context already carried what was needed to get it right.

### Fixed: every overlay frame stopped at the thread boundary

The parent was sending nine elements twice a second and logging `sent=True`,
truthfully. The renderer was running, had reported itself ready, and drew
nothing.

`QTimer.singleShot` creates its timer in the *calling* thread. The stdin reader
is a plain worker thread with no Qt event loop, so the timer it created had
nothing to fire it and every frame was accepted, marshalled, and silently never
delivered.

That is also exactly why `--overlay-selftest` worked. It calls singleShot from
the main thread, before `app.exec()`, where there is a loop to run it — so the
one path that proved the renderer was the one path that did not use the
mechanism the renderer actually depends on. A working selftest and a blank
overlay were not contradictory; they were the same fact seen from two sides.

Frames now cross by Qt signal, emitted from the reader and received by an
object created on the GUI thread, which is what makes the queued connection
land in the right place. The two `app.quit` calls made from worker threads had
the same fault and use `QMetaObject.invokeMethod` with a queued connection.

A test walks the AST of `_reader` and `_watch_parent` and fails on any
`singleShot` in either.

### Added: the overlay component identifies its own build in the trace

Twelve archives in, "is that fix actually applied" has cost more round trips
than any single defect. The component now logs its version, its placement
count, how many are active and whether a renderer client was constructed — at
load, unconditionally, before anything can fail. A trace log now answers which
build produced it without a repo diff.

Every frame send is logged at TRACE with its element count and whether it went
out. INFO would drown at two frames a second; TRACE is on exactly when someone
is diagnosing.

The child reads stdin with `readline()` rather than iterating the file object.
This was done on the theory that iteration read-ahead was holding frames in a
buffer — a measurement showed both deliver in under 20 ms on a pipe, so that
theory was wrong and the change is kept only because an explicit loop is
clearer about its EOF condition.

### Added: the overlay says what is in its frames

`--overlay-doctor` runs before the components load, so it can report config and
placement but never whether a frame would actually have content in it. With
"placement looks sound" and "renderer ready" both true and nothing on screen,
there was still no way to tell a frame carrying three panels from a frame
carrying none.

The first frame that goes out is logged with its element count and which panels
contributed. A frame that comes back empty is logged once, with how many panels
were asked and how many returned content — because a panel on `auto` deciding
it does not apply is the most likely reason for an empty frame, and it is
indistinguishable from a broken one without being told.

### Fixed: the overlay window was invisible, and nothing could tell you so

The renderer started, reported itself ready on xcb with two screens, and drew
nothing anyone could see.

The capability probe called ``app.isEffectivelyCompositing()``, which does not
exist on QApplication. Wrapped in ``getattr(..., lambda: True)``, it answered
True every time, so compositing was reported and never measured. Without a
compositor there is no alpha channel to composite into, a
WA_TranslucentBackground window has no meaningful backing store, and the
overlay renders nothing at all — which is a bare i3 session with no picom, and
is common. It also explains why the first version, which forced an opaque
surface through setWindowOpacity, at least produced visible boxes.

Compositing is now measured by asking X who owns the ``_NET_WM_CM_S0``
selection, through libX11 which is already loaded in any X session. Without a
compositor the window paints its own background so the text is readable — less
pretty, and actually there. When the answer cannot be determined it errs toward
opaque, because assuming a compositor and being wrong renders an invisible
overlay while assuming none and being wrong renders a readable one.

### Added: --overlay-selftest, and the renderer says where the window went

"The renderer is running" and "there is something on screen" are different
claims, and from outside they looked identical — the process was visible in
``ps`` and that was the whole of the available evidence.

The renderer now reports its first mapped frame back over the protocol:
element count, whether the window is actually visible, its geometry, which
screen it landed on, and the alpha in use. That distinguishes a window drawn
off-screen, on the wrong monitor of two, or at zero size from one that was
never sent anything.

``--overlay-selftest`` draws a fixed frame for twenty seconds with no parent
and no panel pipeline, so "the renderer cannot draw" and "nothing is being sent
to it" stop being the same symptom.

### Fixed: every live refine was dropped, silently

190 `MiningRefined` events for Helium-3 in one real session, between LaunchSRV
and DockSRV, with EDLD running throughout. Nothing recorded.

The position join matched a Status.json sample within two seconds of the
event's timestamp. But the game writes the journal in batches, so the gap
between a refine happening and EDLD reading the line routinely exceeds that —
and every refine fell through the hole.

Worse, it fell through in silence. Only the replay branch logged anything, so
the trace showed "replayed MiningRefined events carry no position" at startup
and then nothing at all for two and a half hours of live mining. The one
message printed was about the case that was working as designed.

When the window misses and the event is recent, the current position is used
instead. That is the right answer rather than a fallback: refining requires the
SRV to be parked on the deposit, so where the commander is now is where the
refine happened. It is only wrong once they have driven off, which the
three-second freshness check already covers, and a test asserts a stale
position is still refused.

A live refine that cannot be placed now says so, once. Silence is what made
this look like nothing happening.

### Fixed: config silently discarded every overlay panel placement

`load_setting()` resolves a section by iterating `defaults` and nothing else, so
a key not declared there is invisible however plainly it is written in
config.toml. The overlay names one key per panel and gets its panels from
whichever components are loaded, so those keys cannot be declared in advance.

Placement was written correctly every time, by both front ends, and never read
back by either — which presented as the front ends clobbering each other, then
as a UI that would not save, then as an overlay that would not draw.
`--overlay-doctor` showed thirty-nine keys in the file and zero reaching the
code.

`load_setting()` takes `include_extra`, off by default so every fixed-schema
section behaves exactly as before.

### Added: --overlay-doctor

Every layer of the overlay is individually tested and the thing still does not
appear, which means the faults are in the joins: config written but not read,
panels offered but not placed, placements that parse and resolve to nothing, a
renderer started and handed an empty frame. From outside, every one of those
looks the same — no overlay — and diagnosing it from a screenshot has produced
several wrong answers.

`--overlay-doctor` reads the live ConfigManager, so it sees the same file,
profile and resolution order the running app does, and prints what each stage
produced: which placement keys exist in config, what they parsed to, which
panels the loaded components offer, whether any placement names a panel nothing
provides, how old the last Status.json sample is, and a verdict naming the
first link that breaks.

A doctor that built its own view of the config would end up diagnosing itself,
which is why it takes the manager rather than re-reading the file.

### Added: record the deposit you are parked on

Automatic capture creates a deposit from a `MiningRefined`, which is the only
event the game emits that implies one. Driving onto a deposit emits nothing at
all: across eighteen minutes of approaching and parking on one, the journal
produced a single `ModuleInfo` and nothing else. No approach, no target, no
signal entry. Meanwhile the HUD shows the commodity, the mineral amount and the
density, none of which reaches any file.

So a deposit seen but not yet worked cannot be captured without the commander
saying so. `record_here()` takes the position from Status.json and asks only
for what is on screen and in no file. It creates if there is nothing recorded
nearby and annotates if there is, so pressing it twice corrects a reading
rather than adding a second rock.

A position older than three seconds is refused rather than used. Recording a
deposit at a coordinate from five minutes ago would put a fictional position in
a store whose only value is that its positions are real.

### Changed: the dedupe radius is 100 m

It was 75 m, sized against the positional error of the capture path. The gap
between real deposits is the number that matters, and observed spacing on
surveyed bodies is 400-500 m at the closest — so 100 m cannot merge two
neighbours, and is still close enough to walk from. The rig spacing the game
actually requires is not known; if it turns out to be consistent, this is the
number to revisit.

### Fixed: overlay panel placement could never be saved

The preferences writer stores a pending change by assigning
``target[key] = value``, so the key is written literally. A dotted
``Panels.<id>.Zone`` therefore became a flat string key containing dots rather
than a nested table, and nothing ever read it back. Panel placement could be
changed in either front end, saved without complaint, and have no effect at
all — which is why the two front ends appeared to disagree and why no overlay
window ever surfaced: every panel stayed at its shipped default of off, with no
way to change it.

Placement uses flat ``PanelZone_<id>`` / ``PanelMode_<id>`` / ``PanelOrder_<id>``
keys now, which survive that writer unchanged. A hand-written ``Panels`` table
is still read, for anyone who prefers editing TOML, with flat keys winning
field by field. A test round-trips a placement through the real config writer
and reads it back, and another fails on any dotted key appearing in the
component at all.

### Added: deposits confirm themselves when you drive onto them

The original design was "keep the deposit targeted and get within X metres".
That cannot be built. `ShipTargeted` is the only targeting event in a full
journal corpus and it is ships only; no surface point of interest appears in
any journal event, and Status.json carries no target field. EDLD cannot know
what is targeted.

Position alone turns out to be enough, and is better: nothing else is within
25 m of a deposit, there is nothing to explain to the commander, and there is
no failure mode where they forgot to lock something.

What a visit records is freshness and nothing else. How much is left is a
judgement and stays with the commander — but freshness is the one thing about a
deposit that decays on its own, because sites are worked out by other people,
and it is the one thing nobody will ever update by hand. An old High is not a
current High.

Hysteresis is the whole of the engineering. The naive version fires on every
sample inside the radius, which at two samples a second means a parked SRV
rewrites the same row a hundred times a minute, `last_confirmed` becomes a
record of how long somebody idled, and — since every confirmation clears
`published_at` — that one deposit is pushed to the shared sheet on every flush
forever. An arrival fires once and the deposit must be left, past a wider exit
radius than the entry one, before it can fire again. The two radii differ
deliberately: a single threshold makes a commander parked at exactly 25 m
generate an arrival every other sample, which is the same bug with extra steps.

The check runs on its own tick rather than the overlay's. A commander with the
overlay switched off should still have their survey stay current; tying data
collection to a display would make the data depend on whether anyone was
looking at it.

`touch_deposit()` moves the timestamp and nothing else. `annotate_deposit()`
refuses a call with no fields — which is exactly what a visit is — because it
exists to apply a judgement.

### Fixed: the overlay was a black rectangle, and outlived the dashboard

Three faults in the renderer, reported from a real run.

`setWindowOpacity()` on a `WA_TranslucentBackground` window asks the compositor
for a semi-transparent *surface*, and several compositors answer by giving the
window an opaque one to fade. With nothing placed there was nothing to paint,
so what reached the screen was a black rectangle over the cockpit. Opacity is
applied to the ink now, so an empty frame is genuinely nothing.

The window was shown at startup rather than when it first had content. A shown
window with no content is still a window — a compositor, a screen recorder or a
task switcher can all find it. It appears with its first non-empty frame and
hides again when a frame comes back empty.

And it outlived its parent. Closing stdin is the normal shutdown and the reader
thread handles it, but a parent killed or stopped without running its unload
path left the renderer drawing over the game with nothing feeding it. A
watchdog now quits when `getppid()` changes.

### Fixed: publishing to a sheet returned HTTP 403

Two causes, both in the transport rather than in anyone's Apps Script.

An `/exec` deployment answers a POST with a 302 to
`script.googleusercontent.com`, and the standard library turns a redirected
POST into a GET — so the request arrived at `doGet()` with no body, from a
deployment configured correctly. Redirects now re-issue the POST.

`script.google.com` also rejects unfamiliar clients, and the request announced
itself as `EDLD-surface-survey/1.0`. It presents as a browser now. The request
is still authenticated by the token and still goes to the user's own script;
the alternative is a feature that only works from a browser.

### Fixed: preferences UI faults reported from a real run

The TUI Survey tab had no Test button — the screen's button dispatch named
every button it builds itself, so an injected tab could draw one that did
nothing. Components handle their own buttons through `preferences_action()`
now, and the Test button runs the same code in both front ends rather than two
implementations that would eventually disagree about what counts as success.

TUI dropdowns were sized for "On"/"Off", so "top-centre" wrapped to "Cent"/"re"
and "Reserve" to "Rese"/"rve".

The GUI overlay tab drew three form rows per panel on a page that does not
scroll — thirty-six rows once a dozen components contributed, which overlapped
into unreadable text. It is one row per panel with three pickers side by side,
inside a scroll area.

### Removed: the dead surface_frame path

Replaced by the survey compass panel and referenced by nothing but its own
tests.

### Added: panel ordering, without editing config.toml

Position within a zone is a picker in both front ends rather than an integer
only reachable by hand-editing config. It is a closed vocabulary like zone and
mode, so it gets the same treatment.

Two panels given the same position fall back to panel id — stable and
alphabetical, and deliberately boring. The alternative reorder-by-insertion
renumbers panels the commander never touched, and a tie broken by whatever
order the config happened to parse in would reshuffle the overlay between
launches, which is worse than a dull rule.

The preferences page now lists panels grouped by zone, left to right, in the
order they will actually stack, so the page reads the way the screen will look.

### Changed: overlay panels come from what components already compute

The first cut had each component write a fresh relevance test and a fresh row
set for the overlay. That was wrong, and it was wrong in a way that would have
kept costing: an activity component already answers both questions. It has
`has_activity()`, which is what decides whether the activity gets a tab in the
session block at all, and `get_summary_rows()`, which is already the condensed
subset because that is exactly what the Summary tab needs it to be. Writing
either again for the overlay is a second answer to a question already answered,
and the two would drift the first time one was updated alone.

`ActivityProviderMixin` now supplies the panel. Nine components contribute one
with nothing added to them — combat, exobiology, exploration, income, mining,
missions, odyssey, powerplay, trade — and any future activity component does
too. A component overrides `overlay_panel()` only when the overlay wants
something the dashboard does not show: cargo's two holds, the survey compass's
bearings. Not merely to have a panel at all.

Where a summary row carries a rate, the rate goes on the overlay with it. A
total is knowable after the session; a rate is only interesting while it is
happening, which is the half worth covering a game for.

### Changed: closed vocabularies get pickers

Zone, mode, hide-mode and anchor were text fields. They have three, three, two
and six valid values respectively, and the dialog has had a combo helper all
along — there was no reason to hand-roll text entry, and a typed setting can be
wrong, which means validating it, reporting it, ignoring it, and leaving the
commander to work out why nothing happened. `_choice_combo()` in the GUI and
`Select` in the TUI. The TUI panel rows were read-only labels; a row telling
you what a setting is, in a window whose purpose is changing settings, is the
worst of both. They are pickers now.

### Changed: the overlay is its own component, with its own preferences tab

It used to live inside `surface_mining`, which was only ever true of the first
thing it drew. It shows cargo, commander and ship identity now, and whatever
else components contribute; owning it from a mining component would have made
every future panel a mining feature. `components/overlay.py` owns the window,
the tick loop and the layout, and nothing else — every panel's data belongs to
the component that produced it, including the survey compass, which is now a
contributed `survey_compass` panel like any other.

Overlay settings moved with it to a dedicated Overlay tab in both front ends.
Leaving a copy behind on the Survey tab would have given two pages writing the
same config keys, and whichever was opened last would appear to win.

Panels ship placed but switched off. An overlay that decides for you what to
cover the game with is not a feature.

New panels: `cargo` (both holds in an SRV), `commander` (name, squadron,
balance, location) and `ship` (name, ident, type, value, hull). Those two are
pure identity with no context gate, so `auto` behaves as `on` for them — that
is correct rather than a missing check, because what a streamer wants on camera
is not conditional on what they are doing.

The repo's existing AST guard caught the leftover `OVERLAY_DEFAULTS` reference
during the move, before it could raise on first open.

### Fixed: one commodity priced off the galactic average while its neighbours priced off the station

Reported as Low Temp. Diamonds showing 96K in a hold where Tritium and
Bromellite were showing the station's actual sell prices. 96,438 is the
galactic average; the station was paying 179,090.

The manifest resolves a price as `station sell price, or the stored galactic
average`. That fallback is right — it is what keeps the panel populated at a
carrier or before a market has loaded — but it is also completely silent, so a
commodity missing from the station table produces a plausible number instead of
an error, and sitting next to two correct rows it reads as a price rather than
a miss.

Two things could put a commodity in that state, and both are fixed.

`core/data.py` built the CAPI market table with `name.lower()` while
`components/cargo.py` built the Market.json table with `canonical_name()`.
Both structures are read with the same keys, so any CAPI name whose lowercased
form differs from its canonical one produced an entry nothing could look up.

The same handler then did `state.cargo_mean_prices = mean_prices`, replacing
the whole fallback map with the current station's subset. Every average learned
anywhere else was discarded on arrival — including, necessarily, the averages
for commodities this station does not trade, which are exactly the ones most
likely to need the fallback. It merges now.

### Added: price provenance under --trace

`--trace` produced nothing useful for the above because nothing in the pricing
path wrote a line. It now records, per held commodity per render, the chosen
price, which of the four inputs produced it, and whether the commodity was
present in the station and target tables at all. That last flag is the one that
distinguishes "this station pays the average" from "this commodity was not
found", which from the outside look identical.

### Added: overlay panels, three zones, and who owns what — experimental

The overlay was built as a surface-mining feature that happened to draw on
screen: blank unless you were in an SRV near a recorded deposit. That is a
special case of what an overlay should be, not an overlay. This is the general
form.

Panels belong to the components that own the data. A component declares the
panel ids it can produce and implements `overlay_panel(id, ctx)`, returning
None when its panel does not apply right now. That None *is* the relevance
test — `core/overlay_panels.py` knows nothing about limpets or bio signals, and
adding a panel touches no overlay code at all. Cargo is the first one: how full
the hold is, and both holds when in an SRV, because the run is limited by the
mothership and a commander who can see only the SRV is the one who drives back
to a full ship.

Three fixed anchors across the top — left, centre, right — each holding an
independent vertical stack. No free placement and no drag: that would mean
persisting per-monitor geometry, surviving resolution changes, and a drag mode
that has to defeat click-through to work, all before anyone has found out which
panels are worth keeping on. Zones are anchors rather than boxes, so a stack is
as tall as its contents and nothing can wander into the middle of the viewport.
There is no overflow rule because a stack too tall to fit is visible the moment
it happens.

When an `auto` panel is not eligible the stack either closes up or holds the
space, and that is a setting rather than a decision. `collapse` is denser but
the panels below move, and something that moves has to be re-found rather than
glanced at. `reserve` keeps every panel where it was put at the cost of gaps,
which is steadier to read and the better default with the overlay on camera.
Reserved height is the height the panel last actually had, carried between
frames — reserving a guess would make the stack jump the first time a panel
appeared, which is the exact thing reserving exists to prevent.

The layout works in anchor points because it has no font metrics; turning "this
x is the right edge" into a draw position happens in the renderer, where there
is a QFontMetrics. Without that every zone would have drawn left-aligned and
the right-hand stack would have run off the screen.

One context is built per frame and handed to every panel. A panel reading live
state directly could answer from a position half a second newer than its
neighbour used, and the overlay would disagree with itself.

An invalid zone or mode in config is reported and skipped rather than coerced
to a default, because a typo that silently relocates a panel is worse than one
that says so.

### Fixed: the Survey tab still did not appear in GUI mode (third attempt)

`ConfigManager.load_setting()` takes `warn_missing`; only the `core_api`
wrapper takes `warn`. The GUI builder called the former with `warn=False`,
which raises TypeError, which the preferences tab loop catches and logs — so
the page silently did not exist. The TUI composer reaches the same settings
through the core wrapper, which is why it kept working and why this looked
like a rendering problem rather than a broken call.

That is three failures of one shape: the component calling something the GUI
side did not offer in the form it was offered, with the exception swallowed by
the loop that builds the tabs. None of them could have been caught by testing
the component alone, because each was a disagreement *between* two files.

`tests/test_preferences_contract.py` now reads the real signatures out of
`gui/preferences.py`, `core/config.py` and `core/core_api.py` with `ast` — no
Qt, no Textual, no display — and binds the component's calls against them.
Every `dlg.` attribute the builder reaches for must exist on
`PreferencesDialog`; every helper call must be one the real helper would
accept; both discovery methods must be callable with no arguments; and
`ConfigManager.load_setting` must not be called from a builder at all. The
first version of that last check passed against the reintroduced bug — it
grepped tokens joined by spaces, so the substring never matched. It is an AST
check now, and it has been verified to fail with the bug present and pass with
it fixed.

### Fixed: the Survey tab was invisible in GUI mode, and its rows in both

Three defects, and the last two were hiding each other.

`gui/preferences.py` calls `gui_preferences_tab()` with **no arguments** to
discover a tab, and only the builder it returns receives the dialog. The
component treated the discovery call as the build call and returned `None` when
handed no dialog, so the tab was never registered. TUI has a different discovery
path and showed the page fine, which is why this presented as a GUI-only
problem. The test written alongside asserted the broken behaviour, because the
test and the code came from the same wrong idea about the contract.

`get_tab_rows()` is only called for components registered through
`core.register_session_provider()`. Defining the method is not enough — an
unregistered component renders nowhere in either front end regardless of what it
returns. The component now inherits `ActivityProviderMixin`, declares a tab
title, and registers in `on_load()`.

Registering it immediately surfaced the third: a dead call to `best_parking()`,
left behind when rig placement was removed. It survived a full pass of the test
suite because the method containing it was never invoked — the one code path
that would have raised was the one the second defect had disabled. Tests now
execute `get_tab_rows()` and the discovery calls rather than asserting they
exist.

The on-screen overlay in this entry is marked **experimental** and ships
switched off. It is verified on X11 only — there is no Windows or macOS machine
here to test against — and it stays in the development branch until it has
survived contact with play. `--overlay-probe` reports what any given machine can
actually do, which is what a bug report from one of them should carry.

### Added: a Survey tab in preferences, and a working hook to put it there

One tab with three sections — store, sharing, overlay — rather than three tabs.
The injection hook gives a component one tab, and these are settings a commander
configures in one sitting.

Getting it there meant fixing the hook, which only half worked. On the TUI side
an injected tab's controls were collected through a hardcoded widget-id map
inside `tui/preferences.py`, so a component could draw a tab whose settings were
silently discarded on save unless somebody had also edited the front end. A
component knows its own widget ids and its own config keys, so it now declares
them with `preferences_bindings()` and the screen asks. On the GUI side builders
were called with no arguments and so had no route to the dialog's `_record()`,
which is why nothing had ever used that hook; they are now handed the dialog,
with the bare call kept for anything written against the old signature. A test
asserts every declared binding names a config key that actually exists, because
a binding pointing at a missing key fails invisibly — the control moves, Apply
succeeds, the value is gone by the next load.

The overlay row reports what the renderer is doing rather than what the config
says. "Enabled" and "working on this machine" are different claims and only the
second is worth printing, so the status line distinguishes off, enabled but
unconfigurable, enabled but not yet started, and the capability summary the
renderer actually returned.

The sheet Test button tests what is in the boxes, not what was loaded when the
window opened. A test that checks the saved credentials tells you nothing about
the ones you have just typed in.

### Fixed: the TUI preferences screen printed to stdout

`_extra_tabs()` announced each component it found and printed a traceback when
one failed. Textual owns the terminal in that mode, so both drew over the
dashboard. They go to the debug log now.

### Added: an overlay of EDLD's own, on the platforms that can carry one — experimental

EDLD draws its own rather than speaking to somebody else's. Hooking into an
existing overlay tool would mean every EDLD user installing that tool first,
which is a poor answer to "why would I run this", and the established one is
GPLv3 against EDLD's MIT.

The renderer is a child process rather than a thread. Qt wants its event loop on
the main thread and EDLD's main thread is already the terminal's, the TUI's or
the dashboard's depending on mode; a child gives all three the same overlay,
keeps a renderer crash from taking the dashboard with it, and leaves the TUI
without a runtime Qt dependency. Frames go over stdin as newline-delimited JSON.
A socket was the obvious choice and is the wrong one — binding a localhost
listener raises a Windows Firewall prompt, collides with whatever else wanted
the port, and survives a parent that died badly. A pipe does none of that and
the child exits when the parent closes it.

Capabilities are measured rather than asserted. The renderer tries to be
translucent, click-through and always-on-top, reports what it actually managed,
and the parent logs it. Click-through is treated as mandatory: an overlay that
swallows mouse input over the cockpit presents as the game having locked up, and
nothing about that points the user at EDLD. Wayland reports unavailable outright
instead of half-working, because an ordinary Wayland client cannot request
always-on-top or place itself absolutely at all, and a window that appears
somewhere arbitrary and then sinks behind the game is worse than none. Exclusive
fullscreen defeats every overlay on every platform and cannot be detected from
outside the game; it is documented rather than worked around.

`--overlay-probe` runs the whole capability path and prints the result without
starting EDLD, so "will this work on my machine" is answerable in one command.

The protocol owns the child's stdout, so the real descriptor is duplicated away
and kept private while `sys.stdout` is pointed at stderr. This is not
hypothetical: EDLD's own import graph prints to stdout when an optional
dependency is missing, which lands between process start and the first protocol
line. The parent tolerates it by skipping anything that is not JSON, but a
stray print added later would have become a protocol bug rather than a stray
print.

What it draws is deliberately almost nothing. In an SRV, within 20 km of a
deposit already recorded on this body: a compass tape with the bearings, the
nearest one named with its range, and how many of the body's mining signals are
still unfound. Everywhere else — docked, in supercruise, in the ship, on a body
with nothing recorded — it is blank. There is no header, no logo and no idle
state, because an overlay that is always on is wallpaper and stops being read. A
mark behind the commander is dropped rather than pinned to the edge of the tape,
since a mark at the edge reads as "over there" when the truth is "behind you".

Bearings are driven from the Status.json position ring on a half-second tick
rather than from journal events, because they have to track a moving SRV and no
journal event fires while driving in a straight line. A position older than
three seconds means the game has stopped writing Status.json, and the overlay
clears rather than leaving bearings that are now fiction.

### Added: recording what a deposit is actually like

Automatic capture gets the position, the commodity, and the fact that a deposit
is there. It cannot get how much is left or how dense the seam is, because
nothing in the journal says — those are the commander's assessment and there was
no way to record one. The store had the columns and nothing wrote to them.

`mark_here()` resolves the deposit by position rather than by selection: the
commander standing on the thing they are describing is both the natural way to
do it and the one that needs no list to pick from. Matching uses the same
proximity rule that records a deposit in the first place, so a judgement cannot
attach itself to a neighbour, and unlike the recording path it ignores the
commodity — you do not have to name what you are standing on.

Blank fields leave stored values alone, so setting the amount does not wipe a
density recorded last week, and re-setting a value to what it already was is not
treated as a change. Any real change clears `published_at`, so the correction
reaches the sheet on the next flush; a fix that stays local while the squadron
keeps reading the old number is worse than no fix.

Marking a deposit Depleted stamps the depletion log, the same as the explicit
path already did.

Two separate test-data switches, because they answer different questions.
"Flag my finds as test data" marks everything recorded from now on, for while
you are setting up. "Publish test rows too" decides whether flagged rows leave
the machine at all. Default is flag nothing, publish nothing flagged.

### Added: the survey can publish to a Google Sheet

Optional, off by default, and separate from the store. What EDLD records stays
in `mining.db` on the machine that recorded it; this is the other half, for
commanders who want a squadron reading their finds.

Writing to Sheets needs OAuth or a service account — an API key authenticates
reads of public data and cannot write at all. Both alternatives cost the user a
Google Cloud project, and neither can ship in an open-source binary, because an
embedded client secret is a published one. So the receiver is an Apps Script
web app bound to the target spreadsheet: `sheets/Code.gs`, with the walkthrough
in `sheets/README.md`. No project, no OAuth, no Google client library, and what
a squadron leader hands out is a URL and a token.

The duplicate check lives in the script rather than in EDLD, because only the
sheet knows what is in the sheet. Several commanders write to a squadron sheet
and none of them can see the others' local stores, so a client-side check would
still have two people who found the same rock on the same evening both
appending it, each correct about what they had seen. The script takes a document
lock and the second one updates the first one's row. EDLD's side of the contract
is the deposit id — the geometry is resolved here, where the body radius is
known, and the script matches a twelve-character string.

An existing row is only overwritten by a report carrying a newer
`last_confirmed`, so a commander replaying an old session cannot walk back a
fresher reading; blank cells are filled in regardless of age.

Nothing is marked published until the script has confirmed it. A transport
error, an HTML error page from an uncaught server-side fault, a rejected token,
or a response that accounts for fewer rows than were sent all leave the deposits
pending for the next flush. The failure this is guarding against is the one
where the HTTP request completes and the rows are marked sent on the strength of
that, which is how a shared sheet quietly stops filling up.

Deposits go out when the commander leaves a body rather than as they are mined.
Sheets permits roughly sixty writes a minute and one real session produced 608
refine events, so a send per event would be rate limited inside the first minute
of a rig run.

The deployment URL carries the deployment id in its path, which is half of what
is needed to write to somebody's spreadsheet, so only the hostname is ever
logged. `Token` is redacted from the debug header by name.

The column order is a positional contract between `Code.gs` and
`core/sheets_publish.py` — a field added to one and not the other lands in the
wrong column rather than raising anything, so a test asserts the two lists match.

### Changed: galactic facts moved out of the commander directory

Some of what EDLD stores is a fact about a commander and some of it is a fact
about the galaxy. A commodity's galactic average is the same number whoever
reads it off a market board, and a surface deposit is in the same place whoever
finds it. Both were being written under `commanders/<fid>/`, so a second
commander started from nothing and the two copies then drifted with nothing to
say which was current. `explo.db` has always sat at the data root for this
reason; the rest now joins it in a shared `data/` directory.

The commodity ledger move is a merge rather than a file move, because each
commander directory may hold its own copy. Per commodity the earliest
`first_seen` wins, the latest `last_updated` wins and carries its `mean_price`
with it, and the observation counts are summed. That last one is the trap: the
obvious merge picks a winning row and takes its counters along, silently
discarding the other commander's count, and the number that comes out still
looks entirely plausible. Every merge logs its row count so the arithmetic can
be checked afterwards. Source files are left where they are.

### Fixed: the data directory was Linux-shaped on every platform

`_user_data_dir()` had one branch, and it was the XDG one. That was true of the
machine EDLD was written on and of nothing else the release pipeline builds for.
Windows and macOS binaries were putting the config, the databases and every
plugin's state in `~/.local/share/EDLD` — a directory neither platform shows the
user, backs up, or expects anything to be in. It now resolves to `%LOCALAPPDATA%`
on Windows and `~/Library/Application Support` on macOS, with the XDG path and
its `~/.config/EDLD` symlink unchanged on Linux.

### Fixed: a Status.json the poller could not read looked like a closed game

The Status poller ended in `except Exception: pass`. Status.json is the live
source for hull, shields, fuel, balance and surface position, and it is also the
freshness signal for whether the game is running at all, so a payload the poller
could never parse presented as a commander who had quit — every one of those
values frozen, and nothing anywhere saying why. The poller now reports the first
occurrence of each distinct fault and counts repeats, which keeps a torn read of
a file the game rewrites twice a second from flooding the log while still making
a persistent fault visible.

---

## Released in 20260914

### Fixed: the hold was only ever as fresh as the journal

Cargo.json is a live file — the game rewrites it whenever the hold changes,
for whichever vessel changed. EDLD read it once at startup and thereafter only
when a journal event said to, so the manifest could only ever be as current as
the journal was.

Journals lag. They are buffered, they rotate, and a directory that is synced,
rotated, or rewritten underneath the running game leaves the file on disk
frozen while the game carries on appending to a handle that no longer has a
name. In a real capture the newest journal stood still for five hours — its
last line a return to the main menu — while Cargo.json tracked 620 t of ore
into the hold. EDLD showed an empty ship the whole time, and reported the
commander as not in game, because nothing had told it to look at either.

Cargo.json is now followed the way Market.json already was: the same watcher
thread, the same two-second mtime check, no re-read and no refresh when
nothing has changed. Applied strictly by vessel, as everywhere else that
touches this file — reading it without checking which hold it describes is
what once put SRV ore in the ship's.

This does not repair the journal itself. A stalled journal still costs the
mode, the location, and everything else only the event stream carries. It does
mean the hold is read from the file the game keeps current, rather than
inferred from a record that may have stopped.

---

### Fixed: the SRV's hold was empty until the next chunk was refined

The startup replay rebuilds the ship's hold from the journals, and `on_load`
applies `Cargo.json` over it when that file describes the Ship.  Neither did
anything for the SRV.

The SRV's hold is never listed in a journal event — those carry a count and
nothing else — so the only record of what is in it is `Cargo.json`, and only
while the commander is aboard.  A mining session is left in the SRV, which
means the very case where it matters: resuming with 11 t of Monazite aboard
and `Cargo.json` saying exactly that, the SRV manifest read empty and stayed
empty until the next refined chunk landed.

Seeded from `Cargo.json` at startup now, applied strictly by vessel — reading
that file without checking which hold it describes is what once put SRV ore in
the ship's.  A test asserts the ship's hold is left alone when the snapshot is
the SRV's, so a second unguarded application cannot creep back in here.

---

### Fixed: the cargo replay was reading four-month-old journals

`_bootstrap_from_journals` took the four most recent journals by modification
time.  Elite's journal names are ISO timestamps and sort chronologically on
their own; mtimes do not, and do not survive a file sync between machines.  In
a real capture the four newest by mtime were from 19 May and the newest by
name was from 13 September, so the replay rebuilt the hold from journals four
months stale and never opened the current one.

This had been latent.  The replay used to apply its result with `if items:`,
so an unhelpful answer from an old journal was falsy and fell through to the
persisted copy, which was usually about right — the wrong-file bug was hidden
behind a second bug that happened to mask it.  Correcting the first, so an
empty hold could stand, let the wrong file speak: no cargo after startup, and
a capacity read from whatever ship was flown in May.

`find_latest_journal()` has always chosen by name.  The cargo replay and the
hull bootstrap in `ship_health.py`, which had the same mtime sort, now agree
with it.

---

### Fixed: a dimmed or highlighted value stopped being monospace

The GUI aligns its value columns by rendering them in a monospace face, which
`QLabel[role="val"]` supplied.  But a value's colour is carried by that same
role: `classes_to_props` turns `"val dim"` into `role="dim"` and
`"val highlight"` into `role="highlight"`, and neither named a font family, so
either one dropped the value back to the proportional face.  Every column the
shared helpers had padded into line then lined up with nothing.

The cargo manifest's new column headings were the visible case — the headings
are dimmed, so Tonnes, Price and Value were set proportionally above monospace
figures and sat over none of them.  The fault was not new and was not confined
to cargo; the headings were simply the first place two rows that had to agree
were coloured differently.

Monospace is now keyed on a property `KVRow` sets on its value label once and
never rewrites, rather than on the role, because the role is exactly what
changes when the colour does.  Prose rows are untouched: they are not value
columns and do not carry the property.

The terminal dashboard was never affected — a terminal has one cell width —
and its headings were checked against the same data to confirm it.

---

## Released in 20260913

### Fixed: sold cargo came back after every restart

The hold cannot be read from any one journal event, so it is rebuilt at
startup by replaying the recent journals: the last event carrying a manifest
is the baseline, and everything that moved cargo afterwards is applied on top.
Sales were skipped, on the stated grounds that a sale emits its own cargo
event which resets the baseline.

It does emit one.  It carries no manifest.  In a real capture, selling 120 t
of Tritium produced `Count: 127` with no Inventory, and selling the remaining
127 t of Low Temperature Diamonds produced `Count: 0` with no Inventory.
Neither reset anything, so both cargoes stayed in the hold across every
restart, and a Thortveitite transfer made three hours later was added on top
of goods that had been sold.  The panel read 326 t of a 1024 t hold with 79 t
aboard, and reported 82M credits of cargo when 38M was there.

The replay now applies `MarketSell`, `MarketBuy` and `EjectCargo` as well, and
a Ship cargo event reading `Count: 0` empties the hold whether or not it names
a manifest — that being the one count-only form whose contents are not in
doubt.  A count-only event with a non-zero count is still left alone: the
journal does not say what the count is made of, and `Cargo.json` on disk
belongs to the present rather than to the replayed moment, which after an SRV
session means it is the SRV's.

Alongside it, a second fault in the same handful of lines: the replayed result
was applied with `if items:`, so an empty hold — falsy — fell through to the
persisted copy.  Even once the sales were replayed correctly, a sold-out hold
would have kept its old contents.  The test is now against `None`.

The regression test replays that capture event for event.

---

### Added: column headings on the cargo manifest

The manifest showed three unlabelled numbers per row and left the reader to
work out that the middle one was per tonne and the last was the line total.
Both front ends now head the ship's hold and the SRV's with Commodity, Tonnes,
Price and Value, built from the same column widths as the rows so the headings
sit over what they name, and placed above the rule so it underlines them.

---

### Fixed: the GUI collapsed the column padding the TUI lines up with

The cargo manifest lines up its three columns — tonnes, price per tonne, line
value — by padding each to a fixed width in `core.ui_helpers`.  Both front
ends call the same helper and receive the same string, which is why this was
invisible from the code: the strings were never wrong.

Every label in the Qt window is `Qt.RichText`, and Qt collapses runs of spaces
exactly as a browser does, so the padding was being squeezed to a single space
between the label and the screen.  `    57K cr` arrived as `57K cr`, the
separators in a manifest lined up with nothing, and the totals row — whose
price column is deliberately blank but full width, so the line still sits
under what it totals — rendered as `| |`.

`to_html` now protects runs of two or more spaces, and a leading single space,
as non-breaking.  Ordinary single spaces between words are left alone so the
prose rows elsewhere in the window still wrap.  This was never specific to
cargo: any column the shared helpers pad was arriving squashed, and all of
them now line up.

The tests round-trip each value through a real `QLabel` and a `QTextDocument`
and assert on where the separators land, because comparing the built strings
against each other proves nothing when both front ends are handed the same
one.

---

## Released in 20260912

### Added: the sell table, as two files and a popup

The catalogue answers what a commodity is worth on average.  It does not
answer the question actually asked on arriving somewhere with a full hold,
which is what this place will pay, and in what order to unload.  Market.json
holds that answer for as long as the commander stands there, sorted by
Frontier's own ordering rather than by anything useful.

Two files now sit beside the catalogue and are rewritten on the same trigger:
`data/cargo.commodities.md` and `data/cargo.commodities.html`.  Each carries a
heading naming the market being quoted and a two-column table of localised
commodity name against price, most valuable first.  The HTML is standalone —
no stylesheet to ship beside it, and it follows the reader's light or dark
preference rather than assuming one.

Which market gets quoted comes from `cargo_price_context()`, the same resolver
the Cargo panel prices the manifest against, so the panel and these files can
never name different markets: a Spansh target when one is set and loaded, the
station underfoot otherwise, and the galactic average when there is neither.
The galactic figures come from the catalogue rather than from
`cargo_mean_prices`, because the catalogue is the only source that carries a
display name alongside the price, and a table of internal symbols would not be
readable.

Carriers are excluded throughout.  A fleet or squadron carrier market is
player-run, mobile, and rewritten without notice, so docking at one leaves the
files and the popups describing whatever was quoting beforehand, exactly as if
the commander had not docked at all.  The catalogue still absorbs a carrier's
commodities — identity is worth having wherever it turns up — but its prices
never reach the sell table.  The carrier test is a substring match rather than
a list of station types: Frontier writes `FleetCarrier`, Spansh writes
`Drake-Class Carrier`, and a squadron carrier will be a third spelling that
nobody has captured yet.  Nothing else in the game has "carrier" in its station
type, so the looser test is both sufficient and does not need revisiting.  The
Market.json reader's existing `FleetCarrier` check widens to the same rule,
which means a squadron carrier no longer prices the manifest either — it never
should have.

Only prices an NPC will actually pay appear.  Stations list carrier-only
commodities and quote a sell price for them regardless, and nobody in the
galaxy will honour it: the three Titan Maw tissue samples list at 476,614,
317,614 and 209,527 cr at an ordinary Coriolis station, which put one of them
second in the table at almost every market in the bubble.  The tell is that
they carry no galactic average, because there is no NPC trade in them to
average — every other tissue sample, Titan Deep included at nearly half a
million, has one and sells perfectly well.

So the exclusion is the absence of a galactic average, not the absence of
demand.  A station with nothing on order still pays, and filtering on demand
would have cut the table from 367 rows to 67 and hidden most of what is worth
carrying.  The commodities concerned are read from the catalogue rather than
from the market in hand, which means the judgement improves as more markets
are seen: a commodity that shows a real average anywhere drops out of the
exclusion everywhere, and an empty catalogue excludes nothing rather than
guessing.  Matching is on the display name, since Frontier's internal symbol
for a Titan Maw sample is `thargoidtissuesampletype10a` and no other source
spells it that way.  The catalogue still records them — it records everything
— it just stops quoting them.

The popup opens on a Mineable tab, with All Items behind it.  Arriving with a
hold full of ore, the question is about ore, and the unfiltered table answers
it badly: at a real captured market the most valuable line is Iridium at
542,736 cr, which cannot be mined, and the first thing that can is four rows
down.  Mineable cuts that market from 364 rows to 53.  Both tabs carry their
count in the tab label, so the size of each is known before it is opened.

What can be mined is stated in `data/mining.py`, because Frontier publishes no
flag for it, and it is nearly all category: everything in Minerals is mined,
plus ten named Metals — the refinery outputs — and four named Chemicals, the
ice-ring yields and carrier tritium.  Those fourteen are exactly what appears
in `MiningRefined` and `ProspectedAsteroid` across a real 210-journal capture;
nothing outside Minerals turned up beyond them.  Leaning on the category is
what keeps the table cheap: a mineral added in a future update is mined the
day it ships without an edit, and only a new mineable metal or chemical would
need one.

Both tables stripe their rows.  Two columns a hundred rows deep are hard to
read across without one, and the price sits at the far edge from the name.
The stripe is a new derived palette entry, `$row-alt`: the block fill pulled
12% toward the text colour, which lightens it on the dark palettes and darkens
it on the light one with no per-theme case, and which custom themes inherit
without stating anything.

That figure is set by the terminal rather than by taste.  The obvious choice
was `$title-bg`, already one step above the block fill and already what the
panel title bars use — but one step is six points per channel, and a
256-colour terminal quantises `#1c1810` and `#241e16` onto the same xterm
entry.  Six of the eight palettes collapsed that way.  The stripe was
therefore perfectly visible in the Qt window, which is always truecolor, and
completely absent in the terminal, which is exactly how it was reported.
Anything under a 10% blend still collides somewhere; 12% clears every palette
with margin and still reads as about a 9% step where truecolor is available.
A test now quantises both colours for every palette and fails if they land on
the same entry.

Neither front end got there for free.  Textual has no `:nth-child`, so the
stripe is a class applied while composing, and the two labels in a row had to
be made transparent or they punched the block fill back through the middle of
it.  Qt supplies an `alternate-background-color` of its own when the
stylesheet states none, and its default is a light grey that is unreadable on
every dark palette here; the tables are now styled from the palette like
everything else, header and gridlines included.  The tests assert on rendered
colour — sampled across each row's full width in the TUI, and from the
rendered viewport in the GUI — because a class that is applied but paints
nothing looks exactly like working code from the source.  Rendering in
truecolor was not enough on its own, though: that is what passed while the
terminal showed nothing.

Mineability is decided once, on the row, rather than by each surface — the
files carry it too even though neither renders it, so a later decision to
split them the same way needs no second opinion about what a mineral is.

`Ctrl+S` opens the same table as a popup in both front ends, and closes it
again; `Esc` closes it too.  The key was free — EDLD saves nothing on demand —
and a second press reaches the popup's own binding rather than the app's,
which is the arrangement `Ctrl+O` already uses for Preferences.  The GUI also
carries it as View → Sell Table.  Both front ends ask the Cargo component for
the table rather than building one, so all four surfaces render the same dict
and a commander comparing the popup against the file sees one answer.

The popup is built when it is opened rather than cached, so it reflects the
market underfoot at that moment even when no Market.json has been written
since the last time it was looked at.  The GUI window is non-modal and reused
between openings, which means it has to be refilled rather than rebuilt — a
window that kept its first table would quote a station left behind hours ago.

Tests render both popups for real and assert where the columns landed, rather
than that the widgets exist.  Existence was what let an off-screen footer
survive review once already.

---

### Added: a running catalogue of every commodity seen

Market.json is a snapshot of one station, overwritten the next time the
commander docks, so the galactic average it carries for each commodity is
visible while standing there and gone afterwards.  The prices were already
being kept — `cargo.json` accumulates a name-to-price map so the manifest can
still be priced after leaving — but only the price, with nothing to say which
commodity it belonged to beyond a lowercase symbol, and no record of when it
moved.

EDLD now keeps `data/cargo.commodities.csv` alongside the other per-commander
files: one row per commodity, carrying its internal symbol, Frontier's numeric
id, both localised names, its category, and the galactic average last recorded
for it, with the first sighting, the last price change, and a count of how many
times the price has moved.  A commodity is written once and its row is rewritten
whenever `MeanPrice` drifts from what is on file, so the catalogue accumulates
across stations and sessions rather than tracking the station underfoot.

It follows Market.json wherever it is written from — the existing file watcher
picks up a market opened from the galaxy map within two seconds, and the
`Market`, `Docked` and `Location` events update it immediately when they fire
first.  All of them are guarded on the file's modification time, so one market
write is one pass no matter how many of them notice it.

Fleet Carrier markets are included, which is the one place this parts company
with the manifest pricing: `_read_market_json` discards them because their
`MeanPrice` of 0 is useless for pricing cargo, but a carrier still names real
commodities worth cataloguing.  A zero is treated as the absence of a galactic
average rather than a new one — it never overwrites a price already on file and
never counts as drift — so a carrier visit cannot flatten the catalogue.  The
same rule covers the Thargoid tissue samples, which report zero at ordinary
station markets too: they are recorded, and their rows fill in if Frontier ever
gives them an average.

The catalogue is a side record, so it is built not to take anything with it if
it fails.  A ledger that cannot be created leaves the Cargo component loading
normally, an unreadable file is rebuilt from the next market, and a failed write
leaves the previous file intact — but none of those pass quietly, which is the
failure mode this codebase keeps paying for.  Each one is reported to the debug
log.

`_canonicalise_key` in the Cargo component now delegates to the catalogue's
canonicaliser rather than keeping a second copy of the same regex, so the two
cannot disagree about whether `$gold_name;` and `gold` are the same commodity —
a disagreement there would be two rows for one commodity and no drift ever
detected on either.

---

## Released in 20260911

### Fixed: a bounce to the main menu ended the session

Sessions split on the gap between the end of the last one and the next
`LoadGame`, and the end is recovered from the previous journal — a `Shutdown`,
an exit to the main menu, or, when the client crashed and wrote neither, the
last event in the file.  The scan kept the last main-menu marker it saw
regardless of what followed it, so a commander who dropped to the menu and
picked a mode again seconds later left one sitting mid-file, and everything
played after it counted as idle.

One real capture bounced at 20:22:43, was back in-game at 20:22:48, and played
another eighteen hours before the client died without a clean exit.  The
session was dated as ending at the bounce, so sitting back down two minutes
later looked like an 18.7-hour gap and split the session.

A marker only ends a session when no `LoadGame` follows it.  Checked against
all 194 journal pairs in a real capture: every boundary decision now matches
the actual idle gap, where seven previously split a session that had never
stopped.

### Fixed: the Cargo panel never said which market it was pricing from

The TUI queried `#cargo-price-src` and updated it inside a bare `except`,
`theme.py` carried layout rules for the row, and the row was never composed —
so the query raised on every repaint and the label simply never appeared.  The
GUI built its own copy and worked, with a comment claiming it sat "the same
place the TUI puts it".  The row is now composed, and both front ends read one
label built by `cargo_price_context()` beside the prices it describes, so the
header and the manifest cannot name different markets.

### Fixed: footer controls after the first were laid out off-screen

`.footer-lbl` carried no width rule, and a Textual `Static` defaults to filling
its `Horizontal`, so the first control in a footer took the whole strip and
everything after it was placed past the right edge — present in the DOM,
reachable by a synthetic click, and never drawn.  The navigation footer escaped
only because it set `width: auto` on each of its three controls by id.

The Cargo footer had one control and so never showed the fault, until a second
was added beside it: `cargo-target-btn` computed to the full 80 columns,
putting "Gal. Avg" at x=81 and the target-name label at x=161.  That label had
been invisible all along for the same reason — "No target set" has never once
been drawn.

`.footer-lbl` now sizes to its content, which is what all three footers wanted,
and the per-id navigation rules fold into it.  The Cargo footer gets the same
slack-taking label rule the navigation footer already had.

Tests for this render the block against the real stylesheet and assert where
things actually landed, rather than that a widget exists.  Existence in the DOM
was what made the bug survive review.

### Added: a control to pin the manifest to galactic average

Prices follow the target station when one is set and the docked station
otherwise, and there was no way back to galactic average short of undocking.
Clearing the target was not enough on its own — it falls back to whatever
station is underfoot, which is not what galactic average means — so this is an
explicit third mode rather than a target reset.

"Gal. Avg" sits beside "Set Target" in the Cargo footer in both front ends.  It
drops the target and pins pricing to the average until a new target is chosen;
`set_target()` releases the pin itself, so it is released for every caller
rather than each panel remembering to.


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

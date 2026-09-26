# Publishing the surface survey to a Google Sheet

EDLD records surface mining deposits locally, in
`<data>/mining.db`. That store is yours and stays on your machine. This
directory is for the optional other half: pushing those deposits to a Google
Sheet so a squadron, a wing, or a Discord full of strangers can read them.

Everything here is off until you turn it on.

| File | What it is |
|---|---|
| `Loader.gs` | **The one file you paste into the sheet.** Installs and upgrades everything else from the sheet's own menu. |
| `Mining_Dashboard.xlsx` | Optional starting spreadsheet: a themed, filterable, sortable dashboard over `Deposits`. |
| `Code.gs` | Source: the receiver, which accepts deposits from EDLD and writes the `Deposits` tab. |
| `Dashboard.gs` | Source: the dashboard's theme, click-to-sort and formula repair. |
| `Template.gs` | Source: builds the Dashboard, Settings, Queries and Themes tabs a sheet does not have. |
| `Upgrade.gs` | Source: the sheet's upgrade steps, run by Upgrade after new code is installed. |
| `edld_sheet.js` | Generated: the three sources bundled, which is what the loader installs. Never edit. |
| `release.json` | Generated: the version, the bundle's file name and SHA-256, and what it needs. |
| `build_bundle.py` | Regenerates the bundle and the manifest; `--check` says whether they are stale. Standard library only. |
| `build_dashboard.py` | Regenerates the template, and the bundle and manifest with it. |

## What you are setting up

A small script that lives inside your spreadsheet and accepts writes over HTTP.
EDLD posts batches of deposits to it; it decides what is new, what has changed,
and what to ignore.

No Google Cloud project. No OAuth. No API key — API keys authenticate reads of
public data and cannot write to a sheet at all, which is why this is not built
that way.

You end up with two strings: a URL and a token. Those are what you hand to
anyone you want writing to the sheet, and the token is what you change when you
want them to stop.

## Setting it up

**1. Make or open the spreadsheet.** Any Google Sheet — a new, blank one is
the usual start. Installing builds everything: the Dashboard, Settings and
Deposits tabs, and the hidden Queries and Themes tabs behind them, and removes
Google's empty `Sheet1`. An existing sheet keeps its tabs and gains only the
ones it is missing. See [The dashboard](#the-dashboard) below.

Importing `Mining_Dashboard.xlsx` (Drive → New → File upload, then File → Save
as Google Sheets) gives the same starting point, if you would rather begin from
a file; you still paste the loader into it afterwards.

**2. Paste the loader.** Extensions → Apps Script. Replace everything in
`Code.gs` with the contents of `Loader.gs` from this directory (the file's name
in the editor does not matter), and save. It is the only file the project
needs, and the only one you will ever paste: everything else is installed and
upgraded from the sheet's menu. Why it works that way is in [Upgrading a
sheet](#upgrading-a-sheet).

**3. Install.** Reload the spreadsheet. An **ED Dashboard** menu appears; run
**Install / Upgrade…**. Google asks you to authorise the script the first time
— it needs to fetch the release from GitHub and to change this spreadsheet.
It will also warn that the app is unverified: that is the normal notice for a
script you added yourself and have not submitted to Google for review.
Advanced → Go to *(project name)*.

Upgrade shows the version it found and asks before installing anything. It
then asks for a **token**: leave the box blank and it generates one and shows
it to you. The token is the only thing standing between your sheet and anyone
who learns the URL, and it is kept in the script's properties rather than in
any file, so upgrades never touch it. **ED Dashboard → Set sheet token…**
changes it later. Until one is set, the script refuses every write, so a
half-finished setup fails closed rather than open.

**4. Deploy.** Deploy → New deployment → gear icon → Web app.

| Field | Value |
|---|---|
| Description | anything |
| Execute as | **Me** |
| Who has access | **Anyone with the link** |

"Anyone with the link" sounds worse than it is. It means the *endpoint* is
reachable without a Google account, which it has to be for EDLD to post to it.
Every request still has to carry the token, and the sheet itself is not shared
by this — its own sharing settings are unchanged and still decide who can read
it.

Google will ask you to authorise the script the first time. It will also warn
that the app is unverified: that is the normal notice for a script you wrote
yourself and have not submitted to Google for review. Advanced → Go to
*(project name)*.

**5. Copy the web app URL.** It looks like
`https://script.google.com/macros/s/AKfy.../exec`. Keep the `/exec` on the end.

**6. Point EDLD at it.** In `config.toml`:

```toml
[SurfaceSurvey]
Enabled      = true
WebAppURL    = "https://script.google.com/macros/s/AKfy.../exec"
Token        = "the token you generated"
ReporterName = "CMDR YOUR NAME"   # blank to publish anonymously
IncludeTest  = false
BatchSize    = 200
```

`ReporterName` fills the `reported_by` column. Leave it empty and the column
stays blank — the deposits still publish.

**7. Test it.** The Test button in Options round-trips a ping and tells you what
came back. If it fails it says why: a bad token, an unreachable host and an
unconfigured script are three different messages.

## Sharing it with other people

Give them the URL and the token. That is the whole of it — they paste both into
their own `config.toml` and their finds start landing in your sheet.

Who can *read* the sheet is a separate question, settled the way it always was:
the sheet's own Share button. EDLD does not touch it.

To revoke someone, run **ED Dashboard → Set sheet token…** and give the new
token to everyone but the person you are removing. It takes effect on the next
request — no redeploy — and everyone keeps the same URL.

## Duplicates

The script matches on `deposit_id`, the first column. EDLD works out which
sightings are the same deposit before sending — same system, same body, same
commodity, within 75 metres — and gives each one a stable twelve-character id
that never changes once assigned. The script compares those strings.

This is why the check is on the sheet's side rather than in EDLD. Several
commanders write to one sheet and none of them can see the others' local
stores, so a client-side check would still let two people who found the same
rock on the same evening both append it, each of them right about what they had
seen. The script holds a document lock while it writes, so the second one
updates the first one's row instead.

What a later report may change depends on what the field is:

- **Observations** — rigs, refine count, the body's facts, `last_confirmed` —
  are replaced only by a report with a newer `last_confirmed`, so somebody
  replaying an old session cannot walk back a fresher reading.
- **Assessments** — amount and both densities — are what the HUD says the site
  holds when full. A later report only fills them where they are blank. They
  change when a commander corrects one, which stamps `assessment_updated`, and
  a newer stamp is the only thing that replaces them. Otherwise anyone who
  merely drove onto a site would re-send whatever they imported weeks ago and
  undo the correction.
- **Depletion** is a date and nothing else — never an amount. The latest date
  wins, since sites refill and are worked out again. It is written as text, so
  Sheets does not parse it into a date in its own timezone and hand back a
  different day. A sheet from before this that has `Depleted` in the amount
  column has it cleared the next time the row is written, and never serves it.
- **Notes** are a commander's writing, stamped `notes_updated`. The newest note
  wins outright, a blank one included, since emptying the box is how a note is
  withdrawn; an older copy coming back round is ignored.

Blank cells are always filled in. Any text Sheets would run as a formula —
starting with `=`, `+`, `-` or `@` — is stored as text, so a note cannot
execute in anyone's copy of the sheet.

## Upgrading a sheet

After upgrading EDLD, open the sheet and run **ED Dashboard → Upgrade…**. It
reads the release on the branch the sheet follows — `main` unless you have
picked another — tells you what it will change, and on your say-so:

1. fetches the sheet code from beside that release's manifest and checks its
   SHA-256 against the manifest — a mismatch installs nothing;
2. copies `Deposits` to a hidden tab named `Deposits backup <date>`;
3. installs the code and runs the sheet's upgrade steps — new columns, the
   dashboard's formulas and layout, tidying data an older version wrote —
   recording each as it completes, so an interrupted upgrade resumes where it
   stopped;
4. re-applies the theme.

Deposits are only ever added to, your Settings values are left as they are,
and the URL and token do not change. A dashboard tab the sheet does not have is
built; one it has is never rewritten. The release line in Settings!D1 follows
each upgrade unless you have replaced it with your own text. EDLD's own writes wait while it runs.
Running it again on an up-to-date sheet says so and changes nothing. "Up to
date" is decided by the code's hash, not its version, so a branch whose version
file has not moved still installs each new build. **ED Dashboard → About**
shows what is installed, its hash, and where updates come from.

### Trying sheet code before it is released

Nothing about a sheet's updates involves tags or GitHub Releases: a sheet reads
`sheets/release.json` from a branch and the bundle from beside it. To try what
is on `dev` before it is merged or tagged:

1. Push `dev`, with `sheets/edld_sheet.js` and `sheets/release.json` rebuilt
   (`python3 sheets/build_bundle.py`; the release workflow and
   `scripts/build_local.sh` both refuse a stale pair).
2. In a **copy** of your sheet, run **ED Dashboard → Update from branch…** and
   enter `dev`.
3. Run **ED Dashboard → Upgrade…**.

Each later push to `dev` is another Upgrade away. Enter a blank branch to go
back to `main`; Upgrade then offers `main`'s code, and says so when the sheet's
layout is newer than that code expects — nothing in the sheet is undone, and the
older code leaves the newer columns alone. Any branch name works, including ones
with a slash, such as `exp/server-mode`.

GitHub serves raw files from a cache for a few minutes after a push, so the
manifest and the bundle can briefly disagree. Upgrade then refuses the download
and says to wait five minutes; nothing is changed.

A branch with no `sheets/release.json` — `main`, until the loader is merged —
is reported as having no sheet release rather than as an error.

**Test connection** in EDLD's Options names the release the sheet runs, and
fails with "run ED Dashboard > Upgrade" when the sheet is too old to store
everything this EDLD sends. An out-of-date sheet still accepts writes; it drops
the fields it has no column for, which is why the test says so rather than
reporting success.

### A sheet set up before the Upgrade menu

Sheets set up by pasting `Code.gs` (and `Dashboard.gs`) have no Upgrade menu,
so they need this once:

1. Open Extensions → Apps Script and **copy your token** — the text between the
   quotes in `var TOKEN = '…'` near the top of `Code.gs`. The loader asks for
   it; giving it the same one means nobody's EDLD needs changing.
2. Delete every file in the project, then paste `Loader.gs` as its only file
   and save.
3. Reload the spreadsheet and run **ED Dashboard → Install / Upgrade…**. Paste
   the token when asked.
4. Deploy → Manage deployments → pencil → Version: **New version** → Deploy.
   The web app keeps its URL. This is the last redeploy the sheet needs: from
   now on the deployment runs the loader, and the loader runs whatever Upgrade
   last installed.

Until step 4 the web app still runs the old script, so writes keep working
throughout.

### Why a loader

An Apps Script project can rewrite its own files only through the Apps Script
API, and that API is off in the hidden Cloud project every sheet script gets.
Turning it on means a Cloud console visit for every sheet owner, which is
exactly what this setup promises you never need. So `Loader.gs` never changes:
it keeps the entry points Google calls — the web app, the menu, the edit
triggers — and runs the real code, which Upgrade stores in the script's
properties and the loader re-checks against its SHA-256 every time it loads it.

The check guards against a damaged download or stored copy. It does not make
the code more trustworthy than this repository, which is the same trust as
pasting it by hand: code comes only from `raw.githubusercontent.com`, only from
beside the manifest that names it — a manifest can name a file, not an address
— and never without you confirming the version. A release that needs a newer
loader says so and stops; that is the one case where a sheet needs another
paste.

A fork changes one line of `Loader.gs`, `EDLD_REPO_RAW`. To point one sheet at
a manifest somewhere else on `raw.githubusercontent.com` without editing the
loader, set the script property `EDLD_RELEASE_URL` (Project Settings → Script
properties) to its full address; it takes precedence over the branch.

## Things worth knowing

**Deposits publish when you leave a body,** not as you mine. Sheets allows
around sixty writes a minute; a single real mining session generated 608 refine
events. Batching at the body boundary keeps one rig run from becoming a rate
limit.

**Nothing is marked published until the script says so.** A network failure, an
error page, a bad token or a partial write all leave the rows pending, and the
next flush retries them. The failure mode this avoids is the one where EDLD
reports success because the HTTP request completed.

**`IncludeTest` is off by default.** Deposits flagged as test data stay local.
Useful while you are setting this up and would rather not seed a squadron sheet
with whatever you were poking at.

**The URL is half a credential.** EDLD only ever logs its hostname, and `Token`
is redacted from the debug header by name. If you paste a log somewhere, check
it anyway.

## The dashboard

The dashboard is a read side for people who open the sheet rather than run
EDLD. Installing builds it (`Template.gs`), and `Mining_Dashboard.xlsx` is the
same thing as a file; both come from the constants in `build_dashboard.py`, and
`tests/test_sheets_template.py` checks the two say the same thing cell for
cell. Either way it is a template, not a copy of anybody's data: `Deposits`
holds only its header row, and Settings holds placeholders.

**Settings.** Put your squadron's name in B1 and the maintaining commander in
B2; the dashboard title and subtitle come from those. Leave B1 blank and the
title falls back to "CMDR *name*'s Mining Data". D1 carries the template version.

**Filtering.** Pick a System, a Commodity, or both in A5:B5. The table appears
at row 7 once either is set, and is empty until then. Both lists are built from
whatever is in `Deposits`, so they fill themselves as commanders publish.
Deposits flagged `is_test` are left out, as they are from EDLD's own reads.

**Sorting.** Sort By and Order (E5:F5) sort the table; the header of the sorted
column carries ▲ or ▼. With EDLD installed in the sheet, clicking a header does the
same: once to sort by it, again to reverse. Amount and Density sort by rank —
Low, Medium, High, the levels EDLD records — rather than alphabetically. The sort is shared, since it
lives in two cells: whoever clicks last decides it for everyone viewing.

Sorting is done inside the table's formula, not with Data → Sort range. The
table is one `FILTER` expression, and Sheets cannot reorder a formula's output
in place; a manual sort over it either fails or is undone on the next
recalculation.

**Readability.** Rows alternate between the theme's Panel and Panel Alt colours.
High amounts and densities are highlighted, Low ones dimmed, and a deposit with
a depletion date is struck through. Notes sit in the last column, wrapped, and
the rest of the row aligns with their first line.

**Theme.** Settings B5 picks one of five presets — Classic HUD, Federation,
Empire, Alliance, Thargoid — or Custom, which uses the hex codes in B10:B21.
B6:B7 pick the title and body fonts. The template arrives in Classic HUD;
changing any of this needs EDLD installed in the sheet, because Sheets cannot colour a cell
from a formula and something has to apply the codes. It re-applies on every
edit to Settings, or from the **ED Dashboard** menu. More presets go on the
hidden `Themes` tab: add a column before Custom and it joins the list.

Applying the theme replaces every conditional formatting rule on the Dashboard
tab. Rules of your own belong in `styleDashboard_` in `Dashboard.gs`.

**If the table shows nothing at all** — no header when a filter is set — a
formula has been lost. ED Dashboard → Repair dashboard formulas rewrites them,
and rebuilds any dashboard tab that has been deleted. The template stores its Sheets-only formulas in the wrapper
Google uses for its own xlsx export, which Sheets unwraps on import; the repair
is there for the case where it does not.

### Changing the template

Edit `build_dashboard.py` and run it from the repository root:

```sh
python3 sheets/build_dashboard.py                    # writes sheets/Mining_Dashboard.xlsx
python3 sheets/build_dashboard.py --version 20261001
```

`--version` defaults to the `version` file, so rebuild after bumping it for a
release and the template's Settings!D1 matches it. It needs `openpyxl`,
which is in `requirements-dev.txt`. The dashboard's Sheets-only formulas are defined once, in
`FORMULAS` in `Dashboard.gs`; the build reads them from there and checks that
each one survives the export wrapper intact. Change a formula in `Dashboard.gs`
and rebuild, and the template and the repair command stay in agreement. The
Classic HUD palette appears in both files (`THEMES` and `ED.FALLBACK`).

`tests/test_sheets_dashboard.py` holds the pieces together: the committed
template must match a fresh build, the FILTER's column letters must name the
right fields in `Code.gs` `COLUMNS`, the sort rank must match the levels in
`core/mining_db.py`, and the two copies of Classic HUD must agree. Changing
`COLUMNS` — appending, as it always should be — leaves the letters valid; the
test is there for the day something is inserted instead.

### The bundle and releases

`build_bundle.py` — run on its own, or by `build_dashboard.py` — writes
`edld_sheet.js`, which is `Code.gs`, `Dashboard.gs` and `Upgrade.gs` joined into
the body the loader runs, and `release.json`, which names the bundle by file
name with its SHA-256, the sheet layout version it brings a sheet to, and the
oldest loader it runs under. Both are committed, because sheets install them
straight from the branch.

**For sheets, merging to `main` is the release.** Sheets follow `main` by
default and read whatever `release.json` is there; tags and GitHub Releases
play no part. So **rebuild after bumping `version`**, before committing. Four
things refuse a stale pair: `build_bundle.py --check`, the release workflow's
verify job, `scripts/build_local.sh`, and the tests.

A change that needs the sheet itself changed — a column, a tab, a layout —
is a new entry at the end of `SHEET_MIGRATIONS` in `Upgrade.gs`, with the next
`to:` number. The rules for a step are at the top of that file; the short
version is that it must be safe to run twice and may only add to `Deposits`.
`tests/test_sheets_loader.py` runs the loader, the bundle and an old sheet
through a full upgrade under Node, with `tests/gas_fake.js` standing in for
Google's services.

Raise `LOADER_VERSION` in `Loader.gs` only when the loader itself must change,
and `MIN_LOADER` in `Upgrade.gs` only when a bundle cannot run under an older
one: every raise is another paste for every sheet owner.

Do not round-trip the template through Excel or LibreOffice. Neither can
evaluate the dashboard's formulas, and saving from either replaces them with
errors.

## The columns

Positional, and shared between `Code.gs` and `core/sheets_publish.py`. If you
add one, add it to the end of `COLUMNS` in both. Reordering breaks every
existing row.

`deposit_id` · `system` · `system_address` · `body` · `body_id` ·
`planet_class` · `gravity` · `body_radius_m` · `atmosphere` · `volcanism` ·
`signal_no` · `commodity` · `latitude` · `longitude` · `density_claimed` ·
`density_observed` · `amount` · `rigs` · `refine_count` · `first_seen` ·
`last_confirmed` · `reported_by` · `is_test` · `depleted_on` · `notes` ·
`notes_updated` · `assessment_updated`

`density_claimed` is what the body's own signals advertised. `density_observed`
is what was actually found. They are separate columns because a site can be
rich and empty at the same time.

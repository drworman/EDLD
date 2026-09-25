# Publishing the surface survey to a Google Sheet

EDLD records surface mining deposits locally, in
`<data>/mining.db`. That store is yours and stays on your machine. This
directory is for the optional other half: pushing those deposits to a Google
Sheet so a squadron, a wing, or a Discord full of strangers can read them.

Everything here is off until you turn it on.

| File | What it is |
|---|---|
| `Code.gs` | The receiver. Accepts deposits from EDLD and writes the `Deposits` tab. |
| `Mining_Dashboard.xlsx` | Optional starting spreadsheet: a themed, filterable, sortable dashboard over `Deposits`. |
| `Dashboard.gs` | Optional companion to the template: applies the theme, adds click-to-sort, repairs formulas. |
| `build_dashboard.py` | Regenerates `Mining_Dashboard.xlsx`. Only needed if you change the template. |

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

**1. Make or open the spreadsheet.** Any Google Sheet. The script creates a tab
called `Deposits` and writes its own header row, so an empty sheet is fine.

If you want the dashboard, start from the template instead: in Google Drive,
New → File upload → `Mining_Dashboard.xlsx`, then open it and File → Save as
Google Sheets. It arrives with an empty `Deposits` tab already carrying the
header row, so the receiver writes straight into it. See [The
dashboard](#the-dashboard) below.

**2. Open the script editor.** Extensions → Apps Script. Delete whatever is in
`Code.gs` and paste in the contents of `Code.gs` from this directory.

Using the template? Also add `Dashboard.gs`: the **+** beside Files → Script,
name it `Dashboard`, paste. It sits beside `Code.gs` rather than replacing it;
the two share a project and nothing else.

**3. Set a token.** Near the top:

```js
var TOKEN = 'CHANGE-ME-BEFORE-DEPLOYING';
```

Replace it with something long and random. This is the only thing standing
between your sheet and anyone who learns the URL. A password manager's generate
button is fine; so is:

```sh
head -c 32 /dev/urandom | base64
```

The script refuses to accept anything at all while the token is still the
placeholder, so a half-finished setup fails closed rather than open.

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

To revoke someone, change `TOKEN` in the script and redeploy (Deploy → Manage
deployments → pencil → New version). Everyone keeps the same URL and everyone
gets the new token except the person you are removing.

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

### Updating an existing sheet

A sheet set up before notes needs the current `Code.gs`: paste it over the old
one and publish a new version (Deploy → Manage deployments → pencil → New
version). The URL and token stay the same. Its header row gains the new columns
on the next write. Until then it accepts writes and drops the fields it has no
column for — the **Test connection** button in Options says so rather than
reporting success.

A sheet started from the dashboard template also wants the current
`Dashboard.gs`; paste it in and run **ED Dashboard → Repair dashboard
formulas**, which adds the Notes column, re-lays the table and clears any old
`Depleted` amounts. Nothing needs re-importing.

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

`Mining_Dashboard.xlsx` is a read side for people who open the sheet rather than
run EDLD. It is a template, not a copy of anybody's data: the `Deposits` tab
holds only its header row, and Settings holds placeholders.

**Settings.** Put your squadron's name in B1 and the maintaining commander in
B2; the dashboard title and subtitle come from those. Leave B1 blank and the
title falls back to "CMDR *name*'s Mining Data". D1 carries the template version.

**Filtering.** Pick a System, a Commodity, or both in A5:B5. The table appears
at row 7 once either is set, and is empty until then. Both lists are built from
whatever is in `Deposits`, so they fill themselves as commanders publish.
Deposits flagged `is_test` are left out, as they are from EDLD's own reads.

**Sorting.** Sort By and Order (E5:F5) sort the table; the header of the sorted
column carries ▲ or ▼. With `Dashboard.gs` installed, clicking a header does the
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
changing any of this needs `Dashboard.gs`, because Sheets cannot colour a cell
from a formula and something has to apply the codes. It re-applies on every
edit to Settings, or from the **ED Dashboard** menu. More presets go on the
hidden `Themes` tab: add a column before Custom and it joins the list.

`Dashboard.gs` replaces every conditional formatting rule on the Dashboard tab
each time it applies the theme. Rules of your own belong in `styleDashboard_`.

**If the table shows nothing at all** after importing — no header when a filter
is set — the import dropped a formula. ED Dashboard → Repair dashboard formulas
rewrites them. The template stores its Sheets-only formulas in the wrapper
Google uses for its own xlsx export, which Sheets unwraps on import; the repair
is there for the case where it does not.

### Changing the template

Edit `build_dashboard.py` and run it from the repository root:

```sh
python3 sheets/build_dashboard.py                    # writes sheets/Mining_Dashboard.xlsx
python3 sheets/build_dashboard.py --version 20261001
```

`--version` defaults to the `version` file, so rebuild after bumping it for a
release and the template's Settings!D1 matches the tag. It needs `openpyxl`,
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

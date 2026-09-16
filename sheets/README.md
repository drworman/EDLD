# Publishing the surface survey to a Google Sheet

EDLD records surface mining deposits locally, in
`<data>/mining.db`. That store is yours and stays on your machine. This
directory is for the optional other half: pushing those deposits to a Google
Sheet so a squadron, a wing, or a Discord full of strangers can read them.

Everything here is off until you turn it on.

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

**2. Open the script editor.** Extensions → Apps Script. Delete whatever is in
`Code.gs` and paste in the contents of `Code.gs` from this directory.

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

An existing row is only overwritten by a report with a newer `last_confirmed`,
so somebody replaying an old session cannot walk back a fresher reading. Blank
cells are always filled in.

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

## The columns

Positional, and shared between `Code.gs` and `core/sheets_publish.py`. If you
add one, add it to the end of `COLUMNS` in both. Reordering breaks every
existing row.

`deposit_id` · `system` · `system_address` · `body` · `body_id` ·
`planet_class` · `gravity` · `body_radius_m` · `atmosphere` · `volcanism` ·
`signal_no` · `commodity` · `latitude` · `longitude` · `density_claimed` ·
`density_observed` · `amount` · `rigs` · `refine_count` · `first_seen` ·
`last_confirmed` · `reported_by` · `is_test`

`density_claimed` is what the body's own signals advertised. `density_observed`
is what was actually found. They are separate columns because a site can be
rich and empty at the same time.

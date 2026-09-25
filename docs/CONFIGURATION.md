# EDLD Configuration Reference

> ✅ = **Hot-reloadable** — takes effect within ~1 second of saving `config.toml`
> ❌ = **Restart required** — when changed via the Preferences dialog, EDLD restarts automatically

---

## `[Settings]`

| Key | Default | Hot | Description |
|-----|---------|:---:|-------------|
| `JournalFolder` | *(required)* | ❌ | Path to your Elite Dangerous journal directory |
| `UseUTC` | `false` | ✅ | Use UTC timestamps instead of local time |
| `WarnKillRate` | `20` | ✅ | Alert when average kills/hour drops below this value |
| `WarnNoKills` | `60` | ✅ | Alert after this many minutes without a kill |
| `BountyValue` | `false` | ✅ | Show credit value on each kill line |
| `BountyFaction` | `false` | ✅ | Show victim faction on each kill line |
| `PirateNames` | `false` | ✅ | Show pirate pilot names in kill and scan messages |
| `ExtendedStats` | `false` | ✅ | Show running kill counts and per-faction tallies |
| `MinScanLevel` | `1` | ✅ | Minimum scan stage required to log an outbound scan (0 = all) |
| `PrimaryInstance` | `true` | ❌ | Set to `false` on secondary/remote instances to suppress uploads to EDDN, EDSM, and EDAstro — monitoring, alerts, and the dashboard remain fully active |
| `FullStackSize` | `20` | ✅ | Mission stack size that triggers the "stack full" announcement |
| `WarnCooldown` | `15` | ✅ | Minutes between repeated inactivity / kill-rate alerts |
| `TruncateNames` | `30` | ✅ | Maximum character length for pilot/faction names in output |

---

## `[Discord]`

| Key | Default | Hot | Description |
|-----|---------|:---:|-------------|
| `WebhookURL` | `''` | ❌ | Discord webhook URL |
| `UserID` | `0` | ❌ | Your Discord user ID for `@mention` pings on level-3 events |
| `Identity` | `true` | ❌ | Use EDLD's name and avatar on the webhook |
| `Timestamp` | `false` | ❌ | Append a timestamp to each Discord message |
| `ForumChannel` | `false` | ❌ | Enable forum channel thread support |
| `ThreadCmdrNames` | `false` | ❌ | Use commander name as forum thread title |
| `PrependCmdrName` | `false` | ✅ | Prefix every Discord message with your commander name |

---

## `[UI]`

| Key | Default | Hot | Description |
|-----|---------|:---:|-------------|
| `Mode` | `"textual"` | ❌ | Interface: `textual` (terminal dashboard, default), `gui` (desktop window), or `terminal` (plain scrolling output) |
| `Theme` | `"default"` | ❌ | Theme name — changing this in Preferences triggers an automatic restart |

All three interfaces render the same windows from the same components and share
one config, one set of per-commander data, and one window layout, so you can
switch between them freely. `gui` requires PySide6; see
[INSTALL.md](../INSTALL.md).

### Window layout

Which window sits where is not part of `config.toml`. It lives in
`windows.json` in the commander's data directory, and the usual way to change
it is Preferences > Display, which writes the file for you. `example.layout.json`
in the repository root shows the format and the shipped default.

Slots are addressed `<column><position>` — `A`/`B`/`C` left to right, numbered
top to bottom. Each window has a size class and may only occupy a slot of the
same class:

| Class | Slots | Windows |
|-------|-------|---------|
| Large | `A1`, `A2`, `C1`, `C2` | Exploration / Exobiology, Navigation, Ship, Session / Career |
| Centre | `B1`, `B2`, `B3` | Commander, Crew / Alerts, Objectives |

There are seven windows and seven slots, so every window is on screen at
once; rearranging swaps two windows rather than hiding one.

Left and right columns mirror each other — two large windows apiece — and the
centre column is three equal windows. Any window may occupy any slot of its
own class.

Anything invalid — an unknown window, a class mismatch, the same window twice —
is dropped on load and the slot falls back to its default, so a hand-edited
file cannot leave the dashboard unable to draw.

Several windows no longer exist in their own right, having been folded into the
window they belonged with:

| Was | Now |
|-----|-----|
| Assets | Wallet / Ships / Modules / Carrier / S. Carrier tabs on **Commander** |
| Exobiology | nested under each body in **Exploration** |
| Massacre Mission Stack | the Missions tab in **Objectives** |
| Colonisation | the Colonisation tab in **Objectives** |
| Cargo | the Cargo tab in **Ship** |
| Engineering | the Engineering tab in **Ship** |
| Ship Health | renamed **Ship**; hull, shields and fuel moved to Commander's Info tab |
| Alerts, Crew / SLF | merged into **Crew / Alerts** |
| Session | the Session tab in **Session / Career** |

A `windows.json` written before version 2 describes a window set that no longer
exists, and the slot grid changed shape with it. Rather than leave a
half-populated grid, such a file is replaced with the current defaults and
rewritten once, on the next launch.

---

## `[LogLevels]`

All entries are hot-reloadable. Controls terminal, Discord, and dashboard output independently per event type.

| Level | Behaviour |
|-------|-----------|
| `0` | Disabled entirely |
| `1` | Local only (no Discord) |
| `2` | Local + Discord |
| `3` | Local + Discord + `@mention` ping |

| Key | Default | Event |
|-----|---------|-------|
| `RewardEvent` | `2` | Each kill — bounty or combat bond |
| `FighterDamage` | `2` | Fighter hull damage (every ~20%) |
| `FighterLost` | `3` | Fighter destroyed |
| `ShieldEvent` | `3` | Ship shield dropped or raised |
| `HullEvent` | `3` | Ship hull damaged |
| `Died` | `3` | Ship destroyed |
| `CargoLost` | `3` | Cargo stolen |
| `LowCargoValue` | `2` | Pirate declined to attack (insufficient cargo) |
| `PoliceScan` | `0` | Security vessel scanned your ship |
| `PoliceAttack` | `3` | Security vessel is attacking you |
| `FuelStatus` | `1` | Routine fuel level report |
| `FuelWarning` | `2` | Fuel level below warning threshold |
| `FuelCritical` | `3` | Fuel level below critical threshold |
| `MissionUpdate` | `2` | Mission accepted, completed, redirected, or removed |
| `AllMissionsReady` | `3` | All active massacre missions ready to turn in |
| `CarrierJumpScheduled` | `3` | Fleet or squadron carrier jump scheduled — carrier, destination and countdown |
| `CarrierJumpCancelled` | `3` | A scheduled carrier jump was cancelled |
| `CarrierJumpComplete` | `2` | Carrier arrived at its destination |
| `MeritEvent` | `0` | Individual merit gain from a kill |
| `InactiveAlert` | `3` | No kills for the configured time period |
| `RateAlert` | `3` | Kill rate below the configured threshold |
| `InboundScan` | `0` | Incoming cargo scan from a pirate |

---

## Command Line Arguments

```
python edld.py [-p PROFILE] [-t] [-d] [--tui | --gui | --terminal]
               [--mode MODE] [--log-file PATH] [--version] [--selftest]
```

| Flag | Description |
|------|-------------|
| `-p`, `--config_profile` | Load a named config profile |
| `-t`, `--test` | Re-route Discord output to terminal instead of sending to webhook |
| `-d`, `--trace` | Print verbose debug and trace output to terminal |
| `--tui` | Terminal dashboard (the default) |
| `--gui` | Desktop window — requires PySide6 |
| `--terminal` | Plain scrolling event output |
| `--mode MODE` | Older form of the above: `textual`, `gui`, or `terminal` |
| `--log-file PATH` | Tee all terminal output to PATH |
| `--version` | Print the version and exit |
| `--selftest` | Report whether each interface can be loaded, then exit |

The three interface flags are mutually exclusive, and passing one alongside a
conflicting `--mode` is an error rather than a silent resolution.

`--version` and `--selftest` both answer before any config, journal or
component work, so they run on a machine that has never started the game. The
release workflow uses them to verify each published binary.

### Environment variables

| Variable | Effect |
|----------|--------|
| `EDLD_KEEP_STDERR=1` | Keep stdout and stderr attached in `--tui` and `--gui` |
| `SSL_CERT_FILE` | Override the CA bundle used for HTTPS verification |
| `EDLD_INSTALL_GUI=yes\|no` | Answer `install.sh`'s PySide6 prompt ahead of time |

The dashboards normally route stdout and stderr to `/dev/null` so terminal
noise cannot corrupt the display. A startup failure is recorded in the
diagnostic log regardless; `EDLD_KEEP_STDERR=1` is for the rarer case where
something fails before the log exists.

Packaged builds ship their own CA bundle, because a frozen binary's OpenSSL
looks for certificates where the build machine kept them. `SSL_CERT_FILE` is
respected if you set it — point it at your own root if you are behind a
TLS-inspecting proxy. The startup log records which store is in use.

When a new release is available on GitHub, EDLD displays a notification at startup (terminal), in the title bar (terminal dashboard), or in a bar below the menu (desktop window). Updating is manual — take the new source or binary from the [releases page](https://github.com/drworman/EDLD/releases), and re-run `install.sh` if you run from source.

---

## `[Radio]`

Stations for the Radio tab in the Crew / Alerts window, in both the terminal dashboard and the desktop window. **[HOT]** — the station list follows the file within a second of saving, with no restart.

Each station is two keys joined by an Id of your choosing:

| Key | Meaning |
|---|---|
| `Name_<Id>` | What the station list shows. Optional — the Id is shown if it is missing |
| `Url_<Id>` | The stream address, `http://` or `https://`. A `.m3u` or `.pls` playlist address also works; its first stream is played |

The Id is a TOML bare key: letters, digits, `_` and `-`, no spaces. It only has to pair the two lines up. Stations are listed in the order they appear, defaults first.

Three stations ship as defaults:

```toml
[Radio]
Name_RadioSidewinder = "Radio Sidewinder"
Url_RadioSidewinder  = "https://radiosidewinder.out.airtime.pro:8000/radiosidewinder_b"
Name_HuttonOrbital   = "Hutton Orbital Radio"
Url_HuttonOrbital    = "https://quincy.torontocast.com/hutton"
Name_RadioSkvortsov  = "Radio Skvortsov"
Url_RadioSkvortsov   = "https://cast1.torontocast.com:3225/stream"
```

### Adding, editing and deleting from the Radio tab

The **+**, **✎** and **−** beside the station list do this for you, in both interfaces.

**+** opens a form for the station's name and stream address, and where to keep it:

- **Global — every profile** (preselected) adds the pair to `[Radio]`.
- **Current profile** adds it to the profile loaded now, as `Radio.Name_<Id>` / `Radio.Url_<Id>` lines under `[EDP1]`, or inside `[EDP1.Radio]` if your file already has that table. It is unavailable when no profile is loaded.

The Id is made from the name — "Lave Radio" becomes `LaveRadio` — with a number added if that Id is already used anywhere in the file. A name already in the list, or an address that is not `http(s)://` with a host name, is refused with the reason.

**✎** edits the selected station's name and stream address. The station keeps its Id, so it stays selected and stays the remembered station. The change is saved where the station already lives — the current profile if the profile defines it, otherwise `[Radio]` — and the form says which. Editing a default station writes its keys into `[Radio]`, where they override the default and are not put back at startup. If the station is playing, a new address is tuned in straight away and a new name shows under On air at once; a name-only change does not interrupt the stream. The same checks as adding apply, except that a station's own name is not a clash with itself.

**−** deletes the selected station after asking. The confirmation says exactly what will change:

- a station you added is removed from `[Radio]`, and from the current profile if it is defined there;
- a **default** station has its `Url_` blanked instead of deleted, because deleted default lines are put back at startup (see below);
- a station that is playing is stopped first.

All three edit `config.toml` in place, changing only the station's own lines — your comments, spacing and every other setting are left exactly as they were. Before anything is written the result is parsed back and compared with what was intended; if the file is laid out in a way the editor cannot change safely, it says so and leaves the file untouched, and you can make the edit by hand as below.

### Adding your own station by hand

Add a pair to `[Radio]` to have it everywhere:

```toml
[Radio]
Name_LaveRadio = "Lave Radio"
Url_LaveRadio  = "https://example.org:8000/stream"
```

Or add it to a profile to have it only when that profile is loaded, using the same dotted keys as any other profile setting:

```toml
[EDP1]
Radio.Name_MyStation = "My Station"
Radio.Url_MyStation  = "https://example.org:8000/stream"
```

A profile can also rename a default (`Radio.Name_HuttonOrbital = "Hutton"`) or point it somewhere else.

### Hiding a station

Set its URL to an empty string, globally or in a profile:

```toml
[EDP1]
Radio.Url_RadioSkvortsov = ""
```

Deleting a default station's lines from `[Radio]` does not remove it: like every other default, EDLD adds missing keys back to the section at startup. An empty URL is kept as you wrote it.

### What plays

Streams must be **MP3, Ogg Vorbis or FLAC**. That covers most Icecast and SHOUTcast stations, including all three defaults. **AAC, AAC+ and Opus** stations, and HLS (`.m3u8`) streams, are refused with a message saying which format they are, rather than playing silence. To check a station before adding it:

```bash
curl -sI 'https://example.org:8000/stream' | grep -i content-type
```

`audio/mpeg`, `audio/ogg`, `application/ogg` and `audio/flac` will play.

### Behaviour

- **Nothing plays until you press Play.** The last station you chose is selected again at the next launch, but not started.
- Choosing another station while one is playing switches to it.
- Volume steps by 5%. Volume, mute and the last station are remembered in `radio.json` in the EDLD data directory, not in `config.toml`, so adjusting them never rewrites your config.
- A station that is hidden or has its URL changed while it is playing is stopped.
- Any new alert brings the Crew / Alerts tab back to the front. The radio keeps playing.
- The song title is shown where the station sends one (most do).
- An entry that cannot be used — a `Name_` with no `Url_`, a URL that is not `http(s)://`, a key that is neither — is listed under **Config** in the Radio tab, not dropped silently.
- Playback needs the `miniaudio` package. It is installed by `install.sh` and bundled in the release binaries; if it is missing, the Radio tab says so and everything else works normally.

---

## Config Profiles

Profiles let you override any setting for a specific commander or purpose. Define them as named sections in `config.toml`:

```toml
[MyProfile]
Settings.JournalFolder = "/path/to/alternate/journals"
Discord.WebhookURL = 'https://discord.com/api/webhooks/...'
Discord.UserID = 123456789012345678
UI.Theme = "default-green"
```

Load explicitly with `-p MyProfile`, or name the profile after your commander name for automatic selection at startup.

Multiple profiles coexist in the same config file — useful for multi-account setups:

```toml
[EDP1]
Settings.JournalFolder = "/home/user/games/ED-Logs/EDP1"
Discord.WebhookURL = 'https://discord.com/api/webhooks/...'

[EDP2]
Settings.JournalFolder = "/home/user/games/ED-Logs/EDP2"
Discord.WebhookURL = 'https://discord.com/api/webhooks/...'
```

---

## Notes

- **Fuel alerts** trigger on *either* the percentage threshold *or* the estimated time-remaining threshold — whichever fires first.
- **Duplicate suppression** caps repeated identical Discord messages at 5 before switching to a suppression notice, preventing notification floods.
- **Journal path (Linux/Proton):** varies — use `find ~/ -name "Journal*.log"` to locate it.

---

## How the hold is read

Nothing here is configurable. It is written down because when the cargo
manifest disagrees with the game, the reason is almost always one of these two.

**Journals are read in filename order, not by modification time.** Elite names
them with an ISO timestamp, so they sort chronologically on their own.
Modification times do not survive a copy, a sync, or a search-and-replace
across the directory, and EDLD once rebuilt a hold from journals four months
stale because the four newest by mtime were the four it had touched last.

**The hold itself is followed from `Cargo.json`, not inferred from events.**
Journal events name a count and nothing else once the hold is large, so the
manifest is reconstructed by replaying the recent journals and then taking
`Cargo.json` — which the game rewrites whenever the hold changes — as the
current word. That file is polled every two seconds alongside `Market.json`,
so the manifest stays right even when the journal lags.

It is applied strictly by vessel. `Cargo.json` describes whichever hold last
changed, ship or SRV, and the two are never mixed.

**A journal that stops growing while the game runs** costs everything the
event stream carries — the game mode, the location, the session — even though
the hold keeps updating. That is worth knowing because the usual cause is
outside the game: a rotation, a sync, or an in-place edit of a file the game
has open. Replacing such a file leaves the game writing to a handle that no
longer has a name, and everything after that moment is invisible on disk.

---

## Market files

Three files are written into the commander's data directory — the same place
as `cargo.json` and the window layout — and rewritten whenever the game writes
a new `Market.json`. Nothing here is configurable; they are listed so you know
where to find them and what they mean.

| File | Contents |
|------|----------|
| `data/cargo.commodities.csv` | Every commodity ever seen in a market |
| `data/cargo.commodities.md` | The sell table, as Markdown |
| `data/cargo.commodities.html` | The sell table, as a standalone HTML page |

### The catalogue

`Market.json` is a snapshot of one station and is overwritten the next time you
dock, so the galactic average it carries for each commodity is visible while
you are standing there and gone afterwards. The CSV keeps a running record
instead: one row per commodity, written once and rewritten whenever its
`MeanPrice` drifts.

```
name,id,name_localised,category,category_localised,mean_price,first_seen,last_updated,updates
gold,128049154,Gold,metals,Metals,47113,2026-09-12T04:11:22Z,2026-09-12T04:11:22Z,0
```

Rows are keyed on `name`, the internal symbol, and the file is sorted by `id`
so successive versions diff cleanly. `updates` counts how many times the price
has moved since `first_seen`, which is the closest thing here to a volatility
figure.

A commodity is recorded even when the market reports a `MeanPrice` of 0 —
identity is worth having wherever it turns up — but a zero never overwrites a
price already on file, so a carrier visit cannot flatten the catalogue. Such a
row heals itself the first time the commodity appears at a station market.

### The sell table

The Markdown and HTML files are two renderings of what you would be shown by
pressing **Ctrl+S**: a heading naming the market being quoted, and a
two-column table of commodity against price, most valuable first. The HTML is
standalone — no stylesheet to keep beside it — and follows your reader's light
or dark preference.

Which market gets quoted is resolved the same way the Cargo panel prices your
manifest, so the panel and these files can never name different markets: a
Spansh target market when one is set and loaded, the station you are docked at
otherwise, and the galactic average when there is neither.

Two things are deliberately left out.

**Carrier markets.** Fleet and squadron carriers are player-run, mobile, and
rewritten without notice, so docking at one leaves the files and the popup
describing whatever was quoting beforehand. The catalogue still records a
carrier's commodities; its prices just never reach the sell table.

**Prices no NPC will pay.** Stations list carrier-only commodities and quote a
sell price for them that nobody in the galaxy will honour — the Titan Maw
tissue samples list at over 470,000 cr at an ordinary starport. The tell is
that they carry no galactic average, so any commodity the catalogue has never
seen an average for is left out of the table. This is not a demand filter: a
station with nothing on order still pays, and filtering on demand would hide
most of what is worth carrying.

---

## Data Contributions (opt-in)

All data contribution features are **opt-in** and disabled by default.  They are configured in their own `[SECTION]` blocks and all require a restart when changed (❌).  Settings can be managed in the **Preferences → Data & Integrations** tab.

If you run EDLD on multiple machines reading the same journal share (e.g. a remote monitor over NFS), set `PrimaryInstance = false` in `[Settings]` on the secondary machine to prevent duplicate uploads.  See `[Settings]` above.

---


---

## CAPI Integration

EDLD can connect to Frontier's Companion API (CAPI) to retrieve authoritative
fleet data, market prices, carrier state, and squadron information.

### Enabling CAPI

Use **File → CAPI Authentication** to complete the OAuth2 flow. You will be
redirected to Frontier's login page in your browser. On success, tokens are

### What CAPI provides (vs journal-only)

| Data | CAPI enabled | CAPI disabled |
|------|-------------|---------------|
| Fleet roster | Authoritative — Frontier server | Most recent `StoredShips` event |
| Sold ship exclusion | Automatic | May show sold ships until next dock |
| Stored ship hull % | ✓ | ✗ |
| Stored ship rebuy cost | ✓ | ✗ |
| Current ship loadout | ✓ (immediate) | ✓ (from journal) |
| Stored ship loadout | ✓ (from journal, CAPI-validated) | ✓ (from journal, unvalidated) |
| Market prices | ✓ (live on dock) | From `Market.json` |
| Squadron identity | ✓ | ✗ |
| Community Goals | ✓ | ✗ |

### Persisted CAPI data

After each poll, raw endpoint responses are written to
fleet data is available immediately without waiting for a re-poll:

| File | Source | Updated |
|------|--------|---------|
| `capi_profile.json` | `/profile` | Every dock |
| `capi_market.json` | `/market` | Every dock (outfitting station) |
| `capi_shipyard.json` | `/shipyard` | Every dock (outfitting station) |
| `capi_fleetcarrier.json` | `/fleetcarrier` | Every dock |
| `capi_communitygoals.json` | `/communitygoals` | Every dock, 5-min cooldown |

### Poll frequency

CAPI is polled on every dock event and 10 seconds after startup. Per-endpoint
cooldowns prevent over-polling: profile/carrier 30s, market/shipyard 60s,
community goals 300s.

Frontier requests no more than 1 query per minute in normal use. EDLD respects
this by batching all endpoint polls on dock rather than polling continuously.

### `[EDDN]`

Contributes exploration, market, outfitting, and shipyard data to the [Elite Dangerous Data Network](https://eddn.edcd.io) — the shared relay used by EDSM, Inara, and most third-party tools.

| Key | Default | Description |
|-----|---------|-------------|
| `Enabled` | `false` | ❌ Enable EDDN uploads |
| `UploaderID` | `""` | ❌ Anonymous uploader tag shown in EDDN messages — defaults to your commander name if blank |
| `TestMode` | `false` | ❌ Send to `/test` schemas only (development use) |

---

### `[EDSM]`

Uploads your flight log and discoveries to [edsm.net](https://www.edsm.net).  Requires a free EDSM account.  Generate your API key at **EDSM → Settings → API Key**.

| Key | Default | Description |
|-----|---------|-------------|
| `Enabled` | `false` | ❌ Enable EDSM uploads |
| `CommanderName` | `""` | ❌ Your EDSM commander name — must match your account exactly |
| `ApiKey` | `""` | ❌ Your EDSM API key |

Events are batched and flushed on session transitions (FSDJump, Docked, LoadGame) to stay well within EDSM's rate limit.  A discard list is fetched from EDSM at startup so only requested events are sent.

---

### `[EDAstro]`

Uploads exploration, Odyssey organic scan, and fleet carrier data to [edastro.com](https://edastro.com).  No account or API key required — uploads are anonymous.

| Key | Default | Description |
|-----|---------|-------------|
| `Enabled` | `false` | ❌ Enable EDAstro uploads |
| `UploadCarrierEvents` | `false` | ❌ Include `CarrierStatus` and `CarrierJumpRequest` events — note that these reveal your carrier's location to EDAstro |

An event-interest list is fetched from EDAstro at startup so only the events EDAstro wants are sent.

---

### `[Inara]`

Uploads your flight log, ranks, credits, missions, and ship loadout to [inara.cz](https://inara.cz). Requires a free Inara account. Generate your API key at **inara.cz → Settings → API**.

| Key | Default | Description |
|-----|---------|-------------|
| `Enabled` | `false` | ❌ Enable Inara uploads |
| `CommanderName` | `""` | ❌ Your in-game commander name — must match your Inara profile exactly |
| `ApiKey` | `""` | ❌ Your Inara API key |

---

### `[Colonisation]`

Syncs colonisation construction supply needs and commander contributions to [Raven Colonial](https://ravencolonial.com) — a community tool for tracking colonisation projects. Local tracking of resource requirements and delivery progress works without an API key.

> **Note:** Colonisation support is experimental and under active development.

| Key | Default | Description |
|-----|---------|-------------|
| `ApiKey` | `""` | Your Raven Colonial API key — obtain from ravencolonial.com → Account Settings. Leave blank to disable API sync; local tracking is always active |

The API key can be set at runtime via **Preferences → Data → Raven Colonial API Key** without restarting EDLD.

---

### Data contributions inside profiles

All three sections can be scoped to a profile like any other setting:

```toml
[EDP1.EDDN]
Enabled = true

[EDP1.EDSM]
Enabled       = true
CommanderName = "YourCmdrName"
ApiKey        = "your-api-key-here"

[EDP1.EDAstro]
Enabled = true
```

---

## Session Management — `[SessionMgmt]`

> ⚠️ **Solo mode only.** Session management terminates the Elite Dangerous game process when a trigger fires. It is **hard-gated to Solo play** — it will never act in Open or Private Group, because force-quitting in multiplayer is combat-logging under Frontier's rules. The gate is enforced at the point of termination, so even a manual activation is refused outside Solo.

Disabled by default and entirely opt-in. When enabled, EDLD watches the configured triggers and quits the game — locally via process termination, or on a remote host via SSH — when one is met. See the [Session Management guide](guides/SESSION_MANAGEMENT.md) for usage, the Ctrl+K runtime toggle, and the armed/idle indicator.

| Key | Default | Description |
|-----|---------|-------------|
| `Enabled` | `false` | ❌ Master enable. With this off, every trigger is inert |
| `QuitOnSLFDead` | `false` | ❌ Quit when your ship-launched fighter is destroyed |
| `QuitOnLowFuel` | `false` | ❌ Quit when main-tank fuel drops to or below the percentage threshold |
| `QuitOnLowFuelPercent` | `20` | Fuel percentage at or below which the fuel trigger fires |
| `QuitOnLowFuelMinutes` | `0` | If non-zero, also require estimated burn-time remaining to be at or below this many minutes before the fuel trigger fires (more conservative). `0` disables the time condition |
| `QuitFuelSCGraceSeconds` | `60` | Suppress fuel quits while in supercruise and for this many seconds after exiting it |
| `QuitOnLowHull` | `false` | ❌ Quit when your ship hull drops to or below the hull threshold |
| `QuitOnLowHullThreshold` | `10` | Hull percentage at or below which the hull trigger fires |
| `RemoteKillHost` | `""` | SSH host on which to terminate the game (for a remote/secondary monitor instance). Blank terminates locally |
| `RemoteKillUser` | `""` | SSH user for `RemoteKillHost`. Blank uses the current user |
| `QuitOnNoKillsMinutes` | `0` | Minutes without an NPC kill **while dropped in a Resource Extraction Site** before the session is quit. `0` disables. Solo-only and RES-only — see the guide |

Like any section, these can be scoped to a profile — handy for enabling termination on one commander only, or for keeping a remote monitor inert:

```toml
[SessionMgmt]
Enabled = false

[EDP1.SessionMgmt]
Enabled              = true
QuitOnLowFuel        = true
QuitOnLowFuelPercent = 15
```

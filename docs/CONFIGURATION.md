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
| `Mode` | `"textual"` | ❌ | UI mode: `textual` (TUI dashboard, default) or `terminal` (plain output) |
| `Theme` | `"default"` | ❌ | Theme name — changing this in Preferences triggers an automatic restart |

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
| `MeritEvent` | `0` | Individual merit gain from a kill |
| `InactiveAlert` | `3` | No kills for the configured time period |
| `RateAlert` | `3` | Kill rate below the configured threshold |
| `InboundScan` | `0` | Incoming cargo scan from a pirate |

---

## Command Line Arguments

```
python edld.py [-p PROFILE] [-g] [-t] [-d] [--mode MODE] [--log-file PATH]
```

| Flag | Description |
|------|-------------|
| `-p`, `--config_profile` | Load a named config profile |
| `-t`, `--test` | Re-route Discord output to terminal instead of sending to webhook |
| `-d`, `--trace` | Print verbose debug and trace output to terminal |
| `--mode MODE` | UI mode: `textual` (default) or `terminal` |
| `--log-file PATH` | Tee all terminal output to PATH |

When a new release is available on GitHub, EDLD displays a notification at startup (terminal) or in the title bar (TUI). Updating is performed manually — pull the new source from the [releases page](https://github.com/drworman/EDLD/releases) and re-run `install.sh`.

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

<div align="center">

<img src="images/edld_avatar_512.png" width="140" alt="EDLD"/>

# ED Live Dashboard
**Commander monitoring dashboard for Elite Dangerous**

[![Elite Dangerous](https://img.shields.io/badge/Game-Elite%20Dangerous-orange?style=flat-square)](https://www.elitedangerous.com)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-blue?style=flat-square)]()
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square)](https://python.org)
[![Textual](https://img.shields.io/badge/TUI-Textual-1D8348?style=flat-square)](https://github.com/Textualize/textual)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-41CD52?style=flat-square)](https://doc.qt.io/qtforpython/)
[![Discord](https://img.shields.io/badge/Discord-Webhook%20Support-5865F2?style=flat-square)]()

[![GitHub release](https://img.shields.io/github/v/release/drworman/EDLD?style=flat-square)](https://github.com/drworman/EDLD/releases)
[![GitHub stars](https://img.shields.io/github/stars/drworman/EDLD?style=flat-square)](https://github.com/drworman/EDLD/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/drworman/EDLD?style=flat-square)](https://github.com/drworman/EDLD/network/members)
[![License](https://img.shields.io/github/license/drworman/EDLD?style=flat-square)](LICENSE)

<ins>Career & real-time session tracking</ins></br>
Combat · Trade · Mining · Exploration · Missions · Exobiology · PowerPlay · Assets, and more

<ins>Integrations</ins></br>
FDev CAPI · EDDN · EDSM · EDAstro · Inara · Raven Colonial · Discord Webhooks

<ins>Multiple Interface Options</ins></br>
Terminal dashboard · Desktop window · Terminal scroll

</div>

## Overview

EDLD is a CMDR career and real-time session monitoring dashboard for Elite Dangerous, running on Linux, Windows and macOS. It tails your journal and presents the same dashboard three ways — a live terminal dashboard, a desktop window, or a scrolling feed — tracking everything you do across combat, trade, mining, exploration, missions, exobiology, and PowerPlay.

All three interfaces are built from one layout model and one set of components, so they show the same windows with the same data; only the rendering differs. Pick whichever suits the machine: the terminal dashboard over SSH, the desktop window on a second monitor beside the game.

Alerts fire when things go wrong: shields down, hull taking damage, fuel running low, fighter destroyed. Session statistics accumulate across all activity types in a tabbed panel that shows only what's relevant to your current session.

All game state flows through a unified `DataProvider` — CAPI when authenticated, journal events and local JSON files as fallback.

---

## Features

| | |
|--|--|
| 💥 **Combat Tracking** | Kills, bounties, combat bonds, deaths, and fighter losses with per-kill timing and faction tally |
| 🎯 **Mission Stack** | Active massacre mission tracking — stack value, completion status, and full bootstrap on start |
| 📊 **Session Statistics** | Tabbed activity dashboard — Combat, Trade, Mining, Exploration, Missions, Exobiology, PowerPlay — showing totals and /hr rates |
| 🖵 **Terminal Dashboard** | Full terminal dashboard with all panels. Runs on any machine with Python and a modern terminal |
| 🖥️ **Desktop Window** | The same dashboard as a native PySide6 window on Linux, Windows and macOS, with resizable columns, real menus, and full platform window controls |
| 🛡️ **Combat Alerts** | Shield drops, hull damage, fighter loss, ship destruction. Auto-clear on login and docking, plus a manual clear button |
| ⛽ **Fuel Monitoring** | Warn and critical thresholds for fuel percentage and estimated time remaining |
| 🚨 **Security & Cargo Events** | Cargo scans, police scans, security attacks, low-value cargo notices |
| ⚠️ **Inactivity Warnings** | Alerts on kill rate drop or extended period without kills |
| ✕ **Session Management** | Optional, opt-in auto-quit of the game on configured triggers — SLF destroyed, low fuel, or low hull. **Solo mode only**; runtime toggle with Ctrl+K |
| 💵 **Lifetime Financial Ledger** | Journal-derived earnings and spending by category, voucher reconciliation (issued vs redeemed), and carrier-bank flow — built from 27 credit-moving event types because in-game Statistics fields like `Trading.Goods_Sold` are unreliable |
| 📦 **Cargo Block** | Live ship hold display with tonnage gauge, per-item list, stolen-goods flagging, and Spansh target-market price comparison |
| ⚗️ **Engineering Block** | Engineering materials inventory across Raw, Manufactured, and Encoded categories, plus Odyssey ShipLocker contents |
| 🚀 **Assets Block** | Full fleet overview — current ship, stored ships with loadouts, stored modules, fleet carrier status, wallet with At-Risk holdings and net worth |
| 🧑 **Commander Block** | Commander identity, squadron, home location, fuel, shields/hull, and adaptive display for SRV and on-foot states |
| 🪪 **Career Block** | Combat / Trade / Exploration / Mercenary / Exobiology rank progression with detail tabs |
| 📊 **Session Window** | Current-session activity in full detail across combat, exploration, exobiology, mining, trade, missions, on-foot and PowerPlay. Reset with Ctrl+R |
| 📈 **Career Summary** | Lifetime counterpart to the Session window — the headline figures from every Career tab in one place, built from the same shared model so both read identically at their own scope |
| 🔧 **Ship Health Window** | Hull, shields, and every fitted module sorted by power priority then by health ascending, so modules needing repair surface first. Built for neutron hopping |
| 👥 **Crew / SLF Block** | NPC crew roster and ship-launched fighter status with correct variant identification |
| 💰 **At-Risk Holdings Tracker** | Persistent cross-session tracker for unredeemed bounties, combat bonds, trade vouchers, cartography, and exobiology. Survives session resets, zeroed on death |
| 🛡️ **Unified Data Provider** | Single source of truth for all game state — CAPI › journal › Status.json |
| 🔐 **CAPI Authentication** | OAuth2 to Frontier's Companion API for authoritative fleet roster, market prices, fleet carrier finance, and squadron identity |
| 🌐 **Data Contributions** | Opt-in journal uploading to EDDN, EDSM, EDAstro, and Inara |
| 🏗️ **Colonisation Tracking** | Construction site resource requirements, delivery progress, and Raven Colonial integration (experimental) |
| 🎨 **Themes** | Eight built-in colour themes (default-orange, green, blue, purple, red, yellow, dark, light) plus a documented template for custom themes |
| 🔌 **Plugin Architecture** | Three-tier plugin loader with per-commander data isolation, named config profiles, plugins dialog with enable/disable controls, and a `plugins/` directory for user plugins |
| 📚 **Native Documentation Viewer** | In-app viewer for all bundled documentation |
| 🔍 **Search Modals** | Searchable pickers for home location and Spansh target market |
| 🔔 **Update Notifier** | Background check for new tagged releases on GitHub; notice surfaced in the terminal, the TUI, and the desktop window |

<div align="center">
<img src="images/tui-screenshot.png" alt="EDLD Textual TUI" width="900"/>
<br><em>Textual TUI — default theme, live session in progress</em>
</div>

---

## Installation

**→ Full instructions: [INSTALL.md](INSTALL.md)**

### Linux (Arch)
```bash
sudo pacman -S python-psutil
pip install discord-webhook cryptography --break-system-packages
./install.sh
```

### Linux (Debian / Ubuntu)
```bash
sudo apt install python3-psutil
pip install discord-webhook cryptography --break-system-packages
bash install.sh
```

### Linux (Fedora)
```bash
sudo dnf install python3-psutil
pip install discord-webhook cryptography --break-system-packages
bash install.sh
```

> `psutil` has C extensions requiring system libraries — install it via your distro's package manager, not pip. See [INSTALL.md](INSTALL.md) for details.

`install.sh` offers to install PySide6 for the desktop interface. Decline it if
you only use the terminal interfaces — it is the largest dependency by far and
nothing else needs it. Set `EDLD_INSTALL_GUI=yes` or `=no` to answer ahead of
time in a scripted install.

### Windows and macOS

Download the binary for your platform from the
[Releases page](https://github.com/drworman/EDLD/releases) and run it. No Python
install is required; everything is bundled.

The Windows and macOS builds start the desktop window by default. The terminal
interfaces are still there if you run the executable from a shell with `--tui`
or `--terminal`.

---

## Quick Start

```bash
git clone https://github.com/drworman/EDLD.git
cd EDLD
bash install.sh

./edld.py                    # terminal dashboard (default)
./edld.py --gui              # desktop window
./edld.py --terminal         # plain scrolling output
./edld.py -p MyProfile       # named config profile
./edld.py --version          # print version and exit
```

`--tui`, `--gui` and `--terminal` are the three interfaces. The older
`--mode textual|terminal|gui` form still works and means the same thing.

If no `config.toml` exists, EDLD creates one with defaults and prints its location on startup. Set `JournalFolder` to your ED journal directory before proceeding.

---

## Config file location

`config.toml` lives at `~/.local/share/EDLD/config.toml`. `~/.config/EDLD` is a symlink to the same directory.

---

## Discord Integration

1. In Discord: **Edit Channel → Integrations → Webhooks → New Webhook**
2. Copy the webhook URL into `config.toml`:

```toml
[Discord]
WebhookURL = 'https://discord.com/api/webhooks/...'
UserID = 123456789012345678
```

`UserID` enables `@mention` pings on level-3 alerts. Find yours via Discord's Developer Mode (right-click your username).

<div align="center">
<img src="images/discord_launch_notice.png" alt="Discord launch notice embed" width="420"/>
<br><em>Startup embed posted to Discord when monitoring begins</em>
</div>

---

## Documentation

| Document | Contents |
|----------|----------|
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [INSTALL.md](INSTALL.md) | Full installation instructions |
| [Configuration](docs/CONFIGURATION.md) | All config keys, notification levels, CLI flags, profiles, data integrations (EDDN, EDSM, EDAstro, Inara, Raven Colonial) |
| [Terminal Output](docs/TERMINAL_OUTPUT.md) | Startup banner, event line format, sigil/tag reference, periodic summary |
| [Theming](docs/THEMING.md) | Built-in themes, custom theme creation |
| [Mission Bootstrap](docs/MISSION_BOOTSTRAP.md) | How EDLD reconstructs mission state on startup |
| [Roadmap](docs/ROADMAP.md) | Active, near-term, and deferred work |
| [Release Signing](docs/SIGNING.md) | How to verify release artifacts |
| [Building](docs/BUILDING.md) | Running from source, building binaries, relinking against your own Qt |
| [Licensing](docs/LICENSING.md) | MIT, and how the LGPL obligations for Qt are met |

### Guides

| Guide | Description |
|-------|-------------|
| [Linux Setup](docs/guides/LINUX_SETUP.md) | Elite Dangerous on Linux with Steam, Proton, Minimal ED Launcher, and EDLD |
| [Dual Pilot](docs/guides/DUAL_PILOT.md) | Two accounts simultaneously with independent journals and tool instances |
| [Remote Access](docs/guides/REMOTE_ACCESS.md) | EDLD dashboard on a second machine as a thin client |
| [Session Management](docs/guides/SESSION_MANAGEMENT.md) | Optional Solo-only auto-quit on low fuel/hull or SLF loss — why it is Solo-only, how to enable and use it |

---

## License

EDLD is released under the [MIT License](LICENSE) — use it, fork it, sell it,
embed it in something proprietary. Keep the copyright notice.

Its dependencies carry their own terms. The one that constrains redistribution
is Qt: the desktop interface uses **PySide6 under the LGPL v3**, so a binary
you distribute must ship the licence texts and let recipients relink against
their own Qt. Both obligations are already met by the official builds.

| | |
|--|--|
| [LICENSE](LICENSE) | The MIT licence covering EDLD itself |
| [docs/LICENSING.md](docs/LICENSING.md) | How each LGPLv3 condition is met, and what to do if you fork and distribute binaries |
| [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) | Every dependency, its licence, and whether it is bundled |
| [licenses/](licenses/) | Full GPL and LGPL texts, shipped inside every binary and release archive |

The terminal interfaces depend only on permissively licensed packages; a build
carrying just `--tui` and `--terminal` has no LGPL obligations at all.

---

## Attribution and disclaimer

**ED Live Dashboard (EDLD) is an unofficial community tool.**

Elite Dangerous is a trademark of Frontier Developments plc. This project is
not affiliated with, endorsed by, or supported by Frontier Developments plc.
Please do not imply otherwise in a fork.

EDLD reads the journal files the game writes to your local filesystem, in the
documented format Frontier publishes for exactly this purpose. It does not
modify the game, inject code, or read process memory. Its only contact with
Frontier's servers is through the Companion API, using your own credentials and
only when you choose to connect.

---

<div align="center">

*Fly safe out there, CMDR.*

<img src="images/edld_avatar_512.png" width="56" alt="EDLD"/>

**ED Live Dashboard** · by CMDR HUGH JASSOLE

</div>

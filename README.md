<div align="center">

<img src="images/edld_avatar_512.png" width="140" alt="EDLD"/>

# ED Linux Dash
**Commander monitoring dashboard for Elite Dangerous**

[![Elite Dangerous](https://img.shields.io/badge/Game-Elite%20Dangerous-orange?style=flat-square)](https://www.elitedangerous.com)
[![Linux](https://img.shields.io/badge/Platform-Linux-FCC624?style=flat-square)]()
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square)](https://python.org)
[![GTK4](https://img.shields.io/badge/GUI-GTK4-4A86CF?style=flat-square)](https://gtk.org)
[![Textual](https://img.shields.io/badge/TUI-Textual-1D8348?style=flat-square)](https://github.com/Textualize/textual)
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
Terminal scroll · Textual TUI · GTK4 GUI

</div>

## Overview

EDLD is a CMDR career and real-time session monitoring dashboard for Elite Dangerous on Linux. It tails your journal and presents a feed or live dashboard — either a GTK4 window or a Textual terminal UI — alongside the game, tracking everything you do across combat, trade, mining, exploration, missions, exobiology, and PowerPlay.

Alerts fire when things go wrong: shields down, hull taking damage, fuel running low, fighter destroyed. Session statistics accumulate across all activity types in a tabbed panel that shows only what's relevant to your current session.

All game state flows through a unified `DataProvider` — CAPI when authenticated, journal events and local JSON files as fallback.

---

## Features

| | |
|--|--|
| 💥 **Combat Tracking** | Kills, bounties, combat bonds, deaths, and fighter losses with per-kill timing and faction tally |
| 🎯 **Mission Stack** | Active massacre mission tracking — stack value, completion status, and full bootstrap on start |
| 📊 **Session Statistics** | Tabbed activity dashboard — Combat, Trade, Mining, Exploration, Missions, Exobiology, PowerPlay — showing totals and /hr rates |
| 🖥️ **GTK4 GUI** | Live graphical interface for Linux with all dashboard panels, ghost drag-and-resize, and per-block show/hide |
| 🖵 **Textual TUI** | Full terminal dashboard — same layout and data as the GUI. Runs on any machine with Python and a modern terminal |
| 🛡️ **Combat Alerts** | Shield drops, hull damage, fighter loss, ship destruction. Auto-clear on login and docking, plus a manual clear button |
| ⛽ **Fuel Monitoring** | Warn and critical thresholds for fuel percentage and estimated time remaining |
| 🚨 **Security & Cargo Events** | Cargo scans, police scans, security attacks, low-value cargo notices |
| ⚠️ **Inactivity Warnings** | Alerts on kill rate drop or extended period without kills |
| 💵 **Lifetime Financial Ledger** | Journal-derived earnings and spending by category, voucher reconciliation (issued vs redeemed), and carrier-bank flow — built from 27 credit-moving event types because in-game Statistics fields like `Trading.Goods_Sold` are unreliable |
| 📦 **Cargo Block** | Live ship hold display with tonnage gauge, per-item list, stolen-goods flagging, and Spansh target-market price comparison |
| ⚗️ **Engineering Block** | Engineering materials inventory across Raw, Manufactured, and Encoded categories, plus Odyssey ShipLocker contents |
| 🚀 **Assets Block** | Full fleet overview — current ship, stored ships with loadouts, stored modules, fleet carrier status, wallet with At-Risk holdings and net worth |
| 🧑 **Commander Block** | Commander identity, squadron, home location, fuel, shields/hull, and adaptive display for SRV and on-foot states |
| 🪪 **Career Block** | Combat / Trade / Exploration / Mercenary / Exobiology rank progression with detail tabs |
| 👥 **Crew / SLF Block** | NPC crew roster and ship-launched fighter status with correct variant identification |
| 💰 **At-Risk Holdings Tracker** | Persistent cross-session tracker for unredeemed bounties, combat bonds, trade vouchers, cartography, and exobiology. Survives session resets, zeroed on death |
| 🛡️ **Unified Data Provider** | Single source of truth for all game state — CAPI › journal › Status.json |
| 🔐 **CAPI Authentication** | OAuth2 to Frontier's Companion API for authoritative fleet roster, market prices, fleet carrier finance, and squadron identity |
| 🌐 **Data Contributions** | Opt-in journal uploading to EDDN, EDSM, EDAstro, and Inara |
| 🏗️ **Colonisation Tracking** | Construction site resource requirements, delivery progress, and Raven Colonial integration (experimental) |
| 🎨 **Themes** | Eight built-in themes (default-orange, green, blue, purple, red, yellow, dark, light) plus a documented CSS template for custom themes |
| 🔤 **Bundled JetBrains Mono Font** | Bundled in `fonts/`, auto-installed to your user data directory and registered per-process — no system font directories touched. Falls back to system monospace if absent |
| 🔌 **Plugin Architecture** | Three-tier plugin loader with per-commander data isolation, named config profiles, plugins dialog with enable/disable controls, and a `plugins/` directory for user plugins |
| 📚 **Native Documentation Viewer** | In-app viewer for all bundled documentation |
| 🔍 **Search Modals** | Searchable pickers for home location and Spansh target market |
| 🔔 **Update Notifier** | Background check for new tagged releases on GitHub; notice surfaced in terminal, TUI, and GTK4 title bar |

<div align="center">
<img src="images/gui-screenshot.png" alt="EDLD GTK4 GUI" width="900"/>
<br><em>GTK4 GUI — default theme, live session in progress</em>
</div>

<div align="center">
<img src="images/tui-screenshot.png" alt="EDLD Textual TUI" width="900"/>
<br><em>Textual TUI — same layout, no GTK4 required</em>
</div>

---

## Installation

**→ Full instructions: [INSTALL.md](INSTALL.md)**

### Linux (Arch)
```bash
sudo pacman -S python-psutil python-gobject gtk4
pip install discord-webhook cryptography --break-system-packages
./install.sh
```

### Linux (Debian / Ubuntu)
```bash
sudo apt install python3-psutil python3-gi gir1.2-gtk-4.0
pip install discord-webhook cryptography --break-system-packages
bash install.sh
```

### Linux (Fedora)
```bash
sudo dnf install python3-psutil python3-gobject gtk4
pip install discord-webhook cryptography --break-system-packages
bash install.sh
```

> `psutil` and `PyGObject` have C extensions requiring system libraries — install them via your distro's package manager, not pip. See [INSTALL.md](INSTALL.md) for details.

---

## Quick Start

```bash
git clone https://github.com/drworman/EDLD.git
cd EDLD
bash install.sh

./edld.py                    # terminal output only
./edld.py --mode textual     # Textual TUI
./edld.py --mode gtk4        # GTK4 GUI
./edld.py -p MyProfile       # named config profile
```

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
| [GUI Theming](docs/THEMING.md) | Built-in themes, custom theme creation |
| [Mission Bootstrap](docs/MISSION_BOOTSTRAP.md) | How EDLD reconstructs mission state on startup |
| [Roadmap](docs/ROADMAP.md) | Active, near-term, and deferred work |
| [Release Signing](docs/SIGNING.md) | How to verify release artifacts |

### Guides

| Guide | Description |
|-------|-------------|
| [Linux Setup](docs/guides/LINUX_SETUP.md) | Elite Dangerous on Linux with Steam, Proton, Minimal ED Launcher, EDMC, and EDLD |
| [Dual Pilot](docs/guides/DUAL_PILOT.md) | Two accounts simultaneously with independent journals and tool instances |
| [Remote Access](docs/guides/REMOTE_ACCESS.md) | EDLD GUI on a second machine as a thin client |

---

<div align="center">

*Fly safe out there, CMDR.*

<img src="images/edld_avatar_512.png" width="56" alt="EDLD"/>

**ED Linux Dash** · by CMDR CALURSUS

</div>

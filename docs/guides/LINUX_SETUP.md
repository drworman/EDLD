# Elite Dangerous on Linux

A practical guide to getting Elite Dangerous running on Linux with Steam and
Proton, paired with the supporting tools that make it worth playing.

This guide covers the base installation — one game, one account, one set of
tools. If you want to run multiple pilots simultaneously, see
[DUAL_PILOT.md](DUAL_PILOT.md) once you have this working.

---

## System requirements

This guide was written on Arch Linux with i3 as the window manager. The steps
are the same regardless of distro or desktop environment — path conventions and
package names are the only things that differ, and those are called out
explicitly where they matter.

You will need:

- Steam (via your distro repo or the Steam installer)
- Python 3.11 or later
- A terminal you are comfortable with
- A private Discord server for notifications (free — highly recommended)

---

## Step 1 — Install Steam and Elite Dangerous

Install Steam via your package manager or from the Steam website. Then install
Elite Dangerous through Steam, open its Properties, and set your Proton version
under the Compatibility tab. Proton Hotfix is a solid default — your experience
may vary depending on your hardware and driver stack.

Launch Elite Dangerous once through Steam to confirm it runs and to log in to
your first account. Then close it.

---

## Step 2 — Minimal ED Launcher

The standard Frontier launcher is resource-heavy and unreliable on Linux.
[Minimal ED Launcher](https://github.com/rfvgyhn/min-ed-launcher) replaces it
with a lightweight alternative that handles authentication cleanly and gets out
of the way.

Download the latest release from the GitHub page and extract it somewhere
permanent. The author's documentation covers installation thoroughly — follow
it. This guide will not duplicate instructions that may change between releases.

A straightforward location that works well:

```bash
mkdir -p ~/games/ed-mods/medl
# extract the release archive here
```

When Minimal ED Launcher runs for the first time it will create a settings file
at `~/.config/min-ed-launcher/settings.json`. A working baseline configuration:

```json
{
    "apiUri": "https://api.zaonce.net",
    "watchForCrashes": false,
    "language": null,
    "autoUpdate": false,
    "checkForLauncherUpdates": true,
    "maxConcurrentDownloads": 4,
    "forceUpdate": "",
    "processes": [],
    "shutdownProcesses": [],
    "filterOverrides": [
        { "sku": "FORC-FDEV-DO-1000", "filter": "edo" },
        { "sku": "FORC-FDEV-DO-38-IN-40", "filter": "edh4" }
    ],
    "additionalProducts": []
}
```

**Important:** before using Minimal ED Launcher, confirm that your Frontier
account is linked to your Steam account. Both can originate through Steam — what
matters is that the Frontier account exists and is connected. Log in at
[frontierstore.net](https://www.frontierstore.net/customer/account/login/) to
verify.

---

## Step 3 — Launch script

Put this script somewhere on your `$PATH` — `~/.local/bin/` is a clean choice.

```bash
vim ~/.local/bin/edp1
```

```bash
#!/usr/bin/env bash

# Environment variables
export ED_JOURNAL_DIR="$HOME/games/ED-Logs/EDP1/"
export STEAM_COMPAT_DATA_PATH="$HOME/.local/share/Steam/steamapps/compatdata/EDP1"
export STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.local/share/Steam"

# If compat data path doesn't exist, copy from 359320 (default ED install)
if [ ! -d "$STEAM_COMPAT_DATA_PATH" ]; then
  cp -r "$HOME/.local/share/Steam/steamapps/compatdata/359320" "$STEAM_COMPAT_DATA_PATH"
fi

# Ensure directories from env vars exist
for dir in "$ED_JOURNAL_DIR" "$STEAM_COMPAT_DATA_PATH" "$STEAM_COMPAT_CLIENT_INSTALL_PATH"; do
  mkdir -p "$dir"
done

# Launch Elite Dangerous via Minimal ED Launcher
"$HOME/games/ed-mods/medl/MinEdLauncher" \
  "$HOME/.local/share/Steam/steamapps/common/Proton Hotfix/proton" \
  run \
  "$HOME/.local/share/Steam/steamapps/common/Elite Dangerous/EDLaunch.exe" \
  /novr \
  /autorun \
  /autoquit \
  /edo \
  /frontier \
  edp1 &

# Wait for the game to reach the main menu before launching companions
sleep 60
python "$HOME/.local/bin/EDLD/edld.py" -p EDP1 &
```

Make it executable:

```bash
chmod +x ~/.local/bin/edp1
```

Run it from a terminal the first time so that Minimal ED Launcher can prompt
you to authenticate with Frontier and write the credential file it will use for
future logins. You only need to do this once per account.

The `sleep` values give the game time to reach the main menu before companion
tools try to attach. Adjust them to suit your hardware — slower machines may
need more time.

---

## ## ## Step 5 — EDLD

[EDLD](https://github.com/drworman/EDLD) monitors your Elite Dangerous journal
in real time, posting kill counts, hull and shield events, fuel warnings, and
mission progress to your terminal and a Discord webhook.

Follow the [installation instructions](../../INSTALL.md) in the repo root, then
configure EDLD for your pilot profile — see `example.config.toml` for a
complete reference.

EDLD's `config.toml` lives in `~/.local/share/EDLD/config.toml` (created by
`install.sh`). At minimum, set your journal directory and Discord webhook:

```toml
[EDP1]
Settings.JournalFolder = "/home/username/games/ED-Logs/EDP1"
Discord.WebhookURL     = "https://discord.com/api/webhooks/..."
Discord.UserID         = 123456789098765432
```

---

## Step 7 — Session cleanup script

When you are done playing, this script cleanly terminates all ED-related
processes in the correct order:

```bash
vim ~/.local/bin/edquit
```

```bash
#!/usr/bin/env bash
# edquit — terminate all Elite Dangerous companion processes

# Defined targets — only these processes are touched
TARGETS=(
    "EliteDangerous64.exe"
    "MinEdLauncher"
    "edld.py"
)

for target in "${TARGETS[@]}"; do
    pids=$(pgrep -f "$target" 2>/dev/null) || true
    if [[ -n "$pids" ]]; then
        echo "Stopping: $target (PID $pids)"
        kill $pids
    fi
done

# Give processes a moment to exit gracefully
sleep 2

# Force-kill anything that did not respond
for target in "${TARGETS[@]}"; do
    pids=$(pgrep -f "$target" 2>/dev/null) || true
    if [[ -n "$pids" ]]; then
        echo "Force-killing: $target (PID $pids)"
        kill -9 $pids
    fi
done

echo "Done."
```

```bash
chmod +x ~/.local/bin/edquit
```

Only the four named processes are targeted. Nothing else is touched.

---

## Adjusting sleep timers

The `sleep 60` and `sleep 90` values in the launch script are starting points.
If EDLD attach before the game has finished loading, they may miss early
journal events. If your machine is slower, increase the values. If your SSD
makes loading instantaneous, you can reduce them. There is no penalty for
erring on the side of a longer wait.

---

*Fly dangerous, CMDR.*

---

*Guide by CMDR CALURSUS · [EDLD](https://github.com/drworman/EDLD)*

# Running Multiple Pilots on Linux

This guide covers running two Elite Dangerous accounts simultaneously on a single Linux machine, with independent journal directories, and separate EDLD profiles — one per pilot.

This guide assumes you already have Elite Dangerous running via Steam and Proton with Minimal ED Launcher. If you are not there yet, start with
[LINUX_SETUP.md](LINUX_SETUP.md).

---

## How it works

Elite Dangerous stores each session's journal files inside its Proton prefix directory. By giving each pilot their own Proton prefix, their journal directories are completely isolated. EDLD can then be pointed at the correct directory per pilot with no cross-contamination between accounts.

---

## Step 1 — Create separate Proton prefixes

Steam creates a Proton prefix for Elite Dangerous at:

```
~/.local/share/Steam/steamapps/compatdata/359320/
```

Copy it once per additional pilot:

```bash
cd ~/.local/share/Steam/steamapps/compatdata
cp -R 359320 EDP1
cp -R 359320 EDP2
```

This is the approach that works reliably. If disk space is a concern, you can symlink everything back to the original `359320` prefix *except* for the journal directory inside each pilot's prefix — that path must remain independent:

```
~/.local/share/Steam/steamapps/compatdata/EDP1/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous
~/.local/share/Steam/steamapps/compatdata/EDP2/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous
```

---

## Step 2 — Symlink journal directories

The journal paths inside the Proton prefix are awkward to work with directly. Symlink them somewhere sensible:

```bash
mkdir -p ~/games/ED-Logs/{EDP1,EDP2}

ln -s "$HOME/.local/share/Steam/steamapps/compatdata/EDP1/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous" \
      "$HOME/games/ED-Logs/EDP1"

ln -s "$HOME/.local/share/Steam/steamapps/compatdata/EDP2/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous" \
      "$HOME/games/ED-Logs/EDP2"
```

All tools can now reference the clean paths `~/games/ED-Logs/EDP1` and `~/games/ED-Logs/EDP2` instead of the full Proton paths.

---

## Step 3 — Launch scripts

Create one script per pilot. The key difference between them is `EDP1`/`EDP2` in the environment variables and the profile flag passed to each tool.

`~/.local/bin/edp1`:

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

Copy it for the second pilot and update every `EDP1`/`edp1` reference to
`EDP2`/`edp2`:

```bash
cp ~/.local/bin/edp1 ~/.local/bin/edp2
sed -i 's/EDP1/EDP2/g; s/edp1/edp2/g' ~/.local/bin/edp2
chmod +x ~/.local/bin/edp1 ~/.local/bin/edp2
```

Verify the result before relying on it:

```bash
diff ~/.local/bin/edp1 ~/.local/bin/edp2
```

---

## Step 4 — Minimal ED Launcher credentials

Run each script from a terminal the first time so that Minimal ED Launcher can
prompt for Frontier authentication and write the credential file for that
account. You only need to do this once per pilot:

```bash
edp1   # authenticate first account, then close everything
edp2   # authenticate second account, then close everything
```

---

## ## Step 5 — EDLD profiles

EDLD's profile system is built for exactly this. In `~/.local/share/EDLD/config.toml`,
add a section per pilot:

```toml
[EDP1]
Settings.JournalFolder = "/home/username/games/ED-Logs/EDP1"
Discord.WebhookURL     = "https://discord.com/api/webhooks/..."
Discord.UserID         = 123456789098765432

[EDP2]
Settings.JournalFolder = "/home/username/games/ED-Logs/EDP2"
Discord.WebhookURL     = "https://discord.com/api/webhooks/..."
Discord.UserID         = 123456789098765432
```

Each profile can use the same Discord webhook or separate ones. Using separate
webhooks in separate channels is the cleanest way to keep two pilots' output
distinguishable at a glance.

The launch scripts already pass `-p EDP1` and `-p EDP2` respectively, so each
EDLD instance loads the correct profile automatically.

---

## Step 6 — Session cleanup

The `edquit` script from [LINUX_SETUP.md](LINUX_SETUP.md) terminates all
instances of each named process — both pilots' game instances, both EDLD instances in a single command:

```bash
edquit
```

Because `edquit` uses `pgrep -f` to match process names rather than PIDs, it
will find and terminate all running instances regardless of which pilot launched
them.

---

## Running both pilots

Once everything is configured, launching both pilots is two commands:

```bash
edp1
edp2
```

Each pilot runs a completely independent game instance and EDLD instance. Journal files, kill counts, Discord output, and mission tracking are all isolated per pilot.

---

## Notes

- **Display outputs:** two simultaneous game instances need screen real estate.
  A multi-monitor setup or a tiling window manager makes this considerably
  more manageable.
- **RAM:** two game instances under Proton are memory-hungry. 32 GB is
  comfortable; 16 GB is workable but tight depending on what else is running.
- **Proton prefix size:** each copied prefix can be up to several gigabytes. The symlink
  approach described in Step 1 reduces this if disk space is a concern.
- **Sleep timers:** the `sleep` values in the launch scripts are starting points.
  Adjust them based on how long your machine takes to reach the main menu from
  a cold launch.

---

*Fly dangerous, CMDR.*

---

*Guide by CMDR CALURSUS · [EDLD](https://github.com/drworman/EDLD)*

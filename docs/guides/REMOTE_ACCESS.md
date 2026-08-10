# Remote Access — EDLD on a Second Machine

This guide explains how to run EDLD's dashboard on a secondary machine
(e.g. a laptop) while the game runs on your main machine. The game machine handles
all monitoring, Discord notifications, and session control logic. The secondary machine
connects as a read-only dashboard front-end.

---

## How it works

- **Game machine** — runs EDLD in terminal mode with your normal profile. Discord
  webhooks, kill tracking, and all alerts operate as usual.
- **Secondary machine** — mounts the game machine's journal directory over SSH,
  then runs a local EDLD instance (the dashboard) using the `[REMOTE]` profile.
  Discord is disabled on this instance to avoid duplicate notifications.

Both instances read the same journal files simultaneously. EDLD never writes to
journals, so two readers on the same files is safe.

---

## Prerequisites

On both machines:

- EDLD installed and working
- Python 3.11+
- SSH client (`openssh`)

On the secondary machine only:

- `sshfs` — for mounting the remote journal directory

Install sshfs if needed:

```bash
# Arch
sudo pacman -S sshfs

# Debian / Ubuntu
sudo apt install sshfs

# Fedora
sudo dnf install fuse-sshfs
```

---

## Step 1 — Set up passwordless SSH

You need to be able to SSH from your secondary machine to your game machine
without a password prompt. If you already have this working, skip to Step 2.

**On the secondary machine**, generate an SSH key if you don't have one:

```bash
ssh-keygen -t ed25519 -C "edld-remote"
# Accept the default path (~/.ssh/id_ed25519)
# Leave the passphrase empty for passwordless operation
```

**Copy the public key to the game machine:**

```bash
ssh-copy-id username@gamestation
```

**Test it:**

```bash
ssh username@gamestation echo "OK"
# Should print OK with no password prompt
```

---

## Step 2 — Optional: WAN access with DuckDNS

If you want to connect from outside your local network, you need a stable
hostname that points to your game machine's public IP. DuckDNS provides this
for free.

**Create a DuckDNS account and subdomain:**

1. Go to [duckdns.org](https://www.duckdns.org) and sign in
2. Create a subdomain — e.g. `gamestation.duckdns.org`
3. Note your token from the account page

**Install the auto-update client on the game machine** so DuckDNS always has
your current IP. Create a script at `~/duckdns/duck.sh`:

```bash
mkdir -p ~/duckdns
cat > ~/duckdns/duck.sh << 'EOF'
echo url="https://www.duckdns.org/update?domains=YOURSUBDOMAIN&token=YOURTOKEN&ip=" \
  | curl -k -o ~/duckdns/duck.log -K -
EOF
chmod +x ~/duckdns/duck.sh
```

**Run it on a schedule** with a systemd timer or cron:

```bash
# Cron — update every 5 minutes
crontab -e
# Add:
*/5 * * * * ~/duckdns/duck.sh >/dev/null 2>&1
```

**Forward SSH port on your router:**
Your router needs to forward port 22 (or a custom port) to your game machine's
local IP. This varies by router — consult your router's manual. Once done, test:

```bash
ssh username@gamestation.duckdns.org echo "OK"
```

**Optional — use a custom port for WAN SSH** (recommended for security):
Add to `~/.ssh/config` on the secondary machine:

```
Host gamestation.duckdns.org
    Port 2222
    User username
```

---

## Step 3 — Configure EDLD

**On the game machine**, ensure your normal profile (`[EDP1]` or similar) is set
up in `config.toml` with your journal folder and Discord webhook.

**On both machines**, add the `[REMOTE]` profile to `config.toml`. Since both
machines share the same config file (e.g. via sync), this only needs to be done
once. The `[REMOTE]` profile is already included in `example.config.toml` as a
starting point.

The key line to set is the journal mount point on the secondary machine:

```toml
[REMOTE]
Settings.JournalFolder = "/home/username/mnt/ed-journals"
```

Replace `username` with your actual username. Leave everything else as-is — the
profile disables Discord and sets all log levels to local-only automatically.

`config.toml` lives in the EDLD user data directory:

```
~/.local/share/EDLD/config.toml
```

`~/.config/EDLD` is a symlink to the same directory.

---

## Step 4 — The launcher script

The included `edld_launch.sh` script detects which machine it is running on,
handles the sshfs mount, starts EDLD on the game machine if needed, and launches
the correct local instance automatically.

**Configure the script** — edit the variables at the top:

```bash
DESKTOP_SHORT="gamestation"           # short hostname of the game machine
LAPTOP_SHORT="laptop"                 # short hostname of the secondary machine

DESKTOP_LAN="gamestation.local.net"   # LAN hostname / IP for game machine
DESKTOP_WAN="gamestation.duckdns.org" # WAN hostname (DuckDNS or similar)

JOURNAL_REMOTE="${HOME}/games/ED-Logs/EDP1"  # journal path on game machine
MOUNT_LOCAL="${HOME}/mnt/ed-journals"         # where to mount it locally

EDLD_DIR="$HOME/.local/bin/EDLD"  # path to your EDLD installation
```

`config.toml` does not need to be referenced in the script — EDLD finds it
automatically in `~/.local/share/EDLD/config.toml` on both machines (since your
home directory is synced, both machines share the same config file).

Set `DESKTOP_SHORT` and `LAPTOP_SHORT` to match what `hostname -s` returns on
each machine. If you are not using WAN access, you can set `DESKTOP_WAN` to the
same value as `DESKTOP_LAN` — the script will simply try the same host twice,
which is harmless.

**Make it executable and create the mount point:**

```bash
chmod +x edld_launch.sh
mkdir -p ~/mnt/ed-journals
```

**Run it:**

```bash
./edld_launch.sh
```

The script will:

1. Detect which machine it is on by hostname
2. **Game machine** — launch EDLD using your normal profile
3. **Secondary machine**:
   - Probe LAN first, fall back to WAN if unreachable
   - Mount the journal directory via sshfs if not already mounted
   - Start EDLD on the game machine in terminal mode if it is not already running
   - Launch the local dashboard using the `[REMOTE]` profile

---

## Step 5 — Test the connection

**LAN test** (both machines on the same network):

```bash
# On the secondary machine
ssh gamestation.local.net echo "SSH OK"
sshfs gamestation.local.net:/home/username/games/ED-Logs/EDP1 ~/mnt/ed-journals
ls ~/mnt/ed-journals   # should show journal files
fusermount -u ~/mnt/ed-journals
```

**WAN test** (secondary machine on a different network — use a phone hotspot):

```bash
ssh gamestation.duckdns.org echo "SSH OK"
```

**Full launch test:**

```bash
./edld_launch.sh
# Watch the output — it will report each step
```

---

## Troubleshooting

**`hostname -s` returns something unexpected**
Check with `hostname -s` on each machine and update `DESKTOP_SHORT` /
`LAPTOP_SHORT` in the script to match exactly.

**sshfs mount succeeds but journal files are not visible**
Check `JOURNAL_REMOTE` in the script — it must be the absolute path to the
journal directory on the game machine. Verify with:

```bash
ssh gamestation ls ~/games/ED-Logs/EDP1
```

**Stale mount after network drop**
If the mount becomes unresponsive after a reconnect, unmount and remount:

```bash
fusermount -u ~/mnt/ed-journals
./edld_launch.sh
```

The `-o reconnect` sshfs option handles brief drops automatically, but a
prolonged disconnection may require a manual remount.

**EDLD starts on the secondary machine but shows no events**
Confirm the `[REMOTE]` profile's `JournalFolder` matches the mount point
exactly, and that journal files are visible at that path:

```bash
ls /home/username/mnt/ed-journals
```

**Discord notifications firing twice**
The `[REMOTE]` profile sets `Discord.WebhookURL = ""` which disables Discord
on the secondary instance. If you are seeing duplicates, check that the
secondary machine is using `-p REMOTE` and not your normal profile.

---

## Notes

- The `edld_launch.sh` script is safe to run repeatedly — the sshfs mount is
  idempotent and the remote EDLD check will skip startup if it is already running.
- The `~/mnt/ed-journals` directory is outside your home sync scope by default.
  If your home directory is synced between machines, ensure the mount point path
  is excluded from your sync configuration.
- The `[REMOTE]` profile's log levels are all set to `1` (local only). You can set
  any to `0` to suppress specific event types from the dashboard entirely.

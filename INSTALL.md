# EDLD Installation Guide

EDLD is a Python daemon for real-time Elite Dangerous session monitoring, running on Linux, Windows and macOS. It offers three interfaces over the same dashboard: a Textual terminal dashboard (`--tui`, the default), a PySide6 desktop window (`--gui`), and plain scrolling terminal output (`--terminal`).

Running from source is the norm on Linux. On Windows and macOS, download a prebuilt binary from the [Releases page](https://github.com/drworman/EDLD/releases) — no Python install needed — or follow the source instructions below if you prefer.

---

## Linux — Arch

Arch ships current versions of everything EDLD needs.

```bash
sudo pacman -S python-psutil
pip install discord-webhook cryptography textual --break-system-packages
```

```bash
git clone https://github.com/drworman/EDLD.git
cd EDLD
bash install.sh
nano ~/.local/share/EDLD/config.toml   # set JournalFolder at minimum

./edld.py                    # terminal dashboard (default)
./edld.py --gui              # desktop window
./edld.py --terminal         # plain scrolling output
```

---

## Linux — Debian / Ubuntu

```bash
sudo apt install python3-psutil
pip install discord-webhook cryptography textual --break-system-packages
```

```bash
git clone https://github.com/drworman/EDLD.git
cd EDLD
bash install.sh
nano ~/.local/share/EDLD/config.toml

./edld.py
./edld.py --gui
./edld.py --terminal
```

---

## Linux — Fedora

```bash
sudo dnf install python3-psutil
pip install discord-webhook cryptography textual --break-system-packages
```

---

## Windows and macOS

### Prebuilt binary (recommended)

Download the archive for your platform from the
[Releases page](https://github.com/drworman/EDLD/releases), extract it, and run
the executable. Everything is bundled — Python, Qt and all dependencies.

Verify the download first if you like; see [docs/SIGNING.md](docs/SIGNING.md).

The binary opens the desktop window by default. Run it from a shell with
`--tui` or `--terminal` for the terminal interfaces, or `--version` to confirm
which build you have.

Set `JournalFolder` in the config file on first run — the path is printed at
startup, and you can edit it from Preferences → General.

### From source

```bash
git clone https://github.com/drworman/EDLD.git
cd EDLD
pip install -r requirements.txt
python edld.py --gui
```

---

## The desktop interface

`--gui` needs **PySide6**. It is the largest dependency EDLD has (roughly
100 MB), so `install.sh` asks before installing it rather than assuming, and
the terminal interfaces work perfectly without it.

```bash
pip install PySide6 --break-system-packages
```

If PySide6 is missing, `--gui` exits with a message saying so; `--tui` and
`--terminal` are unaffected.

PySide6 is Qt for Python, under the LGPL v3. See
[docs/LICENSING.md](docs/LICENSING.md) for what that means for redistribution,
and [docs/BUILDING.md](docs/BUILDING.md) for how to build your own binaries.

On a minimal Linux install Qt also needs a few X libraries present at runtime:

```bash
sudo apt-get install -y libegl1 libxkbcommon-x11-0 libxcb-cursor0 \
  libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-randr0 \
  libxcb-render-util0 libxcb-xinerama0
```

---

## Config file location

```
~/.local/share/EDLD/config.toml
```

`~/.config/EDLD` is a symlink to the same directory. A repo-adjacent `config.toml` is accepted as a development fallback.

If no config file is found on startup, EDLD creates one with safe defaults and prints its location. Edit it to set `JournalFolder` before restarting.

---

## Dependencies

| Dependency | Purpose | Install method |
|------------|---------|----------------|
| `python-psutil` | Process utilities | Package manager |
| `discord-webhook` | Discord notifications | pip |
| `cryptography` | CAPI auth and secure transport | pip |
| `textual>=0.47` | Terminal dashboard (`--tui`) | pip |
| `PySide6>=6.6` | Desktop window (`--gui`) — optional | pip |

> **Do not install `psutil` via pip on Linux.** It has C extensions that require system libraries only available through the distro package manager.

---

## Verifying a Linux install

```bash
python3 -c "import psutil, discord_webhook, cryptography, textual; print('Core dependencies OK')"
python3 -c "import PySide6; print('Desktop interface OK')"   # only if you want --gui
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'psutil'`**
Install via package manager: `sudo pacman -S python-psutil` (Arch) · `sudo apt install python3-psutil` (Debian/Ubuntu) · `sudo dnf install python3-psutil` (Fedora).

**`ModuleNotFoundError: No module named 'discord_webhook'`**
Run `pip install discord-webhook --break-system-packages`.

**`ModuleNotFoundError: No module named 'textual'`**
Run `pip install textual --break-system-packages`.

**`PySide6 GUI import failed`**
Run `pip install PySide6 --break-system-packages`. The terminal interfaces do
not need it.

**The desktop window fails to start with an xcb plugin error**
Qt cannot find its X libraries. Install the `libxcb-*` packages listed under
[The desktop interface](#the-desktop-interface) above.

**sshfs for remote access**
`sudo pacman -S sshfs` (Arch) · `sudo apt install sshfs` (Debian/Ubuntu) · `sudo dnf install fuse-sshfs` (Fedora). See [docs/guides/REMOTE_ACCESS.md](docs/guides/REMOTE_ACCESS.md).

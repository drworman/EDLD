# EDLD Installation Guide

EDLD is a Python daemon for real-time Elite Dangerous session monitoring on Linux. Its interface is a Textual terminal dashboard, with a plain scrolling terminal output mode also available.

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

./edld.py                    # Textual TUI dashboard (default)
./edld.py --mode terminal    # plain terminal output
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
./edld.py --mode terminal
```

---

## Linux — Fedora

```bash
sudo dnf install python3-psutil
pip install discord-webhook cryptography textual --break-system-packages
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
| `textual>=0.47` | Textual TUI dashboard | pip |

> **Do not install `psutil` via pip on Linux.** It has C extensions that require system libraries only available through the distro package manager.

---

## Verifying a Linux install

```bash
python3 -c "import psutil, discord_webhook, cryptography, textual; print('All dependencies OK')"
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'psutil'`**
Install via package manager: `sudo pacman -S python-psutil` (Arch) · `sudo apt install python3-psutil` (Debian/Ubuntu) · `sudo dnf install python3-psutil` (Fedora).

**`ModuleNotFoundError: No module named 'discord_webhook'`**
Run `pip install discord-webhook --break-system-packages`.

**`ModuleNotFoundError: No module named 'textual'`**
Run `pip install textual --break-system-packages`.

**sshfs for remote access**
`sudo pacman -S sshfs` (Arch) · `sudo apt install sshfs` (Debian/Ubuntu) · `sudo dnf install fuse-sshfs` (Fedora). See [docs/guides/REMOTE_ACCESS.md](docs/guides/REMOTE_ACCESS.md).

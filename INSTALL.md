# EDLD Installation Guide

EDLD is a Python daemon for real-time Elite Dangerous session monitoring on Linux. It supports two UI modes: a GTK4 graphical interface and a Textual terminal UI.

---

## Linux — Arch

Arch ships current versions of everything EDLD needs.

```bash
sudo pacman -S python-psutil python-gobject gtk4
pip install discord-webhook cryptography --break-system-packages
```

```bash
git clone https://github.com/drworman/EDLD.git
cd EDLD
bash install.sh
nano ~/.local/share/EDLD/config.toml   # set JournalFolder at minimum

./edld.py                    # terminal output only
./edld.py --mode textual     # Textual TUI
./edld.py --mode gtk4        # GTK4 GUI
```

---

## Linux — Debian / Ubuntu

```bash
sudo apt install python3-psutil python3-gi gir1.2-gtk-4.0
pip install discord-webhook cryptography --break-system-packages
```

```bash
git clone https://github.com/drworman/EDLD.git
cd EDLD
bash install.sh
nano ~/.local/share/EDLD/config.toml

./edld.py
./edld.py --mode textual
./edld.py --mode gtk4
```

---

## Linux — Fedora

```bash
sudo dnf install python3-psutil python3-gobject gtk4
pip install discord-webhook cryptography --break-system-packages
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
| `python-gobject` + `gtk4` | GTK4 GUI | Package manager |
| `discord-webhook` | Discord notifications | pip |
| `cryptography` | CAPI auth and secure transport | pip |
| `textual>=0.47` | Textual TUI | pip (optional) |

> **Do not install `psutil` or `PyGObject` via pip on Linux.** They have C extensions that require system libraries only available through the distro package manager.

---

## Verifying a Linux install

```bash
python3 -c "import psutil, discord_webhook, cryptography; print('All dependencies OK')"
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'psutil'`**
Install via package manager: `sudo pacman -S python-psutil` (Arch) · `sudo apt install python3-psutil` (Debian/Ubuntu) · `sudo dnf install python3-psutil` (Fedora).

**`ModuleNotFoundError: No module named 'gi'`**
Install `python-gobject` (Arch) · `python3-gi` (Debian) · `python3-gobject` (Fedora), and GTK4 itself.

**`ModuleNotFoundError: No module named 'discord_webhook'`**
Run `pip install discord-webhook --break-system-packages`.

**`GLib.GError` or blank GTK4 window**
Ensure `adwaita-icon-theme` (or equivalent) is installed.

**sshfs for remote access**
`sudo pacman -S sshfs` (Arch) · `sudo apt install sshfs` (Debian/Ubuntu) · `sudo dnf install fuse-sshfs` (Fedora). See [docs/guides/REMOTE_ACCESS.md](docs/guides/REMOTE_ACCESS.md).

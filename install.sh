#!/usr/bin/env bash
# =============================================================================
# EDLD — install.sh
# Linux installer for ED Monitor Daemon
# https://github.com/drworman/EDLD
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MIN="3.11"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'
CYN='\033[0;36m'; WHT='\033[1;37m'; NC='\033[0m'

info()    { echo -e "${CYN}[EDLD]${NC} $*"; }
ok()      { echo -e "${GRN}[  OK  ]${NC} $*"; }
warn()    { echo -e "${YEL}[ WARN ]${NC} $*"; }
fail()    { echo -e "${RED}[ FAIL ]${NC} $*"; exit 1; }
section() { echo -e "\n${WHT}── $* ──${NC}"; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "${WHT}  ED Monitor Daemon — Linux Installer${NC}"
echo    "  https://github.com/drworman/EDLD"
echo

# ── Detect distro ─────────────────────────────────────────────────────────────
section "Detecting system"

DISTRO="unknown"
PKG_MGR="unknown"

if command -v pacman &>/dev/null; then
    DISTRO="arch"
    PKG_MGR="pacman"
    ok "Arch Linux / pacman"
elif command -v apt-get &>/dev/null; then
    DISTRO="debian"
    PKG_MGR="apt"
    ok "Debian / Ubuntu / apt"
elif command -v rpm-ostree &>/dev/null || [ -f /run/ostree-booted ]; then
    DISTRO="fedora-ostree"
    PKG_MGR="rpm-ostree"
    ok "Fedora Silverblue / Bazzite / rpm-ostree"
elif command -v dnf &>/dev/null; then
    DISTRO="fedora"
    PKG_MGR="dnf"
    ok "Fedora / RHEL / dnf"
elif command -v zypper &>/dev/null; then
    DISTRO="suse"
    PKG_MGR="zypper"
    ok "openSUSE / zypper"
else
    warn "Unknown distro — will attempt pip install for all packages"
    DISTRO="unknown"
fi

# ── Python check ──────────────────────────────────────────────────────────────
section "Checking Python"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 11 ]; then
            PYTHON="$cmd"
            ok "Found $cmd $VER"
            break
        else
            warn "Found $cmd $VER — too old (need $PYTHON_MIN+)"
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python $PYTHON_MIN+ not found. Install it for your distro then re-run this script."
fi

# ── Install system packages ────────────────────────────────────────────────────
section "Installing system packages"

GUI_AVAILABLE=false

case "$DISTRO" in
    arch)
        info "Installing via pacman..."
        sudo pacman -S --needed --noconfirm python-psutil python-gobject gtk4
        GUI_AVAILABLE=true
        ok "python-psutil, python-gobject, gtk4 installed"
        ;;
    debian)
        info "Installing via apt..."
        sudo apt-get update -qq
        sudo apt-get install -y python3-psutil python3-gi python3-gi-cairo \
            gir1.2-gtk-4.0 libgtk-4-dev
        GUI_AVAILABLE=true
        ok "python3-psutil, python3-gi (GTK4 bindings) installed"
        ;;
    fedora-ostree)
        info "Installing via rpm-ostree (immutable base layer)..."
        info "This will stage packages for install — a reboot may be required."
        # rpm-ostree install exits 0 if all packages are already layered,
        # so no special already-installed handling is needed.
        rpm-ostree install --idempotent -y python3-psutil python3-gobject gtk4 ||
            warn "rpm-ostree install encountered an issue — check the output above"
        GUI_AVAILABLE=true
        ok "python3-psutil, python3-gobject, gtk4 staged via rpm-ostree"
        warn "You may need to reboot for the layered packages to take effect."
        ;;
    fedora)
        info "Installing via dnf..."
        sudo dnf install -y python3-psutil python3-gobject gtk4
        GUI_AVAILABLE=true
        ok "python3-psutil, python3-gobject, gtk4 installed"
        ;;
    suse)
        info "Installing via zypper..."
        sudo zypper install -y python3-psutil python3-gobject typelib-1_0-Gtk-4_0
        GUI_AVAILABLE=true
        ok "python3-psutil, python3-gobject installed"
        ;;
    *)
        warn "Could not install system packages automatically."
        warn "Install psutil and PyGObject via your package manager, then re-run."
        warn "See INSTALL.md for distro-specific instructions."
        ;;
esac

# ── Install pip packages ───────────────────────────────────────────────────────
section "Installing pip packages"

# These packages are not in most distro repos — install via pip.
# We check if they are already importable first so we never error
# on "already satisfied" — which some pip versions treat as success
# but external-package guards can still block.
for PKG in "discord-webhook>=1.3.0:discord_webhook" "cryptography>=41.0.0:cryptography" "textual>=0.47.0:textual"; do
    PKG_SPEC="${PKG%%:*}"   # e.g. "discord-webhook>=1.3.0"
    PKG_IMPORT="${PKG##*:}" # e.g. "discord_webhook"
    PKG_NAME="${PKG_SPEC%%[>=]*}"
    # If already importable, skip silently
    if $PYTHON -c "import ${PKG_IMPORT}" &>/dev/null 2>&1; then
        ok "${PKG_NAME} already installed"
        continue
    fi
    info "Installing ${PKG_NAME}..."
    if $PYTHON -m pip install "$PKG_SPEC" --quiet 2>/dev/null; then
        ok "${PKG_NAME} installed"
    elif $PYTHON -m pip install "$PKG_SPEC" --break-system-packages --quiet 2>/dev/null; then
        ok "${PKG_NAME} installed (--break-system-packages)"
    else
        warn "Could not install ${PKG_NAME} automatically."
        warn "Run manually: pip install ${PKG_NAME} --break-system-packages"
    fi
done

# ── Config setup ──────────────────────────────────────────────────────────────
section "Configuration"

# Resolve user data directory (mirrors _user_data_dir() in edld.py)
XDG_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
EDLD_DATA_DIR="$XDG_DATA/EDLD"
mkdir -p "$EDLD_DATA_DIR"

# Create ~/.config/EDLD symlink for XDG hygiene if not already present
XDG_CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_LINK="$XDG_CFG/EDLD"
if [ ! -e "$CONFIG_LINK" ] && [ ! -L "$CONFIG_LINK" ]; then
    ln -s "$EDLD_DATA_DIR" "$CONFIG_LINK" 2>/dev/null &&         ok "Created symlink: $CONFIG_LINK → $EDLD_DATA_DIR" || true
fi

USER_CONFIG="$EDLD_DATA_DIR/config.toml"
EXAMPLE_CONFIG="$REPO_DIR/example.config.toml"

if [ -f "$USER_CONFIG" ]; then
    ok "config.toml already exists at $USER_CONFIG — leaving untouched"
elif [ -f "$EXAMPLE_CONFIG" ]; then
    cp "$EXAMPLE_CONFIG" "$USER_CONFIG"
    ok "Created config.toml at $USER_CONFIG"
    info "Edit $USER_CONFIG to set your journal folder and Discord webhook before running."
else
    warn "example.config.toml not found — config.toml was not created."
    warn "Copy example.config.toml to $USER_CONFIG manually before running EDLD."
fi

# ── Permissions ───────────────────────────────────────────────────────────────

chmod +x "$REPO_DIR/edld.py"
ok "edld.py is now executable"

# ── Summary ───────────────────────────────────────────────────────────────────
section "Installation complete"

echo
echo -e "  ${GRN}EDLD is ready to run.${NC}"
echo
echo -e "  ${WHT}Terminal mode:${NC}"
echo -e "    ./edld.py"
echo

if [ "$GUI_AVAILABLE" = true ]; then
    echo -e "  ${WHT}GUI mode:${NC}"
    echo -e "    ./edld.py --gui"
    echo
else
    warn "GUI mode unavailable — PyGObject was not installed."
    warn "See INSTALL.md for manual GTK4 setup instructions."
    echo
fi

echo -e "  ${WHT}With a config profile:${NC}"
echo -e "    ./edld.py -p YourProfileName"
echo
echo -e "  ${CYN}Edit $XDG_DATA/EDLD/config.toml to set your journal folder path before running.${NC}"
echo -e "  ${CYN}See INSTALL.md and README.md for full documentation.${NC}"
echo

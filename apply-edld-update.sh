#!/usr/bin/env bash
# =============================================================================
# apply-edld-update.sh
#
# Copies the ED Live Dashboard update payload into your project directory,
# clobbering existing files, and removes any paths this update obsoletes.
#
# Usage:
#     ./apply-edld-update.sh <payload-dir> [target-dir]
#
#     <payload-dir>   directory you extracted the archive into — the one that
#                     contains edld.py, core/, gui/ and so on
#     [target-dir]    defaults to ~/projects/EDLD
#
# Examples:
#     mkdir -p /tmp/edld-update
#     tar xzf EDLD-live-dashboard-20260810.tar.gz -C /tmp/edld-update
#     ./apply-edld-update.sh /tmp/edld-update
#
#     ./apply-edld-update.sh /tmp/edld-update ~/src/EDLD    # different target
#     DRY_RUN=1 ./apply-edld-update.sh /tmp/edld-update     # show, don't touch
#
# The script refuses to run against a directory that does not look like an
# EDLD checkout, takes a timestamped backup of every file it overwrites, and
# does nothing at all under DRY_RUN=1.
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YEL='\033[0;33m'; GRN='\033[0;32m'
CYN='\033[0;36m'; WHT='\033[1;37m'; NC='\033[0m'

info()    { echo -e "${CYN}[EDLD]${NC} $*"; }
ok()      { echo -e "${GRN}[  OK  ]${NC} $*"; }
warn()    { echo -e "${YEL}[ WARN ]${NC} $*"; }
fail()    { echo -e "${RED}[ FAIL ]${NC} $*" >&2; exit 1; }
section() { echo -e "\n${WHT}── $* ──${NC}"; }

DRY_RUN="${DRY_RUN:-0}"

# ── Arguments ─────────────────────────────────────────────────────────────────

if [ $# -lt 1 ]; then
    fail "Usage: $0 <payload-dir> [target-dir]   (default target: ~/projects/EDLD)"
fi

PAYLOAD="$(cd "$1" 2>/dev/null && pwd)" || fail "Payload directory not found: $1"
TARGET_RAW="${2:-$HOME/projects/EDLD}"

# ── Obsoleted paths ───────────────────────────────────────────────────────────
#
# Files and directories this update removes from the project.  This update
# adds and modifies only — nothing was renamed away or deleted — so the list
# is empty.  It is kept in place because a future update that does retire a
# path needs somewhere to declare it, and a silently-skipped cleanup step is
# worse than an obviously empty one.
#
# Paths are relative to the target directory.  Both files and directories are
# accepted.
OBSOLETE=(
    # "core/old_module.py"
    # "tui/legacy/"
)

# ── Sanity checks ─────────────────────────────────────────────────────────────

section "Checking payload"

FILE_COUNT="$(find "$PAYLOAD" -type f ! -name '.DS_Store' | wc -l | tr -d ' ')"
[ "$FILE_COUNT" -gt 0 ] || fail "Payload directory is empty: $PAYLOAD"

# A payload may be the full update or a targeted patch touching only a few
# files, so requiring any particular file would reject the latter. Instead the
# payload has to contain at least one path EDLD recognises — enough to catch a
# wrong directory, without assuming how much of the tree an update covers.
RECOGNISED=0
for known in edld.py core gui tui components packaging docs licenses scripts \
             themes data images .github install.sh requirements.txt \
             requirements-dev.txt README.md INSTALL.md CHANGELOG.md LICENSE \
             .gitignore THIRD-PARTY-NOTICES.md example.config.toml; do
    [ -e "$PAYLOAD/$known" ] && RECOGNISED=1 && break
done
[ "$RECOGNISED" -eq 1 ] || \
    fail "Nothing in $PAYLOAD looks like part of EDLD — is that the extracted archive?"

ok "Payload looks right: $FILE_COUNT files in $PAYLOAD"

section "Checking target"

if [ ! -d "$TARGET_RAW" ]; then
    fail "Target directory does not exist: $TARGET_RAW"
fi
TARGET="$(cd "$TARGET_RAW" && pwd)"

# Refuse to write into something that is not an EDLD checkout.  A typo in the
# target argument should not scatter 57 files across an unrelated directory.
if [ ! -f "$TARGET/edld.py" ] || [ ! -d "$TARGET/core" ]; then
    fail "$TARGET does not look like an EDLD checkout (no edld.py / core/). Refusing."
fi

if [ "$PAYLOAD" = "$TARGET" ]; then
    fail "Payload and target are the same directory. Refusing."
fi
ok "Target: $TARGET"

if [ "$DRY_RUN" = "1" ]; then
    warn "DRY_RUN=1 — nothing will be written."
fi

# ── Backup ────────────────────────────────────────────────────────────────────

section "Backing up files that will be overwritten"

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$TARGET/.edld-backup-$STAMP"
BACKED_UP=0

while IFS= read -r -d '' src; do
    rel="${src#$PAYLOAD/}"
    dst="$TARGET/$rel"
    if [ -f "$dst" ]; then
        if [ "$DRY_RUN" != "1" ]; then
            mkdir -p "$BACKUP/$(dirname "$rel")"
            cp -p "$dst" "$BACKUP/$rel"
        fi
        BACKED_UP=$((BACKED_UP + 1))
    fi
done < <(find "$PAYLOAD" -type f ! -name '.DS_Store' -print0)

if [ "$BACKED_UP" -gt 0 ]; then
    ok "$BACKED_UP existing file(s) backed up to $BACKUP"
else
    info "No existing files would be overwritten — nothing to back up."
fi

# ── Copy ──────────────────────────────────────────────────────────────────────

section "Copying files"

COPIED=0
while IFS= read -r -d '' src; do
    rel="${src#$PAYLOAD/}"
    dst="$TARGET/$rel"
    if [ "$DRY_RUN" = "1" ]; then
        echo "  would copy  $rel"
    else
        mkdir -p "$(dirname "$dst")"
        cp -p "$src" "$dst"
    fi
    COPIED=$((COPIED + 1))
done < <(find "$PAYLOAD" -type f ! -name '.DS_Store' -print0)

ok "$COPIED file(s) copied into $TARGET"

# Executables.  cp -p preserves the payload's modes, but the archive may have
# travelled through a filesystem that does not, so these are set explicitly.
if [ "$DRY_RUN" != "1" ]; then
    chmod +x "$TARGET/edld.py" 2>/dev/null || true
    chmod +x "$TARGET/install.sh" 2>/dev/null || true
    ok "edld.py and install.sh marked executable"
fi

# ── Remove obsoleted paths ────────────────────────────────────────────────────

section "Removing obsoleted paths"

REMOVED=0
if [ ${#OBSOLETE[@]} -eq 0 ]; then
    info "This update obsoletes nothing — no paths to remove."
else
    for rel in "${OBSOLETE[@]}"; do
        path="$TARGET/$rel"
        if [ -e "$path" ]; then
            if [ "$DRY_RUN" = "1" ]; then
                echo "  would remove  $rel"
            else
                mkdir -p "$BACKUP/$(dirname "$rel")"
                cp -a "$path" "$BACKUP/$rel"
                rm -rf "$path"
                ok "Removed $rel (backed up)"
            fi
            REMOVED=$((REMOVED + 1))
        fi
    done
    [ "$REMOVED" -eq 0 ] && info "None of the obsoleted paths were present."
fi

# ── Stale bytecode ────────────────────────────────────────────────────────────
# A __pycache__ entry for a module that moved can shadow the new one.  Cheap to
# clear, annoying to diagnose.

if [ "$DRY_RUN" != "1" ]; then
    find "$TARGET" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    ok "Cleared __pycache__ directories"
fi

# ── Summary ───────────────────────────────────────────────────────────────────

section "Done"

if [ "$DRY_RUN" = "1" ]; then
    echo
    echo -e "  ${YEL}Dry run — nothing was written.${NC}"
    echo -e "  Re-run without DRY_RUN=1 to apply."
    echo
    exit 0
fi

echo
echo -e "  ${GRN}Update applied to $TARGET${NC}"
echo -e "  Backup of replaced files: ${WHT}$BACKUP${NC}"
echo
echo -e "  ${WHT}Verify:${NC}"
echo -e "    cd $TARGET && ./edld.py --version"
echo
echo -e "  ${WHT}Run:${NC}"
echo -e "    ./edld.py              ${CYN}# terminal dashboard (default)${NC}"
echo -e "    ./edld.py --gui        ${CYN}# desktop window${NC}"
echo -e "    ./edld.py --terminal   ${CYN}# plain scrolling output${NC}"
echo
echo -e "  ${WHT}The desktop interface needs PySide6:${NC}"
echo -e "    pip install PySide6 --break-system-packages"
echo
echo -e "  ${CYN}To roll back:${NC}"
echo -e "    cp -a $BACKUP/. $TARGET/"
echo

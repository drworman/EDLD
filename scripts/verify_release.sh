#!/usr/bin/env bash
# scripts/verify_release.sh — verify an EDLD release artifact
#
# Usage:
#   bash verify_release.sh EDLD-20260409.tar.gz
#
# Checks:
#   1. SHA-256 checksum matches the published .sha256 file
#   2. Detached SSH signature (.sig) is valid against signing_key.pub
#
# SIGNING_IDENTITY below must match the SIGNING_IDENTITY secret used when
# the artifact was signed in GitHub Actions. Update it if that value changes.
#
# Requirements: ssh-keygen (OpenSSH 8.0+), sha256sum

set -euo pipefail

# Must match the SIGNING_IDENTITY GitHub Actions secret
SIGNING_IDENTITY="david@worman.com"
SIGNING_NS="edld.release"

# ── Argument handling ─────────────────────────────────────────────────────────

if [ $# -ne 1 ]; then
    echo "Usage: $0 <artifact>"
    echo "Example: $0 EDLD-20260409.tar.gz"
    exit 1
fi

ARTIFACT="$(realpath "$1")"
ARTIFACT_DIR="$(dirname "$ARTIFACT")"
ARTIFACT_NAME="$(basename "$ARTIFACT")"

if [ ! -f "$ARTIFACT" ]; then
    echo "ERROR: artifact not found: $ARTIFACT"
    exit 1
fi

# ── Locate supporting files ───────────────────────────────────────────────────

SIG_FILE="${ARTIFACT}.sig"
SHA_FILE="${ARTIFACT_DIR}/${ARTIFACT_NAME%.tar.gz}.sha256"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${ARTIFACT_DIR}/signing_key.pub" ]; then
    PUB_KEY="${ARTIFACT_DIR}/signing_key.pub"
elif [ -f "${SCRIPT_DIR}/../signing_key.pub" ]; then
    PUB_KEY="$(realpath "${SCRIPT_DIR}/../signing_key.pub")"
else
    echo "ERROR: signing_key.pub not found."
    echo "Download it from: https://github.com/drworman/EDLD/raw/main/signing_key.pub"
    exit 1
fi

if [ ! -f "$SIG_FILE" ]; then
    echo "ERROR: signature file not found: $SIG_FILE"
    echo "Download it alongside the artifact from the GitHub release page."
    exit 1
fi

FAIL=0

# ── Step 1: SHA-256 checksum ─────────────────────────────────────────────────

echo ""
echo "[ 1/2 ] Verifying SHA-256 checksum..."

if [ -f "$SHA_FILE" ]; then
    EXPECTED=$(grep "$ARTIFACT_NAME" "$SHA_FILE" | awk '{print $1}')
    ACTUAL=$(sha256sum "$ARTIFACT" | awk '{print $1}')
    if [ "$EXPECTED" = "$ACTUAL" ]; then
        echo "        OK: $ACTUAL"
    else
        echo "        MISMATCH"
        echo "        expected: $EXPECTED"
        echo "        actual:   $ACTUAL"
        FAIL=1
    fi
else
    echo "        .sha256 file not found — skipping"
    echo "        (download EDLD-*.sha256 from the release page to enable this check)"
fi

# ── Step 2: SSH signature ─────────────────────────────────────────────────────

echo ""
echo "[ 2/2 ] Verifying SSH signature..."
echo "        Key:       $PUB_KEY"
echo "        Sig:       $SIG_FILE"
echo "        Identity:  $SIGNING_IDENTITY"

ALLOWED=$(mktemp)
echo "$SIGNING_IDENTITY namespaces=\"$SIGNING_NS\" $(cat "$PUB_KEY")" > "$ALLOWED"

if ssh-keygen -Y verify \
    -f "$ALLOWED" \
    -I "$SIGNING_IDENTITY" \
    -n "$SIGNING_NS" \
    -s "$SIG_FILE" \
    < "$ARTIFACT" 2>/dev/null; then
    echo "        OK"
else
    echo "        INVALID"
    FAIL=1
fi

rm -f "$ALLOWED"

# ── Result ────────────────────────────────────────────────────────────────────

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "VERIFIED: $ARTIFACT_NAME is authentic and unmodified."
    exit 0
else
    echo "FAILED: $ARTIFACT_NAME could not be verified. Do not use this file."
    exit 1
fi

#!/usr/bin/env bash
# scripts/verify_release.sh — verify an EDLD release artifact
#
# Usage:
#   bash verify_release.sh EDLD-20260830-linux-x86_64.tar.gz
#   bash verify_release.sh                       # verify everything present
#
# A release ships one signed manifest rather than a signature per file:
#
#   EDLD-<version>.sha256       lists every artefact by SHA-256 digest
#   EDLD-<version>.sha256.sig   detached SSH signature over that list
#
# So verification is two steps, and one signature check covers the whole
# release:
#
#   1. The manifest's signature is valid for signing_key.pub.
#   2. The artifact's digest matches its line in that manifest.
#
# Step 2 without step 1 proves only that the file matches an unauthenticated
# list, so a failure in step 1 is fatal and never skipped.
#
# SIGNING_IDENTITY below must match the SIGNING_IDENTITY secret used when the
# manifest was signed in GitHub Actions. Update it if that value changes.
#
# Requirements: ssh-keygen (OpenSSH 8.0+), sha256sum

set -euo pipefail

# Must match the SIGNING_IDENTITY GitHub Actions secret
SIGNING_IDENTITY="david@worman.com"
SIGNING_NS="edld.release"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Argument handling ─────────────────────────────────────────────────────────

if [ $# -gt 1 ]; then
    echo "Usage: $0 [artifact]"
    echo "Example: $0 EDLD-20260830-linux-x86_64.tar.gz"
    echo "With no argument, every artifact listed in the manifest is checked."
    exit 1
fi

if [ $# -eq 1 ]; then
    ARTIFACT="$(realpath "$1")"
    if [ ! -f "$ARTIFACT" ]; then
        echo "ERROR: artifact not found: $ARTIFACT"
        exit 1
    fi
    WORK_DIR="$(dirname "$ARTIFACT")"
    ARTIFACT_NAME="$(basename "$ARTIFACT")"
else
    WORK_DIR="$PWD"
    ARTIFACT_NAME=""
fi

# ── Locate supporting files ───────────────────────────────────────────────────

# The manifest is named for the version, which is not derivable from a platform
# archive's filename, so it is found by glob rather than by transformation.
shopt -s nullglob
MANIFESTS=("$WORK_DIR"/EDLD-*.sha256)
shopt -u nullglob

if [ "${#MANIFESTS[@]}" -eq 0 ]; then
    echo "ERROR: no EDLD-*.sha256 manifest found in ${WORK_DIR}."
    echo "Download it, and EDLD-<version>.sha256.sig, from the release page."
    exit 1
elif [ "${#MANIFESTS[@]}" -gt 1 ]; then
    echo "ERROR: more than one EDLD-*.sha256 in ${WORK_DIR}:"
    printf '        %s\n' "${MANIFESTS[@]##*/}"
    echo "Verify one release at a time."
    exit 1
fi

MANIFEST="${MANIFESTS[0]}"
MANIFEST_NAME="$(basename "$MANIFEST")"
SIG_FILE="${MANIFEST}.sig"

if [ ! -f "$SIG_FILE" ]; then
    echo "ERROR: manifest signature not found: $(basename "$SIG_FILE")"
    echo "Download it alongside ${MANIFEST_NAME} from the GitHub release page."
    exit 1
fi

if [ -f "${WORK_DIR}/signing_key.pub" ]; then
    PUB_KEY="${WORK_DIR}/signing_key.pub"
elif [ -f "${SCRIPT_DIR}/../signing_key.pub" ]; then
    PUB_KEY="$(realpath "${SCRIPT_DIR}/../signing_key.pub")"
else
    echo "ERROR: signing_key.pub not found."
    echo "Download it from: https://github.com/drworman/EDLD/raw/main/signing_key.pub"
    exit 1
fi

# ── Step 1: signature over the manifest ───────────────────────────────────────

echo ""
echo "[ 1/2 ] Verifying the signature on ${MANIFEST_NAME}..."
echo "        Key:       $PUB_KEY"
echo "        Identity:  $SIGNING_IDENTITY"

ALLOWED=$(mktemp)
trap 'rm -f "$ALLOWED"' EXIT
echo "$SIGNING_IDENTITY namespaces=\"$SIGNING_NS\" $(cat "$PUB_KEY")" > "$ALLOWED"

if ssh-keygen -Y verify \
    -f "$ALLOWED" \
    -I "$SIGNING_IDENTITY" \
    -n "$SIGNING_NS" \
    -s "$SIG_FILE" \
    < "$MANIFEST" 2>/dev/null; then
    echo "        OK — the checksum list is authentic."
else
    echo "        INVALID"
    echo ""
    echo "FAILED: ${MANIFEST_NAME} is not signed by the EDLD release key."
    echo "        Every checksum in it is untrustworthy. Do not use these files."
    exit 1
fi

# ── Step 2: digests ───────────────────────────────────────────────────────────

echo ""
FAIL=0

if [ -n "$ARTIFACT_NAME" ]; then
    echo "[ 2/2 ] Verifying the SHA-256 of ${ARTIFACT_NAME}..."

    EXPECTED="$(awk -v n="$ARTIFACT_NAME" '$2 == n || $2 == "*" n {print $1}' "$MANIFEST")"
    if [ -z "$EXPECTED" ]; then
        echo "        NOT LISTED in ${MANIFEST_NAME}"
        echo "        This file is not part of that release."
        FAIL=1
    else
        ACTUAL="$(sha256sum "$ARTIFACT" | awk '{print $1}')"
        if [ "$EXPECTED" = "$ACTUAL" ]; then
            echo "        OK: $ACTUAL"
        else
            echo "        MISMATCH"
            echo "        expected: $EXPECTED"
            echo "        actual:   $ACTUAL"
            FAIL=1
        fi
    fi
else
    echo "[ 2/2 ] Verifying every artifact present in ${WORK_DIR}..."
    CHECKED=0
    while read -r expected name; do
        name="${name#\*}"
        if [ ! -f "${WORK_DIR}/${name}" ]; then
            echo "        skipped (not downloaded): $name"
            continue
        fi
        actual="$(sha256sum "${WORK_DIR}/${name}" | awk '{print $1}')"
        if [ "$expected" = "$actual" ]; then
            echo "        OK:       $name"
        else
            echo "        MISMATCH: $name"
            FAIL=1
        fi
        CHECKED=$((CHECKED + 1))
    done < "$MANIFEST"

    if [ "$CHECKED" -eq 0 ]; then
        echo ""
        echo "ERROR: none of the files in ${MANIFEST_NAME} are in ${WORK_DIR}."
        echo "Run this from the directory holding the downloads."
        exit 1
    fi
fi

# ── Result ────────────────────────────────────────────────────────────────────

echo ""
if [ "$FAIL" -eq 0 ]; then
    if [ -n "$ARTIFACT_NAME" ]; then
        echo "VERIFIED: $ARTIFACT_NAME is authentic and unmodified."
    else
        echo "VERIFIED: all downloaded artifacts are authentic and unmodified."
    fi
    exit 0
else
    echo "FAILED: verification did not pass. Do not use these files."
    exit 1
fi

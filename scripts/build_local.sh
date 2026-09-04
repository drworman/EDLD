#!/usr/bin/env bash
#
# scripts/build_local.sh — build, smoke-test and package an EDLD binary the
# same way the Release workflow does, on this machine.
#
# The point is that a local build and a CI build are the same build.  Every
# step here mirrors a step in .github/workflows/release.yml: the same preflight
# on the checkout, the same `pyinstaller packaging/edld.spec --noconfirm
# --clean`, the same --version and --selftest smoke tests, the same archive
# layout with the licence texts LGPLv3 4(b) requires, and the same SHA-256
# file.  If this passes and CI does not, the difference is the runner, not the
# tree — which is the whole reason to be able to run it here.
#
# PyInstaller does not cross-compile: this builds for the platform it runs on.
# Linux and macOS run it directly; on Windows use Git Bash or MSYS2.
#
# Usage:
#   scripts/build_local.sh                 build, test, package
#   scripts/build_local.sh --no-package    build and test only
#   scripts/build_local.sh --skip-tests    build and package, no smoke test
#   scripts/build_local.sh --dir           directory layout instead of onefile
#   scripts/build_local.sh --sign          also sign with SIGNING_KEY
#
set -euo pipefail

# Resolved before the cd below, so --help still finds this file when the
# script is invoked by a relative path from somewhere else.
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PACKAGE=1
RUN_TESTS=1
ONEDIR=0
SIGN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --no-package) PACKAGE=0 ;;
    --skip-tests) RUN_TESTS=0 ;;
    --dir)        ONEDIR=1; PACKAGE=0 ;;
    --sign)       SIGN=1 ;;
    -h|--help)    awk 'NR>1 && /^#/ { sub(/^#[[:space:]]?/, ""); print; next }
                       NR>1 { exit }' "$SELF"; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\n\033[96m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── Platform ─────────────────────────────────────────────────────────────────
case "$(uname -s)" in
  Linux)                      OS=linux;   PLATFORM="linux-$(uname -m)" ;;
  Darwin)                     OS=macos
                              case "$(uname -m)" in
                                arm64) PLATFORM="macos-arm64" ;;
                                *)     PLATFORM="macos-x86_64" ;;
                              esac ;;
  MINGW*|MSYS*|CYGWIN*)       OS=windows; PLATFORM="windows-x86_64" ;;
  *) die "Unsupported platform: $(uname -s)" ;;
esac

VERSION="$(tr -d '[:space:]' < version)"
say "EDLD ${VERSION} — ${PLATFORM}"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
command -v "$PY" >/dev/null 2>&1 || die "No python3 on PATH. Set PYTHON=/path/to/python."
echo "python:      $("$PY" --version 2>&1)  ($(command -v "$PY"))"

# ── Preflight: the same paths the workflow's verify job checks ───────────────
# packaging/edld.spec has been lost to .gitignore once already, and the failure
# it produces three steps later says nothing about the cause.
say "Preflight"
MISSING=0
for path in packaging/edld.spec packaging/build_common.py packaging/icons \
            licenses THIRD-PARTY-NOTICES.md requirements.txt \
            requirements-dev.txt gui components core tui edld.py version; do
  [ -e "$path" ] || { echo "  missing: $path"; MISSING=1; }
done
[ "$MISSING" -eq 0 ] || die "Checkout is incomplete. Check .gitignore is not excluding these."

# Untracked-but-required is the specific trap: the file is here, so the build
# works locally and fails in CI. Warn early rather than let CI find it.
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  for path in packaging/edld.spec packaging/build_common.py; do
    if git check-ignore -q "$path" 2>/dev/null; then
      warn "$path is git-ignored — it will be missing from a CI checkout."
    fi
  done
fi
echo "  all required paths present"

# ── Build tooling ────────────────────────────────────────────────────────────
"$PY" - <<'EOF' || die "Build dependencies missing. Run: pip install -r requirements-dev.txt"
import importlib.util, sys
missing = [m for m in ("PyInstaller", "PySide6", "textual", "psutil", "certifi")
           if importlib.util.find_spec(m) is None]
if missing:
    print("  missing modules: " + ", ".join(missing), file=sys.stderr)
    sys.exit(1)
print("  build dependencies present")
EOF

# ── Build ────────────────────────────────────────────────────────────────────
say "Building"
rm -rf build dist
if [ "$ONEDIR" -eq 1 ]; then
  "$PY" -m PyInstaller packaging/edld.spec --noconfirm --clean -D
else
  "$PY" -m PyInstaller packaging/edld.spec --noconfirm --clean
fi

case "$OS" in
  windows) BIN="dist/EDLD.exe" ;;
  macos)   BIN="dist/EDLD"; [ -d "dist/EDLD.app" ] && APP="dist/EDLD.app" ;;
  *)       BIN="dist/EDLD" ;;
esac
[ -e "$BIN" ] || die "Build produced no $BIN — see the PyInstaller output above."
chmod +x "$BIN" 2>/dev/null || true
echo "  built: $BIN ($(du -h "$BIN" | cut -f1))"

# ── Smoke test ───────────────────────────────────────────────────────────────
# --version proves the process starts; --selftest proves both front ends can
# actually be imported. A frozen build can start perfectly and still be missing
# a lazily-imported Textual widget, which only surfaces when the dashboard is
# drawn — that has shipped before, which is why both run.
if [ "$RUN_TESTS" -eq 1 ] && [ "$ONEDIR" -eq 0 ]; then
  say "Smoke test"

  RUNNER=""
  if [ "$OS" = "linux" ] && [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null 2>&1; then
    RUNNER="xvfb-run -a"
    echo "  no DISPLAY — running under xvfb"
  fi

  set +e
  OUTPUT="$($RUNNER "./$BIN" --version 2>&1)"; RC=$?
  set -e
  echo "  --- binary output (exit $RC) ---"
  printf '%s\n' "$OUTPUT" | sed 's/^/  /'
  echo "  --------------------------------"
  [ "$RC" -eq 0 ] || die "Binary exited with status $RC."

  ACTUAL="$(printf '%s\n' "$OUTPUT" | tail -n1 | tr -d '[:space:]')"
  [ -n "$ACTUAL" ] || die "No output from the binary."
  [ "$ACTUAL" = "$VERSION" ] \
    || die "Version mismatch: binary reported '$ACTUAL', the version file says '$VERSION'."
  echo "  version OK: $ACTUAL"

  set +e
  ST="$($RUNNER "./$BIN" --selftest 2>&1)"; RC=$?
  set -e
  printf '%s\n' "$ST" | sed 's/^/  /'
  [ "$RC" -eq 0 ] || die "Selftest failed with status $RC."
fi

# ── Package ──────────────────────────────────────────────────────────────────
# Every archive carries the licence texts: LGPLv3 section 4(b) wants a copy to
# accompany the binary, and a link does not satisfy it.
if [ "$PACKAGE" -eq 1 ]; then
  say "Packaging"
  STEM="EDLD-${VERSION}-${PLATFORM}"

  case "$OS" in
    windows)
      if command -v 7z >/dev/null 2>&1; then
        7z a "dist/${STEM}.zip" "./dist/EDLD.exe" \
          ./LICENSE ./THIRD-PARTY-NOTICES.md ./licenses >/dev/null
      else
        "$PY" - "$STEM" <<'EOF'
import shutil, sys, zipfile
from pathlib import Path
stem = sys.argv[1]
with zipfile.ZipFile(f"dist/{stem}.zip", "w", zipfile.ZIP_DEFLATED) as z:
    z.write("dist/EDLD.exe", "EDLD.exe")
    for f in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
        z.write(f, f)
    for p in Path("licenses").rglob("*"):
        if p.is_file():
            z.write(p, str(p))
EOF
      fi
      ART="dist/${STEM}.zip" ;;
    macos)
      if [ -n "${APP:-}" ] && command -v ditto >/dev/null 2>&1; then
        ditto -c -k --keepParent "$APP" "dist/${STEM}.zip"
        ART="dist/${STEM}.zip"
      else
        tar -czf "dist/${STEM}.tar.gz" -C dist EDLD \
          -C .. LICENSE THIRD-PARTY-NOTICES.md licenses
        ART="dist/${STEM}.tar.gz"
      fi ;;
    *)
      tar -czf "dist/${STEM}.tar.gz" -C dist EDLD \
        -C .. LICENSE THIRD-PARTY-NOTICES.md licenses
      ART="dist/${STEM}.tar.gz" ;;
  esac
  echo "  packaged: $ART ($(du -h "$ART" | cut -f1))"

  # ── Optional signature, same key and namespace as the workflow ────────────
  if [ "$SIGN" -eq 1 ]; then
    if [ -z "${SIGNING_KEY:-}" ] && [ -z "${SIGNING_KEY_FILE:-}" ]; then
      warn "--sign given but neither SIGNING_KEY nor SIGNING_KEY_FILE is set; skipping."
    else
      KEY="${SIGNING_KEY_FILE:-}"
      TMPKEY=""
      if [ -z "$KEY" ]; then
        TMPKEY="$(mktemp)"; chmod 600 "$TMPKEY"
        printf '%s\n' "$SIGNING_KEY" > "$TMPKEY"
        KEY="$TMPKEY"
      fi
      ssh-keygen -Y sign -f "$KEY" -n "edld.release" "$ART"
      [ -n "$TMPKEY" ] && rm -f "$TMPKEY"
      echo "  signed: ${ART}.sig"
    fi
  fi

  # ── Checksum ──────────────────────────────────────────────────────────────
  # dist/ holds the loose binary too. "EDLD-*" needs the hyphen, so it
  # matches the archives and never EDLD, EDLD.exe or EDLD.app.
  ( cd dist
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum EDLD-* | grep -v '\.sha256' | grep -v '\.sig' > "EDLD-${VERSION}.sha256"
    else
      shasum -a 256 EDLD-* | grep -v '\.sha256' | grep -v '\.sig' > "EDLD-${VERSION}.sha256"
    fi
    cat "EDLD-${VERSION}.sha256" | sed 's/^/  /' )

  say "Done"
  ls -la dist/
else
  say "Done"
  ls -la dist/
fi

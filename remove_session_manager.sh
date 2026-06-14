#!/usr/bin/env bash
# Retire the orphaned session_manager notification shim.
# After the idle timer was rewired to call ksw.flush_session, this plugin has
# no callers and its only output (a 'session_flush' gui_queue message) is
# consumed by nothing. ksw.flush_session already emits the Discord notice and a
# dashboard alert, so nothing is lost. Run from the repo root.
#   --dry-run  show what would be removed without deleting
set -euo pipefail
DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1
TARGET="components/session_manager.py"
if [[ ! -f "$TARGET" ]]; then echo "Already absent: $TARGET"; exit 0; fi
if [[ $DRY -eq 1 ]]; then echo "[dry-run] would delete: $TARGET"; else rm -v "$TARGET"; fi
echo "Done. (Verify no 'session_manager' references remain: grep -rn session_manager --include='*.py' .)"

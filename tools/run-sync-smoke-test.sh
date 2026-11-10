#!/usr/bin/env bash
# Guided end-to-end synchronization test using only /tmp/qpy-rsync-smoke.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MODE=${1:-}
CASE=${2:-default}
ROOT=${QPY_RSYNC_SMOKE_ROOT:-/tmp/qpy-rsync-smoke}
REPORT_DIR="$ROOT/reports"
SESSION_LOG="$ROOT/qpy-rsync-session.log"
GUI_LOG="$ROOT/qpy-rsync-gui.log"
RESULT_REPORT="$REPORT_DIR/${MODE:-unknown}-${CASE}-result.txt"

usage() {
    cat <<'EOF'
Usage:
  ./tools/run-sync-smoke-test.sh update [default|manual-delete]
  ./tools/run-sync-smoke-test.sh mirror [default|protect-one]
  ./tools/run-sync-smoke-test.sh new-only [default|manual-delete]
  ./tools/run-sync-smoke-test.sh update cancel
  ./tools/run-sync-smoke-test.sh update failure

The script recreates /tmp/qpy-rsync-smoke, launches the GUI with fields filled
and comparison queued, then collects exact inventories and logs after the GUI
is closed. The final report is copied using dump-content.sh.
EOF
}

case "$MODE" in
    update|mirror|new-only) ;;
    -h|--help|"") usage; exit 0 ;;
    *) printf 'Unknown mode: %s\n' "$MODE" >&2; usage >&2; exit 2 ;;
esac

case "$MODE:$CASE" in
    update:default|update:manual-delete|update:cancel|update:failure|mirror:default|mirror:protect-one|new-only:default|new-only:manual-delete) ;;
    *) printf 'Unsupported test case: %s %s\n' "$MODE" "$CASE" >&2; usage >&2; exit 2 ;;
esac

cd "$REPO_DIR"
QPY_RSYNC_SMOKE_CASE="$CASE" ./tools/setup-sync-smoke-test.sh
mkdir -p "$REPORT_DIR"

cat <<EOF
===============================================================================
qpy-rsync guided synchronization test
Mode: $MODE
Case: $CASE
Source: $ROOT/source/
Destination: $ROOT/destination/
Backup: $ROOT/backup/
===============================================================================
EOF

cat <<'EOF'

IMPORTANT

The Source and Destination trees are difference views, not filesystem browsers.
When Compare reports 0 remaining differences, both trees are expected to be
empty. This indicates that no further synchronization actions are available.

EOF

case "$MODE:$CASE" in
update:default)
    cat <<'EOF'
Expected pre-sync actions:
  - new-only.txt, Documents/report.txt, Pictures/photo.jpg: checked create
  - update-me.txt: checked update
  - destination-only.txt and extra-dir/: unchecked keep

In the GUI:
  1. Confirm Mode is Update and comparison completed automatically.
  2. Do not change checkboxes.
  3. Click Verify Selected Actions; wait for Actions Verified.
  4. Click Synchronize..., review the counts, check the acknowledgement.
  5. Click Synchronize Now.
  6. Wait for automatic recompare. Retained destination-only objects may remain.
  7. Close the GUI to let this script collect results.
EOF
    ;;
update:manual-delete)
    cat <<'EOF'
Expected pre-sync actions are the Update defaults.

In the GUI:
  1. Confirm Mode is Update and comparison completed automatically.
  2. Check destination-only.txt so Keep changes to Delete.
  3. Leave extra-dir/ unchecked as Keep.
  4. Verify Selected Actions, then Synchronize... and Synchronize Now.
  5. Wait for automatic recompare.
  6. Confirm destination-only.txt is gone but extra-dir/ remains.
  7. Close the GUI.
EOF
    ;;
update:cancel)
    cat <<EOF
Expected behavior:
  - cancel-large.bin (${QPY_RSYNC_CANCEL_MIB:-1024} MiB) provides time to cancel.
  - Cancellation is not a rollback operation.

In the GUI:
  1. Confirm Mode is Update and comparison completed automatically.
  2. Do not change checkboxes.
  3. Click Verify Selected Actions and wait for Actions Verified.
  4. Click Synchronize..., acknowledge, then click Synchronize Now.
  5. While synchronization is active, click Cancel.
  6. Confirm STATE synchronization-cancelled appears.
  7. Confirm no automatic comparison starts.
  8. Close the GUI and let the runner collect diagnostics.
EOF
    ;;
update:failure)
    cat <<EOF
Expected behavior:
  - Synchronization should fail after verification.

In the GUI:
  1. Confirm Mode is Update and comparison completed automatically.
  2. Click Verify Selected Actions and wait for Actions Verified.
  3. In another terminal run:
       mv "$ROOT/source" "$ROOT/source-failure"
  4. Synchronize.
  5. Confirm STATE synchronization-failed appears.
  6. Confirm no automatic comparison starts.
  7. Restore the source:
       mv "$ROOT/source-failure" "$ROOT/source"
  8. Close the GUI and let the runner collect diagnostics.
EOF
    ;;
mirror:default)
    cat <<'EOF'
Expected pre-sync actions:
  - Source changes: checked create/update
  - destination-only.txt and extra-dir/: checked delete

In the GUI:
  1. Confirm Mode is Mirror and comparison completed automatically.
  2. Do not change checkboxes.
  3. Verify Selected Actions.
  4. In confirmation, verify destructive/deletion counts are nonzero.
  5. Acknowledge and click Synchronize Now.
  6. Wait for automatic recompare.
  7. Confirm comparison reports 0 remaining differences.
  8. Confirm both difference trees are empty.
  9. Verify Selected Actions and Synchronize are disabled.
 10. Close the GUI.
EOF
    ;;
mirror:protect-one)
    cat <<'EOF'
Expected pre-sync actions are the Mirror defaults.

In the GUI:
  1. Uncheck destination-only.txt to protect it.
  2. Leave extra-dir/ checked for deletion.
  3. Verify, confirm, and Synchronize Now.
  4. Wait for automatic recompare.
  5. Confirm destination-only.txt remains but extra-dir/ is gone.
  6. Close the GUI.
EOF
    ;;
new-only:default)
    cat <<'EOF'
Expected pre-sync actions:
  - Missing Source objects: checked create
  - Existing update-me.txt: not transferred by --ignore-existing
  - destination-only.txt and extra-dir/: unchecked keep

In the GUI:
  1. Confirm Mode is New Only and comparison completed automatically.
  2. Do not change checkboxes.
  3. Verify, confirm, and Synchronize Now.
  4. Wait for automatic recompare.
  5. Confirm new-only.txt was created.
  6. Confirm update-me.txt retains its original Destination content.
  7. Confirm destination-only.txt and extra-dir/ remain.
  8. Remaining differences are expected because New Only intentionally avoids
     updates and automatic deletions.
  9. Close the GUI.
EOF
    ;;
new-only:manual-delete)
    cat <<'EOF'
Expected pre-sync actions are the New Only defaults.

In the GUI:
  1. Check destination-only.txt so Keep changes to Delete.
  2. Leave extra-dir/ unchecked as Keep.
  3. Verify, confirm, and Synchronize Now.
  4. Wait for automatic recompare.
  5. Confirm new-only.txt was added.
  6. Confirm update-me.txt stayed unchanged.
  7. Confirm destination-only.txt was deleted and backed up.
  8. Confirm extra-dir/ remains.
  9. Remaining differences are expected because New Only intentionally avoids
     updating existing Destination files.
 10. Close the GUI.
EOF
    ;;
esac

printf '\nPress Enter to launch qpy-rsync, or q then Enter to cancel: '
read -r ANSWER
if [[ $ANSWER == q || $ANSWER == Q ]]; then
    exit 0
fi

set +e
PYTHONFAULTHANDLER=1 QT_FATAL_WARNINGS=1 \
    ./qpy-rsync.sh \
    --log-file "$GUI_LOG" \
    --dir-pair "$ROOT/source/" "$ROOT/destination/" \
    --backup "$ROOT/backup/" \
    --mode "$MODE" \
    --compare \
    > >(tee "$SESSION_LOG") 2>&1
APP_STATUS=$?
set -e

{
    printf '===== GUIDED TEST METADATA =====\n'
    printf 'mode=%s\ncase=%s\napp_exit_status=%s\n' "$MODE" "$CASE" "$APP_STATUS"
    printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'git_commit=%s\n' "$(git rev-parse HEAD)"
    printf 'git_status_begin\n'
    git status --short
    printf 'git_status_end\n\n'
    ./tools/collect-sync-smoke-results.sh
    printf '\n===== GUI PROCESS STDOUT/STDERR =====\n'
    if [[ -f $SESSION_LOG ]]; then
        cat "$SESSION_LOG"
    else
        printf '(missing)\n'
    fi
    printf '\n===== GUI XDG/CLI SESSION LOG =====\n'
    if [[ -f $GUI_LOG ]]; then
        cat "$GUI_LOG"
    else
        printf '(missing)\n'
    fi
    printf '\n===== QPY-RSYNC TEST LOG TAIL =====\n'
    if [[ -f /tmp/qpy-rsync.log ]]; then
        tail -n 120 /tmp/qpy-rsync.log
    else
        printf '(not present)\n'
    fi
} > "$RESULT_REPORT"

printf '\nResult report: %s\n' "$RESULT_REPORT"
printf 'Application exit status: %s\n' "$APP_STATUS"
printf 'The report will now be copied in packed clipboard batches.\n'
./dump-content.sh "$RESULT_REPORT"

if ((APP_STATUS != 0)); then
    printf 'qpy-rsync exited nonzero; include all copied report batches.\n' >&2
    exit "$APP_STATUS"
fi

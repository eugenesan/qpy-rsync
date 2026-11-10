#!/bin/sh
set -eu
ROOT=${QPY_RSYNC_SMOKE_ROOT:-/tmp/qpy-rsync-smoke}
SRC=$ROOT/source
DST=$ROOT/destination
BACKUP=$ROOT/backup
printf '===== QPY-RSYNC SYNC SMOKE RESULT =====\n'
printf 'root=%s\n' "$ROOT"
for dir in "$SRC" "$DST" "$BACKUP"; do
    printf '\n--- %s ---\n' "$dir"
    if [ -d "$dir" ]; then
        find "$dir" -printf '%P|%y|%s|%TY-%Tm-%TdT%TH:%TM:%TS\n' | LC_ALL=C sort
    else
        printf '(missing)\n'
    fi
done
printf '\n--- content hashes ---\n'
find "$SRC" "$DST" "$BACKUP" -type f -exec sha256sum {} + 2>/dev/null | LC_ALL=C sort || true
printf '\n--- key content ---\n'
for file in "$DST/update-me.txt" "$DST/new-only.txt" "$DST/destination-only.txt"; do
    if [ -f "$file" ]; then
        printf '%s: ' "$file"; tr '\n' ' ' < "$file"; printf '\n'
    else
        printf '%s: (missing)\n' "$file"
    fi
done
printf '\n--- terminal event summary ---\n'
LOG=$ROOT/qpy-rsync-gui.log
if [ -f "$LOG" ]; then
    grep 'STATE synchronization-' "$LOG" || true
fi
printf '\n--- expected-mode notes ---\n'
if [ -f "$ROOT/README-smoke.txt" ]; then
    cat "$ROOT/README-smoke.txt"
fi

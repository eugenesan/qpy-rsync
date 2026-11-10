#!/bin/sh
set -eu
ROOT=${QPY_RSYNC_SMOKE_ROOT:-/tmp/qpy-rsync-smoke}
SRC=$ROOT/source
DST=$ROOT/destination
BACKUP=$ROOT/backup
CASE=${QPY_RSYNC_SMOKE_CASE:-default}
CANCEL_MIB=${QPY_RSYNC_CANCEL_MIB:-1024}
rm -rf -- "$ROOT"
mkdir -p "$SRC/Documents" "$SRC/Pictures" "$DST/Documents" "$DST/extra-dir" "$BACKUP"
printf 'new file\n' > "$SRC/new-only.txt"
printf 'source version\n' > "$SRC/update-me.txt"
printf 'destination old version\n' > "$DST/update-me.txt"
printf 'same\n' > "$SRC/same.txt"
printf 'same\n' > "$DST/same.txt"
printf 'source document\n' > "$SRC/Documents/report.txt"
printf 'destination-only\n' > "$DST/destination-only.txt"
printf 'extra nested\n' > "$DST/extra-dir/old.txt"
printf 'picture\n' > "$SRC/Pictures/photo.jpg"
if [ "$CASE" = cancel ]; then
    dd if=/dev/zero of="$SRC/cancel-large.bin" bs=1M count="$CANCEL_MIB" status=none
fi
printf '%s\n' "Smoke fixture created" "Source: $SRC/" "Destination: $DST/" "Backup: $BACKUP/" "Run collect-sync-smoke-results.sh after each tested mode."
cat > "$ROOT/README-smoke.txt" <<EOF
Test sequence for each mode:
1. Run this setup script.
2. Compare, choose checkboxes, Verify Selected Actions, then Synchronize.
3. Run collect-sync-smoke-results.sh and paste the full output.
Update: update-me.txt should change, new-only.txt should appear, destination-only.txt should remain unless manually checked.
Mirror: update-me.txt should change, new-only.txt should appear, destination-only.txt and extra-dir should be deleted unless unchecked.
New Only: new-only.txt should appear, update-me.txt and destination-only.txt should remain unchanged unless explicitly selected behavior changes the plan.
EOF

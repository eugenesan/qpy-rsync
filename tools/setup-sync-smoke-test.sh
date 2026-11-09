#!/bin/sh
set -eu
ROOT=${QPY_RSYNC_SMOKE_ROOT:-/tmp/qpy-rsync-smoke}
SRC=$ROOT/source
DST=$ROOT/destination
BACKUP=$ROOT/backup
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
printf '%s\n' "Smoke fixture created" "Source: $SRC/" "Destination: $DST/" "Backup: $BACKUP/" "Run collect-sync-smoke-results.sh after each tested mode."

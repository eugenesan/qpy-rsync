#!/bin/sh

set -eu

OUTPUT=${DUMP_CONTENT_OUTPUT:-/tmp/content.txt}
MAX_BYTES=${DUMP_CONTENT_MAX_BYTES:-32768}

usage() {
    printf 'Usage: %s FILE [FILE ...]\n' "$0" >&2
}

if [ "$#" -eq 0 ]; then
    usage
    exit 2
fi

case $MAX_BYTES in
    ''|*[!0-9]*)
        printf 'dump-content: DUMP_CONTENT_MAX_BYTES must be a positive integer\n' >&2
        exit 2
        ;;
esac
if [ "$MAX_BYTES" -eq 0 ]; then
    printf 'dump-content: DUMP_CONTENT_MAX_BYTES must be greater than zero\n' >&2
    exit 2
fi

for file do
    if [ ! -f "$file" ]; then
        printf 'dump-content: file not found: %s\n' "$file" >&2
        exit 1
    fi
done

included=$(mktemp)
remaining=$(mktemp)
section=$(mktemp)
cleanup() {
    rm -f -- "$included" "$remaining" "$section" "$OUTPUT"
}
trap cleanup EXIT HUP INT TERM

: > "$OUTPUT"
: > "$included"
: > "$remaining"
current_bytes=0
limit_reached=0

for file do
    if [ "$limit_reached" -ne 0 ]; then
        printf '%s\n' "$file" >> "$remaining"
        continue
    fi

    {
        printf '===== FILE: %s =====\n' "$file"
        cat -- "$file"
        printf '\n'
    } > "$section"

    section_bytes=$(wc -c < "$section")
    next_bytes=$((current_bytes + section_bytes))
    if [ "$next_bytes" -gt "$MAX_BYTES" ]; then
        limit_reached=1
        printf '%s\n' "$file" >> "$remaining"
        continue
    fi

    cat -- "$section" >> "$OUTPUT"
    printf '%s\n' "$file" >> "$included"
    current_bytes=$next_bytes
done

included_count=$(wc -l < "$included")
remaining_count=$(wc -l < "$remaining")

printf 'Dump size: %s bytes (limit: %s bytes)\n' "$current_bytes" "$MAX_BYTES"
printf 'Included files (%s):\n' "$included_count"
if [ "$included_count" -eq 0 ]; then
    printf '  (none)\n'
else
    sed 's/^/  /' "$included"
fi

printf 'Remaining files (%s):\n' "$remaining_count"
if [ "$remaining_count" -eq 0 ]; then
    printf '  (none)\n'
else
    sed 's/^/  /' "$remaining"
fi

if [ "$included_count" -eq 0 ]; then
    printf 'dump-content: the first file section exceeds the %s-byte limit\n' "$MAX_BYTES" >&2
    exit 1
fi

copy_to_clipboard() {
    if [ -n "${WAYLAND_DISPLAY:-}" ] && command -v wl-copy >/dev/null 2>&1; then
        wl-copy < "$OUTPUT"
        printf 'Copied with wl-copy for Wayland.\n'
        return
    fi
    if [ -n "${DISPLAY:-}" ] && command -v xclip >/dev/null 2>&1; then
        xclip -selection clipboard < "$OUTPUT"
        printf 'Copied with xclip for X11.\n'
        return
    fi
    if command -v wl-copy >/dev/null 2>&1; then
        wl-copy < "$OUTPUT"
        printf 'Copied with wl-copy.\n'
        return
    fi
    if command -v xclip >/dev/null 2>&1; then
        xclip -selection clipboard < "$OUTPUT"
        printf 'Copied with xclip.\n'
        return
    fi
    printf 'dump-content: install wl-clipboard (Wayland) or xclip (X11)\n' >&2
    exit 1
}

copy_to_clipboard
printf 'Removed temporary dump: %s\n' "$OUTPUT"

if [ "$remaining_count" -gt 0 ]; then
    printf 'Run again with the remaining files listed above.\n'
fi

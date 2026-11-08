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

section=$(mktemp)
included=$(mktemp)
cleanup() {
    rm -f -- "$section" "$included" "$OUTPUT"
}
trap cleanup EXIT HUP INT TERM

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

batch=1
while [ "$#" -gt 0 ]; do
    : > "$OUTPUT"
    : > "$included"
    current_bytes=0
    batch_count=0

    while [ "$#" -gt 0 ]; do
        file=$1
        {
            printf '===== FILE: %s =====\n' "$file"
            cat -- "$file"
            printf '\n'
        } > "$section"
        section_bytes=$(wc -c < "$section")

        if [ "$section_bytes" -gt "$MAX_BYTES" ]; then
            printf 'dump-content: complete section for %s is %s bytes and exceeds the %s-byte limit\n' \
                "$file" "$section_bytes" "$MAX_BYTES" >&2
            exit 1
        fi

        next_bytes=$((current_bytes + section_bytes))
        if [ "$batch_count" -gt 0 ] && [ "$next_bytes" -gt "$MAX_BYTES" ]; then
            break
        fi

        cat -- "$section" >> "$OUTPUT"
        printf '%s\n' "$file" >> "$included"
        current_bytes=$next_bytes
        batch_count=$((batch_count + 1))
        shift
    done

    printf '\nBatch %s: %s bytes (limit: %s bytes)\n' "$batch" "$current_bytes" "$MAX_BYTES"
    printf 'Included files (%s):\n' "$batch_count"
    sed 's/^/  /' "$included"
    printf 'Remaining files (%s):\n' "$#"
    if [ "$#" -eq 0 ]; then
        printf '  (none)\n'
    else
        for file do
            printf '  %s\n' "$file"
        done
    fi

    copy_to_clipboard
    rm -f -- "$OUTPUT"
    printf 'Removed temporary dump: %s\n' "$OUTPUT"

    if [ "$#" -eq 0 ]; then
        printf 'All requested files were copied in %s batch(es).\n' "$batch"
        break
    fi

    printf 'Paste batch %s now. Press Enter to copy the next batch, or Ctrl+C to abort: ' "$batch"
    IFS= read -r _approval
    batch=$((batch + 1))
 done

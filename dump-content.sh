#!/bin/sh

set -eu

OUTPUT=${DUMP_CONTENT_OUTPUT:-/tmp/content.txt}

if [ "$#" -eq 0 ]; then
    printf 'Usage: %s FILE [FILE ...]\n' "$0" >&2
    exit 2
fi

for file do
    if [ ! -f "$file" ]; then
        printf 'dump-content: file not found: %s\n' "$file" >&2
        exit 1
    fi
done

: > "$OUTPUT"

for file do
    {
        printf '===== FILE: %s =====\n' "$file"
        cat -- "$file"
        printf '\n'
    } >> "$OUTPUT"
done

printf 'Wrote %s file(s) to %s\n' "$#" "$OUTPUT"

#kate ${OUTPUT}

xclip -selection clipboard < ${OUTPUT} || wl-copy < ${OUTPUT}

#!/usr/bin/env bash
# Pack requested UTF-8 text files into near-full clipboard batches.
set -euo pipefail

MAX_BATCH_BYTES=${DUMP_CONTENT_MAX_SECTION_BYTES:-32768}

if (($# == 0)); then
    printf 'Usage: %s FILE [FILE ...]\n' "$0" >&2
    exit 2
fi

if command -v wl-copy >/dev/null 2>&1 && [[ -n ${WAYLAND_DISPLAY:-} ]]; then
    CLIPBOARD=(wl-copy)
elif command -v xclip >/dev/null 2>&1 && [[ -n ${DISPLAY:-} ]]; then
    CLIPBOARD=(xclip -selection clipboard)
elif command -v xsel >/dev/null 2>&1 && [[ -n ${DISPLAY:-} ]]; then
    CLIPBOARD=(xsel --clipboard --input)
else
    printf '%s\n' 'dump-content: install wl-clipboard, xclip, or xsel.' >&2
    exit 127
fi

TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/qpy-rsync-dump.XXXXXX")
trap 'rm -rf -- "$TMP_DIR"' EXIT

python3 - "$MAX_BATCH_BYTES" "$TMP_DIR" "$@" <<'PYTHON'
from __future__ import annotations

from pathlib import Path
import json
import sys

limit = int(sys.argv[1])
out_dir = Path(sys.argv[2])
names = sys.argv[3:]
if limit < 512:
    raise SystemExit("dump-content: batch limit must be at least 512 bytes")


def nbytes(text: str) -> int:
    return len(text.encode("utf-8"))


files: list[tuple[str, list[str]]] = []
failed = False
for name in names:
    path = Path(name)
    if not path.is_file():
        print(f"dump-content: file not found: {name}", file=sys.stderr)
        failed = True
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"dump-content: {name}: {exc}", file=sys.stderr)
        failed = True
        continue
    lines = text.splitlines(keepends=True)
    if not lines and not text:
        lines = []
    files.append((name, lines))

# Globally stream file lines into batches. A large file is split according to
# the space actually remaining in the current batch, rather than pre-split into
# maximum-sized file chunks. This fills the first batch after small files.
batches: list[dict[str, object]] = []
current_parts: list[str] = []
current_sources: list[str] = []
current_bytes = 0


def flush() -> None:
    global current_parts, current_sources, current_bytes
    if not current_parts:
        return
    text = "".join(current_parts)
    batches.append({"text": text, "sources": list(current_sources), "bytes": nbytes(text)})
    current_parts = []
    current_sources = []
    current_bytes = 0


def add_part(name: str, header: str, payload: str) -> None:
    global current_bytes
    separator = "\n" if current_parts else ""
    part = separator + header + payload
    if not part.endswith("\n"):
        part += "\n"
    size = nbytes(part)
    if current_parts and current_bytes + size > limit:
        flush()
        part = header + payload
        if not part.endswith("\n"):
            part += "\n"
        size = nbytes(part)
    if size > limit:
        raise ValueError(f"section for {name} exceeds {limit} bytes")
    current_parts.append(part)
    current_bytes += size
    if name not in current_sources:
        current_sources.append(name)


for name, lines in files:
    if not lines:
        add_part(name, f"===== FILE: {name} =====\n", "")
        continue

    line_index = 0
    part_number = 0
    while line_index < len(lines):
        part_number += 1
        first = line_index + 1
        # Reserve a stable continuation header. Total parts are intentionally
        # omitted because adaptive packing does not know the final count yet.
        header = (
            f"===== FILE: {name} =====\n"
            if part_number == 1
            else f"===== FILE: {name} (continued, from line {first}) =====\n"
        )
        separator_bytes = 1 if current_parts else 0
        available = limit - current_bytes - separator_bytes - nbytes(header)
        if available <= 0:
            flush()
            continue

        payload: list[str] = []
        used = 0
        while line_index < len(lines):
            line = lines[line_index]
            line_size = nbytes(line)
            maximum_empty_batch = limit - nbytes(header)
            if line_size > maximum_empty_batch:
                print(
                    f"dump-content: {name}: line {line_index + 1} is {line_size} bytes "
                    f"and cannot fit in a {limit}-byte batch",
                    file=sys.stderr,
                )
                failed = True
                line_index += 1
                break
            if payload and used + line_size > available:
                break
            if not payload and line_size > available:
                flush()
                break
            payload.append(line)
            used += line_size
            line_index += 1

        if payload:
            last = line_index
            if part_number > 1:
                header = f"===== FILE: {name} (continued, lines {first}-{last}) =====\n"
                # Header length may have grown slightly. Repack if necessary.
                if current_bytes + separator_bytes + nbytes(header) + used > limit:
                    flush()
            add_part(name, header, "".join(payload))

flush()

manifest = []
for number, batch in enumerate(batches, 1):
    output = out_dir / f"{number:06d}.txt"
    output.write_text(batch["text"], encoding="utf-8")
    manifest.append({
        "file": str(output),
        "bytes": batch["bytes"],
        "sources": batch["sources"],
    })
(out_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
if failed:
    (out_dir / "had-errors").touch()
PYTHON

mapfile -t BATCHES < <(python3 - "$TMP_DIR/manifest.json" <<'PYTHON'
import json, sys
for item in json.load(open(sys.argv[1], encoding='utf-8')):
    print(item['file'])
PYTHON
)

if ((${#BATCHES[@]} == 0)); then
    printf '%s\n' 'dump-content: no batches were generated.' >&2
    exit 1
fi

TOTAL=${#BATCHES[@]}
for ((INDEX=0; INDEX<TOTAL; INDEX++)); do
    BATCH=${BATCHES[$INDEX]}
    NUMBER=$((INDEX + 1))
    "${CLIPBOARD[@]}" < "$BATCH"
    read -r BYTES SOURCES < <(python3 - "$TMP_DIR/manifest.json" "$INDEX" <<'PYTHON'
import json, sys
item = json.load(open(sys.argv[1], encoding='utf-8'))[int(sys.argv[2])]
print(item['bytes'], ', '.join(item['sources']))
PYTHON
)
    printf 'dump-content: copied packed batch %d/%d (%s bytes)\nFiles: %s\n' \
        "$NUMBER" "$TOTAL" "$BYTES" "$SOURCES" >&2
    if ((NUMBER < TOTAL)); then
        if [[ ! -t 0 ]]; then
            printf '%s\n' 'dump-content: multiple batches require an interactive terminal.' >&2
            exit 2
        fi
        read -r -p 'Paste this batch, then press Enter for the next batch (q to quit): ' ANSWER
        if [[ $ANSWER == q || $ANSWER == Q ]]; then
            exit 0
        fi
    fi
done

printf 'dump-content: complete; copied %d packed batch(es).\n' "$TOTAL" >&2
[[ ! -e "$TMP_DIR/had-errors" ]]

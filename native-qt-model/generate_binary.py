"""Generate a flat binary dataset for the native Qt model handoff experiment.

The format is intentionally minimal: one header, an offset table, an interned
string blob, and four POD vectors. This is the shape the real application
could hand to a native model exactly once per comparison.

    magic 4s, version u4, count u8
    offsets u4[count+1]
    blob bytes (sum of offsets differences)
    actions i1[count], kinds i1[count], sizes i4[count], decisions i1[count]
"""

from __future__ import annotations

import argparse
import array
import struct
import time
from pathlib import Path

MAGIC = b"QPYN"
VERSION = 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=1_000_000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    count = args.items
    offsets = array.array("I", [0]) * (count + 1)
    blob = bytearray()
    actions = array.array("b", [0]) * count
    kinds = array.array("b", [0]) * count
    sizes = array.array("i", [0]) * count
    decisions = array.array("b", [0]) * count

    for i in range(count):
        path = f"d{i % 30000}/f{i}.txt"
        encoded = path.encode("utf-8")
        offsets[i + 1] = len(blob) + len(encoded)
        blob.extend(encoded)
        actions[i] = 3 if i % 17 == 0 else (1 if i % 5 == 0 else 0)
        kinds[i] = 1 if i % 97 == 0 else 0
        sizes[i] = (i * 37) % 100000
        decisions[i] = 0

    header = struct.pack("<4sIQ", MAGIC, VERSION, count)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("wb") as handle:
        handle.write(header)
        offsets.tofile(handle)
        handle.write(blob)
        actions.tofile(handle)
        kinds.tofile(handle)
        sizes.tofile(handle)
        decisions.tofile(handle)
    seconds = time.perf_counter() - started
    print(f"python generation {seconds * 1000:.0f} ms")
    print(f"file size {args.out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

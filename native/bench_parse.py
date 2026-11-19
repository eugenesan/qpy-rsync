"""Benchmark Python vs native rsync record parsing on a synthetic stream."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qpy_rsync.backend.rsync_parser import parse_record  # noqa: E402
from qpy_rsync.core.changes import ChangeAction  # noqa: E402

COUNT = int(os.environ.get("QPY_BENCH_COUNT", "520000"))
SEP = "|qpy-rsync|"


def make_stream() -> str:
    parts: list[str] = []
    for i in range(COUNT):
        code = ">f.st......" if i % 20 == 0 else ">f+++++++++"
        parts.append(f"{code}{SEP}100{SEP}2026/11/19-15:06:12{SEP}d{i // 17}/f{i}.txt\n")
    return "".join(parts)


def main() -> None:
    stream = make_stream()
    print(f"stream {len(stream) / 1e6:.1f} MB, {COUNT:,} records")

    t = time.perf_counter()
    changes = []
    for line in stream.splitlines():
        change = parse_record(line, delete_enabled=False)
        if change is not None:
            changes.append(change)
    python_time = time.perf_counter() - t
    print(f"python parse_record {python_time:.2f} s ({len(changes):,} changes)")

    from qpy_rsync import _qpy_native

    t = time.perf_counter()
    parsed = _qpy_native.parse_records(stream, False)
    native_time = time.perf_counter() - t
    print(f"native parse_records {native_time:.2f} s ({len(parsed.paths):,} paths)")

    t = time.perf_counter()
    actions = list(parsed.actions)
    kinds = list(parsed.kinds)
    sizes = list(parsed.sizes)
    print(f"native array conversion {time.perf_counter() - t:.2f} s")
    assert len(parsed.paths) == len(changes)
    assert parsed.actions[0] == (
        1 if changes[0].action is ChangeAction.UPDATE_CONTENT else 0
    )


if __name__ == "__main__":
    main()

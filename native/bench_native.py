"""Experimental benchmark: Python filter pass vs the native kernel.

Run with PYTHONPATH=src /usr/bin/python3 native/bench_native.py after build.sh.
The native kernel is intentionally minimal: it takes the per-row boolean
flags that the Python pass computes and produces the visible rows and the
per-directory aggregates.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind  # noqa: E402
from qpy_rsync.gui.flat_change_model import FlatChangeModel  # noqa: E402

COUNT = int(os.environ.get("QPY_BENCH_COUNT", "520000"))


def main() -> None:
    app = QApplication([])
    changes = [
        Change(
            f"d{i // 17}/f{i}",
            ChangeAction.UPDATE_CONTENT if i % 20 == 0 else ChangeAction.CREATE,
            ObjectKind.FILE,
            ">f.st......" if i % 20 == 0 else ">f+++++++++",
            size=100,
        )
        for i in range(COUNT)
    ]
    model = FlatChangeModel()
    t = time.perf_counter()
    model.set_changes(changes)
    print(f"set_changes {1000 * (time.perf_counter() - t):.0f} ms")

    times: list[float] = []
    for _ in range(3):
        t = time.perf_counter()
        model._apply_filters()
        times.append(1000 * (time.perf_counter() - t))
    print(f"python _apply_filters {min(times):.0f} ms (of {[round(x) for x in times]})")

    from qpy_rsync import _qpy_native

    row_count = len(model._rows)
    row_dir = list(model._row_dir_index)
    is_dir = [bool(x) for x in model._row_is_dir]
    change_index = [max(0, x) for x in model._row_change_index]
    sizes = [int(x.size or 0) for x in model.changes]

    t = time.perf_counter()
    kernel = _qpy_native.NativeFilter(
        change_index, row_dir, is_dir, sizes, len(model._dir_paths)
    )
    print(f"native one-time load {1000 * (time.perf_counter() - t):.0f} ms")
    visible = [True] * row_count
    excluded = [False] * row_count
    folded = [False] * row_count
    times.clear()
    for _ in range(3):
        t = time.perf_counter()
        rows, changes_seen, aggregates = kernel.apply(
            visible, visible, excluded, False, folded
        )
        times.append(1000 * (time.perf_counter() - t))
    print(f"native apply {min(times):.1f} ms (of {[round(x, 1) for x in times]})")
    print(f"rows {len(rows)} changes {len(changes_seen)} dirs {len(aggregates)}")
    print(f"python rows {len(model._visible_rows)}")
    del app


if __name__ == "__main__":
    main()

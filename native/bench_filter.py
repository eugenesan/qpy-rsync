"""Benchmark the Stage 2 native filter kernel on a 520k-item comparison.

Builds a real FlatChangeModel (the behavioural oracle), then compares the
Python _apply_filters pass with a single native filter() call that computes
the same change and directory flags and the same visible rows/aggregates.

Run with: ./native/build.sh && PYTHONPATH=src /usr/bin/python3 native/bench_filter.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_model import (  # noqa: E402
    ACTION_CODE,
    build_model,
    native_signature,
    python_signature,
)

from qpy_rsync import _qpy_native  # noqa: E402
from qpy_rsync.core.changes import ChangeAction  # noqa: E402
from qpy_rsync.gui.flat_change_model import FlatChangeModel  # noqa: E402


def comparison_for(model: FlatChangeModel) -> _qpy_native.NativeComparison:
    rows = model._rows
    return _qpy_native.NativeComparison(
        [row.path for row in rows],
        [row.name.casefold() for row in rows],
        [row.path.casefold() for row in rows],
        [max(0, row.change_index) for row in rows],
        list(model._row_dir_index),
        [model._dir_index.get(row.path, 0) if row.is_directory else -1 for row in rows],
        [row.is_directory for row in rows],
        [int(change.size or 0) for change in model.changes],
    )


def structure(model: FlatChangeModel) -> tuple[list[int], list[bool], list[int], list[int], list[int]]:
    dir_paths = model._dir_paths
    return (
        [
            model._dir_index.get(
                model._change_paths[ci]
                if model.changes[ci].kind.name == "DIRECTORY"
                else model._change_parents[ci],
                0,
            )
            for ci in range(len(model.changes))
        ],
        [change.kind.name == "DIRECTORY" for change in model.changes],
        [ACTION_CODE[action.value] for action in model._change_effective_actions],
        [model._dir_index.get(model._directories[path].parent, -1) for path in dir_paths],
        [model._directories[path].own_change_index for path in dir_paths],
    )


def main() -> None:
    count = int(os.environ.get("QPY_BENCH_COUNT", "520000"))
    print(f"building {count:,} changes")
    changes = build_model_large(count)
    model = FlatChangeModel()
    t = time.perf_counter()
    model.set_changes(changes)
    print(f"set_changes {1000 * (time.perf_counter() - t):.0f} ms")

    comp = comparison_for(model)
    comp.set_structure(*structure(model))
    print(f"rows {len(model._rows):,} dirs {len(model._dir_paths):,}")

    scenarios: list[tuple[str, object]] = [
        ("all", None),
        ("updates", {ChangeAction.UPDATE_CONTENT}),
        ("creates", {ChangeAction.CREATE}),
    ]
    for name, actions in scenarios:
        model._visible_actions = actions
        python_times: list[float] = []
        for _ in range(3):
            t = time.perf_counter()
            model._apply_filters()
            python_times.append(1000 * (time.perf_counter() - t))
        mask = (
            0
            if actions is None
            else sum(1 << ACTION_CODE[action.value] for action in actions)
        )
        native_times: list[float] = []
        for _ in range(3):
            t = time.perf_counter()
            comp.filter(mask, False, False, [], False, [], 0)
            native_times.append(1000 * (time.perf_counter() - t))
        print(
            f"{name:8s} python {min(python_times):6.0f} ms "
            f"native {min(native_times):6.1f} ms "
            f"speedup {min(python_times) / min(native_times):5.1f}x"
        )

    # One full byte-for-byte check on the largest tree.
    model._visible_actions = {ChangeAction.UPDATE_CONTENT}
    model._apply_filters()
    python = python_signature(model)
    native = native_signature(model, native_filter=True)
    for key in python:
        assert python[key] == native[key], (
            key,
            len(python[key]) if hasattr(python[key], "__len__") else None,
            len(native[key]) if hasattr(native[key], "__len__") else None,
        )
    print(f"differential at {count:,}: matched")


def build_model_large(count: int) -> list[object]:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    return [
        Change(
            f"d{i // 17}/f{i}",
            ChangeAction.UPDATE_CONTENT if i % 20 == 0 else ChangeAction.CREATE,
            ObjectKind.FILE,
            ">f.st......" if i % 20 == 0 else ">f+++++++++",
            size=100,
        )
        for i in range(count)
    ]


if __name__ == "__main__":
    main()

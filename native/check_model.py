"""Differential check: native row kernel vs FlatChangeModel._apply_filters.

This is the Stage 1 checkpoint from docs/native-backend-plan.md. It builds a
synthetic comparison, snapshots the Python model's visible rows, visible change
set and per-directory aggregates, then feeds the equivalent per-row flags to
the persistent NativeComparison kernel and asserts the two signatures match.

The flags are still computed by Python here; Stage 2 moves that computation
into native code. What this proves is that the data boundary and the row loop
are faithful, so later stages can be checked against a stable oracle.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qpy_rsync import _qpy_native  # noqa: E402
from qpy_rsync.core.changes import (  # noqa: E402
    Change,
    ChangeAction,
    ChangeDecision,
    ObjectKind,
)
from qpy_rsync.gui.flat_change_model import FlatChangeModel  # noqa: E402


def build_changes() -> list[Change]:
    """A small tree exercising folders, files and every action kind."""
    code = ">f+++++++++"
    update = ">f.st......"
    meta = ".d..t......"
    delete = "*deleting   "
    return [
        Change(".", ChangeAction.CREATE, ObjectKind.DIRECTORY, meta, 0),
        Change("src", ChangeAction.CREATE, ObjectKind.DIRECTORY, code, 4096),
        Change("src/a.txt", ChangeAction.CREATE, ObjectKind.FILE, code, 100),
        Change("src/b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, update, 200),
        Change("src/lib", ChangeAction.UPDATE_METADATA, ObjectKind.DIRECTORY, meta, 100),
        Change("src/lib/x.py", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, update, 50),
        Change("src/lib/y.py", ChangeAction.CREATE, ObjectKind.FILE, code, 75),
        Change("docs", ChangeAction.CREATE, ObjectKind.DIRECTORY, code, 4096),
        Change("docs/readme.md", ChangeAction.CREATE, ObjectKind.FILE, code, 30),
        Change("docs/gone.txt", ChangeAction.DELETE, ObjectKind.FILE, delete, 0),
        Change("old", ChangeAction.DELETE, ObjectKind.DIRECTORY, delete, 0),
        Change("old/stale.bin", ChangeAction.DELETE, ObjectKind.FILE, delete, 0),
        Change("remote.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, delete, 0),
    ]


def build_model() -> FlatChangeModel:
    model = FlatChangeModel()
    model.source_root = "/src"
    model.destination_root = "/dst"
    model.set_changes(build_changes())
    return model


def folded_parent_flags(model: FlatChangeModel) -> list[int]:
    """Reproduce the fold decision the Python filter pass applies to rows."""
    pattern_active = bool(model._pattern) and model._pattern != "*"
    collapse_active = bool(model.collapsed) and not pattern_active
    directory_folded: dict[str, bool] = {"": False}
    if collapse_active:
        for path, directory in model._directories.items():
            directory_folded[path] = (
                directory_folded.get(directory.parent, False)
                or path in model.collapsed
            )
    return [
        1
        if (
            collapse_active
            and row.path
            and directory_folded.get(row.parent, False)
        )
        else 0
        for row in model._rows
    ]


def python_signature(model: FlatChangeModel) -> dict[str, object]:
    return {
        "rows": list(model._visible_rows),
        "changes": sorted(model._visible_change_indices),
        "aggregates": [list(values) for values in model._aggregate_counts],
    }


def native_signature(model: FlatChangeModel) -> dict[str, object]:
    rows = model._rows
    paths = [row.path for row in rows]
    folded_names = [row.name.casefold() for row in rows]
    folded_paths = [row.path.casefold() for row in rows]
    change_index = [
        row.change_index if row.change_index >= 0 else -1 for row in rows
    ]
    row_dir = list(model._row_dir_index)
    own_dir_index = [
        model._dir_index.get(row.path, 0)
        if row.is_directory and row.change_index >= 0
        else -1
        for row in rows
    ]
    is_dir = [row.is_directory for row in rows]
    change_sizes = [int(change.size or 0) for change in model.changes]

    comparison = _qpy_native.NativeComparison(
        paths,
        folded_names,
        folded_paths,
        change_index,
        row_dir,
        own_dir_index,
        is_dir,
        change_sizes,
    )

    has_exclusion = bool(model.exclusion)
    excluded = model._excluded_paths()
    excluded_get = excluded.get
    excluded_fn = model.exclusion.is_excluded
    row_visible: list[int] = []
    row_path_ok: list[int] = []
    row_faded: list[int] = []
    row_excluded: list[int] = []
    row_explicit: list[int] = []
    for row in rows:
        if row.is_directory and row.directory is not None:
            row_visible.append(1 if row.directory.visible else 0)
            row_path_ok.append(1 if row.directory.path_ok else 0)
            row_faded.append(1 if row.directory.faded else 0)
        elif not row.is_directory:
            ci = row.change_index
            row_visible.append(1 if model._change_visible[ci] else 0)
            row_path_ok.append(1 if model._change_path_ok[ci] else 0)
            row_faded.append(0)
        else:
            row_visible.append(0)
            row_path_ok.append(0)
            row_faded.append(0)
        row_excluded.append(1 if (row.path and excluded_fn(row.path)) else 0)
        row_explicit.append(1 if excluded_get(row.path, False) else 0)

    comparison.apply(
        row_visible,
        row_path_ok,
        row_faded,
        row_excluded,
        row_explicit,
        folded_parent_flags(model),
        has_exclusion,
        model.show_excluded,
        0,
    )

    counts = list(comparison.dir_counts)
    sizes = list(comparison.dir_sizes)
    width = len(model._dir_paths)
    counts += [0] * (width - len(counts))
    sizes += [0] * (width - len(sizes))
    return {
        "rows": list(comparison.visible_rows),
        "changes": sorted(comparison.visible_changes),
        "aggregates": [[counts[i], sizes[i]] for i in range(width)],
    }


def compare(name: str, model: FlatChangeModel) -> None:
    python = python_signature(model)
    native = native_signature(model)
    for key in python:
        if python[key] != native[key]:
            raise AssertionError(
                f"{name}: {key} differs\n"
                f"  python: {python[key]}\n"
                f"  native: {native[key]}"
            )
    print(
        f"{name}: {len(python['rows'])} rows, "
        f"{len(python['changes'])} changes, matched"
    )


def main() -> None:
    scenarios: list[tuple[str, object]] = [
        ("default", lambda m: None),
        (
            "update-only",
            lambda m: m.set_visible_actions({ChangeAction.UPDATE_CONTENT}),
        ),
        (
            "create-or-delete",
            lambda m: m.set_visible_actions(
                {ChangeAction.CREATE, ChangeAction.DELETE}
            ),
        ),
        ("path-substring", lambda m: m.set_path_filter("lib")),
        ("glob-name", lambda m: m.set_path_filter("*.py")),
        ("dir-contents", lambda m: m.set_path_filter("src/lib/")),
        (
            "excluded",
            lambda m: (
                m.decisions.set("src/lib/x.py", ChangeDecision.EXCLUDE),
                m.refresh_exclusions(),
            ),
        ),
        (
            "excluded-shown",
            lambda m: (
                m.decisions.set("src/lib/x.py", ChangeDecision.EXCLUDE),
                m.refresh_exclusions(),
                setattr(m, "show_excluded", True),
                m._apply_filters(),
            ),
        ),
        (
            "collapsed",
            lambda m: (setattr(m, "collapsed", {"src"}), m._apply_filters()),
        ),
    ]
    for name, configure in scenarios:
        model = build_model()
        configure(model)
        compare(name, model)


if __name__ == "__main__":
    main()

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


def subtree_signature(model: FlatChangeModel) -> list[tuple[int, int, int, int]]:
    return [
        (
            directory.subtree_items,
            directory.subtree_destination_items,
            directory.subtree_size,
            directory.subtree_destination_size,
        )
        for directory in model._directories.values()
    ]


def total_up(counts: list[list[int]], model: FlatChangeModel) -> list[tuple[int, int, int, int]]:
    """Replicate FlatChangeModel._total_up_from_aggregates."""
    values = {
        path: [0, 0, 0, 0] for path in model._dir_paths
    }
    for index in range(len(model._dir_paths) - 1, -1, -1):
        path = model._dir_paths[index]
        directory = model._directories[path]
        own = counts[index]
        if own[0]:
            values[path][0] += own[3]
            values[path][1] += own[4]
            values[path][2] += own[1]
            values[path][3] += own[2]
        parent = model._directories.get(directory.parent) if index else None
        if parent is not None:
            for slot in range(4):
                values[parent.path][slot] += values[path][slot]
    return [tuple(values[path]) for path in model._dir_paths]


def python_signature(model: FlatChangeModel) -> dict[str, object]:
    return {
        "rows": list(model._visible_rows),
        "changes": sorted(model._visible_change_indices),
        "aggregates": [list(values) for values in model._aggregate_counts],
        "subtree": subtree_signature(model),
    }


ACTION_CODE = {
    action.value: index
    for index, action in enumerate(
        (
            ChangeAction.CREATE,
            ChangeAction.UPDATE_CONTENT,
            ChangeAction.UPDATE_METADATA,
            ChangeAction.DELETE,
            ChangeAction.DESTINATION_ONLY,
            ChangeAction.NO_CHANGE,
            ChangeAction.MESSAGE,
        )
    )
}


def native_signature(
    model: FlatChangeModel, *, native_filter: bool = False
) -> dict[str, object]:
    rows = model._rows
    paths = [row.path for row in rows]
    folded_names = [row.name.casefold() for row in rows]
    folded_paths = [row.path.casefold() for row in rows]
    change_index = [
        row.change_index if row.change_index >= 0 else -1 for row in rows
    ]
    row_dir = list(model._row_dir_index)
    # Every directory row carries its own folder index, even without a
    # change of its own; the row loop needs it for the flag lookup.
    own_dir_index = [
        model._dir_index.get(row.path, 0) if row.is_directory else -1
        for row in rows
    ]
    is_dir = [row.is_directory for row in rows]
    change_sizes = [int(change.size or 0) for change in model.changes]
    change_dest_sizes = [
        int(change.destination_size or 0) for change in model.changes
    ]

    comparison = _qpy_native.NativeComparison(
        paths,
        folded_names,
        folded_paths,
        change_index,
        row_dir,
        own_dir_index,
        is_dir,
        change_sizes,
        change_dest_sizes,
    )

    has_exclusion = bool(model.exclusion)
    excluded = model._excluded_paths()
    excluded_get = excluded.get
    excluded_fn = model.exclusion.is_excluded
    row_excluded = [
        1 if (row.path and excluded_fn(row.path)) else 0 for row in rows
    ]
    row_explicit = [1 if excluded_get(row.path, False) else 0 for row in rows]
    folded_parent = folded_parent_flags(model)

    # The structure is supplied once for every scenario so the native kernel
    # can also produce the subtree totals. Only the flag computation differs.
    dir_paths = model._dir_paths
    change_dir = [
        model._dir_index.get(
            model._change_paths[ci]
            if model.changes[ci].kind is ObjectKind.DIRECTORY
            else model._change_parents[ci],
            0,
        )
        for ci in range(len(model.changes))
    ]
    change_is_dir = [
        change.kind is ObjectKind.DIRECTORY for change in model.changes
    ]
    change_action = [
        ACTION_CODE[action.value] for action in model._change_effective_actions
    ]
    dir_parent = [
        model._dir_index.get(model._directories[path].parent, -1)
        for path in dir_paths
    ]
    dir_own_change = [
        model._directories[path].own_change_index for path in dir_paths
    ]
    comparison.set_structure(
        change_dir,
        change_is_dir,
        change_action,
        dir_parent,
        dir_own_change,
    )

    if native_filter:
        # The kernel computes change and directory flags itself. Valid only
        # without a path pattern; those cases use the Stage 1 path below.
        visible_actions = model._visible_actions
        mask = (
            0
            if visible_actions is None
            else sum(1 << ACTION_CODE[action.value] for action in visible_actions)
        )
        comparison.filter(
            mask,
            model.filter_directories,
            has_exclusion,
            row_excluded,
            row_explicit,
            model.show_excluded,
            folded_parent,
            0,
        )
    else:
        row_visible: list[int] = []
        row_path_ok: list[int] = []
        row_faded: list[int] = []
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
            row_explicit.append(1 if excluded_get(row.path, False) else 0)

        comparison.apply(
            row_visible,
            row_path_ok,
            row_faded,
            row_excluded,
            row_explicit,
            folded_parent,
            has_exclusion,
            model.show_excluded,
            0,
        )

    counts = list(comparison.dir_counts)
    sizes = list(comparison.dir_sizes)
    width = len(model._dir_paths)
    counts += [0] * (width - len(counts))
    sizes += [0] * (width - len(sizes))
    flat = list(comparison.dir_totals)
    flat += [0] * (width * 5 - len(flat))
    total_counts = [flat[i * 5 : i * 5 + 5] for i in range(width)]
    return {
        "rows": list(comparison.visible_rows),
        "changes": sorted(comparison.visible_changes),
        "aggregates": [[counts[i], sizes[i]] for i in range(width)],
        "subtree": total_up(total_counts, model),
    }


def compare(
    name: str, model: FlatChangeModel, *, native_filter: bool = False
) -> None:
    python = python_signature(model)
    native = native_signature(model, native_filter=native_filter)
    for key in python:
        if python[key] != native[key]:
            raise AssertionError(
                f"{name}: {key} differs\n"
                f"  python: {python[key]}\n"
                f"  native: {native[key]}"
            )
    kind = "native-filter" if native_filter else "flags"
    print(
        f"{name} ({kind}): {len(python['rows'])} rows, "
        f"{len(python['changes'])} changes, matched"
    )


def main() -> None:
    # (name, configure, native_filter). Pattern cases only exercise the
    # Stage 1 flags path; the rest run the Stage 2 native flag kernel too.
    scenarios: list[tuple[str, object, bool]] = [
        ("default", lambda m: None, True),
        (
            "update-only",
            lambda m: m.set_visible_actions({ChangeAction.UPDATE_CONTENT}),
            True,
        ),
        (
            "create-or-delete",
            lambda m: m.set_visible_actions(
                {ChangeAction.CREATE, ChangeAction.DELETE}
            ),
            True,
        ),
        (
            "faded-dirs",
            lambda m: (
                m.set_visible_actions({ChangeAction.UPDATE_CONTENT}),
                setattr(m, "filter_directories", True),
                m._apply_filters(),
            ),
            True,
        ),
        ("path-substring", lambda m: m.set_path_filter("lib"), False),
        ("glob-name", lambda m: m.set_path_filter("*.py"), False),
        ("dir-contents", lambda m: m.set_path_filter("src/lib/"), False),
        (
            "excluded",
            lambda m: (
                m.decisions.set("src/lib/x.py", ChangeDecision.EXCLUDE),
                m.refresh_exclusions(),
            ),
            True,
        ),
        (
            "excluded-shown",
            lambda m: (
                m.decisions.set("src/lib/x.py", ChangeDecision.EXCLUDE),
                m.refresh_exclusions(),
                setattr(m, "show_excluded", True),
                m._apply_filters(),
            ),
            True,
        ),
        (
            "collapsed",
            lambda m: (setattr(m, "collapsed", {"src"}), m._apply_filters()),
            True,
        ),
    ]
    for name, configure, native_filter in scenarios:
        model = build_model()
        configure(model)
        compare(name, model, native_filter=native_filter)


if __name__ == "__main__":
    main()

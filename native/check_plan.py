"""Differential check: native plan kernel vs build_execution_plan.

The native kernel takes the effective "included" decision per change (Python
still owns decision inheritance) and produces plan item arrays, summary
counters and the exact byte stream hashed for items_fingerprint. This harness
rebuilds the equivalent Python objects and asserts byte-for-byte equality.
"""

from __future__ import annotations

import os
from hashlib import sha256

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qpy_rsync import _qpy_native  # noqa: E402
from qpy_rsync.core.changes import (  # noqa: E402
    Change,
    ChangeAction,
    ChangeDecision,
    ChangeDecisions,
    ObjectKind,
)
from qpy_rsync.core.enums import EndpointKind  # noqa: E402
from qpy_rsync.core.execution_plan import (  # noqa: E402
    PlanItem,
    build_execution_plan,
)
from qpy_rsync.core.models import Endpoint, SyncProfile  # noqa: E402

ACTIONS = (
    ChangeAction.CREATE,
    ChangeAction.UPDATE_CONTENT,
    ChangeAction.UPDATE_METADATA,
    ChangeAction.DELETE,
    ChangeAction.DESTINATION_ONLY,
    ChangeAction.NO_CHANGE,
    ChangeAction.MESSAGE,
)
KINDS = (
    ObjectKind.FILE,
    ObjectKind.DIRECTORY,
    ObjectKind.SYMLINK,
    ObjectKind.DEVICE,
    ObjectKind.SPECIAL,
    ObjectKind.UNKNOWN,
)
ACTION_CODE = {action: index for index, action in enumerate(ACTIONS)}
KIND_CODE = {kind: index for index, kind in enumerate(KINDS)}


def build_changes() -> list[Change]:
    def change(path: str, action: ChangeAction, kind: ObjectKind, size: int) -> Change:
        return Change(path, action, kind, ">f", size)

    return [
        change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, 10),
        change("updated.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, 20),
        change("meta/", ChangeAction.UPDATE_METADATA, ObjectKind.DIRECTORY, 0),
        change("gone.txt", ChangeAction.DELETE, ObjectKind.FILE, 30),
        change("dest.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, 40),
        change("kept.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, 50),
        change("untouched.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, 60),
        change("message", ChangeAction.MESSAGE, ObjectKind.FILE, 0),
        change("nested/deep.bin", ChangeAction.CREATE, ObjectKind.FILE, 70),
    ]


def native_result(changes: list[Change], decisions: ChangeDecisions):
    included = [
        1 if decisions.effective(change) is not ChangeDecision.EXCLUDE else 0
        for change in changes
    ]
    return _qpy_native.build_plan_arrays(
        [change.path for change in changes],
        [ACTION_CODE[change.action] for change in changes],
        [KIND_CODE[change.kind] for change in changes],
        [int(change.size or 0) for change in changes],
        [1 if change.size is None else 0 for change in changes],
        included,
    )


def make_profile() -> SyncProfile:
    return SyncProfile(
        "plan",
        Endpoint(EndpointKind.LOCAL, "/src/"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
    )


def python_items(changes: list[Change], decisions: ChangeDecisions) -> list[PlanItem]:
    plan = build_execution_plan(make_profile(), changes, decisions)
    return list(plan.items)


def check(name: str, changes: list[Change], decisions: ChangeDecisions) -> None:
    native = native_result(changes, decisions)
    expected = python_items(changes, decisions)

    assert len(native.paths) == len(expected), (name, len(native.paths), len(expected))
    digest = sha256(native.digest.encode("utf-8")).hexdigest()
    # The Python digest is computed over the same path/action/kind/included
    # stream. Verify it against the real plan's fingerprint below.
    items: list[PlanItem] = []
    for index, item in enumerate(expected):
        assert native.paths[index] == item.path, (name, index, "path")
        assert native.actions[index] == ACTION_CODE[item.action], (name, index, "action")
        assert native.comparison_actions[index] == ACTION_CODE[item.comparison_action]
        assert native.kinds[index] == KIND_CODE[item.kind], (name, index, "kind")
        assert bool(native.included[index]) is item.included
        assert bool(native.destructive[index]) is item.destructive
        assert native.sizes[index] == (item.size or 0)
        assert bool(native.size_none[index]) is (item.size is None)
        items.append(item)

    # Compare the digest stream byte-for-byte with the Python construction.
    expected_digest = ""
    for item in items:
        expected_digest += (
            item.path
            + item.action.value
            + item.kind.value
            + ("1" if item.included else "0")
        )
    assert native.digest == expected_digest, name

    plan = build_execution_plan(make_profile(), changes, decisions)
    assert digest == plan.items_fingerprint, (name, digest, plan.items_fingerprint)
    summary = plan.summary
    assert native.included_count == summary.included
    assert native.excluded == summary.excluded
    assert native.retained_destination_only == summary.retained_destination_only
    assert native.destructive_count == summary.destructive
    assert native.creates == summary.creates
    assert native.updates == summary.updates
    assert native.metadata == summary.metadata
    assert native.deletions == summary.deletions
    assert native.total_size == summary.total_size
    assert native.included_size == summary.included_size
    print(f"{name}: {len(items)} items, summary and fingerprint matched")


def main() -> None:
    changes = build_changes()
    empty = ChangeDecisions()
    check("no-decisions", changes, empty)

    with_include = ChangeDecisions()
    with_include.set("dest.txt", ChangeDecision.INCLUDE)
    check("dest-only-included", changes, with_include)

    with_exclude = ChangeDecisions()
    with_exclude.set("new.txt", ChangeDecision.EXCLUDE)
    with_exclude.set("nested", ChangeDecision.EXCLUDE)
    check("exclusions", changes, with_exclude)

    mixed = ChangeDecisions()
    mixed.set("dest.txt", ChangeDecision.INCLUDE)
    mixed.set("gone.txt", ChangeDecision.EXCLUDE)
    mixed.set("nested/deep.bin", ChangeDecision.EXCLUDE)
    check("mixed", changes, mixed)


if __name__ == "__main__":
    main()

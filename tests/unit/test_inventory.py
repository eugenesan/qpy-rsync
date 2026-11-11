from __future__ import annotations

from pathlib import Path

from qpy_rsync.backend.inventory import InventoryEntry, inventory_paths, unchanged_changes
from qpy_rsync.core.changes import ChangeAction, ObjectKind
from qpy_rsync.core.enums import EndpointKind, FilterRuleType
from qpy_rsync.core.models import Endpoint, FilterRule, SyncProfile


def _profile(root: Path) -> SyncProfile:
    return SyncProfile(
        "filtered",
        Endpoint(EndpointKind.LOCAL, f"{root / 'src'}/"),
        Endpoint(EndpointKind.LOCAL, f"{root / 'dst'}/"),
        filters=[FilterRule("*.tmp", rule_type=FilterRuleType.EXCLUDE)],
    )


def _trees(root: Path) -> SyncProfile:
    for base in ("src", "dst"):
        directory = root / base
        directory.mkdir()
        (directory / "keep.txt").write_text("keep", encoding="utf-8")
        (directory / "skip.tmp").write_text("skip", encoding="utf-8")
    return _profile(root)


def test_inventory_paths_honor_exclude_filters(tmp_path: Path) -> None:
    profile = _trees(tmp_path)

    source = inventory_paths(profile.source, profile)
    destination = inventory_paths(profile.destination, profile)

    assert list(source) == ["keep.txt"]
    assert list(destination) == ["keep.txt"]
    assert source["keep.txt"].kind is ObjectKind.FILE
    assert source["keep.txt"].size == 4
    assert source["keep.txt"].modified_time


def test_unchanged_changes_honor_exclude_filters(tmp_path: Path) -> None:
    profile = _trees(tmp_path)

    changes = unchanged_changes(profile, [])

    assert [(change.path, change.action) for change in changes] == [
        ("keep.txt", ChangeAction.NO_CHANGE)
    ]
    change = changes[0]
    assert change.size == 4
    assert change.modified_time
    assert change.destination_size == 4
    assert change.destination_time

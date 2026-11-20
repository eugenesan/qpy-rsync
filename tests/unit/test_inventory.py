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

    reports: list[int] = []
    source = inventory_paths(profile.source, profile, reports.append)
    destination = inventory_paths(profile.destination, profile)

    assert list(source) == ["keep.txt"]
    assert list(destination) == ["keep.txt"]
    assert reports and reports[-1] >= 1
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


def test_destination_metadata_uses_a_single_narrow_listing(tmp_path, monkeypatch) -> None:
    from qpy_rsync.backend.inventory import gather_destination_metadata
    from qpy_rsync.core.changes import Change

    profile = _profile(tmp_path)
    calls: list[object] = []

    def fake(endpoint, prof=None, progress=None):
        calls.append(prof)
        return {"old": InventoryEntry(ObjectKind.FILE, 321, "t")}

    monkeypatch.setattr("qpy_rsync.backend.inventory.inventory_paths", fake)
    change = Change("old", ChangeAction.DELETE, ObjectKind.FILE, "*deleting")
    result = gather_destination_metadata(profile, [change])
    assert result.destination_metadata["old"][0] == 321
    assert len(calls) == 1


def test_destination_metadata_lists_all_changed_paths_except_creates(tmp_path, monkeypatch) -> None:
    from qpy_rsync.backend.inventory import gather_destination_metadata
    from qpy_rsync.core.changes import Change

    profile = _profile(tmp_path)
    captured: list[object] = []

    def fake(endpoint, prof=None, progress=None):
        captured.append(prof)
        return {
            "old/a": InventoryEntry(ObjectKind.FILE, 12, "t"),
            "changed.txt": InventoryEntry(ObjectKind.FILE, 44, "t"),
            "keep.txt": InventoryEntry(ObjectKind.FILE, 99, "t"),
        }

    monkeypatch.setattr("qpy_rsync.backend.inventory.inventory_paths", fake)
    changes = [
        Change("old/a", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        Change("changed.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
        Change("keep.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
    ]
    result = gather_destination_metadata(profile, changes)
    assert result.destination_metadata["old/a"][0] == 12
    assert result.destination_metadata["changed.txt"][0] == 44
    # One unfiltered listing of the destination, not a pattern per changed
    # item and not a second listing for paths hidden by profile filters. The
    # original profile is left untouched.
    assert len(captured) == 1
    assert captured[0] is not profile
    assert captured[0].filters == []
    assert [rule.rule for rule in profile.filters] == ["*.tmp"]
    assert "keep.txt" not in result.destination_metadata


def test_destination_metadata_two_pass_is_available_for_ab(tmp_path, monkeypatch) -> None:
    from qpy_rsync.backend.inventory import gather_destination_metadata
    from qpy_rsync.core.changes import Change

    profile = _profile(tmp_path)
    captured: list[object] = []

    def fake(endpoint, prof=None, progress=None):
        captured.append(prof)
        return {}

    monkeypatch.setattr("qpy_rsync.backend.inventory.inventory_paths", fake)
    changes = [Change("old/a", ChangeAction.DELETE, ObjectKind.FILE, "*deleting")]
    gather_destination_metadata(profile, changes, two_pass=True)
    assert len(captured) == 2
    assert captured[0] is profile
    assert captured[1] is not profile
    assert captured[1].filters == []


def test_inventory_with_both_caches_needs_no_rsync(tmp_path, monkeypatch) -> None:
    from qpy_rsync.backend.inventory import gather_inventory
    from qpy_rsync.core.changes import Change

    profile = _profile(tmp_path)

    def fake(*_args, **_kwargs):
        raise AssertionError("no rsync should run when both sides are cached")

    monkeypatch.setattr("qpy_rsync.backend.inventory.inventory_paths", fake)
    source = {"same.txt": InventoryEntry(ObjectKind.FILE, 10, "t")}
    destination = {"same.txt": InventoryEntry(ObjectKind.FILE, 10, "t")}
    result = gather_inventory(
        profile,
        [Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")],
        destination_paths=destination,
        source_paths=source,
    )
    assert [change.path for change in result.unchanged] == ["same.txt"]


def test_inventory_reuses_cached_destination_and_lists_source_only(tmp_path, monkeypatch) -> None:
    from qpy_rsync.backend.inventory import gather_inventory
    from qpy_rsync.core.changes import Change

    profile = _profile(tmp_path)
    seen: list[object] = []

    def fake(endpoint, prof=None, progress=None):
        seen.append(endpoint)
        if endpoint == profile.source:
            return {
                "same.txt": InventoryEntry(ObjectKind.FILE, 10, "t"),
                "new.txt": InventoryEntry(ObjectKind.FILE, 20, "t"),
            }
        raise AssertionError("destination must not be listed when cached")

    monkeypatch.setattr("qpy_rsync.backend.inventory.inventory_paths", fake)
    cached = {
        "same.txt": InventoryEntry(ObjectKind.FILE, 10, "t"),
        "gone.txt": InventoryEntry(ObjectKind.FILE, 30, "t"),
    }
    result = gather_inventory(
        profile,
        [Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")],
        destination_paths=cached,
    )
    assert seen == [profile.source]
    assert [change.path for change in result.unchanged] == ["same.txt"]
    assert result.destination_metadata["gone.txt"][0] == 30

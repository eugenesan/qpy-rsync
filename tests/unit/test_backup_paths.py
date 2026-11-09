from qpy_rsync.core.backup_paths import backup_protection_arguments, resolve_backup
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import BackupOptions, Endpoint, SyncProfile


def profile(backup: str, *, protect: bool = True) -> SyncProfile:
    return SyncProfile(
        name="backup",
        source=Endpoint(EndpointKind.LOCAL, "/src/"),
        destination=Endpoint(EndpointKind.LOCAL, "/dst/"),
        backup=BackupOptions(directory=backup, protect_nested=protect),
    )


def test_nested_destination_resolves_protection_pattern() -> None:
    resolved = resolve_backup(profile("/dst/.backup/"))
    assert resolved is not None
    assert resolved.nested_in_destination
    assert resolved.protection_pattern == "/.backup/***"
    assert backup_protection_arguments(profile("/dst/.backup/")) == [
        "--filter", "P /.backup/***", "--filter", "- /.backup/***"
    ]


def test_nested_protection_can_be_disabled() -> None:
    assert backup_protection_arguments(profile("/dst/.backup", protect=False)) == []


def test_external_backup_has_no_protection_pattern() -> None:
    resolved = resolve_backup(profile("/recovery"))
    assert resolved is not None
    assert resolved.protection_pattern is None

from qpy_rsync.core.backup_paths import backup_summary


def test_backup_summary_reports_nested_protection() -> None:
    summary = backup_summary(profile("/dst/.backup"))
    assert summary.enabled
    assert summary.directory == "/dst/.backup"
    assert summary.nested_in_destination
    assert summary.protects_nested_tree


def test_disabled_backup_summary() -> None:
    summary = backup_summary(profile(""))
    assert not summary.enabled
    assert summary.directory is None

def test_local_home_paths_are_expanded_for_nesting(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/home/tester")
    item = SyncProfile(
        name="home",
        source=Endpoint(EndpointKind.LOCAL, "~/source/"),
        destination=Endpoint(EndpointKind.LOCAL, "~/destination/"),
        backup=BackupOptions(directory="~/destination/.backup"),
    )
    resolved = resolve_backup(item)
    assert resolved is not None
    assert resolved.directory == "/home/tester/destination/.backup"
    assert resolved.nested_in_destination
    assert resolved.protection_pattern == "/.backup/***"


def test_relative_backup_is_resolved_inside_destination() -> None:
    item = profile(".backup")
    resolved = resolve_backup(item)
    assert resolved is not None
    assert resolved.directory == "/dst/.backup"
    assert resolved.nested_in_destination
    assert resolved.protection_pattern == "/.backup/***"

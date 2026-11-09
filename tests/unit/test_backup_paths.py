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

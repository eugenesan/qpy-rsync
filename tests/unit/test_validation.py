from qpy_rsync.core.enums import EndpointKind, Severity
from qpy_rsync.core.models import Endpoint, SyncProfile
from qpy_rsync.core.validation import validate_profile


def test_two_remote_endpoints_are_rejected() -> None:
    profile = SyncProfile(name="bad", source=Endpoint(EndpointKind.SSH, "/a", host="one"), destination=Endpoint(EndpointKind.SSH, "/b", host="two"))
    assert any(message.code == "endpoints.two_remote" and message.severity is Severity.ERROR for message in validate_profile(profile))


def test_empty_backup_directory_disables_backup() -> None:
    profile = SyncProfile(name="backup", source=Endpoint(EndpointKind.LOCAL, "/a"), destination=Endpoint(EndpointKind.LOCAL, "/b"))
    assert not profile.backup.enabled
    assert not any(message.code.startswith("backup.") for message in validate_profile(profile))

from qpy_rsync.core.models import BackupOptions


def backup_profile(directory: str, *, protect_nested: bool = True) -> SyncProfile:
    return SyncProfile(
        name="backup",
        source=Endpoint(EndpointKind.LOCAL, "/src/"),
        destination=Endpoint(EndpointKind.LOCAL, "/dst/"),
        backup=BackupOptions(directory=directory, protect_nested=protect_nested),
    )


def test_backup_root_and_remote_operand_are_rejected() -> None:
    root_codes = {message.code for message in validate_profile(backup_profile("/"))}
    remote_codes = {message.code for message in validate_profile(backup_profile("nas:/backup"))}
    assert "backup.directory.root" in root_codes
    assert "backup.directory.remote_operand" in remote_codes


def test_nested_backup_warns_and_unprotected_adds_warning() -> None:
    protected = {message.code for message in validate_profile(backup_profile("/dst/.backup"))}
    unprotected = {
        message.code
        for message in validate_profile(backup_profile("/dst/.backup", protect_nested=False))
    }
    assert "backup.directory.inside_destination" in protected
    assert "backup.directory.unprotected" not in protected
    assert "backup.directory.unprotected" in unprotected

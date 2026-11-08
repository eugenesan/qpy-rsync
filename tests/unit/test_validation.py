from qpy_rsync.core.enums import BackupMode, EndpointKind, Severity
from qpy_rsync.core.models import Endpoint, SyncProfile
from qpy_rsync.core.validation import validate_profile


def test_two_remote_endpoints_are_rejected() -> None:
    profile = SyncProfile(name="bad", source=Endpoint(EndpointKind.SSH, "/a", host="one"), destination=Endpoint(EndpointKind.SSH, "/b", host="two"))
    assert any(message.code == "endpoints.two_remote" and message.severity is Severity.ERROR for message in validate_profile(profile))


def test_backup_mode_requires_directory() -> None:
    profile = SyncProfile(name="backup", source=Endpoint(EndpointKind.LOCAL, "/a"), destination=Endpoint(EndpointKind.LOCAL, "/b"))
    profile.backup.mode = BackupMode.BOTH
    assert any(message.code == "backup.directory.empty" for message in validate_profile(profile))

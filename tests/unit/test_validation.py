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

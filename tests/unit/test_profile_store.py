from pathlib import Path

from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import Endpoint, SyncProfile
from qpy_rsync.storage.profile_store import load_profile, save_profile


def test_profile_round_trip(tmp_path: Path) -> None:
    profile = SyncProfile(name="documents", source=Endpoint(EndpointKind.LOCAL, "/home/me/Documents/"), destination=Endpoint(EndpointKind.SSH, "/backup/Documents/", host="nas", user="me"))
    path = tmp_path / "profile.json"
    save_profile(path, profile)
    loaded = load_profile(path)
    assert loaded.name == profile.name
    assert loaded.destination.rsync_operand() == "me@nas:/backup/Documents/"
    assert loaded.profile_id == profile.profile_id

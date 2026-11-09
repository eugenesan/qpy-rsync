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

from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule


def test_profile_round_trip_preserves_typed_filters(tmp_path: Path) -> None:
    profile = SyncProfile(name="filters", source=Endpoint(EndpointKind.LOCAL, "/a"), destination=Endpoint(EndpointKind.LOCAL, "/b"))
    profile.filters = [FilterRule("*.tmp", rule_type=FilterRuleType.EXCLUDE, comment="temporary")]
    path = tmp_path / "filters.json"
    save_profile(path, profile)
    loaded = load_profile(path)
    assert loaded.filters == profile.filters

from qpy_rsync.core.models import BackupOptions


def test_profile_round_trip_preserves_backup_options(tmp_path: Path) -> None:
    profile = SyncProfile(
        name="backup",
        source=Endpoint(EndpointKind.LOCAL, "/a"),
        destination=Endpoint(EndpointKind.LOCAL, "/b"),
        backup=BackupOptions(directory="/recovery", protect_nested=False),
    )
    path = tmp_path / "backup.json"
    save_profile(path, profile)
    loaded = load_profile(path)
    assert loaded.schema_version == 3
    assert loaded.backup == profile.backup


def test_legacy_backup_none_disables_backup(tmp_path: Path) -> None:
    path = tmp_path / "legacy-none.json"
    path.write_text(
        '{"name":"legacy","source":{"kind":"local","path":"/a"},'
        '"destination":{"kind":"local","path":"/b"},'
        '"backup":{"mode":"none","directory":"/old"}}',
        encoding="utf-8",
    )
    assert not load_profile(path).backup.enabled


def test_legacy_enabled_mode_keeps_configured_directory(tmp_path: Path) -> None:
    path = tmp_path / "legacy-both.json"
    path.write_text(
        '{"name":"legacy","source":{"kind":"local","path":"/a"},'
        '"destination":{"kind":"local","path":"/b"},'
        '"backup":{"mode":"both","directory":"/recovery"}}',
        encoding="utf-8",
    )
    loaded = load_profile(path)
    assert loaded.backup.enabled
    assert loaded.backup.directory == "/recovery"
    assert loaded.backup.protect_nested

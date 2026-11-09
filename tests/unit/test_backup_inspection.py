from pathlib import Path

from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import BackupOptions, Endpoint, SyncProfile
from qpy_rsync.services.backup_inspection import (
    BackupDirectoryState,
    inspect_backup_directory,
)


def profile(directory: str, *, remote: bool = False) -> SyncProfile:
    destination = (
        Endpoint(EndpointKind.SSH, "/dst/", host="nas")
        if remote
        else Endpoint(EndpointKind.LOCAL, "/dst/")
    )
    return SyncProfile(
        name="backup",
        source=Endpoint(EndpointKind.LOCAL, "/src/"),
        destination=destination,
        backup=BackupOptions(directory=directory),
    )


def test_disabled_backup_is_not_inspected() -> None:
    status = inspect_backup_directory(profile(""))
    assert status.state is BackupDirectoryState.DISABLED
    assert status.nonempty is None


def test_missing_local_backup_directory_is_not_an_error(tmp_path: Path) -> None:
    status = inspect_backup_directory(profile(str(tmp_path / "missing")))
    assert status.state is BackupDirectoryState.MISSING
    assert status.nonempty is False


def test_empty_and_nonempty_local_directories(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert inspect_backup_directory(profile(str(empty))).state is BackupDirectoryState.EMPTY
    (empty / "old.txt").write_text("old", encoding="utf-8")
    status = inspect_backup_directory(profile(str(empty)))
    assert status.state is BackupDirectoryState.NONEMPTY
    assert status.nonempty is True
    assert "may replace older files" in status.message


def test_existing_file_is_unknown(tmp_path: Path) -> None:
    path = tmp_path / "not-a-directory"
    path.write_text("x", encoding="utf-8")
    status = inspect_backup_directory(profile(str(path)))
    assert status.state is BackupDirectoryState.UNKNOWN
    assert status.nonempty is None


def test_remote_backup_directory_is_not_probed() -> None:
    status = inspect_backup_directory(profile("/recovery", remote=True))
    assert status.state is BackupDirectoryState.UNCHECKED_REMOTE
    assert status.nonempty is None

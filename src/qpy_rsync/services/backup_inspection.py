from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import SyncProfile


class BackupDirectoryState(StrEnum):
    DISABLED = "disabled"
    MISSING = "missing"
    EMPTY = "empty"
    NONEMPTY = "nonempty"
    UNCHECKED_REMOTE = "unchecked_remote"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class BackupDirectoryStatus:
    state: BackupDirectoryState
    directory: str | None
    message: str

    @property
    def nonempty(self) -> bool | None:
        if self.state is BackupDirectoryState.NONEMPTY:
            return True
        if self.state in {BackupDirectoryState.MISSING, BackupDirectoryState.EMPTY}:
            return False
        return None


def inspect_backup_directory(profile: SyncProfile) -> BackupDirectoryStatus:
    if not profile.backup.enabled:
        return BackupDirectoryStatus(
            BackupDirectoryState.DISABLED,
            None,
            "Backups are disabled.",
        )

    directory = profile.backup.directory.strip()
    if profile.destination.kind is EndpointKind.SSH:
        return BackupDirectoryStatus(
            BackupDirectoryState.UNCHECKED_REMOTE,
            directory,
            "Remote backup directory contents were not checked.",
        )

    path = Path(directory).expanduser()
    try:
        if not path.exists():
            return BackupDirectoryStatus(
                BackupDirectoryState.MISSING,
                str(path),
                "Backup directory does not exist yet and may be created by rsync.",
            )
        if not path.is_dir():
            return BackupDirectoryStatus(
                BackupDirectoryState.UNKNOWN,
                str(path),
                "Backup path exists but is not a directory.",
            )
        nonempty = next(path.iterdir(), None) is not None
    except OSError as exc:
        return BackupDirectoryStatus(
            BackupDirectoryState.UNKNOWN,
            str(path),
            f"Backup directory contents could not be checked: {exc}",
        )

    if nonempty:
        return BackupDirectoryStatus(
            BackupDirectoryState.NONEMPTY,
            str(path),
            "Backup directory is not empty; new backups may replace older files with the same relative paths.",
        )
    return BackupDirectoryStatus(
        BackupDirectoryState.EMPTY,
        str(path),
        "Backup directory is empty.",
    )

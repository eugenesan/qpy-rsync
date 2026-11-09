from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import posixpath
import re
from os.path import expanduser

from .enums import EndpointKind
from .models import SyncProfile


_REMOTE_OPERAND = re.compile(r"^(?:[^/@:]+@)?[^/:]+:/.+")


@dataclass(slots=True, frozen=True)
class ResolvedBackup:
    directory: str
    nested_in_source: bool
    nested_in_destination: bool
    contains_source: bool
    contains_destination: bool
    protection_pattern: str | None


def normalize_posix_path(value: str) -> str:
    stripped = value.strip()
    normalized = posixpath.normpath(stripped)
    return "/" if normalized == "//" else normalized


def is_remote_operand(value: str) -> bool:
    return bool(_REMOTE_OPERAND.match(value.strip()))


def _is_within(path: str, root: str) -> bool:
    if not path.startswith("/") or not root.startswith("/"):
        return False
    return path != root and path.startswith(root.rstrip("/") + "/")


def _relative_pattern(path: str, root: str) -> str | None:
    if not _is_within(path, root):
        return None
    relative = PurePosixPath(path).relative_to(PurePosixPath(root))
    return f"/{relative.as_posix().rstrip('/')}/***"


def destination_backup_directory(profile: SyncProfile) -> str:
    directory = profile.backup.directory.strip()
    if profile.destination.kind is EndpointKind.LOCAL:
        directory = expanduser(directory)
    return normalize_posix_path(directory)


def resolved_backup_path(profile: SyncProfile) -> str:
    directory = destination_backup_directory(profile)
    if directory.startswith("/"):
        return directory
    destination = _endpoint_path(profile, source=False)
    if destination.startswith("/"):
        return normalize_posix_path(posixpath.join(destination, directory))
    return directory


def _endpoint_path(profile: SyncProfile, *, source: bool) -> str:
    endpoint = profile.source if source else profile.destination
    path = endpoint.path
    if endpoint.kind is EndpointKind.LOCAL:
        path = expanduser(path)
    return normalize_posix_path(path)


def resolve_backup(profile: SyncProfile) -> ResolvedBackup | None:
    if not profile.backup.enabled:
        return None
    directory = resolved_backup_path(profile)
    source = _endpoint_path(profile, source=True)
    destination = _endpoint_path(profile, source=False)
    nested_source = _is_within(directory, source)
    nested_destination = _is_within(directory, destination)
    pattern = _relative_pattern(directory, source) or _relative_pattern(directory, destination)
    return ResolvedBackup(
        directory=directory,
        nested_in_source=nested_source,
        nested_in_destination=nested_destination,
        contains_source=_is_within(source, directory),
        contains_destination=_is_within(destination, directory),
        protection_pattern=pattern,
    )


def backup_protection_arguments(profile: SyncProfile) -> list[str]:
    resolved = resolve_backup(profile)
    if (
        resolved is None
        or not profile.backup.protect_nested
        or resolved.protection_pattern is None
    ):
        return []
    return [
        "--filter",
        f"P {resolved.protection_pattern}",
        "--filter",
        f"- {resolved.protection_pattern}",
    ]

@dataclass(slots=True, frozen=True)
class BackupSummary:
    enabled: bool
    directory: str | None
    protects_nested_tree: bool
    nested_in_source: bool
    nested_in_destination: bool


def backup_summary(profile: SyncProfile) -> BackupSummary:
    resolved = resolve_backup(profile)
    if resolved is None:
        return BackupSummary(False, None, False, False, False)
    return BackupSummary(
        enabled=True,
        directory=resolved.directory,
        protects_nested_tree=bool(
            profile.backup.protect_nested and resolved.protection_pattern
        ),
        nested_in_source=resolved.nested_in_source,
        nested_in_destination=resolved.nested_in_destination,
    )

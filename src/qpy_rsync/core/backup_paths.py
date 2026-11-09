from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import posixpath
import re

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


def resolve_backup(profile: SyncProfile) -> ResolvedBackup | None:
    if not profile.backup.enabled:
        return None
    directory = normalize_posix_path(profile.backup.directory)
    source = normalize_posix_path(profile.source.path)
    destination = normalize_posix_path(profile.destination.path)
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

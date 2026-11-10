from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex

from qpy_rsync.core.backup_paths import backup_protection_arguments, destination_backup_directory
from qpy_rsync.core.enums import DeleteTiming, EndpointKind, SyncMode
from qpy_rsync.core.models import SyncProfile
from qpy_rsync.core.validation import has_errors, validate_profile

from .filter_arguments import filter_arguments
from .ssh_askpass import askpass_environment

ITEM_SEPARATOR = "|qpy-rsync|"
DEFAULT_OUT_FORMAT = f"%i{ITEM_SEPARATOR}%l{ITEM_SEPARATOR}%M{ITEM_SEPARATOR}%n%L"


@dataclass(slots=True, frozen=True)
class ProcessSpec:
    program: str
    arguments: tuple[str, ...]
    environment: dict[str, str]

    def argv(self) -> list[str]:
        return [self.program, *self.arguments]


class InvalidProfileError(ValueError):
    pass


def _common_arguments(profile: SyncProfile, *, filter_file: Path | None = None) -> list[str]:
    messages = validate_profile(profile)
    if has_errors(messages):
        detail = "; ".join(message.message for message in messages if message.severity.value == "error")
        raise InvalidProfileError(detail)

    args: list[str] = []
    preserve = profile.preservation
    transfer = profile.transfer

    if preserve.archive:
        args.append("--archive")
    if preserve.hard_links:
        args.append("--hard-links")
    if preserve.acls:
        args.append("--acls")
    if preserve.xattrs:
        args.append("--xattrs")
    if preserve.numeric_ids:
        args.append("--numeric-ids")

    if transfer.copy_links:
        args.append("--copy-links")
    if transfer.whole_file:
        args.append("--whole-file")
    if transfer.relative:
        args.append("--relative")
    args.append("--compress" if transfer.compress else "--no-compress")
    if transfer.inplace:
        args.append("--inplace")
    if transfer.one_file_system:
        args.append("--one-file-system")
    if transfer.sparse:
        args.append("--sparse")
    if transfer.ignore_times:
        args.append("--ignore-times")
    if transfer.fuzzy:
        args.append("--fuzzy")

    if transfer.mirror_enabled:
        timing = DeleteTiming.AFTER if transfer.fuzzy else transfer.delete_timing
        args.append(f"--delete-{timing.value}")
    if transfer.new_only_enabled:
        args.append("--ignore-existing")

    if profile.backup.enabled:
        args.extend(("--backup", f"--backup-dir={destination_backup_directory(profile)}"))

    args.extend(backup_protection_arguments(profile))
    if filter_file is not None:
        args.append(f"--filter=merge {filter_file}")
    args.extend(filter_arguments(profile.filters))

    return args



def _process_environment(profile: SyncProfile) -> dict[str, str]:
    # Do not force the ASCII C locale: Qt-based askpass helpers require UTF-8.
    # The controlled rsync record format is locale-independent.
    environment: dict[str, str] = {}
    if EndpointKind.SSH in {profile.source.kind, profile.destination.kind}:
        environment.update(askpass_environment())
    return environment


def _has_remote_endpoint(profile: SyncProfile) -> bool:
    return EndpointKind.SSH in {profile.source.kind, profile.destination.kind}


def _remote_shell_argument(profile: SyncProfile) -> str | None:
    if not _has_remote_endpoint(profile):
        return None
    display = os.environ.get("DISPLAY", "").strip()
    if not display:
        return "ssh"
    return f"env DISPLAY={shlex.quote(display)} ssh"


def _process_spec(profile: SyncProfile, arguments: list[str]) -> ProcessSpec:
    environment = _process_environment(profile)
    if _has_remote_endpoint(profile):
        return ProcessSpec("setsid", ("--wait", "rsync", *arguments), environment)
    return ProcessSpec("rsync", tuple(arguments), environment)

def build_compare_spec(profile: SyncProfile, *, filter_file: Path | None = None) -> ProcessSpec:
    args = ["--dry-run", "--itemize-changes", f"--out-format={DEFAULT_OUT_FORMAT}"]
    remote_shell = _remote_shell_argument(profile)
    if remote_shell is not None:
        args.extend(("-e", remote_shell))
    args.extend(_common_arguments(profile, filter_file=filter_file))
    # A one-way preview must inventory destination-only objects even when the
    # execution profile is configured to keep them. Dry-run makes this safe.
    # The parser labels them DESTINATION_ONLY unless deletion is enabled.
    if not profile.transfer.mirror_enabled:
        # Inventory destination-only objects for the comparison while the parser
        # keeps them as retained, non-executable rows.
        args.append("--delete-during")
    args.extend(("--", profile.source.rsync_operand(), profile.destination.rsync_operand()))
    return _process_spec(profile, args)


def build_sync_spec(profile: SyncProfile, *, filter_file: Path | None = None) -> ProcessSpec:
    args = ["--itemize-changes", "--info=progress2", "--stats", f"--out-format={DEFAULT_OUT_FORMAT}"]
    remote_shell = _remote_shell_argument(profile)
    if remote_shell is not None:
        args.extend(("-e", remote_shell))
    args.extend(_common_arguments(profile, filter_file=filter_file))
    args.extend(("--", profile.source.rsync_operand(), profile.destination.rsync_operand()))
    return _process_spec(profile, args)

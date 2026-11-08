from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qpy_rsync.core.enums import BackupMode, DeleteTiming, EndpointKind
from qpy_rsync.core.models import SyncProfile
from qpy_rsync.core.validation import has_errors, validate_profile

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


def _common_arguments(profile: SyncProfile) -> list[str]:
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

    if transfer.delete:
        timing = DeleteTiming.AFTER if transfer.fuzzy else transfer.delete_timing
        args.append(f"--delete-{timing.value}")

    if profile.backup.mode is not BackupMode.NONE:
        args.extend(("--backup", f"--backup-dir={profile.backup.directory}"))

    for filter_rule in profile.filters:
        if filter_rule.enabled:
            args.extend(("--filter", filter_rule.rule))

    return args



def _process_environment(profile: SyncProfile) -> dict[str, str]:
    environment = {"LC_ALL": "C"}
    if EndpointKind.SSH in {profile.source.kind, profile.destination.kind}:
        environment.update(askpass_environment())
    return environment

def build_compare_spec(profile: SyncProfile, *, filter_file: Path | None = None) -> ProcessSpec:
    args = ["--dry-run", "--itemize-changes", f"--out-format={DEFAULT_OUT_FORMAT}"]
    args.extend(_common_arguments(profile))
    # A one-way preview must inventory destination-only objects even when the
    # execution profile is configured to keep them. Dry-run makes this safe.
    # The parser labels them DESTINATION_ONLY unless deletion is enabled.
    if not profile.transfer.delete:
        args.append("--delete-during")
    if filter_file is not None:
        args.append(f"--filter=merge {filter_file}")
    args.extend(("--", profile.source.rsync_operand(), profile.destination.rsync_operand()))
    return ProcessSpec("rsync", tuple(args), _process_environment(profile))


def build_sync_spec(profile: SyncProfile, *, filter_file: Path | None = None) -> ProcessSpec:
    args = ["--itemize-changes", "--info=progress2", "--stats", f"--out-format={DEFAULT_OUT_FORMAT}"]
    args.extend(_common_arguments(profile))
    if filter_file is not None:
        args.append(f"--filter=merge {filter_file}")
    args.extend(("--", profile.source.rsync_operand(), profile.destination.rsync_operand()))
    return ProcessSpec("rsync", tuple(args), _process_environment(profile))

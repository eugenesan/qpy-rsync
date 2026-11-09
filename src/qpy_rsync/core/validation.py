from __future__ import annotations

from dataclasses import dataclass

from .enums import DeleteTiming, EndpointKind, Severity
from .models import SyncProfile


@dataclass(slots=True, frozen=True)
class ValidationMessage:
    severity: Severity
    code: str
    message: str


def validate_profile(profile: SyncProfile) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []

    if not profile.name.strip():
        messages.append(ValidationMessage(Severity.ERROR, "profile.name.empty", "Profile name is required."))
    if not profile.source.path:
        messages.append(ValidationMessage(Severity.ERROR, "source.path.empty", "Source path is required."))
    if not profile.destination.path:
        messages.append(ValidationMessage(Severity.ERROR, "destination.path.empty", "Destination path is required."))
    if profile.source.kind is EndpointKind.SSH and not profile.source.host:
        messages.append(ValidationMessage(Severity.ERROR, "source.ssh.host", "SSH source requires a host."))
    if profile.destination.kind is EndpointKind.SSH and not profile.destination.host:
        messages.append(ValidationMessage(Severity.ERROR, "destination.ssh.host", "SSH destination requires a host."))
    if profile.source.kind is EndpointKind.SSH and profile.destination.kind is EndpointKind.SSH:
        messages.append(ValidationMessage(Severity.ERROR, "endpoints.two_remote", "rsync cannot copy between two remote endpoints in one invocation."))

    transfer = profile.transfer
    if transfer.fuzzy and not transfer.delete:
        messages.append(ValidationMessage(Severity.WARNING, "fuzzy.no_delete", "Fuzzy matching works without deletion, but deleted destination candidates are only retained for reuse when deletion is enabled."))
    if transfer.fuzzy and transfer.delete_timing is not DeleteTiming.AFTER:
        messages.append(ValidationMessage(Severity.WARNING, "fuzzy.delete_timing", "Fuzzy rename optimization should use delete-after so candidate basis files survive until transfer completes."))
    if transfer.inplace:
        messages.append(ValidationMessage(Severity.WARNING, "transfer.inplace", "In-place updates reduce interruption safety and may expose partially updated destination files."))
    if transfer.copy_links:
        messages.append(ValidationMessage(Severity.WARNING, "transfer.copy_links", "Copying symlink targets can traverse outside the apparent source tree."))
    if transfer.ignore_times:
        messages.append(ValidationMessage(Severity.INFO, "transfer.ignore_times", "Ignore-times transfers every file even when size and modification time match."))

    backup = profile.backup
    if backup.enabled and backup.directory.strip() in {profile.source.path, profile.destination.path}:
        messages.append(ValidationMessage(Severity.ERROR, "backup.directory.endpoint", "Backup directory cannot equal the source or destination path."))

    return messages


def has_errors(messages: list[ValidationMessage]) -> bool:
    return any(message.severity is Severity.ERROR for message in messages)

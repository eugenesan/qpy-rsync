from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from .enums import BackupMode, ConflictPolicy, DeleteTiming, EndpointKind


@dataclass(slots=True, frozen=True)
class Endpoint:
    kind: EndpointKind
    path: str
    host: str | None = None
    user: str | None = None

    def rsync_operand(self) -> str:
        if self.kind is EndpointKind.LOCAL:
            return self.path
        if not self.host:
            raise ValueError("SSH endpoint requires a host")
        authority = f"{self.user}@{self.host}" if self.user else self.host
        return f"{authority}:{self.path}"

    def display_name(self) -> str:
        return self.rsync_operand()


@dataclass(slots=True)
class PreservationOptions:
    archive: bool = True
    hard_links: bool = False
    acls: bool = False
    xattrs: bool = False
    numeric_ids: bool = False


@dataclass(slots=True)
class TransferOptions:
    delete: bool = False
    delete_timing: DeleteTiming = DeleteTiming.DURING
    fuzzy: bool = False
    copy_links: bool = False
    whole_file: bool = False
    relative: bool = False
    compress: bool = False
    inplace: bool = False
    one_file_system: bool = False
    sparse: bool = False
    ignore_times: bool = False


@dataclass(slots=True)
class BackupOptions:
    mode: BackupMode = BackupMode.NONE
    directory: str | None = None


@dataclass(slots=True)
class FilterRule:
    rule: str
    enabled: bool = True


@dataclass(slots=True)
class SyncProfile:
    name: str
    source: Endpoint
    destination: Endpoint
    profile_id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    schema_version: int = 1
    conflict_policy: ConflictPolicy = ConflictPolicy.OVERRIDE
    preservation: PreservationOptions = field(default_factory=PreservationOptions)
    transfer: TransferOptions = field(default_factory=TransferOptions)
    backup: BackupOptions = field(default_factory=BackupOptions)
    filters: list[FilterRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def normalized_relative_path(path: str) -> str:
        normalized = str(PurePosixPath(path))
        if normalized == ".":
            return ""
        if normalized.startswith("../") or normalized == "..":
            raise ValueError("Relative path may not escape the synchronization root")
        return normalized

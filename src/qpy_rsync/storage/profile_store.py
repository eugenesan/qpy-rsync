from __future__ import annotations

import json
import os
import tempfile
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from qpy_rsync.core.enums import BackupMode, ConflictPolicy, DeleteTiming, EndpointKind, FilterRuleType
from qpy_rsync.core.models import BackupOptions, Endpoint, FilterRule, PreservationOptions, SyncProfile, TransferOptions


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def save_profile(path: Path, profile: SyncProfile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_jsonable(profile), indent=2, sort_keys=True) + "\n"
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def load_profile(path: Path) -> SyncProfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    source = Endpoint(kind=EndpointKind(raw["source"]["kind"]), path=raw["source"]["path"], host=raw["source"].get("host"), user=raw["source"].get("user"))
    destination = Endpoint(kind=EndpointKind(raw["destination"]["kind"]), path=raw["destination"]["path"], host=raw["destination"].get("host"), user=raw["destination"].get("user"))
    preservation = PreservationOptions(**raw.get("preservation", {}))
    transfer_raw = raw.get("transfer", {}).copy()
    if "delete_timing" in transfer_raw:
        transfer_raw["delete_timing"] = DeleteTiming(transfer_raw["delete_timing"])
    transfer = TransferOptions(**transfer_raw)
    backup_raw = raw.get("backup", {}).copy()
    if "mode" in backup_raw:
        backup_raw["mode"] = BackupMode(backup_raw["mode"])
    backup = BackupOptions(**backup_raw)
    filters = []
    for item in raw.get("filters", []):
        value = item.copy()
        value["rule_type"] = FilterRuleType(value.get("rule_type", "advanced"))
        filters.append(FilterRule(**value))
    return SyncProfile(name=raw["name"], description=raw.get("description", ""), source=source, destination=destination, profile_id=raw.get("profile_id", ""), schema_version=raw.get("schema_version", 1), conflict_policy=ConflictPolicy(raw.get("conflict_policy", "override")), preservation=preservation, transfer=transfer, backup=backup, filters=filters)

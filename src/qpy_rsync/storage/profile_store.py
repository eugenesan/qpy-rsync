from __future__ import annotations

import json
import os
import tempfile
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from qpy_rsync.backend.rsync_filters import filter_text_to_rules
from qpy_rsync.core.enums import ConflictPolicy, DeleteTiming, EndpointKind, SyncMode
from qpy_rsync.core.models import BackupOptions, Endpoint, PreservationOptions, SyncProfile, TransferOptions


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def profile_to_json(profile: SyncProfile) -> str:
    """Serialize a profile with the filter text as a list of lines.

    Storing the editor text as ``filter_lines`` keeps it human-editable and
    avoids backslash-n escapes in the JSON file. The derived ``filters`` list
    is rebuilt from those lines when the profile is loaded.
    """
    data = _jsonable(profile)
    text = str(data.pop("filter_text", ""))
    data.pop("filters", None)
    data["filter_lines"] = text.split("\n")
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def save_profile(path: Path, profile: SyncProfile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = profile_to_json(profile)
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


def profile_from_json(payload: str) -> SyncProfile:
    return _profile_from_dict(json.loads(payload))


def load_profile(path: Path) -> SyncProfile:
    return profile_from_json(path.read_text(encoding="utf-8"))


def _profile_from_dict(raw: dict[str, Any]) -> SyncProfile:
    source = Endpoint(kind=EndpointKind(raw["source"]["kind"]), path=raw["source"]["path"], host=raw["source"].get("host"), user=raw["source"].get("user"))
    destination = Endpoint(kind=EndpointKind(raw["destination"]["kind"]), path=raw["destination"]["path"], host=raw["destination"].get("host"), user=raw["destination"].get("user"))
    preservation = PreservationOptions(**raw.get("preservation", {}))
    transfer_raw = raw.get("transfer", {}).copy()
    if "delete_timing" in transfer_raw:
        transfer_raw["delete_timing"] = DeleteTiming(transfer_raw["delete_timing"])
    if "sync_mode" in transfer_raw:
        transfer_raw["sync_mode"] = SyncMode(transfer_raw["sync_mode"])
    else:
        transfer_raw["sync_mode"] = (
            SyncMode.MIRROR if transfer_raw.get("delete", False) else SyncMode.UPDATE
        )
    # The stored legacy Boolean is consumed by migration and must not override mode.
    transfer_raw["delete"] = False
    transfer = TransferOptions(**transfer_raw)
    backup_raw = raw.get("backup", {}).copy()
    backup_directory = str(backup_raw.get("directory") or "")
    if "mode" in backup_raw:
        legacy_mode = str(backup_raw.pop("mode"))
        if legacy_mode == "none":
            backup_directory = ""
    backup = BackupOptions(
        directory=backup_directory,
        protect_nested=bool(backup_raw.get("protect_nested", True)),
    )
    filter_lines = raw.get("filter_lines", [])
    filter_text = "\n".join(str(line) for line in filter_lines) if filter_lines else ""
    filters = filter_text_to_rules(filter_text)
    return SyncProfile(name=raw["name"], description=raw.get("description", ""), source=source, destination=destination, profile_id=raw.get("profile_id", ""), schema_version=raw.get("schema_version", 1), conflict_policy=ConflictPolicy(raw.get("conflict_policy", "override")), preservation=preservation, transfer=transfer, backup=backup, filters=filters, filter_text=filter_text, inventory_after_compare=bool(raw.get("inventory_after_compare", False)))

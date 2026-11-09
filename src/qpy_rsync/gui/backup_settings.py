from __future__ import annotations

import json

from qpy_rsync.core.models import BackupOptions


def encode_backup(options: BackupOptions) -> str:
    return json.dumps(
        {
            "directory": options.directory,
            "protect_nested": options.protect_nested,
        },
        ensure_ascii=False,
    )


def decode_backup(payload: str) -> BackupOptions:
    if not payload:
        return BackupOptions()
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("Stored backup settings must be an object.")
    return BackupOptions(
        directory=str(raw.get("directory", "")),
        protect_nested=bool(raw.get("protect_nested", True)),
    )

from __future__ import annotations

import subprocess
from typing import Iterable

from qpy_rsync.core.endpoints import Endpoint
from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind


def inventory_paths(endpoint: Endpoint) -> dict[str, ObjectKind]:
    operand = endpoint.rsync_operand()
    if not operand.endswith("/"):
        operand += "/"
    result = subprocess.run(
        ["rsync", "-r", "--list-only", operand],
        capture_output=True,
        text=True,
        check=False,
    )
    paths: dict[str, ObjectKind] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith("sending incremental file list"):
            continue
        if line.startswith("sent ") or line.startswith("total "):
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        mode, _size, _date, _time, path = parts
        path = path.rstrip("/")
        if not path or path == ".":
            continue
        kind = ObjectKind.DIRECTORY if mode.startswith("d") else ObjectKind.FILE
        paths[path] = kind
    return paths


def unchanged_changes(profile, changed: Iterable[Change]) -> list[Change]:
    changed_paths = {change.path.rstrip("/") for change in changed}
    ancestor_paths = set()
    for changed_path in changed_paths:
        parts = changed_path.split("/")
        for index in range(1, len(parts)):
            ancestor_paths.add("/".join(parts[:index]))
    source_paths = inventory_paths(profile.source)
    destination_paths = inventory_paths(profile.destination)
    result: list[Change] = []
    for path in sorted(source_paths.keys() & destination_paths.keys()):
        if path in changed_paths or path in ancestor_paths:
            continue
        result.append(
            Change(path, ChangeAction.NO_CHANGE, source_paths[path], "=")
        )
    return result
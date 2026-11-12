from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable

from qpy_rsync.core.endpoints import Endpoint
from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.core.models import SyncProfile

from .rsync_command import build_inventory_spec


@dataclass(slots=True, frozen=True)
class InventoryEntry:
    """One listed object with the metadata rsync reported for it."""

    kind: ObjectKind
    size: int | None = None
    modified_time: str | None = None


def _parse_size(text: str) -> int | None:
    """Parse the size column, which rsync groups with commas."""
    value = text.replace(",", "").strip()
    if not value.isdigit():
        return None
    return int(value)


def _parse_time(date: str, time: str) -> str:
    """Format the timestamp like the itemized output of a comparison."""
    return f"{date.strip()}-{time.strip()}"


def inventory_paths(
    endpoint: Endpoint,
    profile: SyncProfile | None = None,
    progress: Callable[[int], None] | None = None,
) -> dict[str, InventoryEntry]:
    operand = endpoint.rsync_operand()
    if not operand.endswith("/"):
        operand += "/"
    environment = None
    if profile is None:
        command = ["rsync", "-r", "--list-only", "--", operand]
    else:
        spec = build_inventory_spec(profile, endpoint)
        command = spec.argv()
        environment = os.environ.copy()
        environment.update(spec.environment)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=environment,
    )
    paths: dict[str, InventoryEntry] = {}
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        if line.startswith("sending incremental file list"):
            continue
        if line.startswith("sent ") or line.startswith("total "):
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        mode, size_text, date, time, path = parts
        path = path.rstrip("/")
        if not path or path == ".":
            continue
        kind = ObjectKind.DIRECTORY if mode.startswith("d") else ObjectKind.FILE
        paths[path] = InventoryEntry(
            kind=kind,
            size=_parse_size(size_text),
            modified_time=_parse_time(date, time),
        )
        if progress is not None and len(paths) % 500 == 0:
            progress(len(paths))
    process.wait()
    if progress is not None:
        progress(len(paths))
    return paths


@dataclass(slots=True, frozen=True)
class InventoryResult:
    """The outcome of one inventory run.

    The unchanged objects are the ones that both trees share. The metadata of
    the destination is kept for every listed object, so the tree can also
    show the size and the date of the changed items.
    """

    unchanged: list[Change]
    destination_metadata: dict[str, tuple[int | None, str | None]]


def gather_inventory(
    profile,
    changed: Iterable[Change],
    progress: Callable[[str, int], None] | None = None,
) -> InventoryResult:
    """List both trees and report the unchanged objects and the metadata."""
    changed_paths = {change.path.rstrip("/") for change in changed}
    ancestor_paths = set()
    for changed_path in changed_paths:
        parts = changed_path.split("/")
        for index in range(1, len(parts)):
            ancestor_paths.add("/".join(parts[:index]))
    source_progress = (
        (lambda count: progress("Source", count)) if progress is not None else None
    )
    destination_progress = (
        (lambda count: progress("Destination", count))
        if progress is not None
        else None
    )
    source_paths = inventory_paths(profile.source, profile, source_progress)
    destination_paths = inventory_paths(profile.destination, profile, destination_progress)
    if progress is not None:
        progress("Matching", 0)
    unchanged: list[Change] = []
    for path in sorted(source_paths.keys() & destination_paths.keys()):
        if path in changed_paths or path in ancestor_paths:
            continue
        source = source_paths[path]
        destination = destination_paths[path]
        unchanged.append(
            Change(
                path,
                ChangeAction.NO_CHANGE,
                source.kind,
                "=",
                size=source.size,
                modified_time=source.modified_time,
                destination_size=destination.size,
                destination_time=destination.modified_time,
            )
        )
    metadata = {
        path: (entry.size, entry.modified_time)
        for path, entry in destination_paths.items()
    }
    return InventoryResult(unchanged=unchanged, destination_metadata=metadata)


def unchanged_changes(profile, changed: Iterable[Change]) -> list[Change]:
    """Return the objects that both trees share unchanged."""
    return gather_inventory(profile, changed).unchanged

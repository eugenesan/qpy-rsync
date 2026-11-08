from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import which
import subprocess
from typing import Callable

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import SyncProfile

_SUPPORTED_TOOLS = ("meld", "kdiff3", "kompare", "vimdiff")
_COMPARABLE_ACTIONS = {
    ChangeAction.UPDATE_CONTENT,
    ChangeAction.UPDATE_METADATA,
    ChangeAction.REPLACE,
}


@dataclass(slots=True, frozen=True)
class DiffTool:
    name: str
    executable: str


@dataclass(slots=True, frozen=True)
class DiffRequest:
    tool: DiffTool
    source: Path
    destination: Path


class DiffToolError(ValueError):
    pass


def _git_config(key: str) -> str | None:
    try:
        result = subprocess.run(
            ("git", "config", "--get", key),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def resolve_diff_tool(
    *,
    config_get: Callable[[str], str | None] = _git_config,
    executable_find: Callable[[str], str | None] = which,
) -> DiffTool:
    configured = config_get("diff.guitool") or config_get("diff.tool")
    candidates = (configured,) if configured else _SUPPORTED_TOOLS
    for name in candidates:
        if name is None:
            continue
        configured_path = config_get(f"difftool.{name}.path")
        executable = configured_path or executable_find(name)
        if executable:
            return DiffTool(name, executable)
    if configured:
        raise DiffToolError(f"Configured diff tool is not available: {configured}")
    raise DiffToolError(
        "No supported diff tool was found. Install meld, kdiff3, kompare, or vimdiff, "
        "or configure Git's diff.guitool."
    )


def build_diff_request(
    profile: SyncProfile,
    change: Change,
    *,
    tool: DiffTool | None = None,
) -> DiffRequest:
    if profile.source.kind is not EndpointKind.LOCAL or profile.destination.kind is not EndpointKind.LOCAL:
        raise DiffToolError("Remote-file staging is not implemented yet; both endpoints must be local.")
    if change.kind is not ObjectKind.FILE:
        raise DiffToolError("Only changed regular files can be opened in a diff tool.")
    if change.action not in _COMPARABLE_ACTIONS:
        raise DiffToolError("The selected change does not have files on both sides.")

    source = Path(profile.source.path).expanduser() / change.path
    destination = Path(profile.destination.path).expanduser() / change.path
    if not source.is_file() or not destination.is_file():
        raise DiffToolError("Both comparison paths must exist and be regular files.")
    return DiffRequest(tool or resolve_diff_tool(), source, destination)

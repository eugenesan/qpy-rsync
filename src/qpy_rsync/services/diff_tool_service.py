from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from shutil import which
import subprocess
import tempfile
from typing import Callable

from qpy_rsync.backend.rsync_command import build_fetch_spec
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
    staging_directory: Path | None = None


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


def _fetch_remote_file(
    profile: SyncProfile,
    endpoint,
    change_path: str,
    target: Path,
    *,
    on_command: Callable[[object], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> None:
    """Stage one remote file locally for the diff tool."""
    spec = build_fetch_spec(profile, endpoint, change_path, target)
    if on_command is not None:
        on_command(spec)
    environment = os.environ.copy()
    environment.update(spec.environment)
    try:
        result = subprocess.run(
            spec.argv(),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
    except OSError as exc:
        raise DiffToolError(f"Could not run rsync for the diff: {exc}") from exc
    if on_log is not None:
        for output in (result.stdout, result.stderr):
            for line in output.splitlines():
                if line.strip():
                    on_log(line)
    if result.returncode != 0 or not target.is_file():
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"rsync exited with status {result.returncode}"
        )
        raise DiffToolError(
            f"Could not fetch {change_path} from the remote endpoint: {detail}"
        )


def build_diff_request(
    profile: SyncProfile,
    change: Change,
    *,
    tool: DiffTool | None = None,
    staging_dir: Path | None = None,
    on_command: Callable[[object], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> DiffRequest:
    if change.kind is not ObjectKind.FILE:
        raise DiffToolError("Only changed regular files can be opened in a diff tool.")
    if change.action not in _COMPARABLE_ACTIONS:
        raise DiffToolError("The selected change does not have files on both sides.")
    resolved_tool = tool or resolve_diff_tool()

    source_remote = profile.source.kind is not EndpointKind.LOCAL
    destination_remote = profile.destination.kind is not EndpointKind.LOCAL
    if source_remote and destination_remote:
        raise DiffToolError("At most one endpoint may be remote.")

    source = Path(profile.source.path).expanduser() / change.path
    destination = Path(profile.destination.path).expanduser() / change.path
    if not source_remote and not source.is_file():
        raise DiffToolError(f"Source file does not exist: {source}")
    if not destination_remote and not destination.is_file():
        raise DiffToolError(f"Destination file does not exist: {destination}")
    if not source_remote and not destination_remote:
        return DiffRequest(resolved_tool, source, destination)

    created_staging = staging_dir is None
    stage = (
        Path(tempfile.mkdtemp(prefix="qpy-rsync-diff-"))
        if staging_dir is None
        else Path(staging_dir).expanduser()
    )
    stage.mkdir(parents=True, exist_ok=True)
    target = stage / Path(change.path).name
    try:
        if source_remote:
            _fetch_remote_file(
                profile,
                profile.source,
                change.path,
                target,
                on_command=on_command,
                on_log=on_log,
            )
            source = target
        else:
            _fetch_remote_file(
                profile,
                profile.destination,
                change.path,
                target,
                on_command=on_command,
                on_log=on_log,
            )
            destination = target
    except DiffToolError:
        if created_staging:
            shutil.rmtree(stage, ignore_errors=True)
        raise
    return DiffRequest(
        resolved_tool,
        source,
        destination,
        staging_directory=stage,
    )

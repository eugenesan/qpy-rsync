from pathlib import Path

import pytest

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import Endpoint, SyncProfile
from qpy_rsync.services.diff_tool_service import (
    DiffTool,
    DiffToolError,
    build_diff_request,
    resolve_diff_tool,
)


def test_resolver_prefers_git_gui_tool_and_configured_path() -> None:
    values = {"diff.guitool": "meld", "difftool.meld.path": "/opt/meld"}
    tool = resolve_diff_tool(config_get=values.get, executable_find=lambda _name: None)
    assert tool == DiffTool("meld", "/opt/meld")


def test_resolver_detects_first_installed_supported_tool() -> None:
    tool = resolve_diff_tool(
        config_get=lambda _key: None,
        executable_find=lambda name: f"/usr/bin/{name}" if name == "kdiff3" else None,
    )
    assert tool == DiffTool("kdiff3", "/usr/bin/kdiff3")


def test_build_request_returns_two_local_regular_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "file.txt").write_text("before")
    (destination / "file.txt").write_text("after")
    profile = SyncProfile(
        "test",
        Endpoint(EndpointKind.LOCAL, str(source)),
        Endpoint(EndpointKind.LOCAL, str(destination)),
    )
    change = Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")
    request = build_diff_request(profile, change, tool=DiffTool("meld", "/usr/bin/meld"))
    assert request.source == source / "file.txt"
    assert request.destination == destination / "file.txt"


def test_build_request_rejects_one_sided_change(tmp_path: Path) -> None:
    profile = SyncProfile(
        "test",
        Endpoint(EndpointKind.LOCAL, str(tmp_path)),
        Endpoint(EndpointKind.LOCAL, str(tmp_path)),
    )
    change = Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")
    with pytest.raises(DiffToolError, match="both sides"):
        build_diff_request(profile, change, tool=DiffTool("meld", "/usr/bin/meld"))


def test_build_request_rejects_remote_endpoint(tmp_path: Path) -> None:
    profile = SyncProfile(
        "test",
        Endpoint(EndpointKind.LOCAL, str(tmp_path)),
        Endpoint(EndpointKind.SSH, "/tmp/", host="server"),
    )
    change = Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")
    with pytest.raises(DiffToolError, match="both endpoints must be local"):
        build_diff_request(profile, change, tool=DiffTool("meld", "/usr/bin/meld"))

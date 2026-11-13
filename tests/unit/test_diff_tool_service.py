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


def test_build_request_stages_a_remote_destination(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("local")
    profile = SyncProfile(
        "test",
        Endpoint(EndpointKind.LOCAL, str(source)),
        Endpoint(EndpointKind.SSH, "/remote/", host="server"),
    )
    change = Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")

    def fake_fetch(_profile, _endpoint, _path, target):
        target.write_text("remote")

    monkeypatch.setattr(
        "qpy_rsync.services.diff_tool_service._fetch_remote_file", fake_fetch
    )
    stage = tmp_path / "stage"
    request = build_diff_request(
        profile,
        change,
        tool=DiffTool("meld", "/usr/bin/meld"),
        staging_dir=stage,
    )
    assert request.source == source / "file.txt"
    assert request.destination == stage / "file.txt"
    assert request.destination.read_text() == "remote"
    assert request.staging_directory == stage


def test_build_request_stages_a_remote_source(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "file.txt").write_text("local")
    profile = SyncProfile(
        "test",
        Endpoint(EndpointKind.SSH, "/remote/", host="server"),
        Endpoint(EndpointKind.LOCAL, str(destination)),
    )
    change = Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")

    def fake_fetch(_profile, _endpoint, _path, target):
        target.write_text("remote")

    monkeypatch.setattr(
        "qpy_rsync.services.diff_tool_service._fetch_remote_file", fake_fetch
    )
    stage = tmp_path / "stage"
    request = build_diff_request(
        profile,
        change,
        tool=DiffTool("meld", "/usr/bin/meld"),
        staging_dir=stage,
    )
    assert request.source == stage / "file.txt"
    assert request.source.read_text() == "remote"
    assert request.destination == destination / "file.txt"


def test_build_request_rejects_two_remote_endpoints(tmp_path: Path) -> None:
    profile = SyncProfile(
        "test",
        Endpoint(EndpointKind.SSH, "/source/", host="one"),
        Endpoint(EndpointKind.SSH, "/destination/", host="two"),
    )
    change = Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")
    with pytest.raises(DiffToolError, match="At most one"):
        build_diff_request(profile, change, tool=DiffTool("meld", "/usr/bin/meld"))

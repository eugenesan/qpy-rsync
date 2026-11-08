from qpy_rsync.backend.rsync_command import build_compare_spec, build_sync_spec
from qpy_rsync.core.enums import DeleteTiming, EndpointKind
from qpy_rsync.core.models import Endpoint, SyncProfile


def profile() -> SyncProfile:
    return SyncProfile(name="test", source=Endpoint(EndpointKind.LOCAL, "/src/"), destination=Endpoint(EndpointKind.LOCAL, "/dst/"))


def test_compare_is_dry_run_and_uses_argument_vector() -> None:
    spec = build_compare_spec(profile())
    assert spec.program == "rsync"
    assert "--dry-run" in spec.arguments
    assert spec.arguments[-3:] == ("--", "/src/", "/dst/")
    assert spec.environment == {}


def test_fuzzy_delete_forces_delete_after() -> None:
    item = profile()
    item.transfer.fuzzy = True
    item.transfer.delete = True
    item.transfer.delete_timing = DeleteTiming.BEFORE
    spec = build_sync_spec(item)
    assert "--fuzzy" in spec.arguments
    assert "--delete-after" in spec.arguments
    assert "--delete-before" not in spec.arguments


def test_output_format_uses_visible_application_separator() -> None:
    spec = build_compare_spec(profile())
    output_option = next(item for item in spec.arguments if item.startswith("--out-format="))
    assert "|qpy-rsync|" in output_option
    assert all(ord(char) >= 32 for char in output_option)


def test_compare_inventories_destination_only_objects_without_enabling_sync_delete() -> None:
    item = profile()
    item.transfer.delete = False
    compare = build_compare_spec(item)
    sync = build_sync_spec(item)
    assert "--delete-during" in compare.arguments
    assert not any(argument.startswith("--delete-") for argument in sync.arguments)


def test_remote_compare_forces_configured_askpass(monkeypatch, tmp_path) -> None:
    helper = tmp_path / "askpass"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    monkeypatch.setenv("SSH_ASKPASS", str(helper))
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    item = profile()
    item.destination = Endpoint(EndpointKind.SSH, "/backup/", host="nas", user="alice")
    spec = build_compare_spec(item)
    assert spec.environment["SSH_ASKPASS"] == str(helper)
    assert spec.environment["SSH_ASKPASS_REQUIRE"] == "force"


def test_remote_compare_restores_display_and_uses_setsid(monkeypatch, tmp_path) -> None:
    helper = tmp_path / "askpass"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    monkeypatch.setenv("SSH_ASKPASS", str(helper))
    monkeypatch.setenv("DISPLAY", ":0")
    item = profile()
    item.destination = Endpoint(EndpointKind.SSH, "/backup/", host="localhost")
    spec = build_compare_spec(item)
    assert spec.program == "setsid"
    assert spec.arguments[:2] == ("--wait", "rsync")
    index = spec.arguments.index("-e")
    assert spec.arguments[index + 1] == "env DISPLAY=:0 ssh"


def test_remote_sync_uses_same_remote_shell(monkeypatch, tmp_path) -> None:
    helper = tmp_path / "askpass"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    monkeypatch.setenv("SSH_ASKPASS", str(helper))
    monkeypatch.setenv("DISPLAY", ":0")
    item = profile()
    item.destination = Endpoint(EndpointKind.SSH, "/backup/", host="localhost")
    spec = build_sync_spec(item)
    assert spec.program == "setsid"
    assert spec.arguments[:2] == ("--wait", "rsync")
    index = spec.arguments.index("-e")
    assert spec.arguments[index + 1] == "env DISPLAY=:0 ssh"

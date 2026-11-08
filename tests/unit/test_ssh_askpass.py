from pathlib import Path

import pytest

from qpy_rsync.backend.ssh_askpass import askpass_environment, discover_askpass


def test_explicit_executable_ssh_askpass_is_used(tmp_path: Path) -> None:
    helper = tmp_path / "askpass"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    env = {"SSH_ASKPASS": str(helper), "PATH": "", "DISPLAY": ":0"}
    config = discover_askpass(env)
    assert config is not None
    assert config.executable == str(helper)
    result = askpass_environment(env)
    assert result["SSH_ASKPASS"] == str(helper)
    assert result["SSH_ASKPASS_REQUIRE"] == "force"
    assert result["DISPLAY"] == ":0"
    assert result["QT_QPA_PLATFORM"] == "xcb"


def test_missing_askpass_is_actionable() -> None:
    with pytest.raises(ValueError, match="ksshaskpass"):
        askpass_environment({"PATH": "", "SSH_ASKPASS": ""})


def test_wayland_session_forces_wayland_qt_platform(tmp_path: Path) -> None:
    helper = tmp_path / "ksshaskpass"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    result = askpass_environment(
        {
            "SSH_ASKPASS": str(helper),
            "PATH": "",
            "WAYLAND_DISPLAY": "wayland-0",
            "XDG_RUNTIME_DIR": "/run/user/1000",
        }
    )
    assert result["QT_QPA_PLATFORM"] == "wayland"


def test_existing_qt_platform_is_preserved(tmp_path: Path) -> None:
    helper = tmp_path / "askpass"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    result = askpass_environment(
        {"SSH_ASKPASS": str(helper), "PATH": "", "QT_QPA_PLATFORM": "xcb", "DISPLAY": ":0"}
    )
    assert result["QT_QPA_PLATFORM"] == "xcb"


def test_headless_session_is_rejected_before_rsync(tmp_path: Path) -> None:
    helper = tmp_path / "askpass"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    with pytest.raises(ValueError, match="WAYLAND_DISPLAY"):
        askpass_environment({"SSH_ASKPASS": str(helper), "PATH": ""})


def test_x11_display_and_authority_are_explicitly_forwarded(tmp_path: Path) -> None:
    helper = tmp_path / "ksshaskpass"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    result = askpass_environment(
        {
            "SSH_ASKPASS": str(helper),
            "PATH": "",
            "DISPLAY": ":0",
            "XAUTHORITY": "/run/user/1000/xauth_test",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        }
    )
    assert result["DISPLAY"] == ":0"
    assert result["XAUTHORITY"] == "/run/user/1000/xauth_test"
    assert result["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert result["QT_QPA_PLATFORM"] == "xcb"

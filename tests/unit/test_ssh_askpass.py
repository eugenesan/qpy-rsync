from pathlib import Path

import pytest

from qpy_rsync.backend.ssh_askpass import askpass_environment, discover_askpass


def test_explicit_executable_ssh_askpass_is_used(tmp_path: Path) -> None:
    helper = tmp_path / "askpass"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    env = {"SSH_ASKPASS": str(helper), "PATH": ""}
    config = discover_askpass(env)
    assert config is not None
    assert config.executable == str(helper)
    assert askpass_environment(env) == {
        "SSH_ASKPASS": str(helper),
        "SSH_ASKPASS_REQUIRE": "force",
    }


def test_missing_askpass_is_actionable() -> None:
    with pytest.raises(ValueError, match="ksshaskpass"):
        askpass_environment({"PATH": "", "SSH_ASKPASS": ""})

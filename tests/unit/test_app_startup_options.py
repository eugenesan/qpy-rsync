import pytest

from qpy_rsync.app import parse_startup_options
from qpy_rsync.core.enums import SyncMode


def test_parse_complete_gui_startup_options() -> None:
    options, qt_args = parse_startup_options(
        [
            "--dir-pair", "/src/", "/dst/",
            "--backup", "/backup/",
            "--mode", "new-only",
            "--compare",
            "-style", "Fusion",
        ]
    )
    assert options.source == "/src/"
    assert options.destination == "/dst/"
    assert options.backup == "/backup/"
    assert options.mode is SyncMode.NEW_ONLY
    assert options.compare
    assert qt_args == ["-style", "Fusion"]


def test_launch_options_can_populate_without_compare() -> None:
    options, _qt_args = parse_startup_options(
        ["--dir-pair", "/src/", "/dst/", "--mode", "mirror"]
    )
    assert options.mode is SyncMode.MIRROR
    assert not options.compare


def test_compare_requires_directory_pair() -> None:
    with pytest.raises(SystemExit):
        parse_startup_options(["--compare"])


def test_invalid_mode_is_rejected() -> None:
    with pytest.raises(SystemExit):
        parse_startup_options(
            ["--dir-pair", "/src/", "/dst/", "--mode", "two-way"]
        )

def test_parse_log_file_and_disable_logging() -> None:
    options, _ = parse_startup_options(["--dir-pair", "/src/", "/dst/", "--log-file", "/tmp/run.log"])
    assert options.logging_enabled is True
    assert options.log_file == "/tmp/run.log"
    disabled, _ = parse_startup_options(["--dir-pair", "/src/", "/dst/", "--no-log-file"])
    assert disabled.logging_enabled is False

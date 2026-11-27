import os

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


def test_profiles_directory_is_created(tmp_path, monkeypatch) -> None:
    from qpy_rsync.storage.settings import profiles_directory

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    directory = profiles_directory()
    assert directory == tmp_path / "config" / "qpy-rsync" / "profiles"
    assert directory.is_dir()
    # Asking again keeps the same place and does not fail when it exists.
    assert profiles_directory() == directory


def test_qt_environment_keeps_the_glx_probe_out_of_the_terminal(monkeypatch) -> None:
    from qpy_rsync.app import prepare_qt_environment

    for name in (
        "QT_XCB_GL_INTEGRATION",
        "QT_QUICK_BACKEND",
        "QSG_RHI_BACKEND",
        "QT_LOGGING_RULES",
    ):
        monkeypatch.delenv(name, raising=False)

    prepare_qt_environment()

    assert os.environ["QT_XCB_GL_INTEGRATION"] == "none"
    assert os.environ["QT_QUICK_BACKEND"] == "software"
    assert "qt.glx.warning=false" in os.environ["QT_LOGGING_RULES"]
    # There is no "software" RHI backend; asking for it falls back to OpenGL.
    assert "QSG_RHI_BACKEND" not in os.environ

    # A second call must not duplicate the rule.
    prepare_qt_environment()
    assert os.environ["QT_LOGGING_RULES"].count("qt.glx.warning=false") == 1


def test_qt_environment_keeps_the_existing_logging_rules(monkeypatch) -> None:
    from qpy_rsync.app import prepare_qt_environment

    monkeypatch.setenv("QT_LOGGING_RULES", "*.debug=true")
    prepare_qt_environment()
    rules = os.environ["QT_LOGGING_RULES"]
    assert "*.debug=true" in rules
    assert "qt.glx.warning=false" in rules


def test_the_about_dialog_reports_the_commit_of_the_checkout() -> None:
    from qpy_rsync.gui.about import build_stamp

    # The application often runs from a synchronized copy, so the stamp
    # tells which build is on the screen.
    stamp = build_stamp()
    assert stamp == "" or len(stamp) >= 4

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


def test_text_settings_are_stored_in_a_parseable_form() -> None:
    from qpy_rsync.storage.settings import decode_text, encode_text

    value = '{"filters": [], "name": "ad-hoc"}'
    encoded = encode_text(value)
    # Plain text with a prefix, no quotes or backslash escapes.
    assert encoded.startswith("b64:")
    assert '"' not in encoded and "\\" not in encoded
    assert decode_text(encoded) == value
    # A value written by an older version is still readable.
    assert decode_text(value) == value


def test_profiles_directory_is_created(tmp_path, monkeypatch) -> None:
    from qpy_rsync.storage.settings import profiles_directory

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    directory = profiles_directory()
    assert directory == tmp_path / "config" / "qpy-rsync" / "profiles"
    assert directory.is_dir()
    # Asking again keeps the same place and does not fail when it exists.
    assert profiles_directory() == directory


def test_legacy_escaped_json_values_are_rewritten(tmp_path, monkeypatch) -> None:
    from PySide6.QtCore import QCoreApplication, QSettings

    from qpy_rsync.storage.settings import (
        app_settings,
        decode_text,
        migrate_legacy_settings,
        settings_path,
    )

    QCoreApplication.setOrganizationName("qpy-rsync-tests")
    QCoreApplication.setApplicationName("rewrite")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    settings = app_settings()
    # A value written by an older version: plain JSON with escapes.
    settings.setValue("comparison/filters", '[]')
    settings.setValue("main-window/state", b"\x00\x01")
    settings.sync()

    migrate_legacy_settings()

    stored = QSettings(str(settings_path()), QSettings.Format.IniFormat)
    text = str(stored.value("comparison/filters"))
    assert text.startswith("b64:")
    assert decode_text(text) == "[]"
    contents = settings_path().read_text(encoding="utf-8")
    assert '"' not in contents.split("[profile]")[0] or "\\\"" not in contents


def test_legacy_settings_file_is_removed_after_migration(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from PySide6.QtCore import QCoreApplication, QSettings

    from qpy_rsync.storage.settings import (
        migrate_legacy_settings,
        settings_path,
    )

    organization = QCoreApplication.organizationName()
    application_name = QCoreApplication.applicationName()
    QCoreApplication.setOrganizationName("qpy-rsync-tests")
    QCoreApplication.setApplicationName("migration-cleanup")
    try:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        legacy = QSettings()
        legacy.setValue("comparison/source", "/legacy/")
        legacy.sync()
        legacy_path = Path(legacy.fileName())
        assert legacy_path.exists()

        migrate_legacy_settings()

        assert not legacy_path.exists()
        stored = QSettings(str(settings_path()), QSettings.Format.IniFormat)
        assert stored.value("comparison/source") == "/legacy/"
    finally:
        QCoreApplication.setOrganizationName(organization)
        QCoreApplication.setApplicationName(application_name)


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

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

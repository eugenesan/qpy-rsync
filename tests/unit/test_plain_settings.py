"""All persisted settings are plain, human-editable INI scalars."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from qpy_rsync.core.changes import ChangeAction
from qpy_rsync.gui.action_colours import default_colours, save_colours
from qpy_rsync.gui.main_window import MainWindow
from qpy_rsync.services.external_tools import (
    ExternalTool,
    save_diff_command,
    save_tools,
)
from qpy_rsync.storage.settings import (
    SettingsRouter,
    app_settings,
    config_settings_path,
    settings_path,
)


@pytest.fixture
def isolated_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SettingsRouter:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    settings = app_settings()
    settings.clear()
    return settings


def _settings_files() -> list[Path]:
    return [path for path in (settings_path(), config_settings_path()) if path.exists()]


def test_widget_state_is_written_as_plain_scalars(isolated_settings: SettingsRouter) -> None:
    window = MainWindow()
    window.main_splitter.setSizes([320, 180])
    window.preview_log_splitter.setSizes([120, 80])
    window.close()
    isolated_settings.sync()

    settings = isolated_settings
    geometry = str(settings.value("main-window/geometry", ""))
    assert re.fullmatch(r"-?\d+,-?\d+,\d+,\d+", geometry)
    assert settings.value("main-window/maximized", False, bool) is False
    for key in (
        "main-window/layout-state-normal",
        "command-preview/splitter",
        "comparison/flat-splitter",
    ):
        value = str(settings.value(key, ""))
        assert re.fullmatch(r"\d+(,\d+)*", value), (key, value)
    for key in (
        "comparison/flat-source-header",
        "comparison/flat-destination-header",
    ):
        value = str(settings.value(key, ""))
        assert re.fullmatch(r"\d+:\d+:[01](,\d+:\d+:[01])*", value), (key, value)
    for path in _settings_files():
        contents = path.read_text(encoding="utf-8")
        assert "b64:" not in contents
        assert "@ByteArray" not in contents
    assert "maximized=false" in settings_path().read_text(encoding="utf-8")
    QApplication.instance().processEvents()  # type: ignore[union-attr]


def test_tools_and_colours_are_written_as_plain_values(
    isolated_settings: SettingsRouter,
) -> None:
    save_tools(
        [
            ExternalTool(
                name="Editor",
                command="kate %a",
                options="--wait",
                enabled=False,
            )
        ]
    )
    save_diff_command("meld %a %A")
    colours = default_colours()
    colours[ChangeAction.DELETE] = None
    save_colours(colours)

    settings = isolated_settings
    assert settings.value("tools/external/count") == 1
    assert settings.value("tools/external/1/name") == "Editor"
    assert settings.value("tools/diff-command") == "meld %a %A"
    assert settings.value("colours/actions/delete") == ""
    for path in _settings_files():
        contents = path.read_text(encoding="utf-8")
        assert "b64:" not in contents
        assert "@ByteArray" not in contents

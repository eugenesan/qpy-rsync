from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings


def settings_path() -> Path:
    """Return the application settings file in the XDG state directory."""
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    root = (
        Path(state_home).expanduser()
        if state_home
        else Path.home() / ".local" / "state"
    )
    return root / "qpy-rsyncstaterc"


def app_settings() -> QSettings:
    return QSettings(str(settings_path()), QSettings.Format.IniFormat)


def migrate_legacy_settings() -> None:
    """Copy the old ~/.config settings once when the state file is new."""
    target = app_settings()
    known_prefixes = (
        "profile/",
        "comparison/",
        "logging/",
        "main-window/",
        "command-preview/",
    )
    if any(key.startswith(known_prefixes) for key in target.allKeys()):
        return
    legacy = QSettings()
    keys = legacy.allKeys()
    if not keys:
        return
    for key in keys:
        target.setValue(key, legacy.value(key))
    target.sync()

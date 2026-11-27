from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings

from .instance_lock import try_lock


def settings_path() -> Path:
    """Return the application settings file in the XDG state directory."""
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    root = (
        Path(state_home).expanduser()
        if state_home
        else Path.home() / ".local" / "state"
    )
    return root / "qpy-rsyncstaterc"


def config_settings_path() -> Path:
    """Return the user preference file in the XDG config directory."""
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = (
        Path(config_home).expanduser()
        if config_home
        else Path.home() / ".config"
    )
    return root / "qpy-rsync" / "settingsrc"


CONFIG_PREFIXES = (
    "logging/",
    "sound/",
    "verification/",
    "decisions/",
    "advanced/",
    "tools/",
    "colours/",
    "comparison/backup",
    "comparison/filter-directories",
    "profile/current_path",
)
# Keys that used to hold a list of recent profiles. Only the current profile
# is cached now.
DROPPED_KEYS = ("profile/recent", "profile/recent_paths")


class SettingsRouter:
    """Proxy QSettings that routes stable preferences to the config file."""

    def __init__(self) -> None:
        for path in (settings_path(), config_settings_path()):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._state = QSettings(str(settings_path()), QSettings.Format.IniFormat)
        self._config = QSettings(str(config_settings_path()), QSettings.Format.IniFormat)
        self._migrate_config()

    def _migrate_config(self) -> None:
        if config_settings_path().exists():
            return
        for key in self._state.allKeys():
            if key.startswith(CONFIG_PREFIXES):
                self._config.setValue(key, self._state.value(key))
        self._config.sync()
        for key in list(self._state.allKeys()):
            if key.startswith(CONFIG_PREFIXES) or key in DROPPED_KEYS:
                self._state.remove(key)
        self._state.sync()

    def _backend(self, key: str) -> QSettings:
        return self._config if key.startswith(CONFIG_PREFIXES) else self._state

    def value(self, key: str, default: object = None, type: object = None) -> object:
        if type is None:
            return self._backend(key).value(key, default)
        return self._backend(key).value(key, default, type)  # type: ignore[arg-type]

    def setValue(self, key: str, value: object) -> None:
        self._backend(key).setValue(key, value)

    def remove(self, key: str) -> None:
        self._backend(key).remove(key)

    def contains(self, key: str) -> bool:
        return bool(self._backend(key).contains(key))

    def allKeys(self) -> list[str]:
        return sorted(set(self._state.allKeys()) | set(self._config.allKeys()))

    def clear(self) -> None:
        self._state.clear()
        self._config.clear()

    def sync(self) -> None:
        # Best effort: a busy lock should never lose this process's write.
        for path, backend in (
            (settings_path(), self._state),
            (config_settings_path(), self._config),
        ):
            with try_lock(path, timeout=1.0):
                backend.sync()

_ROUTER: SettingsRouter | None = None
_ROUTER_PATHS: tuple[Path, Path] | None = None


def profiles_directory() -> Path:
    """Return the profile folder and create it when it is missing."""
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = (
        Path(config_home).expanduser()
        if config_home
        else Path.home() / ".config"
    )
    directory = root / "qpy-rsync" / "profiles"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def app_settings() -> SettingsRouter:
    global _ROUTER, _ROUTER_PATHS
    paths = (settings_path(), config_settings_path())
    if _ROUTER is None or _ROUTER_PATHS != paths:
        _ROUTER = SettingsRouter()
        _ROUTER_PATHS = paths
    return _ROUTER


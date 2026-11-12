from __future__ import annotations

import base64
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

_BINARY_TYPES = (bytes, bytearray, QByteArray)


def settings_path() -> Path:
    """Return the application settings file in the XDG state directory."""
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    root = (
        Path(state_home).expanduser()
        if state_home
        else Path.home() / ".local" / "state"
    )
    return root / "qpy-rsyncstaterc"


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


def app_settings() -> QSettings:
    return QSettings(str(settings_path()), QSettings.Format.IniFormat)


_TEXT_PREFIX = "b64:"


def encode_text(value: str) -> str:
    """Encode text with quotes and escapes in a form every INI reader takes.

    The KDE configuration parser rejects the backslash escapes that
    ``QSettings`` writes for a JSON value, so those values are stored as
    base64 with a short prefix.
    """
    return _TEXT_PREFIX + base64.b64encode(value.encode("utf-8")).decode("ascii")


def decode_text(value: object) -> str | None:
    """Read a value written by :func:`encode_text` or a legacy plain value."""
    if value is None:
        return None
    if isinstance(value, _BINARY_TYPES):
        return bytes(value).decode("utf-8", errors="replace")
    text = str(value)
    if not text.startswith(_TEXT_PREFIX):
        return text
    encoded = text[len(_TEXT_PREFIX) :]
    try:
        return base64.b64decode(encoded.encode("ascii"), validate=True).decode("utf-8")
    except (ValueError, UnicodeError):
        return None


def encode_binary(value: bytes | bytearray) -> str:
    """Encode binary widget state as text.

    ``QSettings`` stores byte arrays as ``@ByteArray(...)`` with escape
    sequences that other INI readers, for example the one of the KDE
    platform theme, cannot parse. Base64 keeps the file plain text.
    """
    return base64.b64encode(bytes(value)).decode("ascii")


def decode_binary(value: object) -> bytes | None:
    """Decode stored binary widget state, tolerating legacy byte arrays."""
    if value is None:
        return None
    if isinstance(value, _BINARY_TYPES):
        return bytes(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        return None


_TEXT_KEYS = ("profile/recent", "comparison/filters")


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
    legacy = QSettings()
    legacy_path = Path(legacy.fileName())
    if any(key.startswith(known_prefixes) for key in target.allKeys()):
        _rewrite_byte_arrays(target)
        _remove_legacy_settings(legacy, legacy_path)
        return
    keys = legacy.allKeys()
    if not keys:
        return
    for key in keys:
        value = legacy.value(key)
        if isinstance(value, _BINARY_TYPES):
            value = encode_binary(value)
        elif key in _TEXT_KEYS and value is not None:
            value = encode_text(str(value))
        target.setValue(key, value)
    target.sync()
    _remove_legacy_settings(legacy, legacy_path)


def _remove_legacy_settings(settings: QSettings, path: Path) -> None:
    """Drop the old config file once its values live in the state file."""
    try:
        target = settings_path()
        if path.resolve() == target.resolve():
            return
        settings.clear()
        settings.sync()
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _rewrite_byte_arrays(settings: QSettings) -> None:
    """Rewrite stored values so other INI readers can parse the file."""
    changed = False
    for key in settings.allKeys():
        value = settings.value(key)
        if isinstance(value, _BINARY_TYPES):
            settings.setValue(key, encode_binary(value))
            changed = True
        elif (
            key in _TEXT_KEYS
            and isinstance(value, str)
            and not value.startswith(_TEXT_PREFIX)
        ):
            settings.setValue(key, encode_text(value))
            changed = True
    if changed:
        settings.sync()

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


def app_settings() -> QSettings:
    return QSettings(str(settings_path()), QSettings.Format.IniFormat)


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
        _rewrite_byte_arrays(target)
        return
    legacy = QSettings()
    keys = legacy.allKeys()
    if not keys:
        return
    for key in keys:
        value = legacy.value(key)
        if isinstance(value, _BINARY_TYPES):
            value = encode_binary(value)
        target.setValue(key, value)
    target.sync()


def _rewrite_byte_arrays(settings: QSettings) -> None:
    """Replace stored byte arrays with text other INI readers understand."""
    changed = False
    for key in settings.allKeys():
        value = settings.value(key)
        if isinstance(value, _BINARY_TYPES):
            settings.setValue(key, encode_binary(value))
            changed = True
    if changed:
        settings.sync()

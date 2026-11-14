"""The colours that mark the actions of the comparison.

Every action that changes an item has a colour. The colour marks the item in
the list, and the glyph of the action in the middle pane carries the same
colour. The user can change every colour and switch a marking off.
"""

from __future__ import annotations

import json
from typing import Mapping

from PySide6.QtGui import QColor

from qpy_rsync.core.changes import ChangeAction

COLOURS_KEY = "colours/actions"

# The default colour of every action that marks an item.
DEFAULT_COLOURS: dict[ChangeAction, str] = {
    ChangeAction.CREATE: "#208020",  # green
    ChangeAction.UPDATE_CONTENT: "#eab308",  # light yellow
    ChangeAction.UPDATE_METADATA: "#06b6d4",  # cyan
    ChangeAction.REPLACE: "#f97316",  # orange
    ChangeAction.DELETE: "#ef4444",  # red, lightened for the dark themes
    ChangeAction.DESTINATION_ONLY: "#a05020",  # brown
}

_current: dict[ChangeAction, str | None] | None = None


def default_colours() -> dict[ChangeAction, str | None]:
    """The colours of a fresh installation."""
    return dict(DEFAULT_COLOURS)


def load_colours(store: object | None = None) -> dict[ChangeAction, str | None]:
    """The colours the user chose. None means the action is not marked."""
    from qpy_rsync.storage.settings import app_settings, decode_text

    settings = store if store is not None else app_settings()
    raw = decode_text(settings.value(COLOURS_KEY, ""))
    payload: object = {}
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
    stored = payload if isinstance(payload, dict) else {}
    colours: dict[ChangeAction, str | None] = {}
    for action, default in DEFAULT_COLOURS.items():
        value = stored.get(action.value, default)
        colours[action] = value if isinstance(value, str) else None
    return colours


def save_colours(
    colours: Mapping[ChangeAction, str | None], store: object | None = None
) -> None:
    """Remember the colours the user chose."""
    from qpy_rsync.storage.settings import app_settings, encode_text

    settings = store if store is not None else app_settings()
    payload = {action.value: colour for action, colour in colours.items()}
    settings.setValue(COLOURS_KEY, encode_text(json.dumps(payload)))
    settings.sync()


def current_colours() -> dict[ChangeAction, str | None]:
    """The colours in use."""
    global _current
    if _current is None:
        _current = load_colours()
    return _current


def set_current_colours(colours: Mapping[ChangeAction, str | None]) -> None:
    """Use the given colours and refresh the cached icons."""
    global _current
    _current = dict(colours)
    from .icons import action_icon

    action_icon.cache_clear()


def colour_for(action: ChangeAction) -> QColor | None:
    """The colour of an action, or None when the action is not marked."""
    value = current_colours().get(action)
    if not value:
        return None
    colour = QColor(value)
    return colour if colour.isValid() else None

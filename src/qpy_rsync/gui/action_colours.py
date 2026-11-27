"""The colours that mark the actions of the comparison.

Every action that changes an item has a colour. The colour marks the item in
the list, and the glyph of the action in the middle pane carries the same
colour. The user can change every colour and switch a marking off.
"""

from __future__ import annotations

from typing import Mapping

from PySide6.QtGui import QColor

from qpy_rsync.core.changes import ChangeAction

# One plain key per action value, e.g. ``colours/actions/create``.  A colour
# is a ``#rrggbb`` string; an empty value (or a missing key) means unmarked.
COLOURS_KEY = "colours/actions"


def _colour_key(action: ChangeAction) -> str:
    return f"{COLOURS_KEY}/{action.value}"

# The default colour of every action that marks an item.
DEFAULT_COLOURS: dict[ChangeAction, str] = {
    ChangeAction.CREATE: "#208020",  # green
    ChangeAction.UPDATE_CONTENT: "#eab308",  # light yellow
    ChangeAction.UPDATE_METADATA: "#7c3aed",  # violet: distinct from selection blue
    ChangeAction.DELETE: "#ef4444",  # red, lightened for the dark themes
    ChangeAction.DESTINATION_ONLY: "#a05020",  # brown
}

_current: dict[ChangeAction, str | None] | None = None


def default_colours() -> dict[ChangeAction, str | None]:
    """The colours of a fresh installation."""
    return dict(DEFAULT_COLOURS)


def load_colours(store: object | None = None) -> dict[ChangeAction, str | None]:
    """The colours the user chose. None means the action is not marked."""
    from qpy_rsync.storage.settings import app_settings

    settings = store if store is not None else app_settings()
    colours: dict[ChangeAction, str | None] = {}
    for action, default in DEFAULT_COLOURS.items():
        value = settings.value(_colour_key(action))
        if value is None:
            # A key that was never written means the default colour.
            colours[action] = default
        elif isinstance(value, str) and value.strip():
            colours[action] = value.strip()
        else:
            colours[action] = None
    return colours


def save_colours(
    colours: Mapping[ChangeAction, str | None], store: object | None = None
) -> None:
    """Remember the colours as one plain key per action."""
    from qpy_rsync.storage.settings import app_settings

    settings = store if store is not None else app_settings()
    for action, default in DEFAULT_COLOURS.items():
        settings.setValue(_colour_key(action), colours.get(action, default) or "")
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

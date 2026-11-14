import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor

from qpy_rsync.core.changes import ChangeAction
from qpy_rsync.gui.action_colours import (
    DEFAULT_COLOURS,
    colour_for,
    current_colours,
    default_colours,
    load_colours,
    save_colours,
    set_current_colours,
)


def test_every_action_has_a_colour() -> None:
    colours = default_colours()
    assert set(colours) == set(DEFAULT_COLOURS)
    for action, value in colours.items():
        assert value is not None
        assert QColor(value).isValid(), action


def test_the_colours_are_stored_and_read_back(tmp_path) -> None:
    from PySide6.QtCore import QSettings

    store = QSettings(str(tmp_path / "colours.ini"), QSettings.Format.IniFormat)
    colours = default_colours()
    colours[ChangeAction.UPDATE_CONTENT] = "#123456"
    colours[ChangeAction.REPLACE] = None
    save_colours(colours, store)

    loaded = load_colours(store)
    assert loaded[ChangeAction.UPDATE_CONTENT] == "#123456"
    assert loaded[ChangeAction.REPLACE] is None
    assert loaded[ChangeAction.CREATE] == DEFAULT_COLOURS[ChangeAction.CREATE]


def test_the_colours_in_use_can_be_replaced() -> None:
    try:
        set_current_colours({ChangeAction.CREATE: "#00ff00"})
        assert current_colours()[ChangeAction.CREATE] == "#00ff00"
        assert colour_for(ChangeAction.CREATE) == QColor("#00ff00")
        # An action that is not marked has no colour.
        assert colour_for(ChangeAction.DELETE) is None
    finally:
        set_current_colours(default_colours())


def test_a_broken_stored_colour_is_ignored(tmp_path) -> None:
    from PySide6.QtCore import QSettings
    from qpy_rsync.storage.settings import encode_text

    store = QSettings(str(tmp_path / "colours.ini"), QSettings.Format.IniFormat)
    store.setValue("colours/actions", encode_text("not json"))
    assert load_colours(store) == default_colours()

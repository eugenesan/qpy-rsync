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


def test_the_colours_are_stored_as_plain_readable_keys(tmp_path) -> None:
    from pathlib import Path

    from PySide6.QtCore import QSettings

    store = QSettings(str(tmp_path / "colours.ini"), QSettings.Format.IniFormat)
    colours = default_colours()
    colours[ChangeAction.UPDATE_CONTENT] = "#123456"
    colours[ChangeAction.DELETE] = None
    save_colours(colours, store)

    loaded = load_colours(store)
    assert loaded[ChangeAction.UPDATE_CONTENT] == "#123456"
    assert loaded[ChangeAction.DELETE] is None
    assert loaded[ChangeAction.CREATE] == DEFAULT_COLOURS[ChangeAction.CREATE]
    assert store.value("colours/actions/update_content") == "#123456"
    assert store.value("colours/actions/delete") == ""
    assert store.value("colours/actions/create") == DEFAULT_COLOURS[ChangeAction.CREATE]
    contents = Path(store.fileName()).read_text(encoding="utf-8")
    assert "b64:" not in contents
    assert "#123456" in contents


def test_the_colours_in_use_can_be_replaced() -> None:
    try:
        set_current_colours({ChangeAction.CREATE: "#00ff00"})
        assert current_colours()[ChangeAction.CREATE] == "#00ff00"
        assert colour_for(ChangeAction.CREATE) == QColor("#00ff00")
        # An action that is not marked has no colour.
        assert colour_for(ChangeAction.DELETE) is None
    finally:
        set_current_colours(default_colours())


def test_an_empty_or_missing_colour_key_means_unmarked(tmp_path) -> None:
    from PySide6.QtCore import QSettings

    store = QSettings(str(tmp_path / "colours.ini"), QSettings.Format.IniFormat)
    # A key the user deleted falls back to the default; an explicitly empty
    # key switches the marking off.
    store.setValue("colours/actions/delete", "")
    loaded = load_colours(store)
    assert loaded[ChangeAction.DELETE] is None
    assert loaded == {**default_colours(), ChangeAction.DELETE: None}

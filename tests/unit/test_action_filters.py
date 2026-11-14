import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.gui.action_filters import ActionFilterBar, FILTERABLE_ACTIONS
from qpy_rsync.gui.controls import CONTROL_ICON_SIZE, CONTROL_SIZE
from qpy_rsync.gui.flat_change_model import FlatChangeModel


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _model() -> FlatChangeModel:
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
            Change("old.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
            Change("gone.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
            Change("extra.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting"),
        ]
    )
    return model


def _names(model: FlatChangeModel) -> set[str]:
    return {
        path.rpartition("/")[2]
        for path in model.visible_paths()
    }


def test_action_filter_bar_starts_with_every_action_enabled() -> None:
    app()
    bar = ActionFilterBar()
    assert bar.is_all_enabled()
    assert bar.visible_actions() == set(FILTERABLE_ACTIONS)


def test_action_filter_hides_only_selected_actions() -> None:
    model = _model()
    model.set_visible_actions({ChangeAction.CREATE})
    assert _names(model) == {"new.txt"}


def test_action_filter_keeps_ancestors_of_visible_rows() -> None:
    model = FlatChangeModel()
    model.set_changes(
        [Change("docs/new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    )
    model.set_visible_actions({ChangeAction.CREATE})
    assert _names(model) == {"docs", "new.txt"}


def test_action_filter_none_shows_everything() -> None:
    model = _model()
    model.set_visible_actions(None)
    assert _names(model) == {"new.txt", "old.txt", "gone.txt", "extra.txt"}


def test_action_filter_tooltips_mention_display_only_and_mode() -> None:
    app()
    bar = ActionFilterBar()
    boxes = [
        box
        for box in bar.findChildren(QCheckBox)
        if box not in (bar.stashed_box, bar.unchanged_box)
    ]
    tooltips = [child.toolTip() for child in boxes]
    assert tooltips
    for tooltip in tooltips:
        assert "Display only" in tooltip
        assert "doesn't affect the sync" in tooltip
        assert "sync mode selector" in tooltip
    for box in boxes:
        # The glyph matches the size of the buttons in the same row.
        assert box.height() >= CONTROL_SIZE
        assert box.iconSize().width() == CONTROL_ICON_SIZE


def test_the_stashed_toggle_says_it_affects_the_sync() -> None:
    app()
    bar = ActionFilterBar()
    bar.set_stashed_count(3)
    assert "3 stashed item(s)" in bar.stashed_box.toolTip()
    assert "not part of the sync" in bar.stashed_box.toolTip()
    assert bar.stashed_box.text() == "3"


def test_action_filter_survives_model_reset() -> None:
    model = _model()
    model.set_visible_actions({ChangeAction.CREATE})
    assert _names(model) == {"new.txt"}

    model.set_changes(
        [
            Change("fresh.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
            Change("updated.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
        ]
    )
    assert _names(model) == {"fresh.txt"}
    assert model.visible_actions() == {ChangeAction.CREATE}


def test_the_stashed_toggle_mentions_restore_all_in_its_tooltip() -> None:
    app()
    bar = ActionFilterBar()
    bar.set_stashed_count(0)
    assert "Right-click to restore all stashed items" in bar.stashed_box.toolTip()
    bar.set_stashed_count(3)
    assert "3 stashed item(s)" in bar.stashed_box.toolTip()
    assert "Right-click to restore all stashed items" in bar.stashed_box.toolTip()


def test_the_action_toggles_only_take_focus_from_the_keyboard() -> None:
    app()
    bar = ActionFilterBar()
    # A pointer click must not focus the toggle (Breeze draws a focus
    # underline under an icon-only checkbox), but TabFocus still includes
    # the keyboard.
    for box in (*bar._boxes.values(), bar.unchanged_box, bar.stashed_box):
        assert box.focusPolicy() == Qt.FocusPolicy.TabFocus
        assert box.focusPolicy() & Qt.FocusPolicy.TabFocus


def test_the_bar_separates_the_action_filters_from_the_other_toggles() -> None:
    from PySide6.QtWidgets import QFrame

    app()
    bar = ActionFilterBar()
    lines = [
        child
        for child in bar.findChildren(QFrame)
        if child.frameShape() == QFrame.Shape.VLine
    ]
    # One line before the unchanged items, one before the stashed items.
    assert len(lines) == 2

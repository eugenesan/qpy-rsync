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


def test_the_bar_separates_every_pair_of_checkboxes() -> None:
    from PySide6.QtWidgets import QFrame

    from qpy_rsync.gui.action_filters import FILTERABLE_ACTIONS

    app()
    bar = ActionFilterBar()
    lines = [
        child
        for child in bar.findChildren(QFrame)
        if child.frameShape() == QFrame.Shape.VLine
    ]
    # One line between every pair of checkboxes, so it is clear which
    # indicator belongs to which glyph.
    boxes = len(FILTERABLE_ACTIONS) + 2
    assert len(lines) == boxes - 1


def _click(box: QCheckBox, *, ctrl: bool = False) -> None:
    """Send a click to a checkbox of the bar."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    position = QPointF(box.rect().center())
    modifiers = (
        Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    )
    for event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        event = QMouseEvent(
            event_type,
            position,
            position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            modifiers,
        )
        QApplication.sendEvent(box, event)


def test_ctrl_click_shows_only_that_action() -> None:
    app()
    bar = ActionFilterBar()
    seen: list[set] = []
    bar.changed.connect(lambda actions: seen.append(actions))
    box = bar._boxes[ChangeAction.CREATE]

    _click(box, ctrl=True)

    # Only the clicked action is left, so the view shows only its items.
    assert box.isChecked() is True
    for other in bar._boxes.values():
        if other is not box:
            assert other.isChecked() is False
    assert seen[-1] == {ChangeAction.CREATE}


def test_ctrl_click_again_brings_every_action_back() -> None:
    app()
    bar = ActionFilterBar()
    seen: list[set] = []
    bar.changed.connect(lambda actions: seen.append(actions))
    box = bar._boxes[ChangeAction.CREATE]

    _click(box, ctrl=True)
    assert seen[-1] == {ChangeAction.CREATE}

    # The box is now the only one that is shown, so the second inverted
    # click reverses the first one.
    _click(box, ctrl=True)

    assert box.isChecked() is True
    for other in bar._boxes.values():
        assert other.isChecked() is True
    assert seen[-1] == set(FILTERABLE_ACTIONS)


def test_ctrl_click_on_a_switch_that_is_off_brings_every_action_back() -> None:
    app()
    bar = ActionFilterBar()
    seen: list[set] = []
    bar.changed.connect(lambda actions: seen.append(actions))
    create = bar._boxes[ChangeAction.CREATE]
    delete = bar._boxes[ChangeAction.DELETE]

    _click(create, ctrl=True)
    assert delete.isChecked() is False

    # The switch is off, so the inverted click reverses the operation.
    _click(delete, ctrl=True)

    for other in bar._boxes.values():
        assert other.isChecked() is True
    assert seen[-1] == set(FILTERABLE_ACTIONS)


def test_the_reversed_filter_leaves_the_unchanged_and_stashed_toggles_alone() -> None:
    app()
    bar = ActionFilterBar()
    create = bar._boxes[ChangeAction.CREATE]
    bar.stashed_box.setChecked(True)

    _click(create, ctrl=True)
    # The solo switches the other toggles off.
    assert bar.stashed_box.isChecked() is False

    _click(bar._boxes[ChangeAction.DELETE], ctrl=True)

    # The reset restores the actions, but the stashed toggle keeps the state
    # it had.
    assert all(other.isChecked() for other in bar._boxes.values())
    assert bar.stashed_box.isChecked() is False


def test_a_plain_click_still_toggles_the_box() -> None:
    app()
    bar = ActionFilterBar()
    box = bar._boxes[ChangeAction.CREATE]
    assert box.isChecked() is True
    _click(box)
    assert box.isChecked() is False


def test_the_context_menu_of_a_box_offers_the_inverted_choices() -> None:
    app()
    bar = ActionFilterBar()
    box = bar._boxes[ChangeAction.CREATE]
    others = [other for other in bar._all_boxes() if other is not box]

    bar._set_states({other: other is box for other in bar._all_boxes()})
    assert box.isChecked() is True
    assert all(other.isChecked() is False for other in others)

    bar._set_states({other: other is not box for other in bar._all_boxes()})
    assert box.isChecked() is False
    assert all(other.isChecked() is True for other in others)


def test_ctrl_click_on_a_switch_that_is_off_reverses_the_operation() -> None:
    app()
    bar = ActionFilterBar()
    seen: list[set] = []
    bar.changed.connect(lambda actions: seen.append(actions))
    create = bar._boxes[ChangeAction.CREATE]

    _click(create, ctrl=True)
    assert seen[-1] == {ChangeAction.CREATE}

    # The stashed switch is off, so the inverted click reverses the solo.
    _click(bar.stashed_box, ctrl=True)

    assert all(other.isChecked() for other in bar._boxes.values())
    assert bar.stashed_box.isChecked() is False
    assert seen[-1] == set(FILTERABLE_ACTIONS)


def test_the_context_menu_can_still_show_only_the_stashed_items() -> None:
    app()
    bar = ActionFilterBar()
    box = bar.stashed_box

    bar._set_states({other: other is box for other in bar._all_boxes()})

    assert box.isChecked() is True
    for other in bar._all_boxes():
        if other is not box:
            assert other.isChecked() is False


def test_the_context_menu_can_reset_the_bar_to_its_default() -> None:
    app()
    bar = ActionFilterBar()
    box = bar._boxes[ChangeAction.CREATE]
    _click(box, ctrl=True)
    assert box.isChecked() is True
    bar.unchanged_box.setChecked(True)
    bar.stashed_box.setChecked(True)

    bar.reset_defaults()

    # The default is every action and nothing else.
    assert all(other.isChecked() for other in bar._boxes.values())
    assert bar.unchanged_box.isChecked() is False
    assert bar.stashed_box.isChecked() is False

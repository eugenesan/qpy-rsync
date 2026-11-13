import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.gui.action_filters import ActionFilterBar, FILTERABLE_ACTIONS
from qpy_rsync.gui.change_filter_proxy import ChangeTreeFilterProxyModel
from qpy_rsync.gui.change_tree_model import ChangeTreeModel
from qpy_rsync.gui.comparison_view import CONTROL_ICON_SIZE, CONTROL_SIZE


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _model() -> ChangeTreeModel:
    model = ChangeTreeModel()
    model.set_changes(
        [
            Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
            Change("old.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
            Change("gone.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
            Change("extra.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting"),
        ]
    )
    return model


def _proxy(model: ChangeTreeModel) -> ChangeTreeFilterProxyModel:
    proxy = ChangeTreeFilterProxyModel()
    proxy.setSourceModel(model)
    return proxy


def _names(proxy: ChangeTreeFilterProxyModel) -> set[str]:
    names: set[str] = set()
    for row in range(proxy.rowCount()):
        source = proxy.data(proxy.index(row, 0))
        destination = proxy.data(
            proxy.index(row, ChangeTreeModel.DESTINATION_NAME)
        )
        names.add(source or destination)
    return names


def test_action_filter_bar_starts_with_every_action_enabled() -> None:
    app()
    bar = ActionFilterBar()
    assert bar.is_all_enabled()
    assert bar.visible_actions() == set(FILTERABLE_ACTIONS)


def test_action_filter_hides_only_selected_actions() -> None:
    model = _model()
    proxy = _proxy(model)
    proxy.set_visible_actions({ChangeAction.CREATE})
    assert _names(proxy) == {"new.txt"}


def test_action_filter_keeps_ancestors_of_visible_rows() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("docs/new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    )
    proxy = _proxy(model)
    proxy.set_visible_actions({ChangeAction.CREATE})
    assert _names(proxy) == {"docs"}


def test_action_filter_none_shows_everything() -> None:
    model = _model()
    proxy = _proxy(model)
    proxy.set_visible_actions(None)
    assert _names(proxy) == {"new.txt", "old.txt", "gone.txt", "extra.txt"}


def test_action_filter_tooltips_mention_display_only_and_mode() -> None:
    app()
    bar = ActionFilterBar()
    boxes = [
        box for box in bar.findChildren(QCheckBox) if box is not bar.hidden_box
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


def test_the_hidden_toggle_says_it_affects_the_sync() -> None:
    app()
    bar = ActionFilterBar()
    bar.set_hidden_count(3)
    assert "3 hidden item(s)" in bar.hidden_box.toolTip()
    assert "not part of the sync" in bar.hidden_box.toolTip()
    assert bar.hidden_box.text() == "3"


def test_action_filter_survives_model_reset() -> None:
    model = _model()
    proxy = _proxy(model)
    proxy.set_visible_actions({ChangeAction.CREATE})
    assert _names(proxy) == {"new.txt"}

    model.set_changes(
        [
            Change("fresh.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
            Change("updated.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
        ]
    )
    assert _names(proxy) == {"fresh.txt"}
    assert proxy.visible_actions() == {ChangeAction.CREATE}

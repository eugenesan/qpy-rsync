import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QStyleOptionViewItem

from qpy_rsync.core.changes import ChangeAction
from qpy_rsync.gui.comparison_view import (
    CONTROL_ICON_SIZE,
    CONTROL_SIZE,
    ROW_HEIGHT,
    ComparisonView,
)
from qpy_rsync.gui.icons import action_icon


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_trees_share_row_height_and_scroll_mode() -> None:
    application = app()
    view = ComparisonView()
    option = QStyleOptionViewItem()
    for tree in (view.source, view.action, view.destination):
        assert tree.uniformRowHeights()
        assert tree.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
        assert (
            tree.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert tree.itemDelegate().sizeHint(option, QModelIndex()).height() == ROW_HEIGHT
    view.close()
    application.processEvents()


def test_action_filter_keeps_expanded_paths() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    view = ComparisonView()
    view.set_changes(
        [
            Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
            Change(
                "docs/b.txt",
                ChangeAction.UPDATE_CONTENT,
                ObjectKind.FILE,
                ">f.st......",
            ),
        ]
    )
    index = view.proxy.index(0, 0)
    for tree in (view.source, view.action, view.destination):
        tree.expand(index)
    view.set_action_filter({ChangeAction.CREATE})
    filtered = view.proxy.index(0, 0)
    assert view.proxy.rowCount(filtered) == 1
    for tree in (view.source, view.action, view.destination):
        assert tree.isExpanded(filtered)
    view.set_action_filter(None)
    restored = view.proxy.index(0, 0)
    assert view.proxy.rowCount(restored) == 2
    for tree in (view.source, view.action, view.destination):
        assert tree.isExpanded(restored)
    view.close()
    application.processEvents()


def test_control_buttons_use_consistent_large_icons() -> None:
    application = app()
    view = ComparisonView()
    for button in (
        view.inventory_button,
        view.expand_button,
        view.collapse_button,
    ):
        assert button.size().width() == CONTROL_SIZE
        assert button.size().height() == CONTROL_SIZE
        assert button.iconSize().width() == CONTROL_ICON_SIZE
    pixmap = action_icon(ChangeAction.CREATE).pixmap(
        CONTROL_ICON_SIZE, CONTROL_ICON_SIZE
    )
    assert pixmap.width() == CONTROL_ICON_SIZE
    assert pixmap.height() == CONTROL_ICON_SIZE
    view.close()
    application.processEvents()


def test_context_menu_copies_full_path_for_every_pane() -> None:
    from qpy_rsync.core.changes import Change, ObjectKind

    application = app()
    view = ComparisonView()
    view.source_root = "/srv/Source"
    view.destination_root = "/mnt/Destination"
    view.set_changes(
        [Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    )
    application.processEvents()
    for tree, expected in (
        (view.source, "/srv/Source/docs"),
        (view.destination, "/mnt/Destination/docs"),
        (view.action, "/srv/Source/docs"),
    ):
        menu, copy_path, _diff, _one, _subtree, _all = view._build_context_menu(
            tree, "docs", None
        )
        texts = [action.text() for action in menu.actions()]
        assert expected in texts
        assert "Copy Path" in texts
        assert copy_path.isEnabled()
        view._copy_path(tree, "docs")
        assert QApplication.clipboard().text() == expected
    view.close()
    application.processEvents()
def test_inventory_update_preserves_expanded_folders() -> None:
    from qpy_rsync.core.changes import Change, ObjectKind

    application = app()
    view = ComparisonView()
    view.set_changes(
        [Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    )
    application.processEvents()
    directory = view.proxy.index(0, 0)
    for tree in (view.source, view.action, view.destination):
        tree.expand(directory)
    view.set_changes(
        [
            Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
            Change("docs/same.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, "="),
        ],
        preserve_expansion=True,
    )
    application.processEvents()
    restored = view.proxy.index(0, 0)
    assert view.proxy.rowCount(restored) == 2
    for tree in (view.source, view.action, view.destination):
        assert tree.isExpanded(restored)
    view.close()
    application.processEvents()




def test_updated_objects_appear_without_a_new_comparison() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    view = ComparisonView()
    changed = Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")
    view.set_changes([changed])
    application.processEvents()
    assert view.proxy.rowCount() == 1

    unchanged = Change("b.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, "=")
    view.set_changes([changed, unchanged], preserve_expansion=True)
    application.processEvents()
    assert view.proxy.rowCount() == 2
    view.close()
    application.processEvents()


def test_expanding_a_large_tree_stays_responsive() -> None:
    import time

    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    view = ComparisonView()
    changes = [
        Change(f"file{index}.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")
        for index in range(2000)
    ]
    view.set_changes(changes)
    application.processEvents()

    started = time.monotonic()
    view.expand_all()
    application.processEvents()
    elapsed = time.monotonic() - started
    # A quadratic implementation needed minutes for this tree.
    assert elapsed < 20.0
    view.close()
    application.processEvents()

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


def test_action_column_hugs_its_content() -> None:
    from PySide6.QtCore import Qt

    from qpy_rsync.gui.comparison_view import ACTION_PANE_WIDTH

    application = app()
    view = ComparisonView()
    application.processEvents()
    assert view.action.width() == ACTION_PANE_WIDTH
    # The panes scroll together, so only the last one keeps a scroll bar.
    assert (
        view.action.verticalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert (
        view.source.verticalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert (
        view.destination.verticalScrollBarPolicy()
        != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    # The header label uses the same font as the other headers.
    font = view.model.headerData(
        view.model.ACTION, Qt.Orientation.Horizontal, Qt.ItemDataRole.FontRole
    )
    assert font is None
    view.close()
    application.processEvents()


def test_destination_metadata_fills_the_destination_columns() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    view = ComparisonView()
    change = Change(
        "a.txt",
        ChangeAction.UPDATE_CONTENT,
        ObjectKind.FILE,
        ">f.st......",
        size=10,
        modified_time="2026/11/10-20:32:20",
    )
    view.set_changes([change])
    application.processEvents()
    model = view.model
    assert model.data(model.index(0, model.DESTINATION_SIZE)) == ""

    view.set_destination_metadata({"a.txt": (6, "2026/11/09-10:00:00")})
    application.processEvents()
    assert model.data(model.index(0, model.DESTINATION_SIZE)) == "6 B"
    assert (
        model.data(model.index(0, model.DESTINATION_TIME)) == "2026/11/09-10:00:00"
    )
    # The source columns still report the values of the comparison.
    assert model.data(model.index(0, model.SOURCE_SIZE)) == "10 B"
    view.close()
    application.processEvents()


def test_header_click_sorts_the_tree_panes() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    view = ComparisonView()
    changes = [
        Change("b.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=30),
        Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=10),
        Change("c.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=20),
    ]
    view.set_changes(changes)
    application.processEvents()

    def paths() -> list[str]:
        model = view.model
        return [
            model.index(row, 0).internalPointer().path
            for row in range(model.rowCount())
        ]

    def proxy_paths() -> list[str]:
        return [
            view.proxy.index(row, 0).data()
            for row in range(view.proxy.rowCount())
        ]

    # The default order is by name.
    assert paths() == ["a.txt", "b.txt", "c.txt"]

    view._sort_by_section(view.source.header(), 1)
    application.processEvents()
    assert paths() == ["a.txt", "c.txt", "b.txt"]
    assert proxy_paths() == ["a.txt", "c.txt", "b.txt"]

    # A second click reverses the order.
    view._sort_by_section(view.source.header(), 1)
    application.processEvents()
    assert paths() == ["b.txt", "c.txt", "a.txt"]

    # The order survives a rebuild of the tree.
    view.set_changes(changes)
    application.processEvents()
    assert paths() == ["b.txt", "c.txt", "a.txt"]
    view.close()
    application.processEvents()


def test_sort_indicator_marks_the_sorted_column() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    view = ComparisonView()
    view.set_changes(
        [
            Change("b.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=30),
            Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=10),
        ]
    )
    application.processEvents()

    view._sort_by_section(view.source.header(), 1)
    application.processEvents()
    assert view.source.header().sortIndicatorSection() == 1
    assert view.model.sort_column() == 1
    # The other panes do not show the column, so they carry no indicator.
    assert view.action.header().sortIndicatorSection() == -1
    assert view.destination.header().sortIndicatorSection() == -1

    # The destination column marks its own header.
    view._sort_by_section(view.destination.header(), 5)
    application.processEvents()
    assert view.destination.header().sortIndicatorSection() == 5
    assert view.source.header().sortIndicatorSection() == -1
    view.close()
    application.processEvents()


def test_selected_object_is_centered_in_the_panes() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    view = ComparisonView()
    changes = [
        Change(f"file{index}.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")
        for index in range(60)
    ]
    view.set_changes(changes)
    application.processEvents()

    view.select_path("file40.txt")
    application.processEvents()
    index = view.source.currentIndex()
    assert index.isValid()
    rect = view.source.visualRect(index)
    viewport = view.source.viewport().rect()
    assert abs(rect.center().y() - viewport.center().y()) <= rect.height()
    view.close()
    application.processEvents()


def test_saved_header_state_keeps_the_headers_clickable() -> None:
    from qpy_rsync.storage.settings import app_settings, encode_binary

    application = app()
    app_settings().clear()
    view = ComparisonView()
    header = view.source.header()
    # An older version saved a state whose sections were not clickable.
    header.setSectionsClickable(False)
    header.setSortIndicatorShown(False)
    state = header.saveState()
    view.close()
    app_settings().setValue("comparison/source-header", encode_binary(state))
    app_settings().sync()

    restored = ComparisonView()
    application.processEvents()
    for tree in (restored.source, restored.action, restored.destination):
        assert tree.header().sectionsClickable()
        assert tree.header().isSortIndicatorShown()
        assert not tree.header().sectionsMovable()
    restored.close()
    application.processEvents()

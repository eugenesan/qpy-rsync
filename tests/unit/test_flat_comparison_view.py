import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qpy_rsync.core.changes import (
    Change,
    ChangeAction,
    ChangeDecision,
    ObjectKind,
)
from qpy_rsync.gui.flat_change_model import FlatChangeModel
from qpy_rsync.gui.flat_comparison_view import FlatComparisonView


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _paths(model) -> list[str]:
    """The item paths of the visible rows, without the compared folder."""
    return [
        path
        for path in (model.row_path(row) for row in range(model.rowCount()))
        if path
    ]


def file_change(path: str, action: ChangeAction = ChangeAction.UPDATE_CONTENT, size: int = 100):
    code = {
        ChangeAction.CREATE: ">f+++++++++",
        ChangeAction.NO_CHANGE: "=",
        ChangeAction.UPDATE_CONTENT: ">f.st......",
        ChangeAction.DESTINATION_ONLY: "*deleting   ",
    }.get(action, ">f.st......")
    return Change(path, action, ObjectKind.FILE, code, size=size)


def test_a_directory_precedes_its_items_and_then_its_subdirectories() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            file_change("docs/b.txt"),
            file_change("docs/a.txt"),
            file_change("docs/sub/c.txt"),
        ]
    )
    paths = _paths(model)
    assert paths == [
        "docs",
        "docs/a.txt",
        "docs/b.txt",
        "docs/sub",
        "docs/sub/c.txt",
    ]
    model.deleteLater()
    application.processEvents()


def test_every_row_alternates_even_inside_one_directory() -> None:
    from qpy_rsync.gui.flat_change_model import STRIPE_ROLE

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            file_change("docs/a.txt"),
            file_change("docs/b.txt"),
            file_change("docs/c.txt"),
            file_change("docs/sub/d.txt"),
            file_change("pics/e.jpg"),
            file_change("root.txt"),
        ]
    )
    stripes = [
        model.data(model.index(row, model.SOURCE_NAME), STRIPE_ROLE)
        for row in range(model.rowCount())
    ]
    # Every row differs from the one above it, so a directory and its first
    # item never share a stripe and a group of any size is still striped.
    for row in range(1, len(stripes)):
        assert stripes[row] != stripes[row - 1]
    model.deleteLater()
    application.processEvents()


def test_a_directory_row_is_a_decision_target() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            file_change("docs/a.txt"),
            file_change("docs/b.txt"),
        ]
    )
    index = model.index_for_path("docs")
    assert index.isValid()
    action_index = index.siblingAtColumn(model.ACTION)
    assert model.data(action_index, Qt.ItemDataRole.CheckStateRole) is not None
    model.setData(action_index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.decisions.explicit("docs") is ChangeDecision.EXCLUDE
    # The decision of the directory reaches the items below it.
    assert model.decisions.inherited("docs/a.txt") is ChangeDecision.EXCLUDE
    model.deleteLater()
    application.processEvents()


def test_the_items_of_a_directory_report_the_totals_of_the_directory() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            file_change("docs/a.txt", size=100),
            file_change("docs/sub/b.txt", size=250),
        ]
    )
    docs = model.index_for_path("docs")
    items = model.data(docs.siblingAtColumn(model.SOURCE_ITEMS), Qt.ItemDataRole.DisplayRole)
    size = model.data(docs.siblingAtColumn(model.SOURCE_SIZE), Qt.ItemDataRole.DisplayRole)
    assert items == "2"
    assert "350" in str(size)
    model.deleteLater()
    application.processEvents()


def test_the_path_filter_keeps_the_directories_of_the_matches() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            file_change("docs/a.txt"),
            file_change("pics/b.jpg"),
        ]
    )
    # The pattern matches the name of an item, the same as in the tree.
    model.set_path_filter("pics")
    paths = set(_paths(model))
    assert paths == {"pics"}
    # A pattern that ends with a slash also shows the contents.
    model.set_path_filter("pics/")
    paths = set(_paths(model))
    assert paths == {"pics", "pics/b.jpg"}
    model.deleteLater()
    application.processEvents()


def test_the_action_filter_hides_the_other_actions() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            file_change("a.txt", ChangeAction.CREATE),
            file_change("b.txt", ChangeAction.UPDATE_CONTENT),
        ]
    )
    model.set_visible_actions({ChangeAction.CREATE})
    paths = set(_paths(model))
    assert "a.txt" in paths
    assert "b.txt" not in paths
    model.deleteLater()
    application.processEvents()


def test_the_unchanged_items_can_be_shown_and_hidden() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            file_change("a.txt", ChangeAction.UPDATE_CONTENT),
            file_change("b.txt", ChangeAction.NO_CHANGE),
        ]
    )
    assert model.rowCount() == 3
    model.set_visible_actions({ChangeAction.UPDATE_CONTENT})
    assert model.rowCount() == 2
    model.deleteLater()
    application.processEvents()


def test_the_flat_view_shows_everything_without_expanding() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            file_change("docs/a.txt"),
            file_change("docs/sub/b.txt"),
        ]
    )
    assert view.model.rowCount() == 5
    # There is nothing to expand: the rows are all there from the start.
    assert not hasattr(view, "expand_initial")
    view.close()
    application.processEvents()


def test_the_flat_view_sorts_the_whole_list_by_size() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            file_change("docs/b.txt", size=10),
            file_change("docs/a.txt", size=20),
            file_change("pics/c.jpg", size=5),
        ]
    )
    # Size sorts the whole list, the way FreeFileSync does it; the directory
    # rows sort by the size of everything below them.
    view._sort_by_section(view.source, view.model.SOURCE_SIZE)
    paths = _paths(view.model)
    assert paths == ["pics/c.jpg", "pics", "docs/b.txt", "docs/a.txt", "docs"]

    # A second click reverses the order.
    view._sort_by_section(view.source, view.model.SOURCE_SIZE)
    paths = _paths(view.model)
    assert paths == ["docs", "docs/a.txt", "docs/b.txt", "pics", "pics/c.jpg"]
    view.close()
    application.processEvents()


def test_sorting_by_name_keeps_the_hierarchy() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            file_change("docs/b.txt"),
            file_change("docs/a.txt"),
        ]
    )
    # The list starts sorted by name, so the first click reverses it.
    view._sort_by_section(view.source, view.model.SOURCE_NAME)
    paths = _paths(view.model)
    assert paths == ["docs", "docs/b.txt", "docs/a.txt"]

    view._sort_by_section(view.source, view.model.SOURCE_NAME)
    paths = _paths(view.model)
    assert paths == ["docs", "docs/a.txt", "docs/b.txt"]
    view.close()
    application.processEvents()


def test_the_flat_view_selects_a_path() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes([file_change("docs/a.txt")])
    view.select_path("docs/a.txt")
    assert view.source.currentIndex().isValid()
    view.close()
    application.processEvents()


def test_the_flat_view_reports_the_visible_changes() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            file_change("a.txt", ChangeAction.CREATE),
            file_change("b.txt", ChangeAction.UPDATE_CONTENT),
        ]
    )
    assert len(view.visible_changes()) == 2
    view.set_action_filter({ChangeAction.CREATE})
    assert len(view.visible_changes()) == 1
    view.close()
    application.processEvents()


def test_the_root_row_carries_the_folder_name_and_the_totals() -> None:
    application = app()
    view = FlatComparisonView()
    view.source_root = "/home/user/data"
    view.set_changes(
        [
            file_change("docs/a.txt", size=100),
            file_change("docs/b.txt", size=200),
            file_change("pics/c.jpg", size=300),
        ]
    )
    index = view.model.index(0, 0)
    assert view.model.data(index, Qt.ItemDataRole.DisplayRole) == "data"
    assert view.model.data(view.model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "3"
    assert "600" in str(
        view.model.data(view.model.index(0, 2), Qt.ItemDataRole.DisplayRole)
    )
    view.close()
    application.processEvents()


def test_the_root_checkbox_decides_the_whole_comparison() -> None:
    from qpy_rsync.core.changes import ChangeDecision

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            file_change("docs/a.txt"),
            file_change("pics/c.jpg"),
        ]
    )
    root_action = view.model.index(0, view.model.ACTION)
    view.model.setData(
        root_action, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole
    )
    assert view.model.decisions.inherited("docs/a.txt") is ChangeDecision.EXCLUDE
    assert view.model.decisions.inherited("pics/c.jpg") is ChangeDecision.EXCLUDE

    view.model.setData(
        root_action, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
    )
    assert view.model.decisions.inherited("docs/a.txt") is ChangeDecision.INCLUDE
    assert view.model.decisions.inherited("pics/c.jpg") is ChangeDecision.INCLUDE
    view.close()
    application.processEvents()


def test_the_optional_columns_can_be_switched_off() -> None:
    from qpy_rsync.storage.settings import app_settings

    application = app()
    app_settings().clear()
    view = FlatComparisonView()
    assert not view.source.isColumnHidden(view.model.SOURCE_SIZE)
    view._save_hidden_columns("source", {view.model.SOURCE_SIZE})
    view._apply_column_visibility()
    assert view.source.isColumnHidden(view.model.SOURCE_SIZE)
    assert not view.source.isColumnHidden(view.model.SOURCE_NAME)
    # The setting survives a new view.
    other = FlatComparisonView()
    assert other.source.isColumnHidden(view.model.SOURCE_SIZE)
    other.close()
    view.close()
    application.processEvents()


def test_a_narrow_saved_header_does_not_hide_the_names() -> None:
    from qpy_rsync.storage.settings import app_settings, encode_binary

    application = app()
    app_settings().clear()
    view = FlatComparisonView()
    header = view.source.horizontalHeader()
    header.resizeSection(view.model.SOURCE_NAME, 20)
    app_settings().setValue(
        "comparison/flat-source-header", encode_binary(header.saveState())
    )
    app_settings().sync()
    view.close()

    restored = FlatComparisonView()
    assert restored.source.columnWidth(restored.model.SOURCE_NAME) >= 160
    restored.close()
    application.processEvents()


def test_local_items_offer_open_actions() -> None:
    application = app()
    view = FlatComparisonView()
    view.source_root = "/home/user/data"
    view.source_is_local = True
    view.set_changes([file_change("docs/a.txt")])
    index = view.model.index_for_path("docs/a.txt")
    tree = view.source
    row = view.model.row_data(index.row())
    _menu, actions = view._build_context_menu(
        tree, "docs/a.txt", index.data(Qt.ItemDataRole.UserRole), row
    )
    assert actions["open_file"] is not None
    assert actions["open_directory"] is not None
    view.close()
    application.processEvents()


def test_remote_items_do_not_offer_open_actions() -> None:
    application = app()
    view = FlatComparisonView()
    view.source_is_local = False
    view.set_changes([file_change("docs/a.txt")])
    index = view.model.index_for_path("docs/a.txt")
    row = view.model.row_data(index.row())
    _menu, actions = view._build_context_menu(
        view.source, "docs/a.txt", index.data(Qt.ItemDataRole.UserRole), row
    )
    assert actions["open_file"] is None
    assert actions["open_directory"] is None
    view.close()
    application.processEvents()


def test_each_side_names_its_own_root_folder() -> None:
    application = app()
    view = FlatComparisonView()
    view.source_root = "/home/user/source-data"
    view.destination_root = "/home/user/dest-data"
    view.set_changes([file_change("docs/a.txt")])
    assert view.model.data(view.model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "source-data"
    assert (
        view.model.data(view.model.index(0, 5), Qt.ItemDataRole.DisplayRole)
        == "dest-data"
    )
    view.close()
    application.processEvents()


def test_the_row_context_menu_offers_restore_all_stashed() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            file_change("a.txt"),
            file_change("b.txt"),
        ]
    )
    view.stash_path("a.txt")
    view.set_show_stashed(True)
    index = view.model.index_for_path("a.txt")
    row = view.model.row_data(index.row())
    _menu, actions = view._build_context_menu(
        view.action, "a.txt", index.data(Qt.ItemDataRole.UserRole), row
    )
    entry = actions["restore_all_stashed"]
    assert entry is not None
    assert entry.text() == "Restore All Stashed (1)"
    view.close()
    application.processEvents()


def test_the_actions_column_sorts_by_action_label() -> None:
    from qpy_rsync.gui.icons import ACTION_LABELS

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            file_change("a.txt", ChangeAction.CREATE),
            file_change("b.txt", ChangeAction.DELETE),
            file_change("c.txt", ChangeAction.UPDATE_CONTENT),
        ]
    )

    def labels() -> list[str]:
        rows = (
            model.row_data(row)
            for row in range(model.rowCount())
        )
        return [
            ACTION_LABELS[row.change.action]
            for row in rows
            if not row.is_directory
        ]

    model.sort(model.ACTION, Qt.SortOrder.AscendingOrder)
    assert labels() == sorted(labels(), key=str.casefold)
    model.sort(model.ACTION, Qt.SortOrder.DescendingOrder)
    assert labels() == sorted(labels(), key=str.casefold, reverse=True)
    model.deleteLater()
    application.processEvents()


def _nested_changes() -> list:
    return [
        file_change("docs/a.txt"),
        file_change("docs/b.txt"),
        file_change("docs/sub/c.txt"),
        file_change("pics/d.jpg"),
        file_change("root.txt"),
    ]


def test_a_folded_directory_hides_its_children_but_not_its_totals() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(_nested_changes())
    visible_before = {change.path for change in model.visible_changes()}

    assert model.toggle_collapsed("docs") is True
    model.refresh_collapsed()

    paths = _paths(model)
    assert paths == ["root.txt", "docs", "pics", "pics/d.jpg"]
    # The fold is display-only: the folded items are still in the comparison.
    assert {change.path for change in model.visible_changes()} == visible_before
    assert model.row_data(0).has_children is True
    assert model.row_data(2).has_children is True
    # Toggling a file makes no sense and reports that.
    assert model.toggle_collapsed("root.txt") is False
    model.deleteLater()
    application.processEvents()


def test_folding_the_root_leaves_only_the_root_row() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(_nested_changes())
    assert model.toggle_collapsed("") is True
    model.refresh_collapsed()
    assert model.rowCount() == 1
    assert model.row_path(0) == ""
    model.expand_all()
    model.refresh_collapsed()
    assert model.rowCount() == 9
    model.deleteLater()
    application.processEvents()


def test_a_path_filter_temporarily_overrides_the_folds() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(_nested_changes())
    model.set_collapsed("docs", True)
    model.refresh_collapsed()
    assert "docs/a.txt" not in set(_paths(model))

    model.set_path_filter("a.txt")
    assert "docs/a.txt" in set(_paths(model))
    model.set_path_filter("")
    assert "docs/a.txt" not in set(_paths(model))
    model.deleteLater()
    application.processEvents()


def test_collapse_all_and_expand_all() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(_nested_changes())
    model.collapse_all()
    model.refresh_collapsed()
    # Every directory with children is folded, so only the root row remains.
    assert model.rowCount() == 1
    assert model.collapsed == {"", "docs", "docs/sub", "pics"}
    model.expand_all()
    model.refresh_collapsed()
    assert model.collapsed == set()
    assert "docs/sub/c.txt" in set(_paths(model))
    model.deleteLater()
    application.processEvents()


def test_a_fold_is_dropped_when_its_directory_disappears() -> None:
    application = app()
    model = FlatChangeModel()
    model.set_changes(_nested_changes())
    model.set_collapsed("docs/sub", True)
    model.set_changes([file_change("pics/d.jpg")])
    assert model.collapsed == set()
    model.deleteLater()
    application.processEvents()


def test_selecting_a_folded_item_reveals_its_parents() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes(_nested_changes())
    view.collapse_path("docs")
    assert view.model.index_for_path("docs/sub/c.txt").isValid() is False

    view.select_path("docs/sub/c.txt")
    application.processEvents()
    assert view.is_collapsed("docs") is False
    assert view.model.index_for_path("docs/sub/c.txt").isValid()

    # Folding the root and selecting a deep item expands the whole chain.
    view.collapse_path("")
    assert view.model.rowCount() == 1
    view.select_path("docs/sub/c.txt")
    assert view.is_collapsed("") is False
    assert view.model.index_for_path("docs/sub/c.txt").isValid()
    view.close()
    application.processEvents()


def test_clicking_the_branch_marker_toggles_a_directory() -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    application = app()
    view = FlatComparisonView()
    view.set_changes(_nested_changes())
    application.processEvents()

    row = next(
        row for row in range(view.model.rowCount())
        if view.model.row_path(row) == "docs"
    )
    index = view.model.index(row, view.model.SOURCE_NAME)
    rect = view.source.visualRect(index)
    point = __import__(
        "qpy_rsync.gui.flat_comparison_view", fromlist=["FlatPathDelegate"]
    ).FlatPathDelegate.chevron_rect(rect, 0).center()

    def click(at: object) -> None:
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(at),
            QPointF(view.source.viewport().mapToGlobal(at)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(view.source.viewport(), event)

    click(point)
    assert view.is_collapsed("docs") is True
    assert "docs/a.txt" not in set(_paths(view.model))
    click(point)
    assert view.is_collapsed("docs") is False
    assert "docs/a.txt" in set(_paths(view.model))
    view.close()
    application.processEvents()


def test_the_fold_menu_offers_the_directory_and_the_whole_tree() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes(_nested_changes())
    directory = view.model.index_for_path("docs")
    row = view.model.row_data(directory.row())
    _menu, actions = view._build_context_menu(
        view.source, "docs", directory.data(Qt.ItemDataRole.UserRole), row
    )
    assert actions["collapse"] is not None
    assert actions["collapse_all"] is not None
    assert actions["expand_all"] is not None

    file_index = view.model.index_for_path("docs/a.txt")
    file_row = view.model.row_data(file_index.row())
    _menu, file_actions = view._build_context_menu(
        view.source,
        "docs/a.txt",
        file_index.data(Qt.ItemDataRole.UserRole),
        file_row,
    )
    assert file_actions["collapse"] is None
    assert file_actions["collapse_all"] is not None
    view.close()
    application.processEvents()


def test_the_arrow_keys_fold_and_unfold_a_directory() -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    application = app()
    view = FlatComparisonView()
    view.set_changes(_nested_changes())
    directory = view.model.index_for_path("docs")
    view.source.setCurrentIndex(directory)

    left = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier
    )
    assert view.eventFilter(view.source, left) is True
    assert view.is_collapsed("docs") is True

    right = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier
    )
    assert view.eventFilter(view.source, right) is True
    assert view.is_collapsed("docs") is False
    view.close()
    application.processEvents()


def test_double_clicking_a_directory_toggles_it() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes(_nested_changes())
    view._handle_double_click(view.source, view.model.index_for_path("docs"))
    assert view.is_collapsed("docs") is True
    view._handle_double_click(view.source, view.model.index_for_path("docs"))
    assert view.is_collapsed("docs") is False
    view.close()
    application.processEvents()

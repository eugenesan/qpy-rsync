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


def test_rows_start_with_the_directories_and_follow_with_their_items() -> None:
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
        "docs/sub",
        "docs/sub/c.txt",
        "docs/a.txt",
        "docs/b.txt",
    ]
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

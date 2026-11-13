import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qpy_rsync.backend.rsync_patterns import matches, phrases_for
from qpy_rsync.core.changes import StashedItems


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _paths(model) -> list[str]:
    """The item paths of the visible rows, without the compared folder."""
    return [
        path
        for path in (model.row_path(row) for row in range(model.rowCount()))
        if path
    ]


def test_the_three_phrases_of_an_item_are_rsync_patterns() -> None:
    phrases = phrases_for("docs/pictures/photo.jpg", is_directory=False)
    patterns = [phrase.pattern for phrase in phrases]
    assert patterns == ["*.jpg", "*/photo.jpg", "/docs/pictures/photo.jpg"]
    # A directory keeps the trailing slash, like rsync expects.
    directory = phrases_for("docs/pictures", is_directory=True)
    assert [phrase.pattern for phrase in directory] == [
        "*/pictures/",
        "/docs/pictures/",
    ]


def test_the_patterns_match_the_paths_they_name() -> None:
    assert matches("*.jpg", "pictures/photo.jpg")
    assert matches("*.jpg", "photo.jpg")
    assert not matches("*.jpg", "pictures/photo.png")
    assert matches("*/photo.jpg", "a/b/photo.jpg")
    assert not matches("*/photo.jpg", "a/b/other.jpg")
    assert matches("/docs/pictures/photo.jpg", "docs/pictures/photo.jpg")
    assert not matches("/docs/pictures/photo.jpg", "other/docs/pictures/photo.jpg")
    # A directory pattern covers everything below it.
    assert matches("/docs/", "docs/pictures/photo.jpg")
    assert matches("/docs/pictures/", "docs/pictures/photo.jpg")


def test_a_stashed_directory_covers_the_items_below_it() -> None:
    stash = StashedItems()
    stash.add("docs/pictures")
    assert stash.is_stashed("docs/pictures")
    assert stash.is_stashed("docs/pictures/photo.jpg")
    assert not stash.is_stashed("docs")
    assert not stash.is_stashed("docs/notes.txt")


def test_a_stashed_item_can_be_restored() -> None:
    stash = StashedItems()
    stash.add("docs/pictures")
    stash.restore("docs/pictures")
    assert not stash.is_stashed("docs/pictures/photo.jpg")


def test_restoring_a_path_also_restores_the_items_below_it() -> None:
    stash = StashedItems()
    stash.add("docs/pictures")
    stash.add("docs/pictures/old")
    stash.restore("docs/pictures")
    assert not stash.is_stashed("docs/pictures/old")


def test_toggling_reports_the_new_state() -> None:
    stash = StashedItems()
    assert stash.toggle("docs/a.txt") is True
    assert stash.is_stashed("docs/a.txt")
    assert stash.toggle("docs/a.txt") is False
    assert not stash.is_stashed("docs/a.txt")


def test_the_stashed_items_can_be_cleared() -> None:
    stash = StashedItems()
    stash.add("a.txt")
    stash.add("b.txt")
    assert stash.count() == 2
    stash.clear()
    assert stash.count() == 0
    assert not stash


def test_stashing_an_item_removes_it_from_the_list() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    assert view.model.rowCount() == 3
    view.stash_path("a.txt")
    paths = set(_paths(view.model))
    assert "a.txt" not in paths
    assert "b.txt" in paths
    view.restore_all_stashed()
    paths = set(_paths(view.model))
    assert "a.txt" in paths
    view.close()
    application.processEvents()


def test_the_stashed_items_can_be_shown_again_in_the_list() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    view.stash_path("a.txt")
    assert view.model.rowCount() == 1
    # The toggle shows the stashed items again, dimmed.
    view.set_show_stashed(True)
    application.processEvents()
    assert view.model.rowCount() == 2
    view.close()
    application.processEvents()


def test_the_space_bar_hides_the_selected_item() -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    application.processEvents()
    index = view.model.index_for_path("a.txt")
    view.source.setCurrentIndex(index)
    view.source.selectionModel().select(
        index,
        view.source.selectionModel().SelectionFlag.ClearAndSelect
        | view.source.selectionModel().SelectionFlag.Rows,
    )
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier
    )
    assert view.eventFilter(view.source, event) is True
    application.processEvents()
    assert view.stashed_paths() == {"a.txt"}
    paths = set(_paths(view.model))
    assert paths == {"b.txt"}
    view.close()
    application.processEvents()


def test_hiding_an_item_excludes_it_from_the_sync() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ObjectKind
    from qpy_rsync.core.enums import EndpointKind
    from qpy_rsync.core.execution_plan import build_execution_plan
    from qpy_rsync.core.models import Endpoint, SyncProfile

    profile = SyncProfile(
        name="test",
        source=Endpoint(EndpointKind.LOCAL, "/src/"),
        destination=Endpoint(EndpointKind.LOCAL, "/dst/"),
    )
    changes = [
        Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f", size=10),
        Change("b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f", size=20),
    ]
    stash = StashedItems()
    stash.add("a.txt")
    plan = build_execution_plan(profile, changes, ChangeDecisions(), stash)
    included = {item.path for item in plan.items if item.included}
    assert included == {"b.txt"}
    assert plan.summary.excluded == 1


def test_stashing_a_directory_excludes_the_items_below_it() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ObjectKind
    from qpy_rsync.core.enums import EndpointKind
    from qpy_rsync.core.execution_plan import build_execution_plan
    from qpy_rsync.core.models import Endpoint, SyncProfile

    profile = SyncProfile(
        name="test",
        source=Endpoint(EndpointKind.LOCAL, "/src/"),
        destination=Endpoint(EndpointKind.LOCAL, "/dst/"),
    )
    changes = [
        Change("docs/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f", size=10),
        Change("other/b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f", size=20),
    ]
    stash = StashedItems()
    stash.add("docs")
    plan = build_execution_plan(profile, changes, ChangeDecisions(), stash)
    included = {item.path for item in plan.items if item.included}
    assert included == {"other/b.txt"}


def test_the_filter_matches_a_folder_with_a_trailing_slash() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("docs/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("docs/sub/b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("pics/c.jpg", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    model.set_path_filter("docs/")
    paths = set(_paths(model))
    assert paths == {"docs", "docs/a.txt", "docs/sub", "docs/sub/b.txt"}
    model.deleteLater()
    application.processEvents()


def test_the_filter_matches_a_relative_path() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("docs/sub/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("docs/other/b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    model.set_path_filter("docs/sub")
    paths = set(_paths(model))
    assert "docs/sub/a.txt" in paths
    assert "docs/other/b.txt" not in paths
    model.deleteLater()
    application.processEvents()


def test_the_filter_field_waits_for_a_pause_and_enter_applies_it() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("docs/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("pics/b.jpg", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    view.filter_edit.setText("docs/")
    # Typing does not re-filter right away.
    assert view.model.rowCount() == 5
    view.filter_edit.returnPressed.emit()
    paths = set(_paths(view.model))
    assert "docs/a.txt" in paths
    assert "pics/b.jpg" not in paths
    view.close()
    application.processEvents()


def test_showing_stashed_items_does_not_change_the_visible_set() -> None:
    """The overview and the statistics must not react to the show toggle."""
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    view.stash_path("a.txt")
    before = [str(change.path) for change in view.visible_changes()]
    view.set_show_stashed(True)
    after = [str(change.path) for change in view.visible_changes()]
    # The row is back in the list, but it is still stashed for the overview.
    assert any(view.model.row_path(row) == "a.txt" for row in range(view.model.rowCount()))
    assert before == after == ["b.txt"]
    view.close()
    application.processEvents()


def test_a_trailing_slash_filters_directories_in() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("docs", ChangeAction.UPDATE_CONTENT, ObjectKind.DIRECTORY, ">d"),
            Change("docs.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("pics/c.jpg", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    # Without the slash a file whose name contains the pattern matches too.
    model.set_path_filter("docs")
    assert "docs.txt" in set(_paths(model))
    # With the slash only the directory is matched, never the file.
    model.set_path_filter("docs/")
    paths = set(_paths(model))
    assert "docs" in paths
    assert "docs.txt" not in paths
    model.deleteLater()
    application.processEvents()


def test_the_stashed_marker_reports_and_toggles_a_row() -> None:
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent

    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import STASHED_ROLE
    from qpy_rsync.gui.flat_comparison_view import (
        ActionColumnDelegate,
        FlatComparisonView,
    )

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    view.stash_path("a.txt")
    view.set_show_stashed(True)
    application.processEvents()

    row = next(
        row for row in range(view.model.rowCount())
        if view.model.row_path(row) == "a.txt"
    )
    index = view.model.index(row, view.model.ACTION)
    assert view.model.data(index, STASHED_ROLE) is True

    rect = view.action.visualRect(index)
    point = ActionColumnDelegate.marker_rect(rect).center()

    def tap(at: object) -> None:
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(at),
            QPointF(view.action.viewport().mapToGlobal(at)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(view.action.viewport(), event)

    # The click must reach the viewport and restore the stashed row.
    tap(point)
    assert view.stashed_paths() == set()
    # The same spot hides it again, so the marker toggles both ways.
    tap(point)
    assert view.stashed_paths() == {"a.txt"}
    # A finger is less precise than a pointer: the row edge is accepted too.
    tap(QPoint(point.x(), rect.top() + 1))
    assert view.stashed_paths() == set()
    view.close()
    application.processEvents()

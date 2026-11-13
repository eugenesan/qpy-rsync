import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qpy_rsync.backend.rsync_patterns import matches, phrases_for
from qpy_rsync.core.changes import HiddenItems


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


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


def test_a_hidden_directory_covers_the_items_below_it() -> None:
    hidden = HiddenItems()
    hidden.hide("docs/pictures")
    assert hidden.is_hidden("docs/pictures")
    assert hidden.is_hidden("docs/pictures/photo.jpg")
    assert not hidden.is_hidden("docs")
    assert not hidden.is_hidden("docs/notes.txt")


def test_a_hidden_item_can_be_shown_again() -> None:
    hidden = HiddenItems()
    hidden.hide("docs/pictures")
    hidden.show("docs/pictures")
    assert not hidden.is_hidden("docs/pictures/photo.jpg")


def test_showing_a_path_also_shows_the_items_below_it() -> None:
    hidden = HiddenItems()
    hidden.hide("docs/pictures")
    hidden.hide("docs/pictures/old")
    hidden.show("docs/pictures")
    assert not hidden.is_hidden("docs/pictures/old")


def test_toggling_reports_the_new_state() -> None:
    hidden = HiddenItems()
    assert hidden.toggle("docs/a.txt") is True
    assert hidden.is_hidden("docs/a.txt")
    assert hidden.toggle("docs/a.txt") is False
    assert not hidden.is_hidden("docs/a.txt")


def test_the_hidden_items_can_be_cleared() -> None:
    hidden = HiddenItems()
    hidden.hide("a.txt")
    hidden.hide("b.txt")
    assert hidden.count() == 2
    hidden.clear()
    assert hidden.count() == 0
    assert not hidden


def test_hiding_an_item_removes_it_from_the_list() -> None:
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
    assert view.model.rowCount() == 2
    view.hide_path("a.txt")
    paths = {view.model.row_path(row) for row in range(view.model.rowCount())}
    assert "a.txt" not in paths
    assert "b.txt" in paths
    view.show_all_hidden()
    paths = {view.model.row_path(row) for row in range(view.model.rowCount())}
    assert "a.txt" in paths
    view.close()
    application.processEvents()


def test_the_hidden_items_can_be_shown_again_in_the_list() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    view.hide_path("a.txt")
    assert view.model.rowCount() == 0
    # The toggle shows the hidden items again, dimmed.
    view.set_show_hidden(True)
    application.processEvents()
    assert view.model.rowCount() == 1
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
    assert view.hidden_paths() == {"a.txt"}
    paths = {view.model.row_path(row) for row in range(view.model.rowCount())}
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
    hidden = HiddenItems()
    hidden.hide("a.txt")
    plan = build_execution_plan(profile, changes, ChangeDecisions(), hidden)
    included = {item.path for item in plan.items if item.included}
    assert included == {"b.txt"}
    assert plan.summary.excluded == 1


def test_hiding_a_directory_excludes_the_items_below_it() -> None:
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
    hidden = HiddenItems()
    hidden.hide("docs")
    plan = build_execution_plan(profile, changes, ChangeDecisions(), hidden)
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
    paths = {model.row_path(row) for row in range(model.rowCount())}
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
    paths = {model.row_path(row) for row in range(model.rowCount())}
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
    assert view.model.rowCount() == 4
    view.filter_edit.returnPressed.emit()
    paths = {view.model.row_path(row) for row in range(view.model.rowCount())}
    assert "docs/a.txt" in paths
    assert "pics/b.jpg" not in paths
    view.close()
    application.processEvents()

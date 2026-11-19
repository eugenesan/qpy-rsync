import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qpy_rsync.backend.rsync_patterns import matches, phrases_for
from qpy_rsync.core.changes import ChangeDecisions
from qpy_rsync.gui.flat_change_model import ExcludedPaths


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
    assert patterns == ["*.jpg", "photo.jpg", "/docs/pictures/photo.jpg"]
    # A directory keeps the trailing slash, like rsync expects.
    directory = phrases_for("docs/pictures", is_directory=True)
    assert [phrase.pattern for phrase in directory] == [
        "pictures/",
        "/docs/pictures/",
    ]


def test_the_patterns_match_the_paths_they_name() -> None:
    assert matches("*.jpg", "pictures/photo.jpg")
    assert matches("*.jpg", "photo.jpg")
    assert not matches("*.jpg", "pictures/photo.png")
    assert matches("photo.jpg", "a/b/photo.jpg")
    assert matches("photo.jpg", "photo.jpg")
    assert not matches("photo.jpg", "a/b/other.jpg")
    assert matches("pictures/", "a/b/pictures/photo.jpg")
    assert matches("/docs/pictures/photo.jpg", "docs/pictures/photo.jpg")
    assert not matches("/docs/pictures/photo.jpg", "other/docs/pictures/photo.jpg")
    # A directory pattern covers everything below it.
    assert matches("/docs/", "docs/pictures/photo.jpg")
    assert matches("/docs/pictures/", "docs/pictures/photo.jpg")


def test_a_excluded_directory_covers_the_items_below_it() -> None:
    exclusion = ExcludedPaths(ChangeDecisions())
    exclusion.add("docs/pictures")
    assert exclusion.is_excluded("docs/pictures")
    assert exclusion.is_excluded("docs/pictures/photo.jpg")
    assert not exclusion.is_excluded("docs")
    assert not exclusion.is_excluded("docs/notes.txt")


def test_a_excluded_item_can_be_restored() -> None:
    exclusion = ExcludedPaths(ChangeDecisions())
    exclusion.add("docs/pictures")
    exclusion.restore("docs/pictures")
    assert not exclusion.is_excluded("docs/pictures/photo.jpg")


def test_restoring_a_path_also_restores_the_items_below_it() -> None:
    exclusion = ExcludedPaths(ChangeDecisions())
    exclusion.add("docs/pictures")
    exclusion.add("docs/pictures/old")
    exclusion.restore("docs/pictures")
    assert not exclusion.is_excluded("docs/pictures/old")


def test_toggling_reports_the_new_state() -> None:
    exclusion = ExcludedPaths(ChangeDecisions())
    assert exclusion.toggle("docs/a.txt") is True
    assert exclusion.is_excluded("docs/a.txt")
    assert exclusion.toggle("docs/a.txt") is False
    assert not exclusion.is_excluded("docs/a.txt")


def test_the_excluded_items_can_be_cleared() -> None:
    exclusion = ExcludedPaths(ChangeDecisions())
    exclusion.add("a.txt")
    exclusion.add("b.txt")
    assert exclusion.count() == 2
    exclusion.clear()
    assert exclusion.count() == 0
    assert not exclusion


def test_exclusioning_an_item_removes_it_from_the_list() -> None:
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
    view.exclude_path("a.txt")
    paths = set(_paths(view.model))
    assert "a.txt" not in paths
    assert "b.txt" in paths
    view.reset_exclusions()
    paths = set(_paths(view.model))
    assert "a.txt" in paths
    view.close()
    application.processEvents()


def test_overview_aggregates_match_the_visible_changes() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    changes = [
        Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", size=100),
        Change("docs/sub/b.txt", ChangeAction.DELETE, ObjectKind.FILE, "*del", size=50),
        Change("root.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", size=25),
    ]
    model = FlatChangeModel()
    model.set_changes(changes)

    def expected() -> dict[str, tuple[int, int]]:
        counts: dict[str, list[int]] = {}
        for change in model.visible_changes():
            path = str(change.path).rstrip("/")
            parent = path.rpartition("/")[0]
            values = counts.get(parent, [0, 0])
            values[0] += 1
            values[1] += int(change.size or 0)
            counts[parent] = values
        return {path: (values[0], values[1]) for path, values in counts.items()}

    assert model.overview_aggregates() == expected()
    model.set_visible_actions({ChangeAction.CREATE})
    assert model.overview_aggregates() == expected()
    model.set_excluded("docs", True)
    assert model.overview_aggregates() == expected()
    model.deleteLater()
    application.processEvents()


def test_exclusioning_a_directory_removes_its_destination_removals_too() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    changes = [
        Change("dir/new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
        Change("dir/old.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        Change("dir/sub/gone.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        Change("other/keep.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
    ]
    model = FlatChangeModel()
    model.set_changes(changes)
    before = set(_paths(model))

    # The incremental refresh used by the space bar and the context menu has
    # to hide every descendant, not just the directory row itself.
    model.set_excluded("dir", True)
    assert set(_paths(model)) == {"other", "other/keep.txt"}
    assert [change.path for change in model.visible_changes()] == ["other/keep.txt"]

    model.set_excluded("dir", False)
    assert set(_paths(model)) == before
    assert len(model.visible_changes()) == len(changes)

    model.deleteLater()
    application.processEvents()


def test_the_excluded_items_can_be_shown_again_in_the_list() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    view.exclude_path("a.txt")
    assert view.model.rowCount() == 1
    # The toggle shows the excluded items again, dimmed.
    view.set_show_excluded(True)
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
    assert view.excluded_paths() == {"a.txt"}
    paths = set(_paths(view.model))
    assert paths == {"b.txt"}
    view.close()
    application.processEvents()


def test_hiding_an_item_excludes_it_from_the_sync() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ChangeDecisions, ObjectKind
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
    decisions = ChangeDecisions()
    decisions.set("a.txt", ChangeDecision.EXCLUDE)
    plan = build_execution_plan(profile, changes, decisions)
    included = {item.path for item in plan.items if item.included}
    assert included == {"b.txt"}
    assert plan.summary.excluded == 1


def test_exclusioning_a_directory_excludes_the_items_below_it() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ChangeDecisions, ObjectKind
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
    decisions = ChangeDecisions()
    decisions.set("docs", ChangeDecision.EXCLUDE)
    plan = build_execution_plan(profile, changes, decisions)
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


def test_search_jumps_without_changing_the_visible_set() -> None:
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
    before = view.model.rowCount()
    view.search_edit.setText("a.txt")
    view.find_next()
    assert view.model.rowCount() == before
    assert view.model.row_path(view.source.currentIndex().row()) == "docs/a.txt"
    view.close()
    application.processEvents()


def test_search_matches_are_cached_and_follow_the_visible_rows() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
            Change("docs/b.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
        ]
    )
    matches = model.search_matches("a.txt")
    assert [model.path_of_row_index(row) for row in matches] == ["docs/a.txt"]
    assert model.search_matches("a.txt") is matches

    model.set_excluded("docs", True)
    assert model.search_matches("a.txt") == []
    model.deleteLater()
    application.processEvents()


def test_search_follows_the_find_and_filter_rules() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change(".git/config", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
            Change(".git/objects/id", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
            Change("src/main.py", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
            Change("first-dir/x.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
            Change("the-dir-old/y.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
            Change("big-dir/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
        ]
    )

    def found(text: str) -> list[str]:
        return [model.path_of_row_index(row) for row in model.search_matches(text)]

    # A bare name matches only the item with that name.
    assert found(".git") == [".git"]
    assert found("config") == [".git/config"]
    # A trailing slash means folders only, matched exactly: no hierarchy,
    # and "dir/" does not find "first-dir/" or "the-dir-old/".
    assert found(".git/") == [".git"]
    assert found("src/") == ["src"]
    assert found("dir/") == []
    assert found("first-dir/") == ["first-dir"]
    # A slash inside the pattern is an unanchored substring of the path.
    assert found("dir/a") == ["big-dir/a.txt"]
    assert found(".git/config") == [".git/config"]
    # Globs work in both forms, including a globbed folder pattern.
    assert found("*dir/") == ["big-dir", "first-dir"]
    assert found("*dir/*.txt") == ["big-dir/a.txt", "first-dir/x.txt"]
    assert found("*.py") == ["src/main.py"]
    assert found("src/*.py") == ["src/main.py"]

    # Folding a folder must not hide its contents from search.
    model.set_collapsed(".git", True)
    assert found("config") == [".git/config"]

    # A folded match must also be reachable through the real navigation path.
    model.refresh_collapsed()
    assert found("config") == [".git/config"]
    model.deleteLater()
    application.processEvents()


def test_search_navigates_matches_without_changing_the_list() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
            Change("pics/a.jpg", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
            Change("other/c.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
        ]
    )
    before = view.model.rowCount()
    view.search_edit.setText("a")
    view._search_timer.stop()
    view._run_search(jump=False)
    assert view.search_status.text() == "0/2"

    view.find_next()
    assert view.search_status.text() == "1/2"
    view.find_next()
    assert view.search_status.text() == "2/2"
    view.find_next()
    assert view.search_status.text() == "1/2"
    view.find_previous()
    assert view.search_status.text() == "2/2"
    assert view.model.rowCount() == before
    view.close()
    application.processEvents()


def test_showing_excluded_items_does_not_change_the_visible_set() -> None:
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
    view.exclude_path("a.txt")
    before = [str(change.path) for change in view.visible_changes()]
    view.set_show_excluded(True)
    after = [str(change.path) for change in view.visible_changes()]
    # The row is back in the list, but it is still excluded for the overview.
    assert any(view.model.row_path(row) == "a.txt" for row in range(view.model.rowCount()))
    assert before == after == ["b.txt"]
    view.close()
    application.processEvents()


def test_a_trailing_slash_matches_the_directory_exactly() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("test/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("tests/b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("dir test/c.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    model.set_path_filter("test/")
    paths = set(_paths(model))
    assert "test" in paths
    assert "test/a.txt" in paths
    assert "tests" not in paths
    assert "dir test" not in paths
    model.deleteLater()
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


def test_the_checkbox_is_the_only_exclusion_control() -> None:
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
    # The crossed-eye marker and its dedicated hit target are gone.
    assert not hasattr(view.action.itemDelegate(), "marker_rect")
    assert not hasattr(view, "_exclusion_target")

    index = view.model.index_for_path("a.txt")
    view.model.setData(
        view.model.index(index.row(), view.model.ACTION),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert view.excluded_paths() == {"a.txt"}
    assert "a.txt" not in _paths(view.model)

    # The checkbox restores it; there is no second marker to click.
    view.set_show_excluded(True)
    application.processEvents()
    row = next(
        row
        for row in range(view.model.rowCount())
        if view.model.row_path(row) == "a.txt"
    )
    view.model.setData(
        view.model.index(row, view.model.ACTION),
        Qt.CheckState.Checked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert view.excluded_paths() == set()
    view.close()
    application.processEvents()


def test_a_filter_never_leaves_a_folder_without_its_items() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.action_filters import FILTERABLE_ACTIONS
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("docs/photo.png", ChangeAction.NO_CHANGE, ObjectKind.FILE, "="),
            Change("docs/other.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    model.set_visible_actions(set(FILTERABLE_ACTIONS))
    model.set_path_filter("png")

    # The unchanged item is filtered out by the action filter, so the folder
    # that holds it must not stay behind on its own.
    assert "docs" not in set(_paths(model))
    assert "docs/photo.png" not in set(_paths(model))

    # With the unchanged items allowed, the match and its folder are shown.
    model.set_visible_actions(set(FILTERABLE_ACTIONS) | {ChangeAction.NO_CHANGE})
    paths = set(_paths(model))
    assert "docs" in paths
    assert "docs/photo.png" in paths
    model.deleteLater()
    application.processEvents()


def test_the_unchanged_items_survive_the_action_filter() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.action_filters import FILTERABLE_ACTIONS
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("same.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, "="),
            Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
        ]
    )
    model.set_visible_actions(set(FILTERABLE_ACTIONS))
    assert "same.txt" not in set(_paths(model))
    model.set_visible_actions(set(FILTERABLE_ACTIONS) | {ChangeAction.NO_CHANGE})
    assert "same.txt" in set(_paths(model))
    model.deleteLater()
    application.processEvents()


def test_the_excluded_items_are_shown_even_when_the_action_filter_excludes_them() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("updated.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("created.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
        ]
    )
    model.exclusion.add("updated.txt")
    model.set_visible_actions({ChangeAction.CREATE})
    model.refresh_exclusions()

    # The excluded item is put aside, so it is out of the list.
    assert "updated.txt" not in set(_paths(model))

    # Asking for the excluded items shows them, whatever the action filters
    # say, because the toggle is about what was put aside.
    model.show_excluded = True
    model.refresh_exclusions()
    paths = set(_paths(model))
    assert "updated.txt" in paths
    assert "created.txt" in paths
    model.deleteLater()
    application.processEvents()


def test_action_filters_can_apply_to_directories() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel

    app()
    model = FlatChangeModel()
    model.set_changes(
        [
            Change("docs/", ChangeAction.UPDATE_METADATA, ObjectKind.DIRECTORY, ".d...p......"),
            Change("docs/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
        ]
    )
    model._build_rows()
    model._apply_filters()
    before = [c.path for c in model.visible_changes()]
    assert "docs/" in before

    model.set_visible_actions({ChangeAction.UPDATE_CONTENT})
    assert "docs/" in [c.path for c in model.visible_changes()]
    directory = model._directories["docs"]
    assert not directory.faded

    model.set_filter_directories(True)
    after = [c.path for c in model.visible_changes()]
    assert "docs/" not in after
    assert model._directories["docs"].faded
    assert "docs" in [model.row_path(r) for r in range(model.rowCount())]
    model.deleteLater()


def test_directory_sizes_only_count_affected_items() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.flat_change_model import FlatChangeModel
    from PySide6.QtCore import Qt

    app()
    model = FlatChangeModel()
    model.set_changes(
        [Change("Temp/", ChangeAction.UPDATE_METADATA, ObjectKind.DIRECTORY, ".d..t......")]
    )
    model.source_root = "/src"
    model.destination_root = "/dst"
    model._build_rows()
    model._apply_filters()
    model.set_destination_metadata(
        {"Temp": (4096, "t"), "Temp/big.bin": (10_000_000, "t")}
    )
    model._apply_filters()
    row = model.index(1, model.SOURCE_NAME)
    assert model.data(model.index(row.row(), model.SOURCE_ITEMS), Qt.ItemDataRole.DisplayRole) == "0"
    assert model.data(model.index(row.row(), model.SOURCE_SIZE), Qt.ItemDataRole.DisplayRole) == "0 B"
    assert model.data(model.index(row.row(), model.DESTINATION_SIZE), Qt.ItemDataRole.DisplayRole) == "0 B"
    model.deleteLater()


def test_changed_decisions_are_filterable_and_reviewable() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ChangeDecision, ObjectKind
    from qpy_rsync.gui.flat_change_model import CONFLICT_ROLE, FlatChangeModel

    application = app()
    model = FlatChangeModel()
    model.set_changes([Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")])
    model.decisions.set("a.txt", ChangeDecision.INCLUDE)
    model.decisions.reconcile(model.changes)

    model.set_changes(
        [Change("a.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")]
    )
    assert model.conflicts()
    index = model.index_for_path("a.txt")
    assert model.data(model.index(index.row(), model.SOURCE_NAME), CONFLICT_ROLE)

    model.set_conflicts_only(True)
    paths = {
        model.row_path(row)
        for row in range(model.rowCount())
        if model.row_path(row)
    }
    assert paths == {"a.txt"}

    assert model.accept_defaults_for_conflicts() == 1
    assert not model.conflicts()
    assert model.decisions.explicit("a.txt") is ChangeDecision.INHERIT
    model.deleteLater()
    application.processEvents()

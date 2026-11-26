"""Regression tests for the "Use as Source/Destination..." folder action."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QMenu,
    QPushButton,
)

from qpy_rsync.backend.rsync_filters import (
    filter_text_to_rules,
    shorten_filter_rule,
    shorten_filter_text,
)
from qpy_rsync.backend.rsync_parser import ParseResult
from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.gui.flat_comparison_view import FlatComparisonView
from qpy_rsync.gui.main_window import MainWindow
from qpy_rsync.gui.use_as_location_dialog import UseAsLocationDialog
from qpy_rsync.services.compare_service import CompareResult
from qpy_rsync.storage.settings import app_settings


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_filter_prefix_rewriting() -> None:
    assert shorten_filter_rule("- /docs/private/", "docs") == "- /private/"
    assert shorten_filter_rule("+ /docs/**", "/docs/") == "+ /**"
    assert shorten_filter_rule("-s /docs/old/", "docs") == "-s /old/"
    assert shorten_filter_rule("- /other/", "docs") == "- /other/"
    assert shorten_filter_rule("# comment", "docs") == "# comment"
    assert shorten_filter_rule("- /docs/private/", "") == "- /docs/private/"
    # A rule naming the eliminated folder itself matches the new root.
    assert shorten_filter_rule("- /docs/", "docs") == "- /"
    text = "# note\n- /docs/a/\n+ /docs/b/\n- /keep/"
    assert shorten_filter_text(text, "docs") == "# note\n- /a/\n+ /b/\n- /keep/"


def test_dialog_offers_only_both_and_cancel_and_shows_the_new_paths() -> None:
    application = app()
    dialog = UseAsLocationDialog("docs", "/src/", "alice@host:/srv/data/")
    labels = [button.text() for button in dialog.findChildren(QPushButton)]
    assert labels.count("Use as Both") == 1
    assert "Use as Source" not in labels
    assert "Use as Destination" not in labels
    assert "Cancel" in labels
    assert dialog.source_label.text() == "/src/docs/"
    assert dialog.destination_label.text() == "alice@host:/srv/data/docs/"
    checkbox = dialog.findChild(QCheckBox)
    assert checkbox is not None and checkbox.isChecked()
    assert dialog.update_filters()
    note = dialog.findChild(QLabel, "use-as-location-note")
    assert note is not None
    assert "stale" in note.text()
    assert "Compare" in note.text()
    assert "Save" in note.text() and "Save As" in note.text()
    checkbox.setChecked(False)
    assert not dialog.update_filters()
    dialog.close()
    application.processEvents()


def test_dialog_buttons_accept_and_reject() -> None:
    application = app()
    cases = (
        ("Use as Both", QDialog.DialogCode.Accepted),
        ("Cancel", QDialog.DialogCode.Rejected),
    )
    for label, expected in cases:
        dialog = UseAsLocationDialog("docs", "/src/", "/dst/")
        finished: list[int] = []
        dialog.finished.connect(finished.append)
        button = next(
            item for item in dialog.findChildren(QPushButton) if item.text() == label
        )
        button.click()
        application.processEvents()
        assert finished == [expected]
        dialog.close()
    application.processEvents()


def _window_with_comparison() -> MainWindow:
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    window._baseline_profile = window._profile()
    result = CompareResult(
        ParseResult(
            [Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", 10)],
            [],
        ),
        "",
        0,
    )
    window._comparison_finished(result)
    app().processEvents()
    return window


def _click_dialog_button(window: MainWindow, label: str, *, uncheck: bool = False) -> None:
    def click() -> None:
        dialog = window.findChild(UseAsLocationDialog)
        assert dialog is not None
        if uncheck:
            dialog.update_filters_checkbox.setChecked(False)
        button = next(
            item for item in dialog.findChildren(QPushButton) if item.text() == label
        )
        button.click()

    QTimer.singleShot(0, click)


def test_use_as_location_dives_into_both_sides_and_marks_comparison_stale() -> None:
    application = app()
    window = _window_with_comparison()
    try:
        assert not window.comparison.model.stale
        window._filters_text = "# note\n- /docs/private/\n- /keep/"
        window._filters = filter_text_to_rules(window._filters_text)
        window._set_verify_state("verified")
        window._verified_plan = object()

        _click_dialog_button(window, "Use as Both")
        window._use_as_location("docs")

        assert window.source_edit.text() == "/src/docs/"
        assert window.destination_edit.text() == "/dst/docs/"
        assert window._profile().source.kind is EndpointKind.LOCAL
        assert window._profile().destination.kind is EndpointKind.LOCAL
        assert window._filters_text == "# note\n- /private/\n- /keep/"
        assert window.comparison.model.stale
        assert not window.synchronize_button.isEnabled()
        assert not window.validate_plan_button.isEnabled()
        assert window._verify_state == "idle"
        assert window._verified_plan is None
        assert not window.comparison.model.decisions_enabled
        status = window.status_edit.text()
        assert "Stale comparison" in status
        assert "Compare again" in status
        assert "Save or Save As" in status
        assert "STATE stale (locations changed to docs)" in window.log.toPlainText()
    finally:
        window.close()
        application.processEvents()


def test_use_as_location_can_skip_filter_rewriting() -> None:
    application = app()
    window = _window_with_comparison()
    try:
        window._filters_text = "- /docs/private/"
        window._filters = filter_text_to_rules(window._filters_text)
        _click_dialog_button(window, "Use as Both", uncheck=True)
        window._use_as_location("docs")
        assert window._filters_text == "- /docs/private/"
        assert window.comparison.model.stale
    finally:
        window.close()
        application.processEvents()


def test_use_as_location_cancel_keeps_locations_and_fresh_comparison() -> None:
    application = app()
    window = _window_with_comparison()
    try:
        _click_dialog_button(window, "Cancel")
        window._use_as_location("docs")
        assert window.source_edit.text() == "/src/"
        assert window.destination_edit.text() == "/dst/"
        assert not window.comparison.model.stale
    finally:
        window.close()
        application.processEvents()


def test_python_context_menu_offers_the_action_only_on_directory_rows() -> None:
    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", 10)]
    )
    application.processEvents()

    def entries(path: str) -> tuple[list[str], object]:
        index = view.model.index_for_path(path)
        row = view.model.row_data(index.row())
        menu, actions = view._build_context_menu(
            view.source, path, index.data(Qt.ItemDataRole.UserRole), row
        )
        return [action.text() for action in menu.actions()], actions["use_as_location"]

    labels, directory_action = entries("docs")
    assert "Use as Source/Destination..." in labels
    assert directory_action is not None
    labels, _ = entries("docs/a.txt")
    assert "Use as Source/Destination..." not in labels
    labels, _ = entries("")
    assert "Use as Source/Destination..." not in labels
    view.close()
    application.processEvents()


def test_native_context_menus_offer_the_action_only_on_directory_rows(monkeypatch) -> None:
    pytest.importorskip("qpy_rsync.native_hybrid")
    application = app()
    monkeypatch.setenv("QPY_HYBRID_VIEW", "1")
    settings = app_settings()
    settings.setValue("advanced/python_view", False)
    settings.sync()
    window = MainWindow()
    try:
        window.source_edit.setText("/src/")
        window.destination_edit.setText("/dst/")
        window._active_profile = window._profile()
        window._comparison_finished(
            CompareResult(
                ParseResult(
                    [Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", 10)],
                    [],
                ),
                "",
                0,
            )
        )
        application.processEvents()
        assert window._hybrid_view is not None

        captured: list[list[str]] = []

        def capture_menu(menu: QMenu) -> object:
            captured.append([action.text() for action in menu.actions()])
            return None

        # PySide6 resolves exec on the instance, so patch every menu as it is
        # constructed instead of replacing the method on the class.
        original_init = QMenu.__init__

        def menu_init(menu: QMenu, *args, **kwargs) -> None:
            original_init(menu, *args, **kwargs)
            menu.exec = lambda *_a, **_kw: capture_menu(menu)  # type: ignore[method-assign]

        monkeypatch.setattr(QMenu, "__init__", menu_init)
        window._native_context_menu(0, "docs", 0, 0)
        window._native_context_menu(0, "docs/a.txt", 0, 0)
        window._native_context_menu(0, "\x01__qpy_root__", 0, 0)
        assert len(captured) == 3
        assert "Use as Source/Destination..." in captured[0]
        assert "Use as Source/Destination..." not in captured[1]
        assert "Use as Source/Destination..." not in captured[2]

        captured.clear()
        window._native_overview_context_menu("docs", 0, 0)
        window._native_overview_context_menu("", 0, 0)
        assert len(captured) == 1
        assert "Use as Source/Destination..." in captured[0]
    finally:
        window.close()
        application.processEvents()


def test_python_overview_context_menu_offers_the_action(monkeypatch) -> None:
    from qpy_rsync.gui.overview import OverviewPane

    application = app()
    pane = OverviewPane()
    pane.set_paths(["docs/a.txt"])
    pane.set_aggregates({"docs": (1, 10), "": (1, 10)})
    application.processEvents()
    root = pane.model.index(0, 0)
    assert root.isValid()
    folder = next(
        pane.model.index(row, 0, root)
        for row in range(pane.model.rowCount(root))
        if pane.model.index(row, 0, root).internalPointer().path == "docs"
    )
    captured: list[list[str]] = []

    def capture_menu(menu: QMenu) -> object:
        captured.append([action.text() for action in menu.actions()])
        return None

    original_init = QMenu.__init__

    def menu_init(menu: QMenu, *args, **kwargs) -> None:
        original_init(menu, *args, **kwargs)
        menu.exec = lambda *_a, **_kw: capture_menu(menu)  # type: ignore[method-assign]

    monkeypatch.setattr(QMenu, "__init__", menu_init)
    monkeypatch.setattr(pane.tree, "indexAt", lambda _point: folder)
    pane._show_context_menu(QPoint(0, 0))
    assert captured
    assert "Use as Source/Destination..." in captured[0]
    pane.close()
    application.processEvents()


def test_use_as_location_keeps_ssh_and_local_endpoint_semantics() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    try:
        window.source_edit.setText("alice@host:/srv/data/")
        window.destination_edit.setText("/mnt/backup/")
        _click_dialog_button(window, "Use as Both")
        window._use_as_location("docs")
        source = window._profile().source
        destination = window._profile().destination
        assert source.kind is EndpointKind.SSH
        assert source.host == "host" and source.user == "alice"
        assert source.path == "/srv/data/docs/"
        assert destination.kind is EndpointKind.LOCAL
        assert destination.path == "/mnt/backup/docs/"
    finally:
        window.close()
        application.processEvents()

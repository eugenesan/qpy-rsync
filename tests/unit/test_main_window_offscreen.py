import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings, Qt
from PySide6.QtWidgets import QApplication

from qpy_rsync.gui.main_window import MainWindow


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_wide_workflow_controls_and_swap(tmp_path) -> None:
    application = app()
    QCoreApplication.setOrganizationName("qpy-rsync-tests")
    QCoreApplication.setApplicationName("wide-ui")
    QSettings().clear()
    window = MainWindow()
    assert window.validate_plan_button.text() == "Verify Actions"
    assert not window.swap_button.icon().isNull()
    assert window.swap_button.toolTip() == "Swap Source and Destination"
    assert window.comparison.filter_edit.minimumWidth() == 180
    assert window.comparison.filter_edit.maximumWidth() > 1000
    assert window.comparison.controls.sizePolicy().horizontalPolicy().name == "Expanding"
    assert not window.comparison.expand_button.text()
    assert not window.comparison.collapse_button.text()
    assert not window.comparison.expand_button.icon().isNull()
    assert not window.comparison.collapse_button.icon().isNull()
    assert not window.comparison.inventory_button.icon().isNull()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._swap_endpoints()
    assert window.source_edit.text() == "/dst/"
    assert window.destination_edit.text() == "/src/"
    window.close()
    application.processEvents()


def test_startup_hides_selected_actions() -> None:
    application = app()
    QSettings().clear()
    window = MainWindow()
    assert not window.plan_summary_label.isVisible()
    assert "Choose Source and Destination" in window.status_label.text()
    window.close()
    application.processEvents()


def test_backup_change_keeps_comparison_fresh() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.compare_service import CompareResult
    from qpy_rsync.backend.rsync_parser import ParseResult

    application = app()
    QSettings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    result = CompareResult(
        ParseResult(
            [Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")],
            [],
        ),
        "",
        0,
    )
    window._comparison_finished(result)
    assert window.comparison.model.decisions_enabled
    assert window._current_plan is not None
    window.backup_edit.setText("/recovery")
    window._backup_changed()
    assert window.comparison.model.decisions_enabled
    assert window._current_plan is not None
    assert window._current_plan.summary.backup_enabled
    assert window.validate_plan_button.isEnabled()
    window.close()
    application.processEvents()


def test_swap_marks_existing_comparison_outdated() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.services.compare_service import CompareResult

    application = app()
    QSettings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    window._comparison_finished(
        CompareResult(
            ParseResult(
                [Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")],
                [],
            ),
            "",
            0,
        )
    )
    window._swap_endpoints()
    assert window.source_edit.text() == "/dst/"
    assert window.destination_edit.text() == "/src/"
    assert not window.comparison.model.decisions_enabled
    assert not window.comparison.source.isEnabled()
    assert not window.comparison.action.isEnabled()
    assert not window.comparison.destination.isEnabled()
    assert "#0891B2" in window.source_edit.styleSheet()
    assert window._current_plan is None
    assert not window.validate_plan_button.isEnabled()
    assert "old direction" in window.status_label.text()
    window.close()
    application.processEvents()

def test_browse_start_uses_existing_parent(tmp_path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    requested = existing / "missing" / "child"
    assert MainWindow._browse_start_directory(str(requested)) == str(existing)
    assert MainWindow._browse_start_directory("nas:/remote/path") == str(Path.home())


def test_filter_find_focus_and_ui_labels() -> None:
    application = app()
    QSettings().clear()
    window = MainWindow()
    window.comparison.filter_edit.setText("*.jpg")
    window.comparison.filter_button.click()
    application.processEvents()
    assert window.comparison.filter_edit.selectedText() == "*.jpg"
    assert window.comparison.model.HEADERS[0] == "File/Directory"
    assert window.comparison.model.HEADERS[4] == "File/Directory"
    assert window.log_header.text() == "Journal"
    source_label = window.findChild(type(window.status_label), "source-location-label")
    destination_label = window.findChild(type(window.status_label), "destination-location-label")
    assert not source_label.pixmap().isNull()
    assert not destination_label.pixmap().isNull()
    assert source_label.toolTip() == "Source directory"
    assert destination_label.toolTip() == "Destination directory"
    window.close()
    application.processEvents()

def test_mode_reset_sequence_clears_proxy_selection_without_stale_indexes() -> None:
    from PySide6.QtCore import Qt
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    QSettings().clear()
    window = MainWindow()
    window.comparison.set_changes(
        [Change("docs/file.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting")]
    )
    directory = window.comparison.proxy.index(0, window.comparison.model.ACTION)
    window.comparison.action.setCurrentIndex(directory)
    window.comparison.model.setData(
        window.comparison.model.index(0, window.comparison.model.ACTION),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )
    window.comparison.set_changes(
        [Change("docs/file.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")]
    )
    window.comparison.set_stale(True)
    application.processEvents()
    assert not window.comparison.action.currentIndex().isValid()
    window.close()
    application.processEvents()

def test_proxy_index_path_is_mapped_to_source_safely() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    QSettings().clear()
    window = MainWindow()
    window.comparison.set_changes(
        [Change("docs/file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    )
    application.processEvents()
    proxy_index = window.comparison.proxy.index(0, window.comparison.model.ACTION)
    assert window.comparison._source_path_for_proxy_index(proxy_index) == "docs"
    window.close()
    application.processEvents()

def test_command_line_options_override_restored_values_without_immediate_persistence(monkeypatch) -> None:
    from qpy_rsync.app import StartupOptions
    from qpy_rsync.core.enums import SyncMode

    application = app()
    QSettings().clear()
    settings = QSettings()
    settings.setValue("comparison/source", "/remembered-source/")
    settings.setValue("comparison/destination", "/remembered-destination/")
    window = MainWindow()
    window.apply_startup_options(
        StartupOptions(
            "/cli-source/",
            "/cli-destination/",
            "/cli-backup/",
            SyncMode.MIRROR,
            False,
        )
    )
    assert window.source_edit.text() == "/cli-source/"
    assert window.destination_edit.text() == "/cli-destination/"
    assert window.backup_edit.text() == "/cli-backup/"
    assert window.sync_mode.currentData() == SyncMode.MIRROR
    assert settings.value("comparison/source") == "/remembered-source/"
    assert settings.value("comparison/destination") == "/remembered-destination/"
    window.close()
    application.processEvents()


def test_command_line_compare_is_queued(monkeypatch) -> None:
    from qpy_rsync.app import StartupOptions
    from qpy_rsync.core.enums import SyncMode

    application = app()
    QSettings().clear()
    queued = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QTimer.singleShot",
        lambda delay, callback: queued.append((delay, callback)),
    )
    window = MainWindow()
    window.apply_startup_options(
        StartupOptions("/src/", "/dst/", None, SyncMode.UPDATE, True)
    )
    assert len(queued) == 1
    assert queued[0][0] == 0
    assert queued[0][1] == window._compare
    window.close()
    application.processEvents()

def test_xdg_default_log_and_visible_pane_preserve_history(tmp_path, monkeypatch) -> None:
    application = app()
    QSettings().clear()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    window = MainWindow()
    window._restore_logging_settings()
    assert window.log_file_edit.text() == str(tmp_path / "state" / "qpy-rsync.log")
    window._append_log("rsync progress first")
    window._append_log("rsync stats second")
    assert "rsync progress first" in window.log.toPlainText()
    assert "rsync stats second" in window.log.toPlainText()
    content = (tmp_path / "state" / "qpy-rsync.log").read_text(encoding="utf-8")
    assert "rsync progress first" in content
    assert "rsync stats second" in content
    window.close(); application.processEvents()

def test_sync_terminal_events_are_written_to_diagnostics(tmp_path, monkeypatch) -> None:
    from qpy_rsync.core.execution_gate import ExecutionGateState
    from qpy_rsync.services.sync_service import SyncResult

    application = app()
    QSettings().clear()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    window = MainWindow()
    window._restore_logging_settings()

    window._execution_gate._state = ExecutionGateState.EXECUTING
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QTimer.singleShot",
        lambda _delay, _callback: None,
    )
    window._sync_finished(SyncResult(0, "", ""))
    assert "STATE synchronization-completed exit_code=0" in window.log.toPlainText()

    window._execution_gate._state = ExecutionGateState.EXECUTING
    window._sync_error("cancelled", True)
    assert "STATE synchronization-cancelled" in window.log.toPlainText()

    window._execution_gate._state = ExecutionGateState.EXECUTING
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QMessageBox.critical",
        lambda *_args, **_kwargs: None,
    )
    window._sync_error("failed", False)
    assert "STATE synchronization-failed" in window.log.toPlainText()

    content = (tmp_path / "state" / "qpy-rsync.log").read_text(encoding="utf-8")
    assert "STATE synchronization-completed exit_code=0" in content
    assert "STATE synchronization-cancelled" in content
    assert "STATE synchronization-failed" in content
    window.close()
    application.processEvents()

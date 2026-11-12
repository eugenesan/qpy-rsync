import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QLabel

from qpy_rsync.gui.comparison_view import CONTROL_SIZE
from qpy_rsync.gui.main_window import MainWindow
from qpy_rsync.storage.settings import app_settings


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_wide_workflow_controls_and_swap(tmp_path) -> None:
    application = app()
    QCoreApplication.setOrganizationName("qpy-rsync-tests")
    QCoreApplication.setApplicationName("wide-ui")
    app_settings().clear()
    window = MainWindow()
    assert window.validate_plan_button.accessibleName() == "Verify Actions"
    assert window.swap_button.accessibleName() == "Swap Source and Destination"
    assert window.swap_button.toolTip() == "Swap Source and Destination"
    assert window.comparison.filter_edit.minimumWidth() == 180
    assert window.comparison.filter_edit.maximumWidth() > 1000
    assert window.comparison.controls.sizePolicy().horizontalPolicy().name == "Expanding"
    assert not window.comparison.expand_button.text()
    assert not window.comparison.collapse_button.text()
    assert not window.comparison.expand_button.icon().isNull()
    assert not window.comparison.collapse_button.icon().isNull()
    assert not window.comparison.inventory_button.icon().isNull()
    # The toolbar actions are icon buttons of the common control size.
    for button in (
        window.swap_button,
        window.compare_button,
        window.inventory_after_compare_button,
        window.validate_plan_button,
        window.synchronize_button,
        window.cancel_button,
        window.pause_button,
        window.filters_button,
        window.load_profile_button,
        window.save_profile_button,
    ):
        assert not button.icon().isNull()
        assert button.width() == CONTROL_SIZE
        assert button.height() == CONTROL_SIZE
    for button in (
        window.comparison.inventory_button,
        window.comparison.expand_button,
        window.comparison.collapse_button,
    ):
        assert button.size().width() == 40
        assert button.iconSize().width() == 24
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._swap_endpoints()
    assert window.source_edit.text() == "/dst/"
    assert window.destination_edit.text() == "/src/"
    window.close()
    application.processEvents()


def test_startup_hides_selected_actions() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    assert not hasattr(window.overview, "summary_label")
    assert "Selected:" not in window.log.toPlainText()
    assert "Choose Source and Destination" in window.status_edit.text()
    window.close()
    application.processEvents()


def test_backup_change_keeps_comparison_fresh() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.compare_service import CompareResult
    from qpy_rsync.backend.rsync_parser import ParseResult

    application = app()
    app_settings().clear()
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
    app_settings().clear()
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
    assert "old direction" in window.status_edit.text()
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
    app_settings().clear()
    window = MainWindow()
    window.comparison.filter_edit.setText("*.jpg")
    window.comparison.filter_button.click()
    application.processEvents()
    assert window.comparison.filter_edit.selectedText() == "*.jpg"
    assert window.comparison.model.HEADERS[0] == "Item"
    assert window.comparison.model.HEADERS[1] == "Items"
    assert window.comparison.model.HEADERS[5] == "Item"
    assert window.comparison.model.HEADERS[6] == "Items"
    assert window.log_header.text() == "Journal"
    source_label = window.findChild(QLabel, "source-location-label")
    destination_label = window.findChild(QLabel, "destination-location-label")
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
    app_settings().clear()
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
    app_settings().clear()
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
    app_settings().clear()
    settings = app_settings()
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
    app_settings().clear()
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
    app_settings().clear()
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
    app_settings().clear()
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


def test_unchanged_inventory_is_async_and_cached() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    changed = Change(
        "file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"
    )
    window._last_changed_changes = [changed]

    gathered: list[object] = []

    class FakeInventory:
        def gather(self, profile, changes):
            gathered.append((profile, changes))
            return 7

        def cancel(self):
            pass

    window._inventory_service = FakeInventory()
    window.show_unchanged.setChecked(True)
    assert len(gathered) == 1
    # The compared objects are shown while the inventory is still running.
    assert window.comparison.model.rowCount() == 1

    extra = Change("same.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, "=")
    window._inventory_finished(7, [extra])
    assert window.comparison.model.rowCount() == 2
    # The unchanged object appears without another comparison.
    assert window.comparison.proxy.rowCount() == 2
    assert "unchanged=1" in window.log.toPlainText()

    window.show_unchanged.setChecked(False)
    window.show_unchanged.setChecked(True)
    assert len(gathered) == 1
    assert window.comparison.model.rowCount() == 2
    window.close()
    application.processEvents()


def test_command_preview_wraps_without_widening_window() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.resize(900, 620)
    window.ensurePolished()
    width = window.minimumSizeHint().width()
    long_path = "/srv/" + "/".join(f"segment-{index}" for index in range(30)) + "/"
    window.source_edit.setText(long_path)
    window.destination_edit.setText(long_path.replace("/srv/", "/backup/"))
    window._set_hovered_action("compare")
    window._update_command_preview()
    application.processEvents()
    preview = window.command_preview_label
    assert preview.full_text().startswith("$ rsync ")
    assert not preview.isHidden()
    assert preview.lineWrapMode() == preview.LineWrapMode.WidgetWidth
    assert (
        preview.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert window.minimumSizeHint().width() == width
    window.close()
    application.processEvents()


def test_command_preview_splitter_is_resizable() -> None:
    from PySide6.QtWidgets import QSizePolicy

    application = app()
    app_settings().clear()
    window = MainWindow()
    preview = window.command_preview_label
    assert window.preview_log_splitter.orientation() == Qt.Orientation.Vertical
    assert window.preview_log_splitter.indexOf(preview) >= 0
    assert window.preview_log_splitter.handleWidth() >= 6
    assert not preview.isHidden()
    assert preview.sizePolicy().verticalPolicy() != QSizePolicy.Policy.Fixed
    assert preview.maximumHeight() > preview.minimumHeight()
    assert (
        window.log.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
    )
    assert window.log.minimumHeight() < window.log.minimumSizeHint().height()
    # The Journal label keeps its natural height so no gap opens up between
    # the label and the Journal box.
    assert window.log_header.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    # Status messages share the row of the Journal label.
    assert window.log_header.parentWidget() is window.status_edit.parentWidget()
    window.close()
    application.processEvents()


def test_recent_profile_is_stored_in_app_settings(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    window = MainWindow()
    window.source_edit.setText(str(tmp_path / "src"))
    window.destination_edit.setText(str(tmp_path / "dst"))
    window._save_recent_profile()

    settings = app_settings()
    assert settings.contains("profile/recent")
    assert not settings.contains("profile/recent_path")
    assert not (tmp_path / ".local/share/qpy-rsync/recent-profile.json").exists()

    restored = MainWindow()
    # Endpoint parsing treats the location as a directory and appends a slash.
    assert restored.source_edit.text() == str(tmp_path / "src") + "/"
    assert restored.destination_edit.text() == str(tmp_path / "dst") + "/"
    window.close()
    restored.close()
    application.processEvents()
def test_bulk_logging_flushes_once_at_the_end() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.log.clear()
    window._begin_bulk_logging()
    window._append_log("first record")
    window._append_log("second record")
    assert window.log.toPlainText() == ""
    window._end_bulk_logging()
    text = window.log.toPlainText()
    assert "first record" in text
    assert "second record" in text
    window.close()
    application.processEvents()


def test_verification_reuses_fresh_comparison() -> None:
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.compare_service import CompareResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    changes = [
        Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")
    ]
    window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))

    class RejectProcess:
        def validate(self, *_args, **_kwargs):
            raise AssertionError("fresh comparisons must not start another dry run")

    window._plan_validation = RejectProcess()
    window._validate_selected_plan()
    assert window.validate_plan_button.accessibleName() == "Actions Verified"
    assert window._validated_plan is window._current_plan
    assert "STATE verification-reused-comparison" in window.log.toPlainText()
    log = window.log.toPlainText()
    assert "Selected: 1 item, 0 B; new 0, updated 1" in log
    assert (
        "Actions verified, selected: new 0, updated 1, metadata 0, "
        "replaced 0, deleted 0; 1 item, 0 B"
    ) in log
    assert window.progress_label.text() == "Selected actions verified"
    assert not window.cancel_button.isEnabled()
    window.close()
    application.processEvents()


def test_verification_can_be_cancelled() -> None:
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.compare_service import CompareResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    changes = [
        Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")
    ]
    window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
    window._plan_validation_started()
    assert window.cancel_button.isEnabled()
    window._plan_validation_cancelled()
    assert not window.cancel_button.isEnabled()
    assert window.validate_plan_button.accessibleName() == "Verify Actions"
    assert window.progress_label.text() == "Action verification cancelled"
    assert "STATE verification-cancelled" in window.log.toPlainText()
    window.close()
    application.processEvents()
def test_log_spec_renders_process_argv() -> None:
    from qpy_rsync.backend.rsync_command import ProcessSpec

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.log.clear()
    window._log_spec(ProcessSpec("rsync", ("--dry-run", "/src/"), {}))
    assert "$ rsync --dry-run /src/" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_legacy_recent_profile_file_is_migrated_and_removed(
    tmp_path, monkeypatch
) -> None:
    from qpy_rsync.core.endpoints import parse_endpoint
    from qpy_rsync.core.models import SyncProfile
    from qpy_rsync.storage.profile_store import save_profile

    application = app()
    app_settings().clear()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy = tmp_path / ".local/share/qpy-rsync/recent-profile.json"
    save_profile(
        legacy,
        SyncProfile(
            name="legacy",
            source=parse_endpoint(str(tmp_path / "src")),
            destination=parse_endpoint(str(tmp_path / "dst")),
        ),
    )
    assert legacy.is_file()

    window = MainWindow()
    settings = app_settings()
    assert settings.contains("profile/recent")
    assert not settings.contains("profile/recent_path")
    assert not legacy.exists()
    assert window.source_edit.text() == str(tmp_path / "src") + "/"
    window.close()
    application.processEvents()


def test_closing_the_window_stops_running_operations() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    stopped: list[str] = []

    class FakeService:
        def shutdown(self) -> None:
            stopped.append("shutdown")

    window._service = FakeService()
    window._sync_service = FakeService()
    window._plan_validation = FakeService()
    window.close()
    application.processEvents()
    assert stopped == ["shutdown", "shutdown", "shutdown"]
    assert window._closing is True


def test_state_field_replaces_the_status_row() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    # The state messages live next to the Journal label, separated from it.
    assert window.state_label.text() == "State"
    assert window.log_header.parentWidget() is window.status_edit.parentWidget()
    assert window.status_edit.isReadOnly()
    assert window.header_separator.parentWidget() is window.status_edit.parentWidget()
    window._set_status("Comparison failed.", "error")
    assert "Comparison failed." in window.status_edit.text()
    assert "Comparison failed." in window.status_edit.toolTip()
    window.close()
    application.processEvents()


def test_command_preview_minimum_height_follows_the_command() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    preview = window.command_preview_label
    preview.setText("rsync -a /src/ /dst/")
    application.processEvents()
    single_line = preview.minimumHeight()
    assert single_line < preview.fontMetrics().lineSpacing() * 2

    preview.setText("rsync " + "--very-long-option " * 12 + "/src/ /dst/")
    application.processEvents()
    assert preview.minimumHeight() > single_line
    window.close()
    application.processEvents()


def test_rows_use_separators_between_the_control_groups() -> None:
    from PySide6.QtWidgets import QFrame

    application = app()
    app_settings().clear()
    window = MainWindow()
    separators = [
        frame
        for frame in window.findChildren(QFrame)
        if frame.frameShape() == QFrame.Shape.VLine
    ]
    # Swap | Compare, Load Profile | Filter/Find, Source Browse | filters,
    # filters | unchanged, unchanged | Destination, Protect nested | Log and
    # the Journal | State divider.
    assert len(separators) == 7
    window.close()
    application.processEvents()


def test_inventory_toggle_runs_the_inventory_after_a_comparison() -> None:
    from qpy_rsync.backend.inventory import InventoryResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    gathered: list[list[object]] = []

    class FakeInventory:
        def gather(self, profile, changes):
            gathered.append(list(changes))
            return 100 + len(gathered)

        def cancel(self):
            pass

    window._inventory_service = FakeInventory()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    changed = Change(
        "file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"
    )
    window._last_changed_changes = [changed]

    assert (
        window.inventory_after_compare_button.accessibleName()
        == "Inventory after comparison"
    )
    assert "inventory" in window.inventory_after_compare_button.toolTip().lower()

    # Without the toggle the comparison does not gather the unchanged objects.
    window._apply_inventory_after_compare()
    assert gathered == []

    window.inventory_after_compare_button.setChecked(True)
    window._apply_inventory_after_compare()
    assert len(gathered) == 1
    # The unchanged objects stay hidden until the user asks for them.
    assert not window.show_unchanged.isChecked()

    # The unchanged button reuses the result of the comparison.
    window._inventory_finished(101, InventoryResult([], {}))
    application.processEvents()
    window.show_unchanged.setChecked(False)
    window.show_unchanged.setChecked(True)
    assert len(gathered) == 1
    window.close()
    application.processEvents()


def test_help_menu_and_synchronize_tooltip() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    help_menu = None
    for menu_action in window.menuBar().actions():
        menu = menu_action.menu()
        if menu is not None and menu.title() == "&Help":
            help_menu = menu
            break
    assert help_menu is not None
    entries = {action.text(): action.shortcut().toString() for action in help_menu.actions()}
    assert entries["How-To"] == "F1"
    assert entries["About qpy-rsync"] == ""
    tooltip = window.synchronize_button.toolTip()
    assert "confirmation dialog" in tooltip
    assert "Verify Actions" in tooltip
    assert "Shortcut: F9" in tooltip
    window.close()
    application.processEvents()


def test_turning_inventory_on_runs_it_for_the_current_comparison() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    change = Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")
    window._last_changed_changes = [change]
    window.comparison.set_changes([change])
    window.comparison.set_stale(False)

    gathered: list[tuple[object, list[object]]] = []

    class FakeInventory:
        def gather(self, profile, changed):
            gathered.append((profile, list(changed)))
            return 1

        def cancel(self):
            pass

    window._inventory_service = FakeInventory()
    window.inventory_after_compare_button.setChecked(True)
    assert gathered
    assert gathered[0][1][0].path == "file.txt"
    window.close()
    application.processEvents()


def test_restored_expansion_limit_defaults_to_256() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    assert window._expand_limit == 256
    assert window.comparison._expand_limit == 256
    window.close()
    application.processEvents()


def test_loading_a_profile_restores_the_ssh_authority() -> None:
    from qpy_rsync.core.enums import EndpointKind
    from qpy_rsync.core.models import Endpoint, SyncProfile

    application = app()
    app_settings().clear()
    window = MainWindow()
    profile = SyncProfile(
        "ssh",
        Endpoint(EndpointKind.SSH, "/srv/data/", host="example.org", user="alice"),
        Endpoint(EndpointKind.LOCAL, "/backup/"),
    )
    window._apply_profile(profile)
    assert window.source_edit.text() == "alice@example.org:/srv/data/"
    assert window.destination_edit.text() == "/backup/"
    window.close()
    application.processEvents()


def test_window_can_shrink_to_1280() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    assert window.minimumSizeHint().width() <= 1280
    window.resize(1280, 800)
    application.processEvents()
    assert window.width() == 1280
    window.close()
    application.processEvents()


def test_loaded_profile_keeps_its_backup_settings() -> None:
    from qpy_rsync.core.enums import EndpointKind
    from qpy_rsync.core.models import BackupOptions, Endpoint, SyncProfile

    application = app()
    app_settings().clear()
    window = MainWindow()
    profile = SyncProfile(
        "backup",
        Endpoint(EndpointKind.LOCAL, "/src/"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
        backup=BackupOptions(directory="/recovery", protect_nested=True),
    )
    window._apply_profile(profile)
    assert window._backup.directory == "/recovery"
    assert window._profile().backup.directory == "/recovery"
    window.close()
    application.processEvents()


def test_typed_backup_path_is_used_without_leaving_the_field() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window.backup_edit.setText("/typed-backup")
    assert window._profile().backup.directory == "/typed-backup"
    window.close()
    application.processEvents()


def test_filters_button_shows_an_active_and_stale_indicator() -> None:
    from qpy_rsync.core.models import FilterRule

    application = app()
    app_settings().clear()
    window = MainWindow()
    window._filters = []
    window._update_filter_summary()
    inactive = window.filters_button.icon().cacheKey()

    window._filters = [FilterRule("*.tmp", enabled=True)]
    window._update_filter_summary()
    active = window.filters_button.icon().cacheKey()
    assert active != inactive
    assert "Filters [1/1]" in window.filters_button.toolTip()

    window._update_filter_summary(stale=True)
    stale = window.filters_button.icon().cacheKey()
    assert stale != active
    window.close()
    application.processEvents()


def test_external_open_buttons_use_desktop_services(tmp_path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices

    application = app()
    app_settings().clear()
    opened = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    backup = tmp_path / "backup"
    for directory in (source, destination, backup):
        directory.mkdir()
    log_file = tmp_path / "session.log"
    log_file.write_text("log\n", encoding="utf-8")

    window = MainWindow()
    window.source_edit.setText(str(source) + "/")
    window.destination_edit.setText(str(destination) + "/")
    window.backup_edit.setText(str(backup))
    window.log_file_edit.setText(str(log_file))
    application.processEvents()

    for button in (
        window.source_open_button,
        window.destination_open_button,
        window.backup_open,
        window.log_file_open,
    ):
        assert not button.icon().isNull()
        assert button.width() == CONTROL_SIZE

    window._open_location_directory("Source")
    window._open_location_directory("Destination")
    window._open_backup_directory()
    window._open_log_file()
    assert opened == [
        str(source),
        str(destination),
        str(backup),
        str(log_file),
    ]
    window.close()
    application.processEvents()


def test_open_buttons_follow_remote_and_missing_log_file(tmp_path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices

    application = app()
    app_settings().clear()
    opened = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    window = MainWindow()
    window.source_edit.setText("alice@example.org:/srv/data/")
    window.destination_edit.setText(str(tmp_path / "destination") + "/")
    application.processEvents()
    assert not window.source_open_button.isEnabled()
    window._open_location_directory("Source")
    assert not opened
    assert "remote" in window.status_edit.text().lower()

    log_file = tmp_path / "new-session.log"
    window.log_file_edit.setText(str(log_file))
    window._open_log_file()
    assert log_file.exists()
    assert opened == [str(log_file)]
    window.close()
    application.processEvents()

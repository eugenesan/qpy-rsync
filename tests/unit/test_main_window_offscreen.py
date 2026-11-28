import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QLabel

from qpy_rsync.gui.controls import CONTROL_SIZE
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
    assert window.validate_plan_button.accessibleName() == "Verify Decisions"
    assert window.swap_button.accessibleName() == "Swap Source and Destination"
    assert window.swap_button.toolTip() == "Swap Source and Destination"
    assert window.comparison.search_edit.minimumWidth() == 180
    assert window.comparison.search_edit.maximumWidth() > 1000
    assert window.comparison.controls.sizePolicy().horizontalPolicy().name == "Expanding"
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
    for button in (window.comparison.inventory_button,):
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
    assert window.status_edit.text() == "Enter locations to compare"
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
    # A stale comparison stays browsable; only decisions and the sync gate
    # are disabled.
    assert window.comparison.source.isEnabled()
    assert window.comparison.action.isEnabled()
    assert window.comparison.destination.isEnabled()
    assert "#EA580C" in window.source_edit.styleSheet()
    assert window._current_plan is None
    assert not window.validate_plan_button.isEnabled()
    assert "old direction" in window.log.toPlainText()
    window.close()
    application.processEvents()

def test_browse_start_uses_existing_parent(tmp_path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    requested = existing / "missing" / "child"
    assert MainWindow._browse_start_directory(str(requested)) == str(existing)
    assert MainWindow._browse_start_directory("nas:/remote/path") == str(Path.home())


def test_search_and_ui_labels() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.comparison.search_edit.setText("*.jpg")
    window.comparison.find_button.click()
    application.processEvents()
    assert window.comparison.search_edit.text() == "*.jpg"
    assert window.comparison.model.HEADERS[0] == "Item"
    assert window.comparison.model.HEADERS[1] == "Items"
    assert window.comparison.model.HEADERS[5] == "Item"
    assert window.comparison.model.HEADERS[6] == "Items"
    # The Journal and Overview headings are gone; the panes explain
    # themselves.
    assert not window.findChildren(QLabel, "overview-title")
    assert window.source_browse_button.toolTip() == "Browse to Source location"
    assert window.destination_browse_button.toolTip() == "Browse to Destination location"
    assert window.settings_button.toolTip() == "Settings"
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
    directory = window.comparison.model.index(0, window.comparison.model.ACTION)
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
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    window = MainWindow()
    window._restore_logging_settings()
    app_log = tmp_path / "cache" / "qpy-rsync" / "app-default.log"
    rsync_log = tmp_path / "cache" / "qpy-rsync" / "rsync-default.log"
    assert window.log_file_edit.text() == str(app_log)
    window._append_log("app progress first")
    window._append_log("rsync output line", rsync=True)
    assert "app progress first" in window.log.toPlainText()
    assert "app progress first" in app_log.read_text(encoding="utf-8")
    rsync_content = rsync_log.read_text(encoding="utf-8")
    assert "rsync output line" in rsync_content
    assert "app progress first" not in rsync_content
    window.close(); application.processEvents()

def test_sync_terminal_events_are_written_to_diagnostics(tmp_path, monkeypatch) -> None:
    from qpy_rsync.core.execution_gate import ExecutionGateState
    from qpy_rsync.services.sync_service import SyncResult

    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
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

    content = (tmp_path / "cache" / "qpy-rsync" / "app-default.log").read_text(encoding="utf-8")
    assert "STATE synchronization-completed exit_code=0" in content
    assert "STATE synchronization-cancelled" in content
    assert "STATE synchronization-failed" in content
    window.close()
    application.processEvents()


def test_unchanged_inventory_is_async_and_cached(tmp_path) -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    source = tmp_path / "src"
    destination = tmp_path / "dst"
    source.mkdir()
    destination.mkdir()
    window.source_edit.setText(str(source) + "/")
    window.destination_edit.setText(str(destination) + "/")
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
    assert window.comparison.model.rowCount() == 2

    extra = Change("same.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, "=")
    window._inventory_finished(7, [extra])
    assert window.comparison.model.rowCount() == 3
    # The unchanged object appears without another comparison.
    assert window.comparison.model.rowCount() == 3
    assert "unchanged=1" in window.log.toPlainText()

    window.show_unchanged.setChecked(False)
    window.show_unchanged.setChecked(True)
    assert len(gathered) == 1
    assert window.comparison.model.rowCount() == 3
    window.close()
    application.processEvents()


def test_journal_preview_is_temporary_and_selectable() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._update_command_preview()
    # Nothing is shown until the pointer hovers a preview button.
    assert not window._preview_blocks()
    window._set_hovered_action("compare")
    application.processEvents()
    blocks = window._preview_blocks()
    assert len(blocks) == 1
    text = blocks[0].text()
    assert text.startswith("compare rsync preview: $ rsync ")
    assert not text[:2].isdigit()
    assert window.log.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    iterator = blocks[0].begin()
    assert not iterator.atEnd()
    char_format = iterator.fragment().charFormat()
    assert char_format.fontItalic()
    from PySide6.QtGui import QPalette

    assert char_format.foreground().color().name() != (
        window.log.palette().color(QPalette.ColorRole.Text).name()
    )
    window._flush_log()
    assert "compare rsync preview:" not in window._log_file_path.read_text(
        encoding="utf-8"
    )
    # A real journal entry replaces the preview.
    window._append_log("a real entry")
    assert not window._preview_blocks()
    window.close()
    application.processEvents()


def test_journal_preview_replaces_itself_and_follows_hover() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._update_command_preview()
    window._set_hovered_action("compare")
    application.processEvents()
    first_count = window.log.document().blockCount()
    window._set_hovered_action("verify")
    application.processEvents()
    assert len(window._preview_blocks()) == 1
    assert window._preview_blocks()[0].text().startswith(
        "verify rsync preview: $ rsync "
    )
    window._set_hovered_action("compare")
    window._set_hovered_action("compare")
    application.processEvents()
    assert len(window._preview_blocks()) == 1
    assert window.log.document().blockCount() == first_count
    window.close()
    application.processEvents()


def test_journal_preview_is_hidden_while_an_operation_runs() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._update_command_preview()
    window._set_hovered_action("compare")
    assert len(window._preview_blocks()) == 1
    window._set_operation_controls(True)
    assert not window._preview_blocks()
    window._set_hovered_action("verify")
    assert not window._preview_blocks()
    window._set_operation_controls(False)
    window._set_hovered_action("compare")
    assert len(window._preview_blocks()) == 1
    window.close()
    application.processEvents()


def test_progress_bar_is_a_fixed_status_widget() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    assert window.statusBar().isAncestorOf(window.progress_bar)
    assert window.progress_bar in window.statusBar().findChildren(
        type(window.progress_bar)
    )
    assert not hasattr(window, "command_preview_label")
    assert not hasattr(window, "preview_log_splitter")
    window.show()
    window.resize(1000, 700)
    application.processEvents()
    assert window.progress_bar.width() == max(80, window.width() * 15 // 100)
    # Streaming progress goes only to the status label.
    before = window.log.toPlainText()
    window._sync_progress(type("Progress", (), {
        "percent": 42, "files_completed": 3, "files_remaining": 4,
    })())
    assert "42%" in window.status_edit.text()
    assert window.log.toPlainText() == before
    window.close()
    application.processEvents()


def test_recent_profile_is_stored_in_app_settings(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    window = MainWindow()
    window.source_edit.setText(str(tmp_path / "src"))
    window.destination_edit.setText(str(tmp_path / "dst"))
    from qpy_rsync.core.enums import EndpointKind
    from qpy_rsync.core.models import Endpoint, SyncProfile
    from qpy_rsync.storage.profile_store import save_profile

    profile_path = tmp_path / "profile.json"
    save_profile(
        profile_path,
        SyncProfile(
            "recent",
            Endpoint(EndpointKind.LOCAL, str(tmp_path / "src") + "/"),
            Endpoint(EndpointKind.LOCAL, str(tmp_path / "dst") + "/"),
        ),
    )
    window._remember_profile_path(profile_path)

    settings = app_settings()
    assert settings.value("profile/current_path") == str(profile_path)
    assert not settings.contains("profile/recent")
    assert not settings.contains("profile/recent_paths")
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
    assert window.validate_plan_button.accessibleName() == "Decisions Verified"
    assert window._validated_plan is window._current_plan
    assert "STATE verification-reused-comparison" in window.log.toPlainText()
    log = window.log.toPlainText()
    assert "Selected: 1 item, 0 B; new 0, updated 1" in log
    assert (
        "Decisions verified, selected: new 0, updated 1, metadata 0, "
        "deleted 0; 1 item, 0 B"
    ) in log
    assert window.status_edit.text() == "Selected decisions verified."
    assert window.status_edit.text() == "Selected decisions verified."
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
    assert window.validate_plan_button.accessibleName() == "Verify Decisions"
    assert window.status_edit.text() == "Verification was cancelled."
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
    assert settings.contains("profile/current_path")
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


def test_state_field_lives_in_the_status_bar() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    assert window.state_label.text() == "State:"
    assert window.statusBar().isAncestorOf(window.status_edit)
    assert window.status_edit.isReadOnly()
    window._set_state("Comparison failed.", "error")
    assert "Comparison failed." in window.status_edit.text()
    assert "Comparison failed." in window.status_edit.toolTip()
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
    # Swap | Compare, Load Profile | Filter/Find, Pause | Filter, and the
    # separators around the Source and Destination panels.
    assert len(separators) >= 4
    window.close()
    application.processEvents()


def test_inventory_toggle_runs_the_inventory_after_a_comparison(tmp_path) -> None:
    from qpy_rsync.backend.inventory import InventoryResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    source = tmp_path / "src"
    destination = tmp_path / "dst"
    source.mkdir()
    destination.mkdir()
    gathered: list[list[object]] = []

    class FakeInventory:
        def gather(self, profile, changes):
            gathered.append(list(changes))
            return 100 + len(gathered)

        def cancel(self):
            pass

    window._inventory_service = FakeInventory()
    window.source_edit.setText(str(source) + "/")
    window.destination_edit.setText(str(destination) + "/")
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
    assert "optional diagnostic" in tooltip
    assert "Shortcut: F9" in tooltip
    window.close()
    application.processEvents()


def test_turning_inventory_on_runs_it_for_the_current_comparison(tmp_path) -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    source = tmp_path / "src"
    destination = tmp_path / "dst"
    source.mkdir()
    destination.mkdir()
    window.source_edit.setText(str(source) + "/")
    window.destination_edit.setText(str(destination) + "/")
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

    rebuilds: list[object] = []
    original = window.comparison.set_changes
    window.comparison.set_changes = lambda *args, **kwargs: rebuilds.append(args)  # type: ignore[method-assign]
    window.inventory_after_compare_button.setChecked(False)
    window.comparison.set_changes = original  # type: ignore[method-assign]
    # Disabling the button is only a profile setting; the view already shows
    # exactly these changes and must not be rebuilt.
    assert rebuilds == []
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
    window._set_status("A long status message: " + "x" * 500)
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
    assert "remote" in window.log.toPlainText().lower()

    warnings: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QMessageBox.warning",
        lambda *_args, **_kwargs: warnings.append(_args),
    )
    log_file = tmp_path / "new-session.log"
    window.log_file_edit.setText(str(log_file))
    window._open_log_file()
    assert warnings
    assert not log_file.exists()
    assert opened == []
    assert "does not exist" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_compare_refuses_missing_local_directories(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    warnings: list[object] = []
    compared: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QMessageBox.warning",
        lambda *_args, **_kwargs: warnings.append(_args),
    )
    monkeypatch.setattr(
        window._service, "compare", lambda profile: compared.append(profile)
    )
    window.source_edit.setText(str(tmp_path / "missing-source") + "/")
    window.destination_edit.setText(str(tmp_path / "missing-destination") + "/")
    window._compare()
    assert warnings
    assert not compared
    assert "does not exist" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_inventory_refuses_missing_local_directories(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    gathered: list[object] = []

    class FakeInventory:
        def gather(self, profile, changes):
            gathered.append((profile, changes))
            return 1

        def cancel(self):
            pass

    window._inventory_service = FakeInventory()
    warnings: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QMessageBox.warning",
        lambda *_args, **_kwargs: warnings.append(_args),
    )
    window.source_edit.setText(str(tmp_path / "missing-source") + "/")
    window.destination_edit.setText(str(tmp_path / "missing-destination") + "/")
    window._active_profile = window._profile()
    window._start_inventory("key", [])
    assert warnings
    assert not gathered
    window.close()
    application.processEvents()


def test_open_missing_directory_shows_a_warning(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    warnings: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QMessageBox.warning",
        lambda *_args, **_kwargs: warnings.append(_args),
    )
    window.source_edit.setText(str(tmp_path / "missing-source") + "/")
    window._open_location_directory("Source")
    assert warnings
    assert "does not exist" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_state_field_only_shows_operation_states() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window._set_state("Ready for compare")
    assert window.status_edit.text() == "Ready for compare"

    window._set_status("Everything is fine.", "success")
    window._set_status("Just information.", "info")
    window._set_status("Source is missing.", "warning")
    window._set_status("Open failed.", "error")
    # Messages do not overwrite the state; they remain in the journal.
    assert window.status_edit.text() == "Ready for compare"
    log = window.log.toPlainText()
    assert "Everything is fine." in log
    assert "Source is missing." in log
    assert "Open failed." in log
    assert "STATUS " not in log
    window.close()
    application.processEvents()


def test_failed_external_open_shows_an_error(tmp_path, monkeypatch) -> None:
    from PySide6.QtCore import QProcess
    from PySide6.QtGui import QDesktopServices

    application = app()
    app_settings().clear()
    directory = tmp_path / "source"
    directory.mkdir()
    errors: list[object] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda _url: False)
    monkeypatch.setattr(QProcess, "startDetached", lambda *_args: (False, 0))
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QMessageBox.critical",
        lambda *_args, **_kwargs: errors.append(_args),
    )
    window = MainWindow()
    window.source_edit.setText(str(directory) + "/")
    window._open_location_directory("Source")
    assert errors
    assert "Could not open" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_startup_warns_about_missing_remembered_locations(tmp_path) -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText(str(tmp_path / "missing-source") + "/")
    window.destination_edit.setText(str(tmp_path / "missing-destination") + "/")
    window._update_startup_status()
    assert window.status_edit.text() == "Enter locations to compare"
    assert "does not exist" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_journal_lines_get_timestamps_and_severity_colors() -> None:
    import re

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.log.clear()
    window._append_log("app message")
    window._append_log("warning message", severity="warning")
    window._append_log("error message", severity="error")
    window._append_log("rsync line", rsync=True)

    document = window.log.document()
    lines = [document.findBlockByNumber(row).text() for row in range(document.blockCount())]
    assert all(re.match(r"^\d{2}:\d{2}:\d{2}\.\d{2} ", line) for line in lines)
    assert lines[0].endswith("app message")
    assert lines[1].endswith("warning message")

    def colors(row: int) -> list[str]:
        block = document.findBlockByNumber(row)
        result = []
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                result.append(fragment.charFormat().foreground().color().name())
            iterator += 1
        return result

    assert colors(1)[-1] == "#0891b2"
    assert colors(2)[-1] == "#b91c1c"
    from PySide6.QtGui import QPalette

    assert colors(3)[-1] == "#6b7280"
    assert colors(0)[-1] == window.log.palette().color(
        QPalette.ColorRole.Text
    ).name()
    window.close()
    application.processEvents()


def test_backup_warning_is_logged_once_without_status_prefix(tmp_path) -> None:
    application = app()
    app_settings().clear()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    window = MainWindow()
    window.source_edit.setText(str(source) + "/")
    window.destination_edit.setText(str(destination) + "/")
    window.backup_edit.setText(str(destination / "backup"))
    window._set_state("Ready for compare")
    window.log.clear()

    window._update_backup_status()
    window._update_backup_status()

    log = window.log.toPlainText()
    assert log.count("Backup directory is inside the destination tree.") == 1
    assert "STATUS " not in log
    assert "Warning: Backup directory is inside" not in log
    assert window.status_edit.text() == "Ready for compare"
    window.close()
    application.processEvents()


def test_startup_state_is_ready_for_compare_when_locations_exist(tmp_path) -> None:
    application = app()
    app_settings().clear()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    window = MainWindow()
    window.source_edit.setText(str(source) + "/")
    window.destination_edit.setText(str(destination) + "/")
    window._update_startup_status()
    assert window.status_edit.text() == "Ready for compare"
    window.close()
    application.processEvents()


def test_diff_preparation_shows_progress_before_staging(monkeypatch) -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.diff_tool_service import DiffToolError

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    seen: list[tuple[str, str, bool]] = []

    def fake_build(*_args, **_kwargs):
        seen.append(
            (
                window.status_edit.text(),
                window.status_edit.text(),
                not window.progress_bar.isHidden(),
            )
        )
        raise DiffToolError("staging stopped for the test")

    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.build_diff_request", fake_build
    )
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QMessageBox.information",
        lambda *_args, **_kwargs: None,
    )
    change = Change(
        "file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"
    )
    window._open_diff_tool(change)
    assert seen
    assert seen[0][0] == "Preparing the diff tool..."
    assert seen[0][1] == "Preparing the diff tool..."
    assert seen[0][2] is True
    assert "Preparing diff for file.txt..." in window.log.toPlainText()
    assert window.status_edit.text() == "Diff tool unavailable"
    window.close()
    application.processEvents()


def _inventory_changes(count: int, action):
    from qpy_rsync.core.changes import Change, ObjectKind

    return [
        Change(
            f"dir{i % 20}/file{i}.txt",
            action,
            ObjectKind.FILE,
            "=" if action.value == "no_change" else ">f",
            size=i,
        )
        for i in range(count)
    ]


def test_the_flat_list_adds_a_large_inventory_without_a_warning() -> None:
    from qpy_rsync.core.changes import ChangeAction

    application = app()
    app_settings().clear()
    window = MainWindow()

    changed = _inventory_changes(4, ChangeAction.UPDATE_CONTENT)
    unchanged = _inventory_changes(40, ChangeAction.NO_CHANGE)
    window._last_changed_changes = list(changed)

    # There is no dialog left to show: the list simply grows.
    assert not hasattr(window, "_confirm_large_inventory")
    window._populate_unchanged(changed + unchanged, len(unchanged))
    application.processEvents()
    assert window.comparison.model.rowCount() == 65
    window.close()
    application.processEvents()

def test_the_settings_dialog_opens_on_the_requested_section() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    from qpy_rsync.gui.settings_dialog import SettingsDialog, SECTIONS

    dialog = SettingsDialog(
        window,
        holder=window._config_holder,
        log_panel=window._log_panel,
        backup_panel=window._backup_panel,
        sound_enabled=True,
        section="logging",
    )
    assert dialog.tabs.currentIndex() == SECTIONS.index("logging")
    dialog.show_section("logging")
    assert dialog.tabs.currentIndex() == SECTIONS.index("logging")
    dialog.close()
    application.processEvents()
    window.close()
    application.processEvents()


def test_the_log_and_backup_settings_live_in_the_dialog() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    # The configuration rows are no longer laid out in the window itself.
    assert window.backup_edit.isVisible() is False
    assert window.log_file_edit.isVisible() is False
    # The open buttons and the settings button are in the toolbar.
    assert window.backup_open.isVisible() is False  # the window is not shown
    assert window.settings_button.toolTip() == "Settings"
    window.close()
    application.processEvents()


def test_a_finished_comparison_can_play_a_sound(monkeypatch) -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    played: list[str] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.play_completion_sound", played.append
    )
    window._sound_enabled = True
    window._play_completion_sound("success")
    assert played == ["success"]
    window._sound_enabled = False
    window._play_completion_sound("error")
    assert played == ["success"]
    window.close()
    application.processEvents()


def test_showing_excluded_items_is_reported() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.comparison.set_changes(
        [
            Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    window.comparison.exclude_path("a.txt")
    window._apply_show_excluded(True)
    application.processEvents()
    assert "excluded item(s)" in window.status_edit.text()
    assert "Showing 1 excluded item(s)" in window.log.toPlainText()

    window._apply_show_excluded(False)
    application.processEvents()
    assert "hidden again" in window.status_edit.text()
    window.close()
    application.processEvents()


def test_the_backup_button_keeps_its_menu_when_unconfigured() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.backup_edit.setText("")
    window._update_external_open_states()
    # The button stays usable so the settings remain one right-click away.
    assert window.backup_open.isEnabled() is True
    window.close()
    application.processEvents()


def test_reset_exclusions_puts_every_excluded_item_back() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.comparison.set_changes(
        [
            Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
            Change("b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    window.comparison.exclude_path("a.txt")
    window.comparison.exclude_path("b.txt")

    window.comparison.reset_exclusions_requested.emit()
    application.processEvents()

    assert window.comparison.excluded_paths() == set()
    assert "All 2 exclusion(s) are reset" in window.status_edit.text()
    assert "Reset 2 exclusion(s)" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_showing_unchanged_leaves_the_inventory_button_alone() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    assert window.inventory_after_compare_button.isChecked() is False

    window.show_unchanged.setChecked(True)
    application.processEvents()

    # The inventory is run for this comparison, but the persistent setting
    # is never switched on behind the user's back.
    assert window.inventory_after_compare_button.isChecked() is False
    window.close()
    application.processEvents()


def test_the_log_file_can_be_cleared(tmp_path) -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window._log_file_path.write_text("the old app session\n", encoding="utf-8")
    window._rsync_log_path.write_text("the old rsync session\n", encoding="utf-8")

    window._clear_log()
    application.processEvents()

    app_contents = window._log_file_path.read_text(encoding="utf-8")
    rsync_contents = window._rsync_log_path.read_text(encoding="utf-8")
    assert "the old app session" not in app_contents
    assert "the old rsync session" not in rsync_contents
    assert "cleared" in app_contents
    window.close()
    application.processEvents()


def test_comparison_clears_the_stale_filter_indicator() -> None:
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.core.models import FilterRule
    from qpy_rsync.services.compare_service import CompareResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    window._filters = [FilterRule("*.tmp", enabled=True)]
    window._update_filter_summary(stale=True)
    stale = window.filters_button.icon().cacheKey()
    assert "STALE" in window.filters_button.toolTip()

    window._comparison_finished(
        CompareResult(
            ParseResult(
                [Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f")],
                [],
            ),
            "",
            0,
        )
    )
    assert window.filters_button.icon().cacheKey() != stale
    assert "STALE" not in window.filters_button.toolTip()
    window.close()
    application.processEvents()


def test_compare_layout_modes() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.resize(1200, 800)
    application.processEvents()

    window._set_layout_mode("focus")
    application.processEvents()
    assert window.main_splitter.count() == 1
    assert window.log_panel.parent() is not window.main_splitter
    assert window.overview.parent() is not window.log_splitter

    window._set_layout_mode("wide")
    application.processEvents()
    assert window.main_splitter.count() == 2
    assert window.log_panel.parent() is not window.main_splitter
    assert window.overview.parent() is window.main_splitter
    assert window.main_splitter.orientation() == Qt.Orientation.Horizontal

    window._set_layout_mode("normal")
    application.processEvents()
    assert window.main_splitter.count() == 2
    assert window.log_panel.parent() is window.main_splitter
    assert window.overview.parent() is window.log_splitter
    assert window.main_splitter.orientation() == Qt.Orientation.Vertical
    window.close()
    application.processEvents()


def test_view_menu_lists_layout_modes_and_shortcuts() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    view_menu = None
    for menu_action in window.menuBar().actions():
        menu = menu_action.menu()
        if menu is not None and menu.title() == "&View":
            view_menu = menu
            break
    assert view_menu is not None
    entries = {
        action.text(): action.shortcut().toString()
        for action in view_menu.actions()
        if not action.isSeparator()
    }
    # The search repeats from anywhere in the window; F3 belongs to profiles.
    edit_menu = None
    for menu_action in window.menuBar().actions():
        menu = menu_action.menu()
        if menu is not None and menu.title() == "&Edit":
            edit_menu = menu
            break
    assert edit_menu is not None
    find_actions = {
        action.text(): action.shortcut().toString()
        for action in edit_menu.actions()
        if action.text() in {"Find in List", "Find Next", "Find Previous"}
    }
    assert find_actions == {
        "Find in List": "Ctrl+F",
        "Find Next": "Ctrl+G",
        "Find Previous": "Ctrl+Shift+G",
    }
    undo_actions = {
        action.text(): action.shortcut().toString()
        for action in edit_menu.actions()
        if action.text() in {"Undo Decision", "Redo Decision", "Reset Decisions"}
    }
    assert undo_actions == {
        "Undo Decision": "Ctrl+Z",
        "Redo Decision": "Ctrl+Shift+Z",
        "Reset Decisions": "",
    }
    assert not window.undo_decision_action.isEnabled()
    assert not window.redo_decision_action.isEnabled()
    assert entries == {
        "Normal": "",
        "Compare only": "",
        "Compare with overview": "",
        "Next layout": "Ctrl+Tab",
        "Previous layout": "Ctrl+Shift+Tab",
    }
    assert "Ctrl+Tab" in window.layout_button.toolTip()
    index = window.comparison.controls.layout().indexOf(window.layout_button)
    menu_index = window.comparison.controls.layout().indexOf(
        window.comparison.menu_button
    )
    assert index == menu_index - 1
    assert window.comparison.controls.layout().indexOf(
        window.settings_button
    ) == menu_index - 2
    window.close()
    application.processEvents()


def test_profile_menu_offers_profiles_directory() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.profile_menu.aboutToShow.emit()
    labels = [action.text() for action in window.profile_menu.actions()]
    assert "Open profiles directory" in labels
    window.close()
    application.processEvents()


def test_deleted_size_updates_after_metadata_arrives() -> None:
    from qpy_rsync.backend.inventory import InventoryEntry, InventoryResult
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.compare_service import CompareResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    change = Change("old.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting")
    window._comparison_finished(
        CompareResult(ParseResult([change], []), "", 0)
    )
    assert window.overview.statistics.deleted_size_label.text() == "(0 B)"

    window._metadata_token = 7
    result = InventoryResult(
        [], {"old.txt": (12345, "2026/11/16-10:00:00")}
    )
    window._metadata_finished(7, result)
    assert window.overview.statistics.deleted_size_label.text() == "(12.1 KiB)"
    window.close()
    application.processEvents()


def test_exclusion_updates_plan_incrementally() -> None:
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
        Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=10),
        Change("b.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=20),
    ]
    window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
    before = window._current_plan.summary.included
    assert before == 2

    window.comparison.model.exclusion.add("a.txt")
    window._overview_updated([])
    assert window._current_plan.summary.included == 1
    assert [i.path for i in window._current_plan.included_items] == ["b.txt"]
    window.close()
    application.processEvents()


def test_decision_changes_mark_the_plan_stale_without_rebuild() -> None:
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ObjectKind
    from qpy_rsync.services.compare_service import CompareResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    change = Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=10)
    window._comparison_finished(CompareResult(ParseResult([change], []), "", 0))
    assert not window._plan_stale

    calls: list[int] = []
    original = window._refresh_plan_summary
    window._refresh_plan_summary = lambda: calls.append(1) or original()  # type: ignore[method-assign]
    window.comparison.model.decisions.set("a.txt", ChangeDecision.EXCLUDE)
    window._invalidate_validated_plan()
    assert window._plan_stale
    assert calls == []
    assert not window._stale_summary_timer.isActive()
    assert not window._current_plan.items[0].included
    window.close()
    application.processEvents()


def test_stale_comparison_marks_compare_button_and_status() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._set_state("Ready for compare")
    assert window.status_edit.text() == "Ready for compare"
    clean_compare = window.compare_button.icon().cacheKey()
    clean_verify = window.validate_plan_button.icon().cacheKey()
    window.comparison.set_stale(True)
    application.processEvents()
    # The badges are the same icon markers the filter and profile buttons use.
    assert window.compare_button.icon().cacheKey() != clean_compare
    assert window.validate_plan_button.icon().cacheKey() != clean_verify
    assert "STALE" in window.compare_button.toolTip()
    assert window.status_edit.text() == "Stale comparison — click Compare to refresh"
    assert "#EA580C" in window.status_edit.styleSheet()
    assert "#EA580C" in window.state_label.styleSheet()
    assert window.compare_button.styleSheet() == ""
    assert window.validate_plan_button.styleSheet() == ""
    window.comparison.set_stale(False)
    application.processEvents()
    assert "STALE" not in window.compare_button.toolTip()
    assert window.status_edit.text() != "Stale comparison — click Compare to refresh"
    window.close()
    application.processEvents()


def test_compare_and_verify_badges_use_the_same_three_states() -> None:
    from qpy_rsync.gui.icons import ICON_SIZE, compare_icon, filters_icon, verify_icon

    app()

    def badge(icon) -> str:
        image = icon.pixmap(ICON_SIZE, ICON_SIZE).toImage()
        return image.pixelColor(50, 50).name().lower()

    for make in (compare_icon, verify_icon):
        assert badge(make()) != badge(make(info=True))
        assert badge(make(info=True)) == badge(filters_icon(active=True))
        assert badge(make(warning=True)) == badge(filters_icon(stale=True))
        assert len({
            make().cacheKey(),
            make(info=True).cacheKey(),
            make(warning=True).cacheKey(),
        }) == 3


def test_stale_plan_does_not_paint_the_whole_verify_button() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window._plan_stale = True
    window._refresh_verify_button()
    assert window.validate_plan_button.styleSheet() == ""
    window._plan_stale = False
    window._refresh_verify_button()
    assert window.validate_plan_button.styleSheet() == ""
    window.close()
    application.processEvents()


def test_verify_badge_tracks_plan_staleness() -> None:
    from qpy_rsync.gui.icons import ICON_SIZE, verify_icon

    def badge_color(icon) -> str:
        image = icon.pixmap(ICON_SIZE, ICON_SIZE).toImage()
        return image.pixelColor(50, 50).name().lower()

    application = app()
    app_settings().clear()
    window = MainWindow()
    from qpy_rsync.gui.icons import ICON_SIZE

    def badge() -> str:
        image = window.validate_plan_button.icon().pixmap(ICON_SIZE, ICON_SIZE).toImage()
        return image.pixelColor(50, 50).name().lower()

    window._set_verify_state("idle")
    clean = badge()
    window._plan_stale = True
    window._refresh_verify_button()
    assert badge() == badge_color(verify_icon(warning=True))
    assert badge() != clean
    window._plan_stale = False
    window._set_verify_state("verified")
    assert badge() == badge_color(verify_icon(info=True))
    window._set_verify_state("idle")
    assert badge() == clean
    window.close()
    application.processEvents()


def test_undo_to_the_verified_decisions_clears_plan_staleness(tmp_path) -> None:
    from qpy_rsync.services.plan_validation_service import (
        PlanMismatch,
        PlanValidationResult,
    )

    application = app()
    app_settings().clear()
    source = tmp_path / "src"
    destination = tmp_path / "dst"
    source.mkdir()
    destination.mkdir()
    window = MainWindow()
    window.source_edit.setText(str(source))
    window.destination_edit.setText(str(destination))
    window._active_profile = window._profile()
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.core.models import SyncProfile
    window._comparison_profile = SyncProfile(
        "test", window._profile().source, window._profile().destination
    )
    window.comparison.set_changes(
        [Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")]
    )
    window._rebuild_plan_summary()
    window._plan_validation_started()
    window._plan_validation_finished(
        PlanValidationResult(True, PlanMismatch((), ()), "", 0)
    )
    assert not window._plan_stale

    index = window.comparison.model.index_for_path("a.txt")
    assert window.comparison.model.setData(
        window.comparison.model.index(index.row(), window.comparison.model.ACTION),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert window._plan_stale

    assert window.comparison.undo_decision()
    assert not window._plan_stale
    assert window._validated_plan is not None
    window.close()
    application.processEvents()


def test_undo_to_the_comparison_baseline_clears_staleness_without_verification(tmp_path) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.core.models import SyncProfile

    application = app()
    app_settings().clear()
    source = tmp_path / "src"
    destination = tmp_path / "dst"
    source.mkdir()
    destination.mkdir()
    window = MainWindow()
    window.source_edit.setText(str(source))
    window.destination_edit.setText(str(destination))
    window._active_profile = window._profile()
    profile = window._profile()
    window._comparison_profile = SyncProfile("test", profile.source, profile.destination)
    window.comparison.set_changes(
        [Change(f"f{i}.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f") for i in range(4)]
    )
    application.processEvents()
    assert window._baseline_plan is not None
    assert not window._plan_stale

    for path in ("f1.txt", "f2.txt"):
        window.comparison.select_path(path)
        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier
        )
        window.comparison.eventFilter(window.comparison.source, event)
        application.processEvents()
    assert window._plan_stale

    assert window.comparison.undo_decision()
    assert window._plan_stale
    assert window.comparison.undo_decision()
    assert not window._plan_stale
    assert window.synchronize_button.isEnabled()
    assert window._verify_state == "idle"
    window.close()
    application.processEvents()


def test_verification_with_decisions_does_not_rescan_the_live_tree() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    changes = [
        Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
        Change("b.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
    ]
    window.comparison.set_changes(changes)
    application.processEvents()
    window.comparison.model.decisions.set("a.txt", ChangeDecision.EXCLUDE)
    window.comparison.model.decisions.set("b.txt", ChangeDecision.INCLUDE)
    window.comparison.model._after_decision_change({"a.txt", "b.txt"})
    application.processEvents()

    class RejectProcess:
        def validate(self, *_args, **_kwargs):
            raise AssertionError("decision changes must not start another rsync")

    window._plan_validation = RejectProcess()
    window._validate_selected_plan()
    assert window.validate_plan_button.accessibleName() == "Decisions Verified"
    assert "no second rsync run" in window.log.toPlainText()
    assert "STATE verification-reused-comparison" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_mismatch_dialog_keeps_a_scrollable_detail_and_visible_buttons(monkeypatch) -> None:
    from types import SimpleNamespace
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.plan_validation_service import (
        PlanMismatch,
        PlanValidationResult,
    )
    import qpy_rsync.gui.main_window as main_window

    captured: dict[str, object] = {}

    class FakeBox:
        Icon = SimpleNamespace(Critical=1, Warning=2)
        StandardButton = SimpleNamespace(Ok=2)

        def __init__(self, parent=None) -> None:
            pass

        def setIcon(self, value) -> None:
            pass

        def setWindowTitle(self, value) -> None:
            pass

        def setText(self, value) -> None:
            captured["text"] = value

        def setInformativeText(self, value) -> None:
            captured["info"] = value

        def setDetailedText(self, value) -> None:
            captured["detail"] = value

        def setStandardButtons(self, value) -> None:
            captured["buttons"] = value

        def exec(self) -> None:
            captured["shown"] = True

    monkeypatch.setattr(main_window, "QMessageBox", FakeBox)
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.comparison.set_changes(
        [Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")]
    )
    application.processEvents()
    window._rebuild_plan_summary()
    window._execution_gate.selection_changed(included=1)
    window._plan_validation_started()
    missing = tuple(
        (f"path/{i}", ChangeAction.CREATE, "file") for i in range(500)
    )
    window._plan_validation_finished(
        PlanValidationResult(False, PlanMismatch(missing, ()), "", 0)
    )
    assert captured.get("shown") is True
    assert "500 missing" in str(captured.get("info"))
    assert str(captured.get("detail")).count("Missing:") == 500
    assert "Synchronization is not blocked" in str(captured.get("text"))
    window.close()
    application.processEvents()


def test_verify_button_is_hidden_unless_enabled_in_settings() -> None:
    application = app()
    app_settings().clear()
    settings = app_settings()
    settings.setValue("verification/enabled", False)
    settings.sync()
    window = MainWindow()
    assert window.validate_plan_button.isHidden()
    assert window.verify_action.isVisible() is False
    window._verification_enabled = True
    window._update_verification_visibility()
    assert not window.validate_plan_button.isHidden()
    assert window.verify_action.isVisible() or window.verify_action.isVisibleTo(window)
    window.close()
    application.processEvents()


def test_second_rsync_run_is_only_used_when_both_flags_are_enabled() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    profile = window._profile()
    from qpy_rsync.core.models import SyncProfile
    window._comparison_profile = SyncProfile("test", profile.source, profile.destination)
    window.comparison.set_changes(
        [Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")]
    )
    application.processEvents()

    class RejectProcess:
        def validate(self, *_args, **_kwargs):
            raise AssertionError("rsync run must stay off by default")

    window._plan_validation = RejectProcess()
    window._validate_selected_plan()
    assert "no second rsync run" in window.log.toPlainText()

    window._verification_rsync = True
    window._verification_enabled = False
    window._validate_selected_plan()
    assert "no second rsync run" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_preserve_button_sits_by_compare_and_reports_its_state() -> None:
    from PySide6.QtWidgets import QToolButton

    application = app()
    app_settings().clear()
    window = MainWindow()
    assert isinstance(window.preserve_button, QToolButton)
    assert window.preserve_button.isCheckable()
    assert window.preserve_button.isChecked()
    assert "ON" in window.preserve_button.toolTip()
    on_icon = window.preserve_button.icon().cacheKey()
    window.preserve_button.setChecked(False)
    application.processEvents()
    assert window.preserve_button.icon().cacheKey() != on_icon
    assert "OFF" in window.preserve_button.toolTip()
    window.close()
    application.processEvents()


def test_stale_comparison_unchecks_preserve_but_allows_forcing_it(monkeypatch) -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.comparison.set_changes(
        [Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")]
    )
    application.processEvents()
    assert window.preserve_button.isChecked()
    window.comparison.set_stale(True)
    application.processEvents()
    assert window.preserve_button.isEnabled()
    assert not window.preserve_button.isChecked()
    assert "forced" in window.preserve_button.toolTip()
    window.preserve_button.setChecked(True)
    application.processEvents()
    assert window._preserve_decisions is True
    window.comparison.set_stale(False)
    application.processEvents()
    assert window.preserve_button.isChecked()
    window.close()
    application.processEvents()


def test_compare_warns_before_discarding_decisions(monkeypatch) -> None:
    import qpy_rsync.gui.main_window as main_window

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.preserve_button.setChecked(False)
    application.processEvents()
    calls: list[object] = []

    def warning(*args, **kwargs):
        calls.append(args)
        return main_window.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(main_window.QMessageBox, "warning", warning)
    window._compare()
    assert calls
    assert "discard all" in str(calls[0][2])
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: main_window.QMessageBox.StandardButton.Ok,
    )
    window._compare()
    window.close()
    application.processEvents()


def test_conflict_ui_is_hidden_unless_inherited_detection_is_enabled(tmp_path) -> None:
    application = app()
    settings = app_settings()
    settings.setValue("decisions/detect-inherited", False)
    settings.sync()
    window = MainWindow()
    assert window.action_filters.conflicts_box.isHidden()
    assert not window.comparison.model.conflicts_visible
    window._detect_inherited_conflicts = True
    window._update_conflict_ui()
    assert window.comparison.model.conflicts_visible
    assert not window.action_filters.conflicts_box.isHidden()
    window.close()
    application.processEvents()


def test_preserve_button_restores_after_a_fresh_comparison() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.enums import SyncMode
    from qpy_rsync.services.compare_service import CompareResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    window.comparison.set_changes(
        [Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")]
    )
    application.processEvents()
    assert window.preserve_button.isChecked()

    window.sync_mode.setCurrentIndex(window.sync_mode.findData(SyncMode.MIRROR))
    application.processEvents()
    # A mode change only invalidates the comparison; it must not turn the
    # Preserve Decisions setting off.
    assert window.comparison.model.stale
    assert window.preserve_button.isChecked()
    assert "ON" in window.preserve_button.toolTip()

    window._comparison_finished(
        CompareResult(ParseResult([], [], ), "", 0)
    )
    application.processEvents()
    assert window.preserve_button.isChecked()
    window.close()
    application.processEvents()


def test_log_files_follow_the_profile_name(tmp_path, monkeypatch) -> None:
    from qpy_rsync.storage.profile_store import save_profile

    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    assert window._profile_name() == "default"
    assert window._log_file_path.name == "app-default.log"
    assert window._rsync_log_path.name == "rsync-default.log"
    profile_path = tmp_path / "backup.json"
    save_profile(profile_path, window._profile())
    window._remember_profile_path(profile_path)
    assert window._profile_name() == "backup"
    assert window._log_file_path.name == "app-backup.log"
    assert window._rsync_log_path.name == "rsync-backup.log"
    window.close()
    application.processEvents()


def test_large_log_warns_in_orange(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    window = MainWindow()
    window._log_file_path.parent.mkdir(parents=True, exist_ok=True)
    with window._log_file_path.open("wb") as handle:
        handle.truncate(1_000_000_001)
    window._write_session_log("one more line")
    assert "1 GB" in window.log.toPlainText()
    assert "Clear Log" in window.log.toPlainText()
    block = window.log.document().findBlockByNumber(0)
    colors = []
    iterator = block.begin()
    while not iterator.atEnd():
        fragment = iterator.fragment()
        if fragment.isValid():
            colors.append(fragment.charFormat().foreground().color().name())
        iterator += 1
    assert "#ea580c" in colors
    window.close()
    application.processEvents()


def test_rsync_elapsed_is_logged() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window._start_rsync_clock("comparison")
    window._log_rsync_elapsed("comparison")
    assert "rsync comparison finished in" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_automatically_loaded_profile_is_logged(monkeypatch) -> None:
    from pathlib import Path

    import qpy_rsync.gui.main_window as module

    application = app()
    app_settings().clear()
    profile_path = Path("/profiles/laptop.json")

    def fake_restore(self):
        self._profile_path = profile_path
        return True

    monkeypatch.setattr(module.MainWindow, "_restore_recent_profile", fake_restore)
    window = module.MainWindow()
    assert "Profile loaded automatically: laptop" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_session_log_uses_local_time(tmp_path, monkeypatch) -> None:
    from datetime import datetime

    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    window = MainWindow()
    window._write_session_log("local timestamp")
    content = window._log_file_path.read_text(encoding="utf-8")
    stamp = content.splitlines()[-1].split(" ", 1)[0]
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == datetime.now().astimezone().utcoffset()
    window.close()
    application.processEvents()


def test_raw_rsync_output_logging_is_off_by_default(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    window = MainWindow()
    assert window._rsync_output_logging is False
    window._append_rsync_log("itemized record")
    window._append_transient_log("progress line")
    window._end_bulk_logging()
    assert not window._rsync_log_path.exists() or (
        "itemized record" not in window._rsync_log_path.read_text(encoding="utf-8")
    )
    window.close()
    application.processEvents()


def test_bulk_rsync_output_is_written_in_batches(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    window = MainWindow()
    writes: list[str] = []
    original = window._write_session_log
    def counted(text, *, rsync=False):
        if rsync:
            writes.append(text)
        return original(text, rsync=rsync)

    window._write_session_log = counted
    window._rsync_output_logging = True
    window._bulk_logging = True
    for index in range(2500):
        window._append_rsync_log(f"record {index}")
    window._end_bulk_logging()
    assert len(writes) == 3
    content = window._rsync_log_path.read_text(encoding="utf-8")
    assert "record 0" in content and "record 2499" in content
    window.close()
    application.processEvents()


def test_compare_progress_does_not_override_the_item_count() -> None:
    from types import SimpleNamespace

    application = app()
    app_settings().clear()
    window = MainWindow()
    window._comparison_items(1234)
    label = window.status_edit.text()
    window._comparison_progress(
        SimpleNamespace(percent=99, files_completed=999, files_remaining=5, files_total=1000)
    )
    assert window.status_edit.text() == label
    window.close()
    application.processEvents()


def test_version_and_commit_are_logged_once_in_the_session_header(tmp_path, monkeypatch) -> None:
    from qpy_rsync import __version__

    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.MainWindow._app_identity",
        staticmethod(lambda: f"qpy-rsync {__version__} (testcommit)"),
    )
    window = MainWindow()
    window._write_session_log("one line")
    content = window._log_file_path.read_text(encoding="utf-8")
    header = content.splitlines()[1]
    assert "qpy-rsync 0.4.0 (testcommit)" in header
    assert content.count("qpy-rsync 0.4.0") == 1
    assert "one line" in content
    window.close()
    application.processEvents()


def test_inventory_advanced_options_default_off(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    window = MainWindow()
    assert window._metadata_two_pass is False
    assert window._inventory_preload is False
    assert window._metadata_service._gather_options["two_pass"] is False
    window.close()
    application.processEvents()


def test_journal_reports_inventory_rsync_commands(tmp_path, monkeypatch) -> None:
    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()

    class FakeInventory:
        def gather(self, *_args):
            return 1

        def cancel(self):
            pass

        def has_cached_destination(self):
            return False

        def set_cached_destination(self, _paths):
            pass

    window._inventory_service = FakeInventory()
    monkeypatch.setattr(
        MainWindow, "_missing_local_directories", lambda self, profile: []
    )
    window._start_inventory("key", [])
    text = window.log.toPlainText()
    assert "$ rsync" in text
    assert "/src/" in text
    assert "/dst/" in text
    window.close()
    application.processEvents()


def _modified_profile_window(tmp_path, monkeypatch):
    """A window whose current profile differs from its loaded baseline."""
    from copy import deepcopy

    application = app()
    app_settings().clear()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    current = window._profile()
    baseline = deepcopy(current)
    baseline.backup.directory = "/different"
    window._baseline_profile = baseline
    window._profile_path = tmp_path / "my-profile.json"
    return application, window, current, baseline


def _answer_exit_prompt(application, window, label: str) -> None:
    """Click one of the three modal exit-prompt buttons once it is visible."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox, QPushButton

    def click() -> None:
        boxes = [
            widget
            for widget in application.topLevelWidgets()
            if isinstance(widget, QMessageBox) and widget.isVisible()
        ]
        assert len(boxes) == 1, boxes
        box = boxes[0]
        assert "Changed:" in box.text()
        assert "backup" in box.text()
        if window._profile_path is None:
            assert "No profile file is associated" in box.text()
        else:
            assert window._profile_path.name in box.text()
        buttons = [button.text() for button in box.findChildren(QPushButton)]
        assert set(buttons) == {"Save", "Save As...", "Don't Save"}, buttons
        button = next(b for b in box.findChildren(QPushButton) if b.text() == label)
        button.click()

    QTimer.singleShot(0, click)


def test_exit_prompt_save_writes_the_current_profile_path(tmp_path, monkeypatch) -> None:
    application, window, current, baseline = _modified_profile_window(
        tmp_path, monkeypatch
    )
    saved: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.save_profile",
        lambda path, profile: saved.append(path),
    )
    try:
        _answer_exit_prompt(application, window, "Save")
        window._save_profile_on_exit_if_modified(current, baseline)
        assert saved == [tmp_path / "my-profile.json"]
        assert window._profile_path == tmp_path / "my-profile.json"
        assert window._same_profile(window._baseline_profile, current)
    finally:
        window._baseline_profile = window._profile()
        window.close()
        application.processEvents()


def test_exit_prompt_save_as_uses_the_save_profile_dialog(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    application, window, current, baseline = _modified_profile_window(
        tmp_path, monkeypatch
    )
    saved: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.save_profile",
        lambda path, profile: saved.append(path),
    )
    captions: list[str] = []
    new_path = tmp_path / "renamed-profile.json"

    def get_save_filename(_parent, caption, *_args, **_kwargs):
        captions.append(caption)
        return str(new_path), "JSON (*.json)"

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(get_save_filename)
    )
    try:
        _answer_exit_prompt(application, window, "Save As...")
        window._save_profile_on_exit_if_modified(current, baseline)
        assert captions == ["Save Profile"]
        assert saved == [new_path]
        assert window._profile_path == new_path
        assert window._same_profile(window._baseline_profile, current)
    finally:
        window._baseline_profile = window._profile()
        window.close()
        application.processEvents()


def test_exit_prompt_save_without_a_profile_routes_to_save_as(
    tmp_path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    application, window, current, baseline = _modified_profile_window(
        tmp_path, monkeypatch
    )
    window._profile_path = None
    saved: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.save_profile",
        lambda path, profile: saved.append(path),
    )
    captions: list[str] = []
    new_path = tmp_path / "new-profile.json"

    def get_save_filename(_parent, caption, *_args, **_kwargs):
        captions.append(caption)
        return str(new_path), "JSON (*.json)"

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(get_save_filename)
    )
    try:
        _answer_exit_prompt(application, window, "Save")
        window._save_profile_on_exit_if_modified(current, baseline)
        assert captions == ["Save Profile"]
        assert saved == [new_path]
        assert window._profile_path == new_path
    finally:
        window._baseline_profile = window._profile()
        window.close()
        application.processEvents()


def test_exit_prompt_dont_save_leaves_the_profile_untouched(tmp_path, monkeypatch) -> None:
    application, window, current, baseline = _modified_profile_window(
        tmp_path, monkeypatch
    )
    saved: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.save_profile",
        lambda path, profile: saved.append(path),
    )
    try:
        _answer_exit_prompt(application, window, "Don't Save")
        window._save_profile_on_exit_if_modified(current, baseline)
        assert saved == []
        assert window._profile_path == tmp_path / "my-profile.json"
        assert window._baseline_profile is baseline
        assert not window._same_profile(window._baseline_profile, current)
    finally:
        window._baseline_profile = window._profile()
        window.close()
        application.processEvents()


def test_failed_destination_metadata_clears_the_busy_status() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window._metadata_token = 7
    window._metadata_pending = True
    window.progress_bar.setRange(0, 0)
    window._set_progress_status("Gathering destination metadata...")

    window._metadata_failed(7, "rsync is missing")

    assert window._metadata_pending is False
    assert window._metadata_token == 0
    assert window.progress_bar.maximum() == 100
    assert "Gathering" not in window.status_edit.text()
    window.close()
    application.processEvents()


def test_swap_button_precedes_the_sync_mode_selector() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    controls = window._controls_layout
    assert controls.indexOf(window.swap_button) < controls.indexOf(window.sync_mode)
    assert controls.indexOf(window.settings_button) == -1
    assert window.comparison.controls.layout().indexOf(
        window.settings_button
    ) < window.comparison.controls.layout().indexOf(window.layout_button)
    window.close()
    application.processEvents()



def test_metadata_watchdog_clears_the_comparing_status() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window._metadata_token = 7
    window._metadata_pending = True
    window.progress_bar.setRange(0, 0)
    window._set_progress_status("Gathering destination metadata...")
    window._set_state("Comparing...")

    window._metadata_timeout()

    assert window._metadata_pending is False
    assert window._metadata_token == 0
    assert window.progress_bar.maximum() == 100
    assert "Comparing" not in window.status_edit.text()
    window.close()
    application.processEvents()


def test_completion_is_announced_once() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    sounds: list[str] = []
    window._play_completion_sound = lambda kind: sounds.append(kind)  # type: ignore[method-assign]
    window._last_compare_count = 3
    window._comparison_announced = False

    window._finish_comparison_status()
    window._finish_comparison_status()

    assert sounds == ["success"]
    window.close()
    application.processEvents()


def test_stale_compare_result_is_ignored_after_a_new_compare() -> None:
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.services.compare_service import CompareResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window._last_compare_count = 1
    window._active_compare_generation = window._compare_generation = 7
    # A stale callback from generation 6 arrives after a new Compare started.
    window._active_compare_generation = 6
    stale = CompareResult(ParseResult([], []), "", 0)
    window._comparison_finished(stale)
    assert window._last_compare_count == 1
    window.close()
    application.processEvents()



def test_missing_native_extension_falls_back_to_python_view(monkeypatch) -> None:
    application = app()
    app_settings().clear()
    import qpy_rsync.gui.native_hybrid_view as nhv

    monkeypatch.setattr(nhv, "module", lambda: None)
    settings = app_settings()
    settings.setValue("advanced/python_view", False)
    settings.sync()
    window = MainWindow()
    assert window._hybrid_view is None
    assert type(window.overview).__name__ == "OverviewPane"
    settings.setValue("advanced/python_view", True)
    settings.sync()
    window.close()
    application.processEvents()


def test_cancel_gives_immediate_feedback() -> None:
    from qpy_rsync.backend.process_runner import ProcessState

    application = app()
    app_settings().clear()
    window = MainWindow()

    class FakeService:
        state = ProcessState.RUNNING

        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    fake = FakeService()
    window._service = fake  # type: ignore[assignment]
    window._cancel_active_operation()
    assert fake.cancelled
    assert window.status_edit.text() == "Cancelling..."
    assert window.status_edit.text() == "Cancelling..."
    assert not window.cancel_button.isEnabled()
    window.close()
    application.processEvents()


def test_cancelling_fresh_comparison_dialog_keeps_stale_state(monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    application = app()
    app_settings().clear()
    window = MainWindow()
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel),
    )
    window.preserve_button.setChecked(False)
    window._compare()
    assert "stale" in window.status_edit.text().casefold()
    assert "Compare cancelled" in window.log.toPlainText()
    assert window.compare_button.isEnabled()
    window.close()
    application.processEvents()


def test_folder_decision_patches_plan_without_full_estimate() -> None:
    """A folder decision must not fall back to a full summary scan."""
    from PySide6.QtWidgets import QApplication

    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.gui.main_window import MainWindow
    from qpy_rsync.services.compare_service import CompareResult
    from qpy_rsync.storage.settings import app_settings

    application = QApplication.instance() or QApplication([])
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    changes = [
        Change(f"folder/f{i:03d}.txt", ChangeAction.CREATE, ObjectKind.FILE,
               ">f+++++++++", size=10)
        for i in range(50)
    ]
    window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
    before = window._current_plan.summary.included
    assert before == 50

    # No plan item exists for the folder itself; excluding it must patch the
    # 50 children incrementally instead of starting the full-estimate timer.
    window.comparison.model.set_excluded("folder", True)
    window.comparison.changes_updated.emit("decision")
    assert window._current_plan.summary.included == 0
    assert not window._stale_summary_timer.isActive()

    window.comparison.model.set_excluded("folder", False)
    window.comparison.changes_updated.emit("decision")
    assert window._current_plan.summary.included == before
    assert not window._stale_summary_timer.isActive()
    window.close()
    application.processEvents()


def test_window_shortcuts_work_from_any_focus() -> None:
    application = app()
    window = MainWindow()
    window.show()
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent, QShortcut

    keys = {shortcut.key().toString(): shortcut
            for shortcut in window.findChildren(QShortcut)}
    for key in ("Ctrl+S", "Ctrl+D", "Ctrl+N", "Ctrl+2", "Ctrl+3", "Ctrl+8"):
        assert key in keys
        assert keys[key].context() == Qt.ShortcutContext.ApplicationShortcut

    window.activateWindow()
    application.processEvents()
    window.source_edit.setFocus()
    application.processEvents()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_S, Qt.ControlModifier)
    QCoreApplication.postEvent(window, event)
    application.processEvents()
    assert QApplication.focusWidget() is window.comparison.source
    window.close()


def test_operation_buttons_are_disabled_until_an_operation_runs() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    assert not window.cancel_button.isEnabled()
    assert not window.pause_button.isEnabled()
    window._set_operation_controls(True)
    assert window.cancel_button.isEnabled()
    assert window.pause_button.isEnabled()
    window.pause_button.setChecked(True)
    window._set_operation_controls(False)
    assert not window.cancel_button.isEnabled()
    assert not window.pause_button.isEnabled()
    assert not window.pause_button.isChecked()
    window.close()
    application.processEvents()


def test_menu_buttons_show_a_chevron_and_hint() -> None:
    from qpy_rsync.gui.main_window import _MenuToolButton

    application = app()
    app_settings().clear()
    window = MainWindow()
    for button in (window.profile_button, window.backup_open, window.log_file_open):
        assert isinstance(button, _MenuToolButton)
        assert "Right-click for more options" in button.toolTip()
    assert not isinstance(window.settings_button, _MenuToolButton)
    window.close()
    application.processEvents()


def test_backup_and_log_menus_open_the_buttons_own_menu() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    from PySide6.QtWidgets import QToolButton

    for button in (window.backup_open, window.log_file_open):
        assert button.menu() is not None
        assert button.menu().parent() is button
        assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert [action.text() for action in window.backup_menu.actions()] == [
        "Open the backup directory",
        "Configure...",
    ]
    assert [action.text() for action in window.log_menu.actions()] == [
        "Open the log file",
        "Clear Log",
        "Configure...",
    ]
    window.close()
    application.processEvents()


def test_unconfigured_buttons_point_at_their_settings(monkeypatch) -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    calls: list[str] = []
    monkeypatch.setattr(
        window, "_edit_settings", lambda section="general": calls.append(section)
    )
    monkeypatch.setattr(window, "_edit_profile", lambda section="options": calls.append(section))
    window.backup_edit.setText("")
    window.log_file_checkbox.setChecked(False)
    window._update_open_button_states()
    assert window.backup_open.isEnabled()
    assert window.log_file_open.isEnabled()
    assert "Configure the backup directory" in window.backup_open.toolTip()
    assert "Configure logging" in window.log_file_open.toolTip()
    window.backup_open_action.trigger()
    window.log_open_action.trigger()
    assert calls == ["backup", "logging"]
    window.close()
    application.processEvents()


def test_clear_log_asks_for_approval(monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox

    application = app()
    app_settings().clear()
    window = MainWindow()
    window._log_file_path.write_text("keep this line\n", encoding="utf-8")
    answers = iter((QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted))
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: next(answers))
    window.log_clear_action.trigger()
    assert "keep this line" in window._log_file_path.read_text(encoding="utf-8")
    window.log_clear_action.trigger()
    assert "keep this line" not in window._log_file_path.read_text(encoding="utf-8")
    window.close()
    application.processEvents()


def test_profile_menu_puts_edit_directly_under_save() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.profile_menu.aboutToShow.emit()
    labels = [action.text() for action in window.profile_menu.actions()]
    assert labels[labels.index("Edit...")] == "Edit..."
    assert labels.index("Edit...") == labels.index("Save") + 1
    assert labels.index("Edit...") > labels.index("Load...")
    window.close()
    application.processEvents()


def test_filters_dialog_states_where_rules_are_stored(monkeypatch) -> None:
    from qpy_rsync.gui import profile_editor

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    assert "current profile" in window.filters_button.toolTip()
    assert "Save" in window.filters_button.toolTip()

    captured: list[object] = []
    original = profile_editor.ProfileEditorDialog

    class CaptureDialog(original):  # type: ignore[valid-type,misc]
        def exec(self):  # type: ignore[no-untyped-def]
            captured.append(self)
            return QDialog.DialogCode.Rejected

    from PySide6.QtWidgets import QDialog, QLabel

    monkeypatch.setattr(profile_editor, "ProfileEditorDialog", CaptureDialog)
    window._edit_filters()
    assert captured
    notes = captured[0].findChildren(QLabel, "filter-storage-note")  # type: ignore[attr-defined]
    assert len(notes) == 1
    assert "Save" in notes[0].text()
    application.processEvents()
    window.close()


def _finished_comparison(window: MainWindow):
    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.compare_service import CompareResult

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


def test_location_changes_mark_the_comparison_stale_and_restore() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    _finished_comparison(window)
    assert not window.comparison.model.stale
    assert window.synchronize_button.isEnabled()

    window.destination_edit.setText("/other/")
    assert window.comparison.model.stale
    assert not window.synchronize_button.isEnabled()
    assert not window.validate_plan_button.isEnabled()
    assert "#EA580C" in window.destination_edit.styleSheet()
    assert "Stale comparison" in window.log.toPlainText()

    window.destination_edit.setText("/dst/")
    assert not window.comparison.model.stale
    assert window.synchronize_button.isEnabled()
    assert "#EA580C" not in window.destination_edit.styleSheet()
    assert "Locations restored" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_sync_confirmation_checkbox_controls_recompare(monkeypatch) -> None:
    from qpy_rsync.core.execution_gate import ExecutionGateState
    from qpy_rsync.services.sync_service import SyncResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    _finished_comparison(window)
    scheduled: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QTimer.singleShot",
        lambda delay, callback: scheduled.append(callback),
    )
    window._execution_gate._state = ExecutionGateState.EXECUTING
    window._compare_after_sync = False
    window._sync_finished(SyncResult(0, "", ""))
    assert scheduled == []
    window._execution_gate._state = ExecutionGateState.EXECUTING
    window._compare_after_sync = True
    window._sync_finished(SyncResult(0, "", ""))
    assert len(scheduled) == 1
    window.close()
    application.processEvents()


def test_sync_confirmation_checkbox_value_is_used(monkeypatch) -> None:
    from PySide6.QtWidgets import QCheckBox, QDialog
    from qpy_rsync.gui import main_window as mw_module
    from qpy_rsync.gui.sync_confirmation import SyncConfirmationDialog

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    _finished_comparison(window)
    started: list[object] = []
    monkeypatch.setattr(
        window._sync_service,
        "synchronize",
        lambda *_args, **_kwargs: started.append(True),
    )

    class UncheckedDialog(SyncConfirmationDialog):
        def exec(self):  # type: ignore[no-untyped-def]
            for checkbox in self.findChildren(QCheckBox):
                checkbox.setChecked(False)
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(mw_module, "SyncConfirmationDialog", UncheckedDialog)
    window._compare_after_sync = True
    window._show_sync_confirmation()
    assert started
    assert window._compare_after_sync is False
    window.close()
    application.processEvents()


def test_sync_confirmation_adds_enabled_checkbox(monkeypatch) -> None:
    from PySide6.QtWidgets import QCheckBox, QDialog

    application = app()
    app_settings().clear()
    dialog = QDialog()
    from PySide6.QtWidgets import QDialogButtonBox, QVBoxLayout

    layout = QVBoxLayout(dialog)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    dialog.buttons = buttons  # type: ignore[attr-defined]
    layout.addWidget(buttons)
    checkbox = MainWindow._compare_after_checkbox(dialog)
    assert checkbox.isChecked()
    assert "Compare again after synchronization" in checkbox.text()
    assert layout.indexOf(checkbox) == layout.indexOf(buttons) - 1
    assert MainWindow._compare_after_checkbox(dialog) is checkbox
    application.processEvents()
    dialog.close()


def test_overview_width_survives_layout_switches() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    application.processEvents()
    original = window.overview.width()
    window._set_layout_mode("wide")
    application.processEvents()
    assert abs(window.overview.width() - original) <= 2
    window._set_layout_mode("normal")
    application.processEvents()
    assert abs(window.overview.width() - original) <= 2
    window.close()
    application.processEvents()


def test_escape_clears_the_search_field() -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    application = app()
    app_settings().clear()
    window = MainWindow()
    search = window.comparison.search_edit
    search.setText("a pattern")
    QCoreApplication.sendEvent(
        search,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier),
    )
    assert search.text() == ""
    window.close()
    application.processEvents()


def test_pane_focus_shortcuts_land_on_visible_columns() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    app_settings().clear()
    window = MainWindow()
    window.comparison.set_changes(
        [Change("docs/file.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    )
    window._focus_named_pane("action")
    assert window.comparison.action.currentIndex().column() == window.comparison.model.ACTION
    window._focus_named_pane("source")
    assert window.comparison.source.currentIndex().column() == window.comparison.model.SOURCE_NAME
    window._focus_named_pane("destination")
    assert (
        window.comparison.destination.currentIndex().column()
        == window.comparison.model.DESTINATION_NAME
    )
    window.close()
    application.processEvents()

"""Journal continuity, sync staleness and noisy remote output."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

from PySide6.QtWidgets import QApplication

from qpy_rsync.backend.diagnostics import clean_qt_noise
from qpy_rsync.core.changes import ChangeDecision
from qpy_rsync.core.enums import SyncMode
from qpy_rsync.gui.main_window import MainWindow
from qpy_rsync.storage.settings import app_settings


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_benign_qt_lines_are_removed_but_real_failures_kept() -> None:
    raw = (
        "QXcbIntegration: Cannot create platform OpenGL context, neither GLX nor EGL are enabled\n"
        "Warning: fallback to QtQuick software backend.\n"
        "Permission denied, please try again."
    )
    assert clean_qt_noise(raw) == "Permission denied, please try again."
    assert clean_qt_noise("rsync: normal output") == "rsync: normal output"


def test_compare_keeps_the_journal(monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    application = app()
    app_settings().clear()
    window = MainWindow()
    root = tempfile.gettempdir()
    window.source_edit.setText(root)
    window.destination_edit.setText(root)
    window._active_profile = window._profile()
    window.preserve_button.setChecked(True)
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok),
    )

    # A previous operation is still on screen when Compare starts.
    window._append_log("PREVIOUS OPERATION")
    window._flush_log()
    assert "PREVIOUS OPERATION" in window.log.toPlainText()

    calls: list[object] = []
    window._service.compare = lambda profile: calls.append(profile)  # type: ignore[method-assign]
    window._compare()
    assert calls  # the comparison actually started
    window._flush_log()
    assert "PREVIOUS OPERATION" in window.log.toPlainText()
    assert "$ rsync" in window.log.toPlainText()
    window.close()
    application.processEvents()


def test_sync_finish_marks_stale_without_auto_compare(monkeypatch) -> None:
    from qpy_rsync.core.execution_gate import ExecutionGateState
    from qpy_rsync.services.sync_service import SyncResult

    application = app()
    app_settings().clear()
    window = MainWindow()
    window._execution_gate._state = ExecutionGateState.EXECUTING
    window.comparison.model.decisions.set("a.txt", ChangeDecision.EXCLUDE)

    scheduled: list[object] = []
    monkeypatch.setattr(
        "qpy_rsync.gui.main_window.QTimer.singleShot",
        lambda delay, callback: scheduled.append(callback),
    )
    window._sync_finished(SyncResult(0, "", ""))
    assert scheduled == []
    assert window.comparison.model.stale
    assert window.comparison.model.decisions.explicit("a.txt") is ChangeDecision.EXCLUDE
    assert "click Compare" in window.status_edit.text()
    window.close()
    application.processEvents()


def test_rsync_log_drops_qt_noise(monkeypatch) -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window._rsync_output_logging = True
    window._append_rsync_log(
        "QXcbIntegration: Cannot create platform OpenGL context\n"
        "Permission denied, please try again."
    )
    window._flush_log()
    text = window.log.toPlainText()
    assert "Permission denied" in text
    assert "QXcbIntegration" not in text
    window.close()
    application.processEvents()


def test_native_exclude_keeps_sync_available() -> None:
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
        Change(f"f{i}.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", size=10)
        for i in range(5)
    ]
    window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
    assert window.synchronize_button.isEnabled()

    # A single Exclude decision made in the native checkbox must not take
    # the Sync action away: the remaining four items are still executable.
    window._on_native_decision(2, 2)
    assert window.synchronize_button.isEnabled()
    assert window._current_plan.summary.included == 4
    window.close()
    application.processEvents()


def test_native_space_excludes_every_selected_item(monkeypatch) -> None:
    from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QTableView

    from qpy_rsync.backend.rsync_parser import ParseResult
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.services.compare_service import CompareResult

    monkeypatch.setenv("QPY_HYBRID_VIEW", "1")
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    changes = [
        Change(f"f{i}.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", size=10)
        for i in range(6)
    ]
    window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
    table = sorted(
        window._hybrid_view.widget.findChildren(QTableView),
        key=lambda item: item.x(),
    )[0]
    selection = table.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row in (1, 2, 3):
        selection.select(table.model().index(row, 0), flags)
    assert window._hybrid_view.selected_paths() == ["f0.txt", "f1.txt", "f2.txt"]

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    application.sendEvent(table, event)
    for i in (0, 1, 2):
        assert window._hybrid_view.decision_for_path(f"f{i}.txt") == 2
    assert window.comparison.model.decisions.explicit_items() == tuple(
        (f"f{i}.txt", ChangeDecision.EXCLUDE) for i in (0, 1, 2)
    )
    window.close()
    application.processEvents()


def test_journal_does_not_double_timestamp_a_prefixed_line() -> None:
    application = app()
    app_settings().clear()
    window = MainWindow()
    window.log.clear()
    window._append_log("10:11:12.34 already stamped")
    window._append_log("2026-11-26T10:11:12.345+00:00 iso stamped")
    window._flush_log()
    lines = [
        window.log.document().findBlockByNumber(row).text()
        for row in range(window.log.document().blockCount())
    ]
    assert len(lines) == 2
    assert lines[0].endswith("10:11:12.34 already stamped")
    assert lines[0].count("10:11:12.34") == 1  # one timestamp only
    assert lines[1].endswith("2026-11-26T10:11:12.345+00:00 iso stamped")
    assert lines[1].count("10:11:12.345") == 1
    window.close()
    application.processEvents()


def test_compare_diagnostic_reports_real_timings(monkeypatch) -> None:
    import re

    from qpy_rsync.backend.process_runner import ProcessResult
    from qpy_rsync.services import compare_service
    from qpy_rsync.services.compare_service import CompareService

    app()
    service = CompareService()
    diagnostics: list[str] = []
    service.on_diagnostic = diagnostics.append
    clock = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    monkeypatch.setattr(compare_service, "perf_counter", lambda: next(clock))
    service._stdout_chunk(
        ">f+++++++++|qpy-rsync|8|qpy-rsync|2024/01/01|qpy-rsync|file.txt\r"
    )
    service._finish(ProcessResult(0, "", ""))
    line = diagnostics[-1]
    match = re.search(
        r"parsing (\d+\.\d{2}) s, journal writes (\d+\.\d{2}) s, "
        r"total (\d+\.\d{2}) s",
        line,
    )
    assert match is not None
    assert match.group(1) == "1.00"
    assert match.group(2) == "1.00"
    assert match.group(3) == "5.00"

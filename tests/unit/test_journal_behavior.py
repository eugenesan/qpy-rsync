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

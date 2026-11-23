"""The Advanced timing-diagnostics setting (for bug reports)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from qpy_rsync.backend import diagnostics
from qpy_rsync.gui.settings_dialog import SettingsDialog
from qpy_rsync.storage.settings import app_settings


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_timing_override_controls_timing_output(monkeypatch) -> None:
    for name in ("QPY_RSYNC_DEBUG", "QPY_RSYNC_TIMING", "QPY_RSYNC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    original = diagnostics.timing_enabled()
    try:
        diagnostics.set_timing_enabled(True)
        assert diagnostics.timing_enabled()
        diagnostics.set_timing_enabled(False)
        assert not diagnostics.timing_enabled()
    finally:
        diagnostics.set_timing_enabled(original)


def test_settings_dialog_exposes_timing_checkbox() -> None:
    application = app()
    holder = QWidget()
    dialog = SettingsDialog(
        holder, holder=holder, log_panel=QWidget(holder), backup_panel=QWidget(holder),
        timing_logging=True,
    )
    assert dialog.timing_logging() is True
    dialog.timing_logging_checkbox.setChecked(False)
    assert dialog.timing_logging() is False
    dialog.close()
    application.processEvents()


def test_timing_setting_is_loaded_and_applied() -> None:
    from qpy_rsync.gui.main_window import MainWindow

    application = app()
    settings = app_settings()
    settings.clear()
    settings.setValue("logging/timing", True)
    settings.sync()
    try:
        window = MainWindow()
        assert window._timing_logging is True
        assert diagnostics.timing_enabled()
    finally:
        diagnostics.set_timing_enabled(False)
    window.close()
    application.processEvents()

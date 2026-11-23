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
    original_timing = diagnostics.timing_enabled()
    original_debug = diagnostics.enabled()
    try:
        diagnostics.set_timing_enabled(True)
        assert diagnostics.timing_enabled()
        assert not diagnostics.enabled()  # timing alone is not debug
        diagnostics.set_timing_enabled(False)
        assert not diagnostics.timing_enabled()
        diagnostics.set_debug_enabled(True)
        assert diagnostics.enabled()
        assert diagnostics.timing_enabled()  # debug implies timing
        assert "debug" in _render_debug_line()
    finally:
        diagnostics.set_timing_enabled(original_timing)
        diagnostics.set_debug_enabled(original_debug)


def _render_debug_line() -> str:
    lines: list[str] = []
    diagnostics.set_timing_sink(lines.append)
    try:
        diagnostics.debug("probe", value=1)
    finally:
        diagnostics.set_timing_sink(None)
    return "\n".join(lines)


def test_settings_dialog_exposes_timing_checkbox() -> None:
    application = app()
    holder = QWidget()
    dialog = SettingsDialog(
        holder, holder=holder, log_panel=QWidget(holder), backup_panel=QWidget(holder),
        timing_logging=True,
        debug_logging=True,
    )
    assert dialog.timing_logging() is True
    assert dialog.debug_logging() is True
    timing_tip = dialog.timing_logging_checkbox.toolTip()
    debug_tip = dialog.debug_logging_checkbox.toolTip()
    assert "performance" in timing_tip and "session log" in timing_tip
    assert "Warning" in debug_tip and "verbose" in debug_tip
    dialog.timing_logging_checkbox.setChecked(False)
    dialog.debug_logging_checkbox.setChecked(False)
    assert dialog.timing_logging() is False
    assert dialog.debug_logging() is False
    dialog.close()
    application.processEvents()


def test_timing_setting_is_loaded_and_applied() -> None:
    from qpy_rsync.gui.main_window import MainWindow

    application = app()
    settings = app_settings()
    settings.clear()
    settings.setValue("logging/timing", True)
    settings.setValue("logging/debug", True)
    settings.sync()
    try:
        window = MainWindow()
        assert window._timing_logging is True
        assert window._debug_logging is True
        assert diagnostics.timing_enabled()
        assert diagnostics.enabled()
    finally:
        diagnostics.set_timing_enabled(False)
        diagnostics.set_debug_enabled(False)
    window.close()
    application.processEvents()

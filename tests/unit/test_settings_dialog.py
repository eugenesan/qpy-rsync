import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from qpy_rsync.gui.settings_dialog import SettingsDialog


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_settings_expose_both_expansion_limits() -> None:
    application = app()
    dialog = SettingsDialog(
        expand_mode="all", expand_limit=256, expand_total_limit=10000
    )
    assert dialog.expand_limit() == 256
    assert dialog.expand_total_limit() == 10000
    dialog.total_limit_spin.setValue(12345)
    assert dialog.expand_total_limit() == 12345
    dialog.close()
    application.processEvents()

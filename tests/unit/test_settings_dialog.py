import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from qpy_rsync.gui.settings_dialog import SettingsDialog


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_settings_expose_the_comparison_expansion_limit() -> None:
    application = app()
    dialog = SettingsDialog(expand_mode="all", expand_total_limit=10000)
    assert dialog.expand_total_limit() == 10000
    dialog.total_limit_spin.setValue(12345)
    assert dialog.expand_total_limit() == 12345
    dialog.close()
    application.processEvents()


def test_the_expansion_settings_are_disabled_for_the_flat_list() -> None:
    application = app()
    dialog = SettingsDialog(expand_mode="all", list_layout="tree")
    assert dialog.expand_combo.isEnabled()
    assert dialog.total_limit_spin.isEnabled()
    assert not dialog.expansion_hint.isVisible()

    dialog.layout_combo.setCurrentIndex(dialog.layout_combo.findData("flat"))
    application.processEvents()
    assert not dialog.expand_combo.isEnabled()
    assert not dialog.total_limit_spin.isEnabled()
    assert not dialog.expansion_hint_2.isEnabled()
    dialog.close()
    application.processEvents()

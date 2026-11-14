import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialogButtonBox, QWidget

from qpy_rsync.gui.settings_dialog import SECTIONS, SettingsDialog


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dialog(**kwargs) -> tuple[SettingsDialog, QWidget, QWidget, QWidget]:
    """A settings dialog with the panels the main window would pass."""
    app()
    holder = QWidget()
    log_panel = QWidget(holder)
    backup_panel = QWidget(holder)
    dialog = SettingsDialog(
        holder,
        holder=holder,
        log_panel=log_panel,
        backup_panel=backup_panel,
        **kwargs,
    )
    return dialog, holder, log_panel, backup_panel


def test_the_dialog_has_a_tab_for_every_section() -> None:
    dialog, _holder, _log, _backup = _dialog()
    titles = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
    assert titles == ["General", "Logging", "Backup"]
    assert len(SECTIONS) == 3


def test_show_section_selects_the_tab() -> None:
    dialog, _holder, _log, _backup = _dialog(section="backup")
    assert dialog.tabs.currentIndex() == SECTIONS.index("backup")
    dialog.show_section("logging")
    assert dialog.tabs.currentIndex() == SECTIONS.index("logging")
    # An unknown section falls back to the first tab.
    dialog.show_section("nonsense")
    assert dialog.tabs.currentIndex() == 0


def test_the_sound_setting_is_read_back() -> None:
    dialog, _holder, _log, _backup = _dialog(sound_enabled=True)
    assert dialog.sound_enabled() is True
    dialog.sound_checkbox.setChecked(False)
    assert dialog.sound_enabled() is False


def test_closing_the_dialog_keeps_the_panels_alive() -> None:
    dialog, holder, log_panel, backup_panel = _dialog()
    dialog.done(0)
    # The panels belong to the main window, so they go back to their holder
    # instead of being destroyed with the dialog.
    assert log_panel.parent() is holder
    assert backup_panel.parent() is holder
    assert log_panel.isVisible() is False
    assert backup_panel.isVisible() is False


def test_the_dialog_offers_ok_and_cancel() -> None:
    dialog, _holder, _log, _backup = _dialog()
    buttons = dialog.findChildren(QDialogButtonBox)
    assert buttons
    standard = buttons[0].standardButtons()
    assert standard & QDialogButtonBox.StandardButton.Ok
    assert standard & QDialogButtonBox.StandardButton.Cancel

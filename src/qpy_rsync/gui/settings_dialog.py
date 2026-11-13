"""Application settings: logging, backups and completion sounds."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# The tabs are named so a context menu can open the matching one.
SECTIONS = ("general", "logging", "backup")


class SettingsDialog(QDialog):
    """The settings that are not part of a sync profile.

    The logging and backup panels are built by the main window, because they
    already bind to its state; the dialog only presents them in tabs and
    hands them back when it closes.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        holder: QWidget,
        log_panel: QWidget,
        backup_panel: QWidget,
        sound_enabled: bool = True,
        section: str = "general",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 380)
        self._holder = holder
        self._log_panel = log_panel
        self._backup_panel = backup_panel

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        general = QWidget(self.tabs)
        general_layout = QVBoxLayout(general)
        self.sound_checkbox = QCheckBox(
            "Play a sound when a comparison or a sync finishes"
        )
        self.sound_checkbox.setChecked(bool(sound_enabled))
        self.sound_checkbox.setToolTip(
            "Uses the desktop sound when one is installed and the terminal "
            "bell otherwise."
        )
        general_layout.addWidget(self.sound_checkbox)
        hint = QLabel(
            "Logging and backup configuration live in their own tabs. The "
            "toolbar keeps a button that opens each location."
        )
        hint.setWordWrap(True)
        general_layout.addWidget(hint)
        general_layout.addStretch(1)
        self.tabs.addTab(general, "General")
        self.tabs.addTab(log_panel, "Logging")
        self.tabs.addTab(backup_panel, "Backup")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.show_section(section)

    def show_section(self, section: str) -> None:
        """Select the tab named by a settings section."""
        try:
            index = SECTIONS.index(section)
        except ValueError:
            index = 0
        if index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    def sound_enabled(self) -> bool:
        return self.sound_checkbox.isChecked()

    def done(self, result: int) -> None:  # noqa: D102
        # The panels belong to the main window; keep them alive when the
        # dialog closes, otherwise their widgets would be destroyed.
        for widget in (self._log_panel, self._backup_panel):
            widget.setParent(self._holder)
            widget.setVisible(False)
        super().done(result)

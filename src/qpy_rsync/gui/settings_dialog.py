"""Application settings: logging, backups and completion sounds."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.core.changes import ChangeAction
from qpy_rsync.gui.icons import ACTION_LABELS
from qpy_rsync.services.external_tools import ExternalTool

from .action_colours import DEFAULT_COLOURS

from .tools_panel import ToolsPanel

# The tabs are named so a context menu can open the matching one.
SECTIONS = ("general", "logging", "backup", "tools")


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
        tools: list[ExternalTool] | None = None,
        diff_command: str = "",
        colours: dict[ChangeAction, str | None] | None = None,
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

        # The colours that mark the actions.
        colours_box = QGroupBox("Action colours", general)
        colours_layout = QVBoxLayout(colours_box)
        colours_hint = QLabel(
            "The colour marks the items of an action in the list. "
            "Switch the marking off to leave an action in the plain colour.",
            colours_box,
        )
        colours_hint.setWordWrap(True)
        colours_layout.addWidget(colours_hint)
        self.colour_table = QTableWidget(0, 3, colours_box)
        self.colour_table.setHorizontalHeaderLabels(
            ["Action", "Colour", "Marked"]
        )
        self.colour_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.colour_table.verticalHeader().setVisible(False)
        header = self.colour_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        colours_layout.addWidget(self.colour_table)
        general_layout.addWidget(colours_box, 1)
        general_layout.addStretch(0)
        self.colour_table.cellClicked.connect(self._colour_clicked)
        self.set_action_colours(colours)
        self.tools_panel = ToolsPanel(self, tools or [], diff_command)
        self.tabs.addTab(general, "General")
        self.tabs.addTab(log_panel, "Logging")
        self.tabs.addTab(backup_panel, "Backup")
        self.tabs.addTab(self.tools_panel, "Tools")

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

    def set_action_colours(
        self, colours: dict[ChangeAction, str | None] | None
    ) -> None:
        """Show the colours of the actions."""
        self.colour_table.setRowCount(0)
        for action, default in DEFAULT_COLOURS.items():
            row = self.colour_table.rowCount()
            self.colour_table.insertRow(row)
            self.colour_table.setItem(
                row, 0, QTableWidgetItem(ACTION_LABELS.get(action, action.value))
            )
            value = colours.get(action, default) if colours else default
            self._set_colour(row, value)
            marked = QTableWidgetItem("")
            marked.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            marked.setCheckState(
                Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
            )
            self.colour_table.setItem(row, 2, marked)

    def action_colours(self) -> dict[ChangeAction, str | None]:
        """The colours the page describes."""
        colours: dict[ChangeAction, str | None] = {}
        for row in range(self.colour_table.rowCount()):
            name = self.colour_table.item(row, 0)
            if name is None:
                continue
            action = next(
                (
                    action
                    for action in DEFAULT_COLOURS
                    if ACTION_LABELS.get(action, action.value) == name.text()
                ),
                None,
            )
            if action is None:
                continue
            marked = self.colour_table.item(row, 2)
            if marked is not None and marked.checkState() != Qt.CheckState.Checked:
                colours[action] = None
                continue
            item = self.colour_table.item(row, 1)
            colours[action] = item.text() if item is not None else None
        return colours

    def _set_colour(self, row: int, value: str | None) -> None:
        """Show one colour in the table."""
        item = QTableWidgetItem(value or "")
        if value:
            colour = QColor(value)
            item.setBackground(QBrush(colour))
            # A readable text on the colour itself.
            item.setForeground(
                QBrush(QColor("#000000") if colour.lightness() > 128 else QColor("#ffffff"))
            )
            item.setToolTip(value)
        self.colour_table.setItem(row, 1, item)

    def _colour_clicked(self, row: int, column: int) -> None:
        """Open the colour picker of one action."""
        if column != 1:
            return
        item = self.colour_table.item(row, 1)
        current = QColor(item.text()) if item is not None else QColor()
        chosen = QColorDialog.getColor(current, self, "Action colour")
        if not chosen.isValid():
            return
        self._set_colour(row, chosen.name())
        marked = self.colour_table.item(row, 2)
        if marked is not None and marked.checkState() != Qt.CheckState.Checked:
            marked.setCheckState(Qt.CheckState.Checked)

    def external_tools(self) -> list[ExternalTool]:
        """The tools the page describes."""
        return self.tools_panel.tools()

    def diff_command(self) -> str:
        """The diff tool command the page describes."""
        return self.tools_panel.diff_command()

    def done(self, result: int) -> None:  # noqa: D102
        # The panels belong to the main window; keep them alive when the
        # dialog closes, otherwise their widgets would be destroyed.
        for widget in (self._log_panel, self._backup_panel):
            widget.setParent(self._holder)
            widget.setVisible(False)
        super().done(result)

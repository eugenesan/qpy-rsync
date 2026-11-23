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
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
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
SECTIONS = ("general", "logging", "tools", "advanced")


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
        verification_enabled: bool = False,
        verification_rsync: bool = False,
        detect_inherited_conflicts: bool = False,
        rsync_output_logging: bool = False,
        metadata_two_pass: bool = False,
        inventory_preload: bool = False,
        python_view: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(720, 600)
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
        advanced = QWidget(self.tabs)
        advanced_layout = QVBoxLayout(advanced)
        self.verification_checkbox = QCheckBox(
            "Show the Verify Decisions check", advanced
        )
        self.verification_checkbox.setChecked(bool(verification_enabled))
        self.verification_checkbox.setToolTip(
            "Off by default. Shows an optional consistency check between the "
            "selected decisions and the execution plan. Synchronization does "
            "not depend on it."
        )
        advanced_layout.addWidget(self.verification_checkbox)
        self.verification_rsync_checkbox = QCheckBox(
            "Verify with a second rsync dry run", advanced
        )
        self.verification_rsync_checkbox.setChecked(bool(verification_rsync))
        self.verification_rsync_checkbox.setToolTip(
            "Off by default. Re-scans the live tree and reports differences "
            "from the reviewed comparison as a warning. On a changing "
            "directory this will report unrelated changes; re-compare close "
            "to verification to reduce them."
        )
        advanced_layout.addWidget(self.verification_rsync_checkbox)
        self.inherited_checkbox = QCheckBox(
            "Flag new destination-only items below included folders", advanced
        )
        self.inherited_checkbox.setChecked(bool(detect_inherited_conflicts))
        self.inherited_checkbox.setToolTip(
            "Off by default. When a folder has an INCLUDE decision, a new "
            "destination-only item below it would be deleted. This check "
            "flags that decision for review.\n"
            "A folder-wide INCLUDE is often a deliberate choice\n"
            "to own everything below it: rotating logs under\n"
            "/var/log, for example, would produce a review on every\n"
            "sync. Leave off unless those deletions should be\n"
            "confirmed explicitly."
        )
        advanced_layout.addWidget(self.inherited_checkbox)
        self.rsync_output_checkbox = QCheckBox(
            "Log raw rsync output", advanced
        )
        self.rsync_output_checkbox.setChecked(bool(rsync_output_logging))
        self.rsync_output_checkbox.setToolTip(
            "Off by default. Writes every itemized rsync record to the rsync "
            "log file. On a large tree this can add hundreds of MB per "
            "comparison and costs measurable time in the Python log path. "
            "Application events and timing lines are always logged."
        )
        advanced_layout.addWidget(self.rsync_output_checkbox)
        self.metadata_two_pass_checkbox = QCheckBox(
            "Use two rsync runs for destination metadata", advanced
        )
        self.metadata_two_pass_checkbox.setChecked(bool(metadata_two_pass))
        self.metadata_two_pass_checkbox.setToolTip(
            "Off by default: one unfiltered rsync listing fills in destination "
            "sizes and dates after a compare. Turn on to run a filtered listing "
            "first and an unfiltered one only for paths the filters hid. This "
            "can be faster when the profile excludes very large subtrees, but "
            "normally costs an extra rsync process and SSH handshake."
        )
        advanced_layout.addWidget(self.metadata_two_pass_checkbox)
        self.inventory_preload_checkbox = QCheckBox(
            "Preload the source listing for unchanged items", advanced
        )
        self.inventory_preload_checkbox.setChecked(bool(inventory_preload))
        self.inventory_preload_checkbox.setToolTip(
            "Off by default: the source is listed only when you ask to show "
            "unchanged items. Turn on to list source and destination together "
            "after each compare, so showing unchanged needs no extra rsync. "
            "Useful when you routinely browse unchanged items, but endpoint "
            "I/O contention can cancel the benefit: two listings at once may "
            "be no faster than one, and every compare pays the extra work. "
            "It also keeps roughly a million extra entries in memory."
        )
        advanced_layout.addWidget(self.inventory_preload_checkbox)
        self.python_view_checkbox = QCheckBox(
            "Use legacy Python comparison views", advanced
        )
        self.python_view_checkbox.setChecked(bool(python_view))
        self.python_view_checkbox.setToolTip(
            "Off by default: the native Qt comparison views are used. Enable "
            "this to switch to the original Python view for compatibility or "
            "when the native extension is unavailable. Both views share the "
            "same decisions, plan and validation in Python. The setting "
            "applies immediately; switching back rebuilds the Python view."
        )
        advanced_layout.addWidget(self.python_view_checkbox)
        advanced_layout.addSpacing(24)
        advanced_hint = QLabel(
            "Verification checks are diagnostics, not gates: the "
            "synchronization confirmation dialog remains the final review "
            "before writing, and the optional rsync check needs Verify "
            "Decisions. Native Qt comparison views are the default; the "
            "legacy Python view remains available for compatibility, with "
            "decisions, plan and validation in Python in both modes."
        )
        advanced_hint.setWordWrap(True)
        advanced_layout.addWidget(advanced_hint)
        self.verification_checkbox.toggled.connect(
            self._verification_toggle_changed
        )
        self.verification_rsync_checkbox.toggled.connect(
            self._rsync_toggle_changed
        )
        self._rsync_toggle_changed(self.verification_rsync_checkbox.isChecked())
        advanced_layout.addStretch(1)

        self.tabs.addTab(general, "General")
        self.tabs.addTab(log_panel, "Logging")
        self.tabs.addTab(self.tools_panel, "Tools")
        self.tabs.addTab(advanced, "Advanced")
        self._verification_checkbox = self.verification_checkbox
        self._verification_rsync_checkbox = self.verification_rsync_checkbox

        button_row = QHBoxLayout()
        defaults_button = QPushButton("Defaults", self)
        defaults_button.clicked.connect(self._reset_defaults)
        button_row.addWidget(defaults_button)
        button_row.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

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

    def _verification_toggle_changed(self, _checked: bool) -> None:
        self.verification_rsync_checkbox.setEnabled(
            self.verification_checkbox.isChecked()
        )

    def _rsync_toggle_changed(self, checked: bool) -> None:
        if checked and not self.verification_checkbox.isChecked():
            self.verification_checkbox.setChecked(True)
        self.verification_rsync_checkbox.setEnabled(
            self.verification_checkbox.isChecked()
        )

    def verification_enabled(self) -> bool:
        return self.verification_checkbox.isChecked()

    def rsync_output_logging(self) -> bool:
        return self.rsync_output_checkbox.isChecked()

    def metadata_two_pass(self) -> bool:
        return self.metadata_two_pass_checkbox.isChecked()

    def inventory_preload(self) -> bool:
        return self.inventory_preload_checkbox.isChecked()

    def python_view(self) -> bool:
        return self.python_view_checkbox.isChecked()

    def detect_inherited_conflicts(self) -> bool:
        return self.inherited_checkbox.isChecked()

    def verification_rsync(self) -> bool:
        return (
            self.verification_enabled()
            and self.verification_rsync_checkbox.isChecked()
        )

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

    def _reset_defaults(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "Restore defaults",
            "Reset all settings to their default values?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.sound_checkbox.setChecked(True)
        self.set_action_colours(None)

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

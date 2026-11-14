"""The settings page for the external tools.

The page lists the tools the user can run on an item of the comparison and
holds the command of the diff tool.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.services.external_tools import (
    PLACEHOLDER_HELP,
    ExternalTool,
    ExternalToolError,
    unknown_placeholders,
)

COLUMNS = ("Name", "Command", "Options", "Enabled")


class ExternalToolDialog(QDialog):
    """Edit one external tool."""

    def __init__(
        self,
        parent: QWidget | None = None,
        tool: ExternalTool | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("External tool")
        self.resize(560, 460)

        layout = QVBoxLayout(self)
        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("Kate")
        self.command_edit = QLineEdit(self)
        self.command_edit.setPlaceholderText("kate %d/%f")
        self.options_edit = QLineEdit(self)
        self.options_edit.setPlaceholderText("options for the tool")

        form = QVBoxLayout()
        for label, edit in (
            ("Name", self.name_edit),
            ("Command", self.command_edit),
            ("Options", self.options_edit),
        ):
            caption = QLabel(label, self)
            form.addWidget(caption)
            form.addWidget(edit)
        layout.addLayout(form)

        self.enabled_box = QCheckBox("Offer the tool in the context menu", self)
        self.enabled_box.setChecked(True)
        layout.addWidget(self.enabled_box)

        self.warning = QLabel(self)
        self.warning.setWordWrap(True)
        self.warning.setVisible(False)
        layout.addWidget(self.warning)

        help_box = QGroupBox("Placeholders", self)
        help_layout = QVBoxLayout(help_box)
        help_text = "\n".join(
            f"{name}   {text}" for name, text in PLACEHOLDER_HELP
        )
        help_label = QLabel(help_text, help_box)
        help_label.setTextFormat(Qt.TextFormat.PlainText)
        help_label.setWordWrap(True)
        help_layout.addWidget(help_label)
        layout.addWidget(help_box, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if tool is not None:
            self.name_edit.setText(tool.name)
            self.command_edit.setText(tool.command)
            self.options_edit.setText(tool.options)
            self.enabled_box.setChecked(tool.enabled)
        self.command_edit.textChanged.connect(self._check_command)

    def _check_command(self) -> None:
        """Warn about a placeholder that the tool does not know."""
        command = self.command_edit.text()
        unknown = unknown_placeholders(command)
        if unknown:
            self.warning.setText(
                "Unknown placeholder(s): " + ", ".join(sorted(unknown))
            )
            self.warning.setVisible(True)
        else:
            self.warning.setVisible(False)

    def tool(self) -> ExternalTool:
        """The tool the dialog describes."""
        name = self.name_edit.text().strip()
        command = self.command_edit.text().strip()
        if not name or not command:
            raise ExternalToolError("A tool needs a name and a command.")
        return ExternalTool(
            name=name,
            command=command,
            options=self.options_edit.text().strip(),
            enabled=self.enabled_box.isChecked(),
        )


class ToolsPanel(QWidget):
    """The list of the external tools and the diff tool command."""

    def __init__(
        self,
        parent: QWidget | None = None,
        tools: list[ExternalTool] | None = None,
        diff_command: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tools-panel")
        layout = QVBoxLayout(self)

        caption = QLabel("Tools that the context menu offers on an item:", self)
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add...", self)
        self.edit_button = QPushButton("Edit...", self)
        self.remove_button = QPushButton("Remove", self)
        for button in (self.add_button, self.edit_button, self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        diff_caption = QLabel("Diff tool command (empty uses the found tool):", self)
        diff_caption.setWordWrap(True)
        layout.addWidget(diff_caption)
        self.diff_edit = QLineEdit(self)
        self.diff_edit.setPlaceholderText("meld %a %A")
        self.diff_edit.setText(diff_command)
        layout.addWidget(self.diff_edit)

        self.add_button.clicked.connect(self._add_tool)
        self.edit_button.clicked.connect(self._edit_tool)
        self.remove_button.clicked.connect(self._remove_tools)

        self.set_tools(tools or [])

    def tools(self) -> list[ExternalTool]:
        """The tools the table describes."""
        tools: list[ExternalTool] = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0)
            command = self.table.item(row, 1)
            if name is None or command is None:
                continue
            options = self.table.item(row, 2)
            enabled = self.table.item(row, 3)
            tools.append(
                ExternalTool(
                    name=name.text().strip(),
                    command=command.text().strip(),
                    options=options.text().strip() if options else "",
                    enabled=bool(enabled and enabled.checkState().value)
                    if enabled
                    else True,
                )
            )
        return tools

    def set_tools(self, tools: list[ExternalTool]) -> None:
        """Show the given tools in the table."""
        self.table.setRowCount(0)
        for tool in tools:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(tool.name))
            self.table.setItem(row, 1, QTableWidgetItem(tool.command))
            self.table.setItem(row, 2, QTableWidgetItem(tool.options))
            enabled = QTableWidgetItem("")
            enabled.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            enabled.setCheckState(
                Qt.CheckState.Checked if tool.enabled else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, 3, enabled)

    def diff_command(self) -> str:
        """The diff tool command the user wrote."""
        return self.diff_edit.text().strip()

    def set_diff_command(self, command: str) -> None:
        self.diff_edit.setText(command)

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return -1
        return rows[0].row()

    def _add_tool(self) -> None:
        dialog = ExternalToolDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            tool = dialog.tool()
        except ExternalToolError:
            return
        self.set_tools([*self.tools(), tool])

    def _edit_tool(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        tools = self.tools()
        if row >= len(tools):
            return
        dialog = ExternalToolDialog(self, tools[row])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            tool = dialog.tool()
        except ExternalToolError:
            return
        tools[row] = tool
        self.set_tools(tools)

    def _remove_tools(self) -> None:
        rows = sorted(
            {index.row() for index in self.table.selectionModel().selectedRows()},
            reverse=True,
        )
        tools = self.tools()
        for row in rows:
            if 0 <= row < len(tools):
                del tools[row]
        self.set_tools(tools)

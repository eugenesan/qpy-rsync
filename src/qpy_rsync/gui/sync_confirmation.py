from __future__ import annotations

import shlex
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.backend.decision_filters import decision_filter_lines
from qpy_rsync.backend.rsync_command import build_sync_argv
from qpy_rsync.core.backup_paths import backup_summary
from qpy_rsync.core.changes import ChangeAction
from qpy_rsync.core.units import format_size
from qpy_rsync.core.execution_plan import ExecutionPlan
from qpy_rsync.core.models import SyncProfile


@dataclass(slots=True, frozen=True)
class ConfirmationSummary:
    source: str
    destination: str
    included: int
    excluded: int
    retained_destination_only: int
    destructive: int
    creates: int
    updates: int
    metadata: int
    replacements: int
    deletions: int
    total_size: int
    backup: str
    nested_protection: str
    fingerprint: str


def confirmation_summary(profile: SyncProfile, plan: ExecutionPlan) -> ConfirmationSummary:
    backup = backup_summary(profile)
    backup_text = backup.directory if backup.enabled and backup.directory else "Disabled"
    if not backup.enabled:
        protection = "Not required"
    elif backup.protects_nested_tree:
        protection = "Enabled"
    elif backup.nested_in_source or backup.nested_in_destination:
        protection = "DISABLED for nested backup directory"
    else:
        protection = "Not required"
    summary = plan.summary
    return ConfirmationSummary(
        source=plan.source_operand,
        destination=plan.destination_operand,
        included=summary.included,
        excluded=summary.excluded,
        retained_destination_only=summary.retained_destination_only,
        destructive=summary.destructive,
        creates=summary.creates,
        updates=summary.updates,
        metadata=summary.metadata,
        replacements=summary.replacements,
        deletions=summary.deletions,
        total_size=summary.total_size,
        backup=backup_text,
        nested_protection=protection,
        fingerprint=plan.profile_fingerprint[:12],
    )


class _StaticTableWidget(QTableWidget):
    """A summary table that never scrolls away from its content."""

    def wheelEvent(self, event) -> None:  # noqa: N802
        # The table is sized to its rows. Ignore the wheel so hovering over
        # it cannot shift the text by a few pixels.
        event.ignore()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        # Even a programmatic scroll must not move the summary contents.
        return None


class SyncConfirmationDialog(QDialog):
    """Final review required before write-capable synchronization."""

    def __init__(
        self,
        profile: SyncProfile,
        plan: ExecutionPlan,
        parent=None,
        *,
        filter_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm synchronization")
        self.resize(720, 700)
        summary = confirmation_summary(profile, plan)

        layout = QVBoxLayout(self)
        self.heading = QLabel(
            "Review verified synchronization "
            f"(fingerprint: {summary.fingerprint})"
        )
        self.heading.setObjectName("confirmation-heading")
        self.heading.setWordWrap(True)
        self.heading.setStyleSheet("font-weight: bold; font-size: 115%;")
        layout.addWidget(self.heading)

        endpoints = QGridLayout()
        endpoints.setHorizontalSpacing(12)
        endpoints.setVerticalSpacing(4)
        endpoints.setColumnStretch(1, 1)
        endpoint_rows = (
            ("Source", summary.source),
            ("Destination", summary.destination),
        )
        for row, (title, value) in enumerate(endpoint_rows):
            name = QLabel(title)
            name.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            path = QLabel(value)
            path.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            path.setWordWrap(True)
            endpoints.addWidget(name, row, 0)
            endpoints.addWidget(path, row, 1)
        layout.addLayout(endpoints)

        stats = [
            ("Included", str(summary.included)),
            ("Total size", format_size(summary.total_size)),
            ("Unchecked", str(summary.excluded)),
            ("Retained in Destination", str(summary.retained_destination_only)),
            ("Destructive", str(summary.destructive)),
            ("Create", str(summary.creates)),
            ("Update", str(summary.updates)),
            ("Metadata", str(summary.metadata)),
            ("Replace", str(summary.replacements)),
            ("Delete", str(summary.deletions)),
            ("Backup", summary.backup),
            ("Nested protection", summary.nested_protection),
        ]
        half = (len(stats) + 1) // 2
        left, right = stats[:half], stats[half:]
        self.stats = _StaticTableWidget(max(len(left), len(right)), 4)
        self.stats.setObjectName("confirmation-stats")
        self.stats.horizontalHeader().hide()
        self.stats.verticalHeader().hide()
        self.stats.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stats.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.stats.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stats.setWordWrap(True)
        for row, pairs in enumerate(zip(left, right)):
            for pair_index, (label, value) in enumerate(pairs):
                self.stats.setItem(row, pair_index * 2, QTableWidgetItem(label))
                self.stats.setItem(row, pair_index * 2 + 1, QTableWidgetItem(value))
        header = self.stats.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.stats.resizeRowsToContents()
        self.stats.setFixedHeight(
            self.stats.verticalHeader().length()
            + 2 * self.stats.frameWidth()
            + 2
        )
        self.stats.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stats.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.stats)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        if summary.destructive:
            self.warning.setText(
                f"Warning: {summary.destructive} destructive item(s) will replace or delete destination items."
            )
            self.warning.setStyleSheet("color: #B91C1C; font-weight: bold;")
        else:
            self.warning.setText("No destructive operations are selected.")
            self.warning.setStyleSheet("color: #15803D;")
        layout.addWidget(self.warning)

        effective = deepcopy(profile)
        effective.transfer.delete = any(
            item.included and item.action is ChangeAction.DELETE
            for item in plan.items
        )
        try:
            command = shlex.join(
                build_sync_argv(
                    effective,
                    filter_file=filter_path
                    or Path("<temporary decision filter>"),
                )
            )
        except ValueError as exc:
            command = f"Command unavailable: {exc}"
        command_panel = QWidget(self)
        command_layout = QVBoxLayout(command_panel)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(2)
        command_label = QLabel("rsync command")
        command_label.setStyleSheet("font-weight: bold;")
        command_layout.addWidget(command_label)
        self.command = QPlainTextEdit()
        self.command.setObjectName("confirmation-command")
        self.command.setReadOnly(True)
        self.command.setPlainText(command)
        self.command.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self.command.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.command.setWordWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self.command.setMinimumHeight(82)
        self.command.setToolTip(
            "The full rsync command for this synchronization. The temporary "
            "decision filter is created for this confirmation and removed "
            "after the synchronization."
        )
        command_layout.addWidget(self.command, 1)

        rules_panel = QWidget(self)
        rules_layout = QVBoxLayout(rules_panel)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        rules_layout.setSpacing(2)
        rules_label = QLabel("Decision rules")
        rules_label.setStyleSheet("font-weight: bold;")
        rules_layout.addWidget(rules_label)
        self.rules = QPlainTextEdit()
        self.rules.setObjectName("confirmation-rules")
        self.rules.setReadOnly(True)
        rule_lines = decision_filter_lines(plan)
        self.rules.setPlainText("\n".join(rule_lines))
        self.rules.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self.rules.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.rules.setWordWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self.rules.setMinimumHeight(82)
        self.rules.setToolTip(
            "The temporary rsync filter rules that implement the selected "
            "decisions for this synchronization."
        )
        rules_layout.addWidget(self.rules, 1)

        self.preview_splitter = QSplitter(Qt.Orientation.Vertical)
        self.preview_splitter.setChildrenCollapsible(False)
        self.preview_splitter.setHandleWidth(6)
        self.preview_splitter.addWidget(command_panel)
        self.preview_splitter.addWidget(rules_panel)
        self.preview_splitter.setStretchFactor(0, 1)
        self.preview_splitter.setStretchFactor(1, 1)
        self.preview_splitter.setSizes([220, 220])
        layout.addWidget(self.preview_splitter, 1)

        self.details = QLabel(
            "This confirmation is based on a verified second dry run. "
            "Confirming will launch write-capable rsync for the reviewed "
            "Source and Destination. The private decision filter is created "
            "for this confirmation and removed after execution."
        )
        self.details.setObjectName("confirmation-details")
        self.details.setWordWrap(True)
        details_font = self.details.font()
        details_font.setBold(True)
        self.details.setFont(details_font)
        layout.addWidget(self.details)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.confirm_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText("Synchronize Now")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

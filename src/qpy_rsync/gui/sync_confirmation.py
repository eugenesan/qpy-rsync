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
    QFormLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

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


class SyncConfirmationDialog(QDialog):
    """Final review required before write-capable synchronization."""

    def __init__(self, profile: SyncProfile, plan: ExecutionPlan, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm synchronization")
        self.resize(720, 620)
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

        form = QFormLayout()
        form.addRow("Source", QLabel(summary.source))
        form.addRow("Destination", QLabel(summary.destination))
        layout.addLayout(form)

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
        self.stats = QTableWidget(max(len(left), len(right)), 4)
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
            sum(self.stats.rowHeight(row) for row in range(self.stats.rowCount()))
            + 2 * self.stats.frameWidth()
        )
        self.stats.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
                    filter_file=Path("<temporary decision filter>"),
                )
            )
        except ValueError as exc:
            command = f"Command unavailable: {exc}"
        command_label = QLabel("rsync command")
        command_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(command_label)
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
        self.command.setFixedHeight(92)
        self.command.setToolTip(
            "The full rsync command for this synchronization. The temporary "
            "decision filter is created when the synchronization starts."
        )
        layout.addWidget(self.command)

        self.details = QLabel(
            "This confirmation is based on a verified second dry run. "
            "Confirming will launch write-capable rsync for the reviewed "
            "Source and Destination. The private decision filter is recreated "
            "and removed after execution."
        )
        self.details.setObjectName("confirmation-details")
        self.details.setWordWrap(True)
        details_font = self.details.font()
        details_font.setBold(True)
        self.details.setFont(details_font)
        layout.addWidget(self.details)
        layout.addStretch(1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.confirm_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText("Synchronize Now")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

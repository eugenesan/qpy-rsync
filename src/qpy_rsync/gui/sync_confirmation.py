from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from qpy_rsync.core.backup_paths import backup_summary
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
        self.resize(620, 520)
        summary = confirmation_summary(profile, plan)

        layout = QVBoxLayout(self)
        heading = QLabel("Review verified synchronization")
        heading.setStyleSheet("font-weight: bold; font-size: 115%;")
        layout.addWidget(heading)

        form = QFormLayout()
        form.addRow("Source", QLabel(summary.source))
        form.addRow("Destination", QLabel(summary.destination))
        form.addRow("Included", QLabel(str(summary.included)))
        form.addRow("Total size", QLabel(format_size(summary.total_size)))
        form.addRow("Unchecked", QLabel(str(summary.excluded)))
        form.addRow("Retained in Destination", QLabel(str(summary.retained_destination_only)))
        form.addRow("Destructive", QLabel(str(summary.destructive)))
        form.addRow("Create", QLabel(str(summary.creates)))
        form.addRow("Update", QLabel(str(summary.updates)))
        form.addRow("Metadata", QLabel(str(summary.metadata)))
        form.addRow("Replace", QLabel(str(summary.replacements)))
        form.addRow("Delete", QLabel(str(summary.deletions)))
        form.addRow("Backup", QLabel(summary.backup))
        form.addRow("Nested protection", QLabel(summary.nested_protection))
        form.addRow("Verification fingerprint", QLabel(summary.fingerprint))
        layout.addLayout(form)

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

        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(
            "This confirmation is based on a verified second dry run.\n"
            "Confirming will launch write-capable rsync for the reviewed "
            "Source and Destination.\n"
            "The private decision filter is recreated and removed after execution."
        )
        details.setMaximumHeight(90)
        layout.addWidget(details)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.confirm_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText("Synchronize Now")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

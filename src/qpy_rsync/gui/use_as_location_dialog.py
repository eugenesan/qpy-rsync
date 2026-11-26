"""Dialog for narrowing the comparison to a folder on both endpoints.

The dialog only reports the user's choice; applying the new locations and
marking the comparison stale belongs to the caller (see ``MainWindow``).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class UseAsLocationDialog(QDialog):
    """Offer to use a comparison folder as both Source and Destination."""

    def __init__(
        self,
        relative_path: str,
        source_root: str,
        destination_root: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Use folder as Source or Destination")
        self.resize(560, 260)

        layout = QVBoxLayout(self)
        heading = QLabel(f'Narrow the comparison to "{relative_path}"?', self)
        heading.setObjectName("use-as-location-heading")
        heading.setStyleSheet("font-weight: bold;")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        def joined(root: str) -> str:
            base = root.strip()
            while base.endswith("/"):
                base = base[:-1]
            return f"{base}/{relative_path}/"

        details = QFormLayout()
        self.source_label = QLabel(joined(source_root), self)
        self.destination_label = QLabel(joined(destination_root), self)
        details.addRow("New Source", self.source_label)
        details.addRow("New Destination", self.destination_label)
        layout.addLayout(details)

        self.update_filters_checkbox = QCheckBox(
            "Update paths in the permanent filter rules", self
        )
        self.update_filters_checkbox.setChecked(True)
        self.update_filters_checkbox.setToolTip(
            "Remove the eliminated directory prefix from filters "
            "that name paths inside it."
        )
        layout.addWidget(self.update_filters_checkbox)

        note = QLabel(
            "The current comparison will become stale: run Compare "
            "again before synchronizing. The changed locations and "
            "filters are not saved automatically — use Save or Save "
            "As afterwards to persist the profile.",
            self,
        )
        note.setObjectName("use-as-location-note")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(self)
        self.both_button: QPushButton = buttons.addButton(
            "Use as Both", QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        self.both_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def update_filters(self) -> bool:
        """Whether permanent filter rules should have the prefix removed."""
        return bool(self.update_filters_checkbox.isChecked())

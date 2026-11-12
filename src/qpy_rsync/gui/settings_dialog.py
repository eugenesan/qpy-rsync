from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

EXPAND_MODES: tuple[tuple[str, str], ...] = (
    ("all", "Expand every folder"),
    ("first", "Expand the first level only"),
    ("none", "Keep every folder collapsed"),
)


class SettingsDialog(QDialog):
    """Application preferences that are not part of a sync profile."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        expand_mode: str = "all",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(460, 200)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.expand_combo = QComboBox()
        for value, label in EXPAND_MODES:
            self.expand_combo.addItem(label, value)
        index = self.expand_combo.findData(expand_mode)
        self.expand_combo.setCurrentIndex(max(0, index))
        self.expand_combo.setToolTip(
            "How the comparison opens its folders after a comparison.\n"
            "Folders that stay collapsed still show that they contain changes."
        )
        form.addRow("After a comparison", self.expand_combo)

        hint = QLabel(
            "Collapsed folders keep a marker in the Actions column when they "
            "contain changed items, and their tooltip reports the count."
        )
        hint.setWordWrap(True)
        form.addRow("", hint)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def expand_mode(self) -> str:
        return str(self.expand_combo.currentData())

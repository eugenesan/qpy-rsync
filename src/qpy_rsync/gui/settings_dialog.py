from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
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
        expand_limit: int = 256,
        expand_total_limit: int = 10000,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(480, 250)

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

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 1_000_000)
        self.limit_spin.setValue(max(1, int(expand_limit)))
        self.limit_spin.setSuffix(" items")
        self.limit_spin.setToolTip(
            "A folder with more direct items than this stays collapsed after "
            "a comparison. The tree marks every such folder, and you can open "
            "it manually."
        )
        form.addRow("Auto-expand folders up to", self.limit_spin)

        self.total_limit_spin = QSpinBox()
        self.total_limit_spin.setRange(1, 10_000_000)
        self.total_limit_spin.setSingleStep(1000)
        self.total_limit_spin.setValue(max(1, int(expand_total_limit)))
        self.total_limit_spin.setSuffix(" items")
        self.total_limit_spin.setToolTip(
            "A comparison with more items than this stays collapsed after a "
            "comparison, even when each folder is below the per-folder limit. "
            "You are offered a choice before a large inventory is added."
        )
        form.addRow("Auto-expand comparison up to", self.total_limit_spin)

        hint = QLabel(
            "Folders left collapsed by the limit carry an amber marker; their "
            "tooltip explains why. Collapsed folders with changes keep a "
            "marker in the Actions column as well."
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

    def expand_limit(self) -> int:
        return int(self.limit_spin.value())

    def expand_total_limit(self) -> int:
        return int(self.total_limit_spin.value())

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

LIST_LAYOUTS: tuple[tuple[str, str], ...] = (
    ("tree", "Tree with expandable folders"),
    ("flat", "Flat list (FreeFileSync style)"),
)


class SettingsDialog(QDialog):
    """Application preferences that are not part of a sync profile."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        expand_mode: str = "all",
        expand_total_limit: int = 10000,
        list_layout: str = "tree",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(480, 250)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.layout_combo = QComboBox()
        for value, label in LIST_LAYOUTS:
            self.layout_combo.addItem(label, value)
        layout_index = self.layout_combo.findData(list_layout)
        self.layout_combo.setCurrentIndex(max(0, layout_index))
        self.layout_combo.setToolTip(
            "How the comparison is listed.\n"
            "The flat list has no folders to expand, so a comparison with "
            "tens of thousands of items stays responsive."
        )
        form.addRow("Comparison list", self.layout_combo)

        self.expansion_hint = QLabel(
            "The flat list shows every item at once, so the expansion "
            "settings below do not apply to it."
        )
        self.expansion_hint.setWordWrap(True)
        form.addRow("", self.expansion_hint)

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

        self.total_limit_spin = QSpinBox()
        self.total_limit_spin.setRange(1, 10_000_000)
        self.total_limit_spin.setSingleStep(1000)
        self.total_limit_spin.setValue(max(1, int(expand_total_limit)))
        self.total_limit_spin.setSuffix(" items")
        self.total_limit_spin.setToolTip(
            "A tree with more items than this stays collapsed after a "
            "comparison and marks the top-level folders. The flat list shows "
            "everything anyway, so the limit only applies to the tree."
        )
        self.total_limit_label = QLabel("Auto-expand comparison up to")
        form.addRow(self.total_limit_label, self.total_limit_spin)

        self.expansion_hint_2 = QLabel(
            "Folders left collapsed by the limit carry an amber marker; their "
            "tooltip explains why. Collapsed folders with changes keep a "
            "marker in the Actions column as well."
        )
        self.expansion_hint_2.setWordWrap(True)
        form.addRow("", self.expansion_hint_2)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._expansion_widgets = (
            self.expand_combo,
            self.total_limit_spin,
            self.expansion_hint_2,
        )
        self.layout_combo.currentIndexChanged.connect(self._layout_changed)
        self._layout_changed()

    def _layout_changed(self) -> None:
        """The expansion settings only apply to the tree."""
        tree = self.list_layout() == "tree"
        for widget in self._expansion_widgets:
            widget.setEnabled(tree)
        self.expansion_hint.setVisible(not tree)
        self.total_limit_label.setEnabled(tree)

    def expand_mode(self) -> str:
        return str(self.expand_combo.currentData())

    def list_layout(self) -> str:
        return str(self.layout_combo.currentData())

    def expand_total_limit(self) -> int:
        return int(self.total_limit_spin.value())

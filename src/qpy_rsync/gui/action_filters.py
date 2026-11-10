from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QSizePolicy, QWidget

from qpy_rsync.core.changes import ChangeAction

from .icons import ACTION_LABELS, action_icon

FILTERABLE_ACTIONS: tuple[ChangeAction, ...] = (
    ChangeAction.CREATE,
    ChangeAction.UPDATE_CONTENT,
    ChangeAction.UPDATE_METADATA,
    ChangeAction.REPLACE,
    ChangeAction.DELETE,
    ChangeAction.DESTINATION_ONLY,
)


class ActionFilterBar(QWidget):
    """Display-only checkboxes that hide or show individual action types."""

    changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._boxes: dict[ChangeAction, QCheckBox] = {}
        for action in FILTERABLE_ACTIONS:
            box = QCheckBox(self)
            box.setIcon(action_icon(action))
            box.setToolTip(self._tooltip(action))
            box.setAccessibleName(f"Show {ACTION_LABELS.get(action, action.value)} objects")
            box.setChecked(True)
            box.toggled.connect(lambda _checked: self._emit_change())
            layout.addWidget(box)
            self._boxes[action] = box

    @staticmethod
    def _tooltip(action: ChangeAction) -> str:
        label = ACTION_LABELS.get(action, action.value)
        return (
            f"Display only: {label}\n"
            "This checkbox filters the comparison view only. "
            "It does not change what rsync transfers or deletes. "
            "Use the mode selection to control synchronization behavior."
        )

    def visible_actions(self) -> set[ChangeAction]:
        return {action for action, box in self._boxes.items() if box.isChecked()}

    def is_all_enabled(self) -> bool:
        return all(box.isChecked() for box in self._boxes.values())

    def _emit_change(self) -> None:
        self.changed.emit(self.visible_actions())

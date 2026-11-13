from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QMenu,
    QSizePolicy,
    QWidget,
)

from qpy_rsync.core.changes import ChangeAction

from .controls import CONTROL_ICON_SIZE, CONTROL_SIZE
from .icons import ACTION_LABELS, action_icon, hidden_icon, unchanged_icon

FILTERABLE_ACTIONS: tuple[ChangeAction, ...] = (
    ChangeAction.CREATE,
    ChangeAction.UPDATE_CONTENT,
    ChangeAction.UPDATE_METADATA,
    ChangeAction.REPLACE,
    ChangeAction.DELETE,
    ChangeAction.DESTINATION_ONLY,
)


class ActionFilterBar(QWidget):
    """Checkboxes that hide or show items, and the hidden items toggle."""

    changed = Signal(object)
    hidden_toggled = Signal(bool)
    unchanged_toggled = Signal(bool)
    unhide_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._hidden_count = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._boxes: dict[ChangeAction, QCheckBox] = {}
        for action in FILTERABLE_ACTIONS:
            box = QCheckBox(self)
            box.setIcon(action_icon(action))
            # The checkbox indicator and the glyph fit into a compact square.
            box.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
            box.setFixedSize(CONTROL_ICON_SIZE + 20, CONTROL_SIZE)
            box.setToolTip(self._tooltip(action))
            box.setAccessibleName(f"Show {ACTION_LABELS.get(action, action.value)} items")
            box.setChecked(True)
            box.toggled.connect(lambda _checked: self._emit_change())
            layout.addWidget(box)
            self._boxes[action] = box

        # The unchanged items and the hidden items are toggles rather than
        # display filters, so they sit together at the end of the bar.
        self.unchanged_box = QCheckBox(self)
        self.unchanged_box.setIcon(unchanged_icon())
        self.unchanged_box.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.unchanged_box.setFixedSize(CONTROL_ICON_SIZE + 20, CONTROL_SIZE)
        self.unchanged_box.setToolTip(
            "Show the unchanged items of the comparison.\n"
            "The inventory lists both sides, so the unchanged items can be "
            "shown next to the changed ones."
        )
        self.unchanged_box.setAccessibleName("Show unchanged items")
        self.unchanged_box.toggled.connect(self.unchanged_toggled.emit)
        layout.addWidget(self.unchanged_box)

        # The hidden items are the ones the user put aside. They affect the
        # sync, so this is not just a display filter: it shows what is
        # already excluded from the sync, the way the unchanged toggle shows
        # what the comparison kept.
        self.hidden_box = QCheckBox(self)
        self.hidden_box.setIcon(hidden_icon())
        self.hidden_box.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.hidden_box.setFixedSize(CONTROL_ICON_SIZE + 20, CONTROL_SIZE)
        self.hidden_box.setToolTip(self._hidden_tooltip(0))
        self.hidden_box.setAccessibleName("Show hidden items")
        self.hidden_box.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.hidden_box.customContextMenuRequested.connect(
            self._show_hidden_menu
        )
        self.hidden_box.toggled.connect(self.hidden_toggled.emit)
        layout.addWidget(self.hidden_box)

    @staticmethod
    def _tooltip(action: ChangeAction) -> str:
        label = ACTION_LABELS.get(action, action.value)
        return (
            f"Display only: {label}\n"
            "This checkbox filters the view and doesn't affect the sync. "
            "Use the sync mode selector or the action checkboxes below to "
            "control the sync."
        )

    def visible_actions(self) -> set[ChangeAction]:
        return {action for action, box in self._boxes.items() if box.isChecked()}

    def is_all_enabled(self) -> bool:
        return all(box.isChecked() for box in self._boxes.values())

    def show_hidden(self) -> bool:
        return self.hidden_box.isChecked()

    @staticmethod
    def _hidden_tooltip(count: int) -> str:
        head = (
            f"{count} hidden item(s)."
            if count
            else "Show the items that were hidden from the comparison."
        )
        return (
            f"{head}\n"
            "A hidden item is not part of the sync. The list is kept in "
            "memory only, so it is gone after the next comparison.\n"
            "Right-click to unhide all hidden items."
        )

    def set_hidden_count(self, count: int) -> None:
        """Report how many items are hidden next to the toggle."""
        self._hidden_count = count
        self.hidden_box.setText(str(count) if count else "")
        self.hidden_box.setVisible(True)
        self.hidden_box.setToolTip(self._hidden_tooltip(count))

    def _show_hidden_menu(self, point: object) -> None:
        """Offer to put every hidden item back from the toggle."""
        menu = QMenu(self)
        unhide = menu.addAction(
            f"Unhide All ({self._hidden_count})"
            if self._hidden_count
            else "Unhide All"
        )
        unhide.setEnabled(self._hidden_count > 0)
        selected = menu.exec(
            self.hidden_box.mapToGlobal(point)  # type: ignore[arg-type]
        )
        if selected is unhide and self._hidden_count:
            self.unhide_all_requested.emit()

    def _emit_change(self) -> None:
        self.changed.emit(self.visible_actions())

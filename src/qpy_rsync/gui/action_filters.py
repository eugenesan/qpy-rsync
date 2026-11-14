from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QMenu,
    QSizePolicy,
    QWidget,
)

from qpy_rsync.core.changes import ChangeAction

from .controls import CONTROL_ICON_SIZE, CONTROL_SIZE
from .icons import ACTION_LABELS, action_icon, stashed_icon, unchanged_icon

def _separator() -> QFrame:
    """A thin line that groups the checkboxes of the bar."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedWidth(1)
    line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    return line


FILTERABLE_ACTIONS: tuple[ChangeAction, ...] = (
    ChangeAction.CREATE,
    ChangeAction.UPDATE_CONTENT,
    ChangeAction.UPDATE_METADATA,
    ChangeAction.REPLACE,
    ChangeAction.DELETE,
    ChangeAction.DESTINATION_ONLY,
)


class ActionFilterBar(QWidget):
    """Checkboxes that filter the view, and the stashed items toggle."""

    changed = Signal(object)
    stashed_toggled = Signal(bool)
    unchanged_toggled = Signal(bool)
    restore_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._stashed_count = 0
        # The checkbox whose inverted click is being handled.
        self._inverse_click: QCheckBox | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._boxes: dict[ChangeAction, QCheckBox] = {}
        for index, action in enumerate(FILTERABLE_ACTIONS):
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
            if index < len(FILTERABLE_ACTIONS) - 1:
                # A line between every pair of checkboxes, so it is clear
                # which indicator belongs to which glyph.
                layout.addWidget(_separator())

        # The unchanged items and the stashed items are toggles rather than
        # display filters, so they sit together at the end of the bar, behind
        # a separator that tells them apart from the action filters.
        layout.addWidget(_separator())
        self.unchanged_box = QCheckBox(self)
        self.unchanged_box.setIcon(unchanged_icon())
        self.unchanged_box.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.unchanged_box.setFixedSize(CONTROL_ICON_SIZE + 20, CONTROL_SIZE)
        self.unchanged_box.setToolTip(
            "Show the unchanged items of the comparison.\n"
            "The inventory lists both sides, so the unchanged items can be "
            "shown next to the changed ones.\n"
            "Ctrl+click shows only the unchanged items."
        )
        self.unchanged_box.setAccessibleName("Show unchanged items")
        self.unchanged_box.toggled.connect(self.unchanged_toggled.emit)
        layout.addWidget(self.unchanged_box)

        # The stashed items are the ones the user put aside. They affect the
        # sync, so this is not just a display filter: it shows what is
        # already excluded from the sync, the way the unchanged toggle shows
        # what the comparison kept.
        layout.addWidget(_separator())
        self.stashed_box = QCheckBox(self)
        self.stashed_box.setIcon(stashed_icon())
        self.stashed_box.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.stashed_box.setFixedSize(CONTROL_ICON_SIZE + 20, CONTROL_SIZE)
        self.stashed_box.setToolTip(self._stashed_tooltip(0))
        self.stashed_box.setAccessibleName("Show stashed items")
        self.stashed_box.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.stashed_box.customContextMenuRequested.connect(
            self._show_stashed_menu
        )
        self.stashed_box.toggled.connect(self.stashed_toggled.emit)
        layout.addWidget(self.stashed_box)

        # Breeze marks a focused icon-only checkbox with an underline. A
        # pointer click should not leave that marker behind, but Tab must
        # still reach the control, so focus follows the keyboard only.
        for box in self._all_boxes():
            box.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            # Ctrl+click inverts the filter of the bar, and the context menu
            # offers the same choice.
            box.installEventFilter(self)
            box.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            box.customContextMenuRequested.connect(
                lambda point, b=box: self._show_box_menu(b, point)
            )

    @staticmethod
    def _tooltip(action: ChangeAction) -> str:
        label = ACTION_LABELS.get(action, action.value)
        return (
            f"Display only: {label}\n"
            "This checkbox filters the view and doesn't affect the sync. "
            "Use the sync mode selector or the action checkboxes below to "
            "control the sync.\n"
            "Ctrl+click shows only this action, and only this action again."
        )

    def visible_actions(self) -> set[ChangeAction]:
        return {action for action, box in self._boxes.items() if box.isChecked()}

    def is_all_enabled(self) -> bool:
        return all(box.isChecked() for box in self._boxes.values())

    def show_stashed(self) -> bool:
        return self.stashed_box.isChecked()

    @staticmethod
    def _stashed_tooltip(count: int) -> str:
        head = (
            f"{count} stashed item(s)."
            if count
            else "Show the items that were stashed from the comparison."
        )
        return (
            f"{head}\n"
            "A stashed item is not part of the sync. The stash is kept in "
            "memory only, so it is gone after the next comparison.\n"
            "Right-click to restore all stashed items.\n"
            "Ctrl+click shows only the stashed items."
        )

    def set_stashed_count(self, count: int) -> None:
        """Report how many items are stashed next to the toggle."""
        self._stashed_count = count
        text = str(count) if count else ""
        self.stashed_box.setText(text)
        # The fixed size leaves room for the indicator and the glyph, so the
        # count needs its own width when there is one.
        extra = self.stashed_box.fontMetrics().horizontalAdvance(text) + 10 if text else 0
        self.stashed_box.setFixedWidth(CONTROL_ICON_SIZE + 20 + extra)
        self.stashed_box.setVisible(True)
        self.stashed_box.setToolTip(self._stashed_tooltip(count))

    def _show_stashed_menu(self, point: object) -> None:
        """Offer to restore every stashed item from the toggle."""
        menu = QMenu(self)
        restore = menu.addAction(
            f"Restore All Stashed ({self._stashed_count})"
            if self._stashed_count
            else "Restore All Stashed"
        )
        restore.setEnabled(self._stashed_count > 0)
        selected = menu.exec(
            self.stashed_box.mapToGlobal(point)  # type: ignore[arg-type]
        )
        if selected is restore and self._stashed_count:
            self.restore_all_requested.emit()

    def _emit_change(self) -> None:
        self.changed.emit(self.visible_actions())

    def _all_boxes(self) -> list[QCheckBox]:
        """Every checkbox of the bar."""
        return [*self._boxes.values(), self.unchanged_box, self.stashed_box]

    def eventFilter(self, watched: object, event: object) -> bool:  # noqa: N802
        """Handle the inverted click on a checkbox of the bar."""
        if isinstance(watched, QCheckBox) and watched in self._all_boxes():
            event_type = getattr(event, "type", lambda: None)()
            if event_type == QEvent.Type.MouseButtonPress:
                modifiers = getattr(event, "modifiers", lambda: Qt.KeyboardModifier.NoModifier)()
                if modifiers & Qt.KeyboardModifier.ControlModifier:
                    # The click is handled here, so the checkbox must not
                    # toggle itself.
                    self._inverse_click = watched
                    self._apply_inverse(watched)
                    return True
            elif event_type == QEvent.Type.MouseButtonRelease:
                if self._inverse_click is watched:
                    self._inverse_click = None
                    return True
        return super().eventFilter(watched, event)  # type: ignore[arg-type]

    def _apply_inverse(self, box: QCheckBox) -> None:
        """Show only the action of the box, or everything but it.

        A box that is the only checked one is inverted, so the second
        inverted click shows everything but that action.
        """
        boxes = self._all_boxes()
        others = [other for other in boxes if other is not box]
        solo = box.isChecked() and not any(
            other.isChecked() for other in others
        )
        if solo:
            wanted = {other: other is not box for other in boxes}
        else:
            wanted = {other: other is box for other in boxes}
        self._set_states(wanted)

    def _set_states(self, wanted: dict[QCheckBox, bool]) -> None:
        """Set the checkboxes and report the change once."""
        action_changed = False
        unchanged_changed = False
        stashed_changed = False
        for box, value in wanted.items():
            if box.isChecked() == value:
                continue
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)
            if box is self.unchanged_box:
                unchanged_changed = True
            elif box is self.stashed_box:
                stashed_changed = True
            else:
                action_changed = True
        if action_changed:
            self._emit_change()
        if unchanged_changed:
            self.unchanged_toggled.emit(self.unchanged_box.isChecked())
        if stashed_changed:
            self.stashed_toggled.emit(self.stashed_box.isChecked())

    def _show_box_menu(self, box: QCheckBox, point: object) -> None:
        """Offer the inverted choice for one checkbox."""
        menu = QMenu(self)
        only = menu.addAction("Show only this")
        others = menu.addAction("Show everything but this")
        every = menu.addAction("Show all")
        selected = menu.exec(box.mapToGlobal(point))  # type: ignore[arg-type]
        boxes = self._all_boxes()
        if selected is only:
            self._set_states({other: other is box for other in boxes})
        elif selected is others:
            self._set_states({other: other is not box for other in boxes})
        elif selected is every:
            self._set_states({other: True for other in boxes})

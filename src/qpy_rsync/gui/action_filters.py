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
from .icons import (
    ACTION_LABELS,
    action_icon,
    conflict_icon,
    folder_icon,
    excluded_icon,
    unchanged_icon,
)

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
    ChangeAction.DELETE,
    ChangeAction.DESTINATION_ONLY,
)


class ActionFilterBar(QWidget):
    """Checkboxes that filter the view, and the excluded items toggle."""

    changed = Signal(object)
    excluded_toggled = Signal(bool)
    unchanged_toggled = Signal(bool)
    conflicts_toggled = Signal(bool)
    reset_exclusions_requested = Signal()
    directory_filter_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._excluded_count = 0
        # The checkbox whose inverted click is being handled.
        self._inverse_click: QCheckBox | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        # The excluded items are the ones the user put aside. They affect the
        # sync, so this is not just a display filter: it shows what is
        # already excluded from the sync, the way the unchanged toggle shows
        # what the comparison kept.
        self.excluded_box = QCheckBox(self)
        self.excluded_box.setIcon(excluded_icon())
        self.excluded_box.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.excluded_box.setFixedSize(CONTROL_ICON_SIZE + 20, CONTROL_SIZE)
        self.excluded_box.setToolTip(
            self._excluded_tooltip(0)
            + "\nAlt+1 clicks this checkbox; Ctrl+1 inverts it."
        )
        self.excluded_box.setAccessibleName("Show excluded items")
        self.excluded_box.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.excluded_box.customContextMenuRequested.connect(
            self._show_excluded_menu
        )
        self.excluded_box.toggled.connect(self.excluded_toggled.emit)
        layout.addWidget(self.excluded_box)
        layout.addWidget(_separator())

        self.directory_filter_box = QCheckBox(self)
        self.directory_filter_box.setIcon(folder_icon())
        self.directory_filter_box.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.directory_filter_box.setFixedSize(CONTROL_ICON_SIZE + 20, CONTROL_SIZE)
        self.directory_filter_box.setToolTip(
            "Apply the action filters to reported directories too.\n"
            "A directory whose own action is filtered out stays as a faded "
            "parent when it holds visible items, and is not counted."
        )
        self.directory_filter_box.setAccessibleName("Apply filters to directories")
        self.directory_filter_box.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.directory_filter_box.toggled.connect(self.directory_filter_toggled.emit)
        layout.addWidget(self.directory_filter_box)
        layout.addWidget(_separator())

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

        # The unchanged items and the excluded items are toggles rather than
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
            "Ctrl+click shows only the unchanged items.\n"
            "Alt+8 clicks this checkbox; Ctrl+8 inverts it."
        )
        self.unchanged_box.setAccessibleName("Show unchanged items")
        self.unchanged_box.toggled.connect(self.unchanged_toggled.emit)
        layout.addWidget(self.unchanged_box)
        layout.addWidget(_separator())
        self.conflicts_box = QCheckBox(self)
        self.conflicts_box.setIcon(conflict_icon())
        self.conflicts_box.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.conflicts_box.setFixedSize(CONTROL_ICON_SIZE + 20, CONTROL_SIZE)
        self.conflicts_box.setAccessibleName("Review changed decisions")
        self.conflicts_box.setToolTip(
            "Show only the items whose decision no longer applies after a "
            "comparison — for example an item that became destination-only. "
            "Review them and choose the rsync default with the context menu."
        )
        self.conflicts_box.toggled.connect(self.conflicts_toggled.emit)
        layout.addWidget(self.conflicts_box)

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

    def toggle_shortcut(self, number: int, *, inverted: bool = False) -> None:
        """Emulate a click on the checkbox with the given number (1-8)."""
        boxes = self._numbered_boxes()
        if 1 <= number <= len(boxes):
            self.activate_box(boxes[number - 1], inverted=inverted)

    def activate_box(self, box: QCheckBox, *, inverted: bool = False) -> None:
        """Click a checkbox, with Ctrl held when ``inverted`` is set."""
        if inverted:
            self._apply_inverse(box)
        else:
            box.click()

    def _numbered_boxes(self) -> list[QCheckBox]:
        return [self.excluded_box, *self._boxes.values(), self.unchanged_box]

    def _tooltip(self, action: ChangeAction) -> str:
        label = ACTION_LABELS.get(action, action.value)
        number = list(FILTERABLE_ACTIONS).index(action) + 2
        return (
            f"Display only: {label}\n"
            "This checkbox filters the view and doesn't affect the sync. "
            "Use the sync mode selector or the action checkboxes below to "
            "control the sync.\n"
            f"Alt+{number} clicks this checkbox; Ctrl+{number} inverts it.\n"
            "Ctrl+click shows only this action, and a second inverted click "
            "brings every action back. Right-click opens the same choices."
        )

    def visible_actions(self) -> set[ChangeAction]:
        return {action for action, box in self._boxes.items() if box.isChecked()}

    def is_all_enabled(self) -> bool:
        return all(box.isChecked() for box in self._boxes.values())

    def show_excluded(self) -> bool:
        return self.excluded_box.isChecked()

    @staticmethod
    def _excluded_tooltip(count: int) -> str:
        head = (
            f"{count} excluded item(s)."
            if count
            else "Show the items excluded from this comparison."
        )
        return (
            f"{head}\n"
            "An excluded item is not part of the sync. Exclusions are kept "
            "in memory only, so they are gone after the next comparison.\n"
            "Right-click to reset all exclusions.\n"
            "Ctrl+click shows only the excluded items."
        )

    def set_excluded_count(self, count: int) -> None:
        """Report how many items are excluded next to the toggle."""
        self._excluded_count = count
        text = str(count) if count else ""
        self.excluded_box.setText(text)
        # The fixed size leaves room for the indicator and the glyph, so the
        # count needs its own width when there is one.
        extra = self.excluded_box.fontMetrics().horizontalAdvance(text) + 10 if text else 0
        self.excluded_box.setFixedWidth(CONTROL_ICON_SIZE + 20 + extra)
        self.excluded_box.setVisible(True)
        self.excluded_box.setToolTip(
            self._excluded_tooltip(count)
            + "\nAlt+1 clicks this checkbox; Ctrl+1 inverts it."
        )

    def _show_excluded_menu(self, point: object) -> None:
        """Offer to restore every excluded item from the toggle."""
        menu = QMenu(self)
        restore = menu.addAction(
            f"Reset All Exclusions ({self._excluded_count})"
            if self._excluded_count
            else "Reset All Exclusions"
        )
        restore.setEnabled(self._excluded_count > 0)
        selected = menu.exec(
            self.excluded_box.mapToGlobal(point)  # type: ignore[arg-type]
        )
        if selected is restore and self._excluded_count:
            self.reset_exclusions_requested.emit()

    def _emit_change(self) -> None:
        self.changed.emit(self.visible_actions())

    def refresh_icons(self) -> None:
        """Draw the action glyphs again after the colours changed."""
        for action, box in self._boxes.items():
            box.setIcon(action_icon(action))

    def _all_boxes(self) -> list[QCheckBox]:
        """Every checkbox of the bar."""
        return [*self._boxes.values(), self.unchanged_box, self.excluded_box]

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
        """Show only the kind of the box, or bring every action back.

        A box that is on becomes the only one that is shown. A box that is
        off, or one that is already the only one that is shown, reverses
        that: every action comes back and the unchanged and the excluded
        toggles keep their state.
        """
        boxes = self._all_boxes()
        if box.isChecked():
            others = [other for other in boxes if other is not box]
            if any(other.isChecked() for other in others):
                self._set_states({other: other is box for other in boxes})
                return
        wanted = {other: True for other in self._boxes.values()}
        # The unchanged and the excluded toggles are not part of the action
        # filter, so the reset leaves them alone.
        wanted[self.unchanged_box] = self.unchanged_box.isChecked()
        wanted[self.excluded_box] = self.excluded_box.isChecked()
        self._set_states(wanted)

    def _set_states(self, wanted: dict[QCheckBox, bool]) -> None:
        """Set the checkboxes and report the change once."""
        action_changed = False
        unchanged_changed = False
        excluded_changed = False
        for box, value in wanted.items():
            if box.isChecked() == value:
                continue
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)
            if box is self.unchanged_box:
                unchanged_changed = True
            elif box is self.excluded_box:
                excluded_changed = True
            else:
                action_changed = True
        if action_changed:
            self._emit_change()
        if unchanged_changed:
            self.unchanged_toggled.emit(self.unchanged_box.isChecked())
        if excluded_changed:
            self.excluded_toggled.emit(self.excluded_box.isChecked())

    def reset_defaults(self) -> None:
        """The state the bar starts in: every action and nothing else."""
        wanted = {box: True for box in self._boxes.values()}
        wanted[self.unchanged_box] = False
        wanted[self.excluded_box] = False
        self._set_states(wanted)
        self.directory_filter_box.setChecked(False)

    def _show_box_menu(self, box: QCheckBox, point: object) -> None:
        """Offer the inverted choice for one checkbox."""
        menu = QMenu(self)
        only = menu.addAction("Show only this")
        others = menu.addAction("Show everything but this")
        every = menu.addAction("Show all")
        menu.addSeparator()
        reset = menu.addAction("Reset to default")
        selected = menu.exec(box.mapToGlobal(point))  # type: ignore[arg-type]
        boxes = self._all_boxes()
        if selected is only:
            self._set_states({other: other is box for other in boxes})
        elif selected is others:
            self._set_states({other: other is not box for other in boxes})
        elif selected is every:
            self._set_states({other: True for other in boxes})
        elif selected is reset:
            self.reset_defaults()

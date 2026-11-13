"""A flat comparison view, modelled after the FreeFileSync file grid.

The comparison is a flat list of rows: a directory, the items below it, the
next directory. The hierarchy is painted, not modelled, so the view never
expands anything and never freezes on a large comparison.

The pane layout, the columns and the decisions are the same as in the tree
view, so the two can be compared on the same data.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QRect,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.backend.rsync_patterns import phrases_for
from qpy_rsync.core.changes import ChangeAction

from .controls import ACTION_PANE_WIDTH, CONTROL_ICON_SIZE, CONTROL_SIZE, ROW_HEIGHT
from .flat_change_model import HIDDEN_ROLE, STRIPE_ROLE, FlatChangeModel
from .icons import app_menu_icon, hidden_icon, search_icon, unchanged_icon
from .paths import full_path
from qpy_rsync.storage.settings import app_settings

# The colour of the dimmed path that precedes the name of a directory.
PREFIX_COLOR = QColor("#707070")
# The colour of the rule that connects the items to their directory.
RULE_COLOR = QColor("#c8c8c8")
# The shade of every second directory group, the way a printed table
# alternates its rows. Kept faint so the text stays the focus.
STRIPE_COLOR = QColor(0, 0, 0, 22)
HIDDEN_COLOR = QColor("#9ca3af")


class UniformRowDelegate(QStyledItemDelegate):
    """Keep row heights identical in all three panes.

    Also paints the alternating group background, which the panes share so a
    row is shaded the same way in all three of them.
    """

    def sizeHint(self, option: object, index: QModelIndex) -> QSize:  # noqa: N802
        # The default implementation asks the model for every role and walks
        # the style, which is far too expensive for a large list.
        text = index.data(Qt.ItemDataRole.DisplayRole)
        metrics = option.fontMetrics  # type: ignore[attr-defined]
        width = metrics.horizontalAdvance(str(text or "")) + 24
        return QSize(width, ROW_HEIGHT)

    def paint(self, painter: object, option: object, index: QModelIndex) -> None:
        styled = QStyleOptionViewItem(option)  # type: ignore[arg-type]
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        if index.data(STRIPE_ROLE) and not selected:
            painter.fillRect(styled.rect, STRIPE_COLOR)  # type: ignore[attr-defined]
        # The focus rectangle is dropped: the selected row is already marked
        # by its background, and the dotted outline reads like a second
        # cursor next to the hover highlight.
        styled.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, styled, index)  # type: ignore[arg-type]


class ActionColumnDelegate(UniformRowDelegate):
    """Paint the action column, the hidden marker and the row background.

    Rows that cannot be selected carry no check indicator, so the style
    draws their icon where the checkbox of the other rows sits. Painting
    the background first and shifting the content keeps the icons in one
    column.

    The crossed eye at the right marks a row that is hidden from the sync.
    It is drawn for every row, filled for a hidden one and faded otherwise,
    so it also works as the button that hides and restores the row.
    """

    MARKER_SIZE = 14
    MARKER_RIGHT = 20

    @classmethod
    def marker_rect(cls, rect: QRect) -> QRect:
        size = cls.MARKER_SIZE
        return QRect(
            rect.right() - cls.MARKER_RIGHT,
            rect.top() + (rect.height() - size) // 2,
            size,
            size,
        )

    def _paint_marker(self, painter: object, option: object, index: QModelIndex) -> None:
        icon = hidden_icon()
        rect = self.marker_rect(option.rect)  # type: ignore[attr-defined]
        if not index.data(HIDDEN_ROLE):
            painter.setOpacity(0.25)  # type: ignore[attr-defined]
        icon.paint(painter, rect)  # type: ignore[arg-type]
        painter.setOpacity(1.0)  # type: ignore[attr-defined]

    def paint(self, painter: object, option: object, index: QModelIndex) -> None:
        if index.data(Qt.ItemDataRole.CheckStateRole) is not None:
            super().paint(painter, option, index)  # type: ignore[arg-type]
            self._paint_marker(painter, option, index)
            return
        styled = QStyleOptionViewItem(option)  # type: ignore[arg-type]
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        if index.data(STRIPE_ROLE) and not selected:
            painter.fillRect(styled.rect, STRIPE_COLOR)  # type: ignore[attr-defined]
        styled.state &= ~QStyle.StateFlag.State_HasFocus
        blank = QStyleOptionViewItem(styled)
        blank.text = ""
        blank.icon = QIcon()
        widget = blank.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, blank, painter, widget
        )
        shifted = QStyleOptionViewItem(styled)
        offset = (
            style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, widget) + 4
        )
        shifted.rect = shifted.rect.adjusted(offset, 0, 0, 0)
        super().paint(painter, shifted, index)  # type: ignore[arg-type]
        self._paint_marker(painter, option, index)


class FlatPathDelegate(UniformRowDelegate):
    """Draw the directory hierarchy of the flat list.

    A directory row is indented by its depth. The items below it are
    indented one step further, and a thin rule connects them to it. This is
    the "virtual" hierarchy of FreeFileSync: it is painted, so the model
    stays a plain list.
    """

    ICON_SIZE = 16
    LEVEL_WIDTH = 14

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        model = index.model()
        row = model.row_data(index.row())
        if row is None:
            super().paint(painter, option, index)
            return
        column = index.column()
        if column not in (model.SOURCE_NAME, model.DESTINATION_NAME):
            super().paint(painter, option, index)
            return

        text = str(model.data(index, Qt.ItemDataRole.DisplayRole) or "")
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        # A directory sits at its own depth, its items one level below it.
        depth = row.depth
        is_hidden = model.hidden.is_hidden(row.path)

        styled = QStyleOptionViewItem(option)
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        # Paint the row background (alternating group, selection, hover) with
        # the style first, so the custom text below sits on the right colour.
        styled.state &= ~QStyle.StateFlag.State_HasFocus
        if index.data(STRIPE_ROLE) and not selected:
            painter.fillRect(styled.rect, STRIPE_COLOR)
        blank = QStyleOptionViewItem(styled)
        blank.text = ""
        blank.icon = QIcon()
        widget = blank.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, blank, painter, widget
        )

        painter.save()
        painter.translate(option.rect.left(), option.rect.top())
        baseline = option.rect.height() // 2 + option.fontMetrics.ascent() // 2 - 1
        x = 4 + depth * self.LEVEL_WIDTH
        if not row.is_directory:
            # The rule that shows which directory the item belongs to.
            rule_x = x - 8
            painter.setPen(QPen(RULE_COLOR, 1))
            painter.drawLine(rule_x, 0, rule_x, option.rect.height())
            x += 6
        if selected:
            color = styled.palette.color(
                styled.palette.ColorRole.HighlightedText
            )
        else:
            color = styled.palette.color(styled.palette.ColorRole.Text)
            if is_hidden:
                # A hidden row stays readable but is clearly marked.
                color = HIDDEN_COLOR
        painter.setPen(color)
        if icon is not None:
            icon.paint(
                painter,
                QRect(x, (option.rect.height() - self.ICON_SIZE) // 2, self.ICON_SIZE, self.ICON_SIZE),
            )
            x += self.ICON_SIZE + 4
        painter.drawText(x, baseline, text)
        painter.restore()


class FlatComparisonView(QWidget):
    """Synchronized source/action/destination panes over a flat list."""

    diff_requested = Signal(object)
    decision_changed = Signal()
    inventory_toggled = Signal(bool)
    changes_updated = Signal(object)
    unhide_all_requested = Signal()
    sort_changed = Signal(int, object)
    expansion_limited = Signal(int, int)
    # A filter rule for the selected item, as an rsync pattern.
    filter_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = FlatChangeModel(self)
        self._source_root = ""
        self._destination_root = ""
        # Whether each side lives on this machine, so local items can be
        # opened with the desktop handlers.
        self.source_is_local = True
        self.destination_is_local = True
        self._syncing = False
        self._update_freeze = 0

        self.source = self._tree("Source")
        self.action = self._tree("Action")
        self.action.setItemDelegate(ActionColumnDelegate(self.action))
        self.destination = self._tree("Destination")
        self.source.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.action.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.action.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self.action.setFixedWidth(ACTION_PANE_WIDTH)
        self._configure_columns()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.source)
        self.splitter.addWidget(self.action)
        self.splitter.addWidget(self.destination)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setStretchFactor(2, 1)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Pictures/, Documents, School-Report-202*, *.jpg")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMinimumWidth(180)
        self.filter_edit.setSizePolicy(
            self.filter_edit.sizePolicy().horizontalPolicy(),
            self.filter_edit.sizePolicy().verticalPolicy(),
        )
        self.filter_edit.setToolTip(
            "Temporarily filter paths shown in the current comparison. "
            "This does not change rsync include or exclude rules."
        )

        self.inventory_button = QToolButton()
        self.inventory_button.setCheckable(True)
        self.inventory_button.setIcon(unchanged_icon())
        self.inventory_button.setToolTip("Show unchanged items")
        self.inventory_button.setAccessibleName("Show unchanged items")
        self.inventory_button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        self.inventory_button.setIconSize(
            QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE)
        )

        self.view_controls = QWidget(self)
        self.view_controls.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        view_layout = QHBoxLayout(self.view_controls)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(2)
        view_layout.addWidget(self.inventory_button)

        self.controls = QWidget(self)
        self.controls.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.filter_button = QToolButton()
        self.filter_button.setIcon(search_icon())
        self.filter_button.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.filter_button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        self.filter_button.setToolTip("Filter/Find (Ctrl+F)")
        self.filter_button.setAccessibleName("Filter/Find")
        self.filter_button.clicked.connect(self.focus_path_filter)
        controls.addWidget(self.filter_button)
        controls.addWidget(self.filter_edit, 1)
        self.menu_button = QToolButton()
        self.menu_button.setIcon(app_menu_icon())
        self.menu_button.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        self.menu_button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
        self.menu_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.menu_button.setToolTip("Application menu")
        self.menu_button.setAccessibleName("Application menu")
        controls.addWidget(self.menu_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self.inventory_button.toggled.connect(self.inventory_toggled.emit)
        # Re-filtering a large comparison costs a few hundred milliseconds,
        # so typing waits for a short pause and Enter applies immediately.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)
        self._filter_timer.timeout.connect(self._apply_path_filter)
        self.filter_edit.textChanged.connect(self._filter_changed)
        self.filter_edit.returnPressed.connect(self._apply_path_filter)
        self.splitter.splitterMoved.connect(lambda _position, _index: self.save_view_state())
        self.source.horizontalHeader().sectionResized.connect(lambda _logical, _old, _new: self.save_view_state())
        self.destination.horizontalHeader().sectionResized.connect(
            lambda _logical, _old, _new: self.save_view_state()
        )
        for pane, tree in (
            ("source", self.source),
            ("destination", self.destination),
        ):
            tree.horizontalHeader().setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu
            )
            tree.horizontalHeader().customContextMenuRequested.connect(
                lambda point, p=pane, t=tree: self._show_column_menu(p, t, point)
            )
        self._restore_view_state()
        self._synchronize()
        for tree in (self.source, self.action, self.destination):
            tree.sortByColumn(self.model.SOURCE_NAME, Qt.SortOrder.AscendingOrder)
        self._show_sort_indicator(self.model.SOURCE_NAME, Qt.SortOrder.AscendingOrder)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    def _tree(self, label: str) -> QTableView:
        """Build one comparison pane.

        The list is flat, so a table is the honest widget. A tree would keep
        per-index tree state for rows that have no children, which is the
        dominant cost of loading a comparison with hundreds of thousands of
        items.
        """
        pane = QTableView()
        pane.setModel(self.model)
        pane.setObjectName(label.lower())
        # A fixed row height replaces the tree's uniform row heights; the row
        # numbers of the vertical header are not wanted.
        row_header = pane.verticalHeader()
        row_header.hide()
        row_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        row_header.setDefaultSectionSize(ROW_HEIGHT)
        pane.setShowGrid(False)
        pane.setWordWrap(False)
        pane.setItemDelegate(FlatPathDelegate(pane))
        pane.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        pane.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pane.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        pane.setSortingEnabled(True)
        pane.horizontalHeader().setStretchLastSection(False)
        pane.horizontalHeader().setSortIndicatorShown(True)
        pane.horizontalHeader().setSectionsClickable(True)
        pane.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        pane.customContextMenuRequested.connect(
            lambda point, t=pane: self._show_context_menu(t, point)
        )
        pane.doubleClicked.connect(self._request_diff)
        # The space bar hides the selected items; the key event goes to the
        # focused pane, so the panes are watched. The mouse events of a pane
        # go to its viewport, so the viewport is watched as well.
        pane.installEventFilter(self)
        pane.viewport().installEventFilter(self)
        return pane

    # The optional columns of each pane, in the order they are offered.
    OPTIONAL_COLUMNS = {
        "source": (
            ("Items", 1),
            ("Size", 2),
            ("Modified", 3),
        ),
        "destination": (
            ("Items", 6),
            ("Size", 7),
            ("Modified", 8),
        ),
    }

    def _hidden_columns(self, pane: str) -> set[int]:
        """The optional columns of a pane that the user switched off."""
        key = f"comparison/flat-hidden-{pane}"
        stored = str(app_settings().value(key, "")).strip()
        hidden: set[int] = set()
        if stored:
            for value in stored.split(","):
                try:
                    hidden.add(int(value))
                except ValueError:
                    continue
        return hidden

    def _save_hidden_columns(self, pane: str, hidden: set[int]) -> None:
        settings = app_settings()
        settings.setValue(
            f"comparison/flat-hidden-{pane}",
            ",".join(str(column) for column in sorted(hidden)),
        )
        settings.sync()

    def _apply_column_visibility(self) -> None:
        """Show the columns of each pane, minus the ones switched off."""
        source_hidden = self._hidden_columns("source")
        destination_hidden = self._hidden_columns("destination")
        for column in range(self.model.COLUMN_COUNT):
            self.source.setColumnHidden(column, column not in {
                self.model.SOURCE_NAME,
                self.model.SOURCE_ITEMS,
                self.model.SOURCE_SIZE,
                self.model.SOURCE_TIME,
            } or column in source_hidden)
            self.action.setColumnHidden(column, column != self.model.ACTION)
            self.destination.setColumnHidden(column, column not in {
                self.model.DESTINATION_NAME,
                self.model.DESTINATION_ITEMS,
                self.model.DESTINATION_SIZE,
                self.model.DESTINATION_TIME,
            } or column in destination_hidden)

    def _show_column_menu(self, pane: str, tree: QTableView, point: object) -> None:
        """Offer the optional columns of a pane as a checkable menu."""
        menu = QMenu(tree)
        hidden = self._hidden_columns(pane)
        actions = {}
        for label, column in self.OPTIONAL_COLUMNS[pane]:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(column not in hidden)
            actions[action] = column
        selected = menu.exec(tree.horizontalHeader().mapToGlobal(point))
        if selected is None:
            return
        column = actions.get(selected)
        if column is None:
            return
        if selected.isChecked():
            hidden.discard(column)
        else:
            hidden.add(column)
        self._save_hidden_columns(pane, hidden)
        self._apply_column_visibility()

    def _configure_columns(self) -> None:
        self._apply_column_visibility()
        # The header only needs the height of its text, so the list starts a
        # little higher.
        for tree in (self.source, self.action, self.destination):
            tree.horizontalHeader().setFixedHeight(
                max(16, tree.fontMetrics().height() + 2)
            )
        self.source.horizontalHeader().setSectionResizeMode(self.model.SOURCE_NAME, QHeaderView.ResizeMode.Stretch)
        self.source.horizontalHeader().setSectionResizeMode(self.model.SOURCE_ITEMS, QHeaderView.ResizeMode.Interactive)
        self.source.horizontalHeader().setSectionResizeMode(self.model.SOURCE_SIZE, QHeaderView.ResizeMode.Interactive)
        self.source.horizontalHeader().setSectionResizeMode(self.model.SOURCE_TIME, QHeaderView.ResizeMode.Interactive)
        self.source.horizontalHeader().resizeSection(self.model.SOURCE_NAME, 240)
        self.source.horizontalHeader().resizeSection(self.model.SOURCE_ITEMS, 60)
        self.source.horizontalHeader().resizeSection(self.model.SOURCE_SIZE, 90)
        self.source.horizontalHeader().resizeSection(self.model.SOURCE_TIME, 150)
        self.action.horizontalHeader().setSectionResizeMode(
            self.model.ACTION, QHeaderView.ResizeMode.Interactive
        )
        self.action.horizontalHeader().resizeSection(self.model.ACTION, ACTION_PANE_WIDTH)
        self.destination.horizontalHeader().setSectionResizeMode(
            self.model.DESTINATION_NAME, QHeaderView.ResizeMode.Stretch
        )
        self.destination.horizontalHeader().setSectionResizeMode(
            self.model.DESTINATION_ITEMS, QHeaderView.ResizeMode.Interactive
        )
        self.destination.horizontalHeader().setSectionResizeMode(
            self.model.DESTINATION_SIZE, QHeaderView.ResizeMode.Interactive
        )
        self.destination.horizontalHeader().setSectionResizeMode(
            self.model.DESTINATION_TIME, QHeaderView.ResizeMode.Interactive
        )
        self.destination.horizontalHeader().resizeSection(self.model.DESTINATION_NAME, 240)
        self.destination.horizontalHeader().resizeSection(self.model.DESTINATION_ITEMS, 60)
        self.destination.horizontalHeader().resizeSection(self.model.DESTINATION_SIZE, 90)
        self.destination.horizontalHeader().resizeSection(self.model.DESTINATION_TIME, 150)

    def _synchronize(self) -> None:
        trees = (self.source, self.action, self.destination)
        for origin in trees:
            for target in trees:
                if origin is target:
                    continue
                origin.verticalScrollBar().valueChanged.connect(
                    target.verticalScrollBar().setValue
                )
                origin.selectionModel().currentChanged.connect(
                    lambda current, _previous, t=target: self._set_current(t, current)
                )

    # ------------------------------------------------------------------
    # Hiding items, the way FreeFileSync does it with the space bar
    # ------------------------------------------------------------------
    def eventFilter(self, watched: object, event: object) -> bool:  # noqa: N802
        """Hide the selected items when the space bar is pressed in a pane.

        The key events go to the focused tree, not to this widget, so the
        panes are watched instead.
        """
        # The filter is installed while the panes are still being built, so
        # it must not assume that all of them exist yet.
        panes = [
            pane
            for pane in (
                getattr(self, "source", None),
                getattr(self, "action", None),
                getattr(self, "destination", None),
            )
            if pane is not None
        ]
        event_type = getattr(event, "type", lambda: None)()
        action = getattr(self, "action", None)
        action_viewport = getattr(action, "viewport", lambda: None)()
        if watched is action_viewport:
            # The viewport accepts touch events, so a touchscreen sends
            # TouchBegin instead of the synthesized mouse press that a mouse
            # would send. Both paths reach the same hit test.
            if event_type == QEvent.Type.MouseButtonPress:
                if self._toggle_hidden_at(event.position().toPoint()):
                    return True
            elif event_type == QEvent.Type.TouchBegin:
                points = getattr(event, "points", lambda: ())()
                if len(points) == 1 and self._toggle_hidden_at(
                    points[0].position().toPoint()
                ):
                    return True
        if watched in panes:
            if (
                event_type == QEvent.Type.KeyPress
                and getattr(event, "key", lambda: None)() == Qt.Key.Key_Space
            ):
                if self._toggle_hidden():
                    return True
        return super().eventFilter(watched, event)  # type: ignore[arg-type]

    def _toggle_hidden_at(self, position: object) -> bool:
        """Toggle the hidden state when the crossed eye is clicked or tapped."""
        index = self.action.indexAt(position)
        if not index.isValid():
            return False
        rect = self.action.visualRect(index)
        marker = ActionColumnDelegate.marker_rect(rect)
        # A finger is not as precise as a pointer, so the marked area is
        # widened to the full height of the row and a little to the left.
        hit = marker.adjusted(-8, -(rect.height() - marker.height()) // 2, 0, 0)
        hit.setTop(rect.top())
        hit.setBottom(rect.bottom())
        hit.setRight(rect.right())
        if not hit.contains(position):
            return False
        path = self.model.row_path(index.row())
        if not path:
            return False
        self.model.hidden.toggle(path)
        self._refresh_hidden()
        return True

    def _toggle_hidden(self) -> bool:
        """Hide or show the selected items. Returns True when it handled it."""
        paths = self._selected_paths()
        if not paths:
            return False
        hidden = self.model.hidden
        for path in paths:
            hidden.toggle(path)
        self.model.refresh_hidden()
        self.changes_updated.emit(list(self.model.changes))
        return True

    def _selected_paths(self) -> list[str]:
        """The paths of the selected rows, without their parents."""
        paths: list[str] = []
        for tree in (self.source, self.action, self.destination):
            selection = tree.selectionModel().selectedRows()
            if not selection:
                continue
            for index in selection:
                path = self.model.row_path(index.row())
                if path:
                    paths.append(path)
            break
        return paths

    def hide_path(self, path: str) -> None:
        """Hide a path and everything below it."""
        self.model.hidden.hide(path)
        self._refresh_hidden()

    def show_path(self, path: str) -> None:
        """Show a path again."""
        self.model.hidden.show(path)
        self._refresh_hidden()

    def show_all_hidden(self) -> None:
        """Show every hidden item again."""
        self.model.hidden.clear()
        self._refresh_hidden()

    def hidden_paths(self) -> set[str]:
        """The paths that the user hid."""
        return self.model.hidden.paths()

    def set_show_hidden(self, show: bool) -> None:
        """Show or hide the items the user hid."""
        self.model.show_hidden = show
        self._refresh_hidden()

    def _refresh_hidden(self) -> None:
        """Update the list after the hidden items changed."""
        self.model.refresh_hidden()
        self.changes_updated.emit(list(self.model.changes))

    @staticmethod
    def _set_current(tree: QTableView, index: QModelIndex) -> None:
        if not index.isValid():
            return
        visible = next(
            (
                column
                for column in range(index.model().columnCount())
                if not tree.isColumnHidden(column)
            ),
            0,
        )
        target_index = index.siblingAtColumn(visible)
        if tree.currentIndex() == target_index:
            return
        tree.selectionModel().setCurrentIndex(
            target_index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )

    # ------------------------------------------------------------------
    # Roots
    # ------------------------------------------------------------------
    @property
    def source_root(self) -> str:
        return self._source_root

    @source_root.setter
    def source_root(self, value: str) -> None:
        self._source_root = value.rstrip("/")
        self.model.source_root = self._source_root

    @property
    def destination_root(self) -> str:
        return self._destination_root

    @destination_root.setter
    def destination_root(self, value: str) -> None:
        self._destination_root = value.rstrip("/")
        self.model.destination_root = self._destination_root

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def set_changes(self, changes: list[object]) -> None:
        """Show a new comparison."""
        for tree in (self.source, self.action, self.destination):
            tree.setCurrentIndex(QModelIndex())
            tree.selectionModel().clear()
        self.model.set_changes(changes)  # type: ignore[arg-type]
        self.changes_updated.emit(list(self.model.changes))

    def set_action_filter(self, actions: set[ChangeAction] | None) -> None:
        """Show only the given actions and refresh the overview."""
        self.model.set_visible_actions(actions)
        self.changes_updated.emit(list(self.model.changes))

    def set_destination_metadata(
        self, metadata: dict[str, tuple[int | None, str | None]]
    ) -> None:
        """Show the size and the date of the listed destination items."""
        self.model.set_destination_metadata(metadata)

    def visible_changes(self) -> list[object]:
        """The items of the comparison that the filters show."""
        return self.model.visible_changes()

    def select_path(self, path: str) -> None:
        """Select the object with the given path in the panes."""
        index = self.model.index_for_path(path)
        if not index.isValid():
            return
        for tree in (self.source, self.action, self.destination):
            tree.setCurrentIndex(index)
            tree.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def set_stale(self, stale: bool) -> None:
        if stale:
            for tree in (self.source, self.action, self.destination):
                tree.setCurrentIndex(QModelIndex())
                tree.selectionModel().clear()
        self.model.decisions_enabled = not stale
        self.model.stale = stale
        self.source.setEnabled(not stale)
        self.action.setEnabled(not stale)
        self.destination.setEnabled(not stale)
        self.model.layoutAboutToBeChanged.emit()
        self.model.layoutChanged.emit()
        self.action.setToolTip(
            "Comparison is stale; compare again before changing decisions."
            if stale
            else ""
        )

    def focus_path_filter(self) -> None:
        self.filter_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.filter_edit.selectAll()

    def _filter_changed(self, _text: str) -> None:
        """Re-filter after the typing pauses, or when Enter is pressed."""
        self._filter_timer.start()

    def _apply_path_filter(self) -> None:
        self._filter_timer.stop()
        self.model.set_path_filter(self.filter_edit.text())
        self.changes_updated.emit(list(self.model.changes))

    def set_path_filter(self, text: str) -> None:
        """Apply a path filter right away, for callers other than the field."""
        self._filter_timer.stop()
        self.model.set_path_filter(text)

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------
    def _sort_by_section(self, tree: QTableView, section: int) -> None:
        """Sort the panes by the given column, like a header click."""
        column = section
        order = Qt.SortOrder.AscendingOrder
        if self.model.sort_column() == column:
            order = (
                Qt.SortOrder.DescendingOrder
                if self.model.sort_order() == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        self.model.sort(column, order)
        self._show_sort_indicator(self.model.sort_column(), self.model.sort_order())
        self.sort_changed.emit(self.model.sort_column(), self.model.sort_order())

    def _show_sort_indicator(self, column: int, order: Qt.SortOrder) -> None:
        for tree in (self.source, self.action, self.destination):
            header = tree.horizontalHeader()
            visible = [
                section
                for section in range(header.count())
                if not header.isSectionHidden(section)
            ]
            if column in visible:
                header.setSortIndicator(column, order)
            elif header.sortIndicatorSection() >= 0:
                header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------
    def reset_all_decisions(self) -> None:
        """Reset every explicit decision after asking the user."""
        if not self.model.decisions.has_explicit():
            return
        answer = QMessageBox.question(
            self,
            "Reset all decisions",
            "Reset every manual checkbox decision to its inherited default?",
            QMessageBox.StandardButton.Reset | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Reset:
            self.model.reset_all_decisions()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------
    def _show_context_menu(self, tree: QTableView, point: object) -> None:
        index = tree.indexAt(point)
        if not index.isValid():
            # An empty part of the Actions pane still offers the one action
            # that belongs to the list as a whole.
            if tree is self.action and self.model.hidden:
                menu = QMenu(tree)
                unhide = menu.addAction(
                    f"Unhide All ({self.model.hidden.count()})"
                )
                selected = menu.exec(tree.viewport().mapToGlobal(point))
                if selected is unhide:
                    self.unhide_all_requested.emit()
            return
        path = self.model.row_path(index.row())
        change = index.data(Qt.ItemDataRole.UserRole)
        row = self.model.row_data(index.row())
        menu, actions = self._build_context_menu(tree, path, change, row)
        selected = menu.exec(tree.viewport().mapToGlobal(point))
        if selected is actions["diff"]:
            self._request_diff(index)
        elif selected is actions["copy"] and path is not None:
            self._copy_path(tree, path)
        elif selected is actions["open_file"] and path is not None:
            self._open_local(tree, path)
        elif selected is actions["open_directory"] and path is not None:
            self._open_local_directory(tree, path)
        elif selected is actions["reset_one"] and path is not None:
            self.model.reset_decision(path)
        elif selected is actions["reset_subtree"] and path is not None:
            self.model.reset_subtree_decisions(path)
        elif selected is actions["reset_all"]:
            self.reset_all_decisions()
        elif selected is actions["hide"] and path is not None:
            self.hide_path(path)
        elif selected is actions["show"] and path is not None:
            self.show_path(path)
        elif selected is actions["show_all_hidden"]:
            self.unhide_all_requested.emit()
        elif selected in actions["filters"]:
            self.filter_requested.emit(selected.text(), path)

    def _side_is_local(self, tree: QTableView) -> bool:
        """Whether the pane's endpoint lives on this machine."""
        if tree is self.destination:
            return self.destination_is_local
        return self.source_is_local

    def _local_path(self, tree: QTableView, path: str) -> str:
        root = self.destination_root if tree is self.destination else self.source_root
        return full_path(root, path)

    def _open_local(self, tree: QTableView, path: str) -> None:
        """Open a file with the desktop handler."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(self._local_path(tree, path)))

    def _open_local_directory(self, tree: QTableView, path: str) -> None:
        """Open the file manager at the item or at the directory that holds it."""
        from pathlib import Path as _Path

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        target = _Path(self._local_path(tree, path))
        if not target.is_dir():
            target = target.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _absolute_path(self, tree: QTableView, path: str | None) -> str:
        if not path:
            return ""
        root = self.destination_root if tree is self.destination else self.source_root
        return full_path(root, path)

    def _copy_path(self, tree: QTableView, path: str) -> None:
        QApplication.clipboard().setText(self._absolute_path(tree, path))

    def _build_context_menu(
        self,
        tree: QTableView,
        path: str | None,
        change: object | None,
        row: object | None = None,
    ) -> tuple[QMenu, dict[str, object]]:
        """Build the context menu of a row.

        The filter entries follow FreeFileSync: the selected item can be
        filtered by extension, by name or by its relative path. The rules
        are ordinary rsync patterns.
        """
        is_unchanged = (
            change is not None
            and getattr(change, "action", None) is ChangeAction.NO_CHANGE
        )
        absolute_path = self._absolute_path(tree, path)
        menu = QMenu(tree)
        actions: dict[str, object] = {
            "copy": None,
            "open_file": None,
            "open_directory": None,
            "diff": None,
            "reset_one": None,
            "reset_subtree": None,
            "reset_all": None,
            "hide": None,
            "show": None,
            "show_all_hidden": None,
            "filters": [],
        }
        if absolute_path:
            heading = menu.addAction(absolute_path)
            heading.setEnabled(False)
            menu.addSeparator()
        actions["copy"] = menu.addAction("Copy Path")
        actions["copy"].setEnabled(path is not None)  # type: ignore[union-attr]
        if path is not None and self._side_is_local(tree):
            is_directory = bool(getattr(row, "is_directory", False))
            menu.addSeparator()
            if not is_directory:
                actions["open_file"] = menu.addAction("Open File")
            actions["open_directory"] = menu.addAction(
                "Open in Directory" if not is_directory else "Open Directory"
            )
        if not is_unchanged:
            menu.addSeparator()
            actions["diff"] = menu.addAction("Open in Diff Tool")
            actions["diff"].setEnabled(change is not None)  # type: ignore[union-attr]
            if tree is self.action and path is not None:
                menu.addSeparator()
                actions["reset_one"] = menu.addAction("Reset This Decision")
                actions["reset_subtree"] = menu.addAction("Reset Subtree Decisions")
                actions["reset_all"] = menu.addAction("Reset All Decisions")
                actions["reset_all"].setEnabled(  # type: ignore[union-attr]
                    self.model.decisions.has_explicit()
                )

        # The filter entries of FreeFileSync, with rsync patterns.
        if path:
            menu.addSeparator()
            is_directory = bool(getattr(row, "is_directory", False))
            phrases = phrases_for(path, is_directory=is_directory)
            if phrases:
                filter_menu = menu.addMenu("Exclude via Filter")
                for phrase in phrases:
                    action = filter_menu.addAction(phrase.label)
                    action.setData(phrase.pattern)
                    actions["filters"].append(action)  # type: ignore[union-attr]

        # Hiding items from the comparison.
        menu.addSeparator()
        hidden = self.model.hidden
        if path and hidden.is_hidden(path):
            actions["show"] = menu.addAction("Show Item")
        elif path:
            actions["hide"] = menu.addAction("Hide Item\tSpace")
        if hidden:
            actions["show_all_hidden"] = menu.addAction(
                f"Unhide All ({hidden.count()})"
            )
        return menu, actions

    def _request_diff(self, index: QModelIndex) -> None:
        change = index.data(Qt.ItemDataRole.UserRole)
        if change is not None:
            self.diff_requested.emit(change)

    # ------------------------------------------------------------------
    # View state
    # ------------------------------------------------------------------
    def save_view_state(self) -> None:
        from qpy_rsync.storage.settings import app_settings, encode_binary

        settings = app_settings()
        settings.setValue(
            "comparison/flat-splitter", encode_binary(self.splitter.saveState())
        )
        settings.setValue(
            "comparison/flat-source-header",
            encode_binary(self.source.horizontalHeader().saveState()),
        )
        settings.setValue(
            "comparison/flat-destination-header",
            encode_binary(self.destination.horizontalHeader().saveState()),
        )
        settings.sync()

    def _restore_view_state(self) -> None:
        from qpy_rsync.storage.settings import app_settings, decode_binary

        settings = app_settings()
        state = decode_binary(settings.value("comparison/flat-splitter"))
        if state is not None:
            self.splitter.restoreState(state)
        else:
            self.splitter.setSizes([450, ACTION_PANE_WIDTH, 450])
        source = decode_binary(settings.value("comparison/flat-source-header"))
        destination = decode_binary(settings.value("comparison/flat-destination-header"))
        if source is not None:
            self.source.horizontalHeader().restoreState(source)
        if destination is not None:
            self.destination.horizontalHeader().restoreState(destination)
        # A saved state can carry a width from an older layout, so the name
        # columns are kept wide enough to stay readable.
        for tree, name_column in (
            (self.source, self.model.SOURCE_NAME),
            (self.destination, self.model.DESTINATION_NAME),
        ):
            if tree.columnWidth(name_column) < 160:
                tree.setColumnWidth(name_column, 240)
        self._apply_column_visibility()

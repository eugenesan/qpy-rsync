from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .change_filter_proxy import ChangeTreeFilterProxyModel
from .change_tree_model import ChangeTreeModel, full_path
from .icons import app_menu_icon, unchanged_icon
from qpy_rsync.core.changes import ChangeAction
from qpy_rsync.storage.settings import app_settings, decode_binary, encode_binary

CONTROL_SIZE = 40
CONTROL_ICON_SIZE = 24
# The action column only carries a checkbox, a glyph and the short "Actions"
# header, so it hugs its content instead of leaving empty background.
ACTION_PANE_WIDTH = 78
ROW_HEIGHT = 22


class UniformRowDelegate(QStyledItemDelegate):
    """Keep row heights identical in all three synchronized tree panes."""

    def sizeHint(self, option: object, index: QModelIndex) -> QSize:  # noqa: N802
        # The default implementation asks the model for every role and walks
        # the style, which is far too expensive while a large tree expands.
        # Only the text width matters here; the height is fixed anyway.
        text = index.data(Qt.ItemDataRole.DisplayRole)
        metrics = option.fontMetrics  # type: ignore[attr-defined]
        width = metrics.horizontalAdvance(str(text or "")) + 24
        return QSize(width, ROW_HEIGHT)


class ActionColumnDelegate(UniformRowDelegate):
    """Align the icon of a row without a checkbox with the other icons.

    Rows that cannot be selected carry no check indicator, so the style
    draws their icon where the checkbox of the other rows sits. Painting
    the background first and shifting the content keeps the icons in one
    column.
    """

    def paint(self, painter: object, option: object, index: QModelIndex) -> None:
        if index.data(Qt.ItemDataRole.CheckStateRole) is not None:
            super().paint(painter, option, index)  # type: ignore[arg-type]
            return
        styled = QStyleOptionViewItem(option)  # type: ignore[arg-type]
        styled.text = ""
        styled.icon = QIcon()
        widget = styled.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, styled, painter, widget
        )
        shifted = QStyleOptionViewItem(option)  # type: ignore[arg-type]
        offset = (
            style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, widget) + 4
        )
        shifted.rect = shifted.rect.adjusted(offset, 0, 0, 0)
        super().paint(painter, shifted, index)  # type: ignore[arg-type]


class ComparisonView(QWidget):
    """Synchronized source/action/destination tree panes."""

    diff_requested = Signal(object)
    decision_changed = Signal()
    inventory_toggled = Signal(bool)
    changes_updated = Signal(object)
    sort_changed = Signal(int, object)


    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = ChangeTreeModel(self)
        self._source_root = ""
        self._destination_root = ""
        self._update_freeze = 0
        self._syncing_expansion = False
        self._expand_mode = "all"
        self._destination_metadata: dict[str, tuple[int | None, str | None]] = {}
        self.model.decision_changed.connect(self.decision_changed)
        self.model.decision_changed.connect(self._refresh_action_filter)
        self.proxy = ChangeTreeFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.source = self._tree("Source")
        self.action = self._tree("Action")
        self.action.setItemDelegate(ActionColumnDelegate(self.action))
        self.destination = self._tree("Destination")
        # The panes scroll together, so only the last one needs a scroll bar.
        # The others use the full width for the file names.
        self.source.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.action.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # The action column only carries a checkbox and an icon, so it keeps a
        # fixed width and the two file panes share the remaining space.
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
        self.expand_button = QToolButton()
        self.expand_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.expand_button.setToolTip("Expand all comparison paths")
        self.expand_button.setAccessibleName("Expand all comparison paths")
        self.collapse_button = QToolButton()
        self.collapse_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        )
        self.collapse_button.setToolTip("Collapse all comparison paths")
        self.collapse_button.setAccessibleName("Collapse all comparison paths")
        self.view_controls = QWidget(self)
        self.view_controls.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        view_layout = QHBoxLayout(self.view_controls)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(2)
        view_layout.addWidget(self.inventory_button)
        view_layout.addWidget(self.expand_button)
        view_layout.addWidget(self.collapse_button)
        self.controls = QWidget(self)
        self.controls.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.filter_button = QPushButton("Filter/Find")
        self.filter_button.setToolTip("Focus the comparison path filter")
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
        self.inventory_button.toggled.connect(self.inventory_toggled.emit)
        for button in (self.inventory_button, self.expand_button, self.collapse_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setFixedSize(CONTROL_SIZE, CONTROL_SIZE)
            button.setIconSize(QSize(CONTROL_ICON_SIZE, CONTROL_ICON_SIZE))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)
        self.filter_edit.textChanged.connect(self.set_path_filter)
        self.expand_button.clicked.connect(self.expand_all)
        self.collapse_button.clicked.connect(self.collapse_all)
        # The header of a pane sorts the shared model, so every pane follows.
        self.proxy.sorted.connect(self._sync_sort_indicators)
        self.splitter.splitterMoved.connect(lambda _position, _index: self.save_view_state())
        self.source.header().sectionResized.connect(lambda _logical, _old, _new: self.save_view_state())
        self.destination.header().sectionResized.connect(
            lambda _logical, _old, _new: self.save_view_state()
        )
        self._restore_view_state()
        self._synchronize()
        # Tell the panes that the tree starts sorted by name. The first click
        # on that header then reverses the order instead of doing nothing.
        for tree in (self.source, self.action, self.destination):
            tree.sortByColumn(self.model.SOURCE_NAME, Qt.SortOrder.AscendingOrder)
        self._show_sort_indicator(self.model.SOURCE_NAME, Qt.SortOrder.AscendingOrder)

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

    def _tree(self, label: str) -> QTreeView:
        tree = QTreeView()
        tree.setModel(self.proxy)
        tree.setObjectName(label.lower())
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setItemDelegate(UniformRowDelegate(tree))
        tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tree.setSortingEnabled(True)
        tree.header().setStretchLastSection(False)
        tree.header().setSortIndicatorShown(True)
        # Without clickable sections the header never reports a click.
        tree.header().setSectionsClickable(True)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(lambda point, t=tree: self._show_context_menu(t, point))
        tree.doubleClicked.connect(self._request_diff)
        return tree

    def _sort_by_section(self, tree: QTreeView, section: int) -> None:
        """Sort the tree panes by the given column, like a header click.

        All three panes show the same items, so they share the order. The
        section of a header is the column of the model, because every pane
        shows a subset of the same columns.
        """
        column = section
        order = Qt.SortOrder.AscendingOrder
        if self.model.sort_column() == column:
            order = (
                Qt.SortOrder.DescendingOrder
                if self.model.sort_order() == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        self.proxy.sort(column, order)

    def _sync_sort_indicators(self) -> None:
        """Show the sorted column in every pane that displays it."""
        self._show_sort_indicator(self.model.sort_column(), self.model.sort_order())
        self.sort_changed.emit(self.model.sort_column(), self.model.sort_order())

    def _show_sort_indicator(self, column: int, order: Qt.SortOrder) -> None:
        for tree in (self.source, self.action, self.destination):
            header = tree.header()
            visible = [
                section
                for section in range(header.count())
                if not header.isSectionHidden(section)
            ]
            if column in visible:
                header.setSortIndicator(column, order)
            elif header.sortIndicatorSection() >= 0:
                header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    def _source_path_for_proxy_index(self, index: QModelIndex) -> str | None:
        if not index.isValid():
            return None
        source_index = self.proxy.mapToSource(index.siblingAtColumn(0))
        if not source_index.isValid():
            return None
        node = source_index.internalPointer()
        return None if node is None else node.path

    def _show_context_menu(self, tree: QTreeView, point: object) -> None:
        index = tree.indexAt(point)
        if not index.isValid():
            return
        # QTreeView indexes belong to the proxy. Never dereference a proxy
        # index's internalPointer as a TreeNode; doing so can crash PySide/Qt.
        path = self._source_path_for_proxy_index(index)
        change = self._change_for_index(index)
        menu, copy_path_action, diff_action, reset_one, reset_subtree, reset_all = (
            self._build_context_menu(tree, path, change)
        )
        selected = menu.exec(tree.viewport().mapToGlobal(point))
        if selected is diff_action:
            self._request_diff(index)
        elif selected is copy_path_action and path is not None:
            self._copy_path(tree, path)
        elif selected is reset_one and path is not None:
            self.model.reset_decision(path)
        elif selected is reset_subtree and path is not None:
            self.model.reset_subtree_decisions(path)
        elif selected is reset_all:
            self.reset_all_decisions()

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

    def _absolute_path(self, tree: QTreeView, path: str | None) -> str:
        if path is None:
            return ""
        root = self.destination_root if tree is self.destination else self.source_root
        return full_path(root, path)

    def _copy_path(self, tree: QTreeView, path: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._absolute_path(tree, path))

    def _build_context_menu(
        self, tree: QTreeView, path: str | None, change: object | None
    ) -> tuple[QMenu, object | None, object | None, object | None, object | None, object | None]:
        is_unchanged = (
            change is not None
            and getattr(change, "action", None) is ChangeAction.NO_CHANGE
        )
        absolute_path = self._absolute_path(tree, path)
        menu = QMenu(tree)
        if absolute_path:
            heading = menu.addAction(absolute_path)
            heading.setEnabled(False)
            menu.addSeparator()
        copy_path_action = menu.addAction("Copy Path")
        copy_path_action.setEnabled(path is not None)
        diff_action = None
        reset_one = reset_subtree = reset_all = None
        if not is_unchanged:
            menu.addSeparator()
            diff_action = menu.addAction("Open in Diff Tool")
            diff_action.setEnabled(change is not None)
            if tree is self.action and path is not None:
                menu.addSeparator()
                reset_one = menu.addAction("Reset This Decision")
                reset_subtree = menu.addAction("Reset Subtree Decisions")
                reset_all = menu.addAction("Reset All Decisions")
                reset_all.setEnabled(self.model.decisions.has_explicit())
        return menu, copy_path_action, diff_action, reset_one, reset_subtree, reset_all

    def _request_diff(self, index: QModelIndex) -> None:
        change = self._change_for_index(index)
        if change is not None:
            self.diff_requested.emit(change)

    def _change_for_index(self, index: QModelIndex) -> object | None:
        if not index.isValid():
            return None
        return self.proxy.data(index, Qt.ItemDataRole.UserRole)

    def _configure_columns(self) -> None:
        source_columns = {0, 1, 2}
        action_columns = {3}
        destination_columns = {4, 5, 6}
        for column in range(self.model.COLUMN_COUNT):
            self.source.setColumnHidden(column, column not in source_columns)
            self.action.setColumnHidden(column, column not in action_columns)
            self.destination.setColumnHidden(column, column not in destination_columns)
        self.source.setTreePosition(self.model.SOURCE_NAME)
        self.destination.setTreePosition(self.model.DESTINATION_NAME)
        self.action.setRootIsDecorated(False)
        self.action.setIndentation(0)
        self.source.header().setSectionResizeMode(self.model.SOURCE_NAME, QHeaderView.ResizeMode.Stretch)
        self.source.header().setSectionResizeMode(self.model.SOURCE_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        self.source.header().setSectionResizeMode(self.model.SOURCE_TIME, QHeaderView.ResizeMode.ResizeToContents)
        self.action.header().setSectionResizeMode(
            self.model.ACTION, QHeaderView.ResizeMode.Stretch
        )
        self.destination.header().setSectionResizeMode(
            self.model.DESTINATION_NAME, QHeaderView.ResizeMode.Stretch
        )
        self.destination.header().setSectionResizeMode(
            self.model.DESTINATION_SIZE, QHeaderView.ResizeMode.ResizeToContents
        )
        self.destination.header().setSectionResizeMode(
            self.model.DESTINATION_TIME, QHeaderView.ResizeMode.ResizeToContents
        )

    def _synchronize(self) -> None:
        trees = (self.source, self.action, self.destination)
        for origin in trees:
            for target in trees:
                if origin is target:
                    continue
                origin.verticalScrollBar().valueChanged.connect(target.verticalScrollBar().setValue)
                origin.expanded.connect(lambda index, t=target: self._expand_in(t, index))
                origin.collapsed.connect(lambda index, t=target: self._collapse_in(t, index))
                origin.selectionModel().currentChanged.connect(
                    lambda current, _previous, t=target: self._set_current(t, current)
                )

    def _expand_in(self, tree: QTreeView, index: QModelIndex) -> None:
        """Mirror a user expansion into the other panes."""
        if self._syncing_expansion:
            # Programmatic expansion updates every pane at once. Mirroring it
            # row by row would relayout each tree once per row.
            return
        tree.expand(self._column_zero(index))

    def _collapse_in(self, tree: QTreeView, index: QModelIndex) -> None:
        """Mirror a user collapse into the other panes."""
        if self._syncing_expansion:
            return
        tree.collapse(self._column_zero(index))

    @contextmanager
    def _synced_expansion(self) -> Iterator[None]:
        self._syncing_expansion = True
        try:
            yield
        finally:
            self._syncing_expansion = False

    @staticmethod
    def _column_zero(index: QModelIndex) -> QModelIndex:
        return index.siblingAtColumn(0)

    @staticmethod
    def _set_current(tree: QTreeView, index: QModelIndex) -> None:
        if not index.isValid():
            return
        visible = next(
            (column for column in range(index.model().columnCount()) if not tree.isColumnHidden(column)),
            0,
        )
        target_index = index.siblingAtColumn(visible)
        if tree.currentIndex() == target_index:
            return
        tree.selectionModel().setCurrentIndex(
            target_index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
        )

    def select_path(self, path: str) -> None:
        """Select the object with the given path in the tree panes."""
        node = self._find_node(self.model.root, path)
        if node is None:
            return
        chain = []
        current = node
        while current is not None and current.parent is not None:
            chain.append(current)
            current = current.parent
        index = QModelIndex()
        for item in reversed(chain):
            index = self.model.index(item.row_index, 0, index)
        proxy_index = self.proxy.mapFromSource(index)
        if not proxy_index.isValid():
            return
        for tree in (self.source, self.action, self.destination):
            tree.expand(proxy_index)
            tree.setCurrentIndex(proxy_index)
            # The object should appear in the middle of the pane.
            tree.scrollTo(
                proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter
            )

    def _find_node(self, node: object, path: str) -> object | None:
        for child in getattr(node, "children", ()):  # type: ignore[arg-type]
            if getattr(child, "path", None) == path:
                return child
            found = self._find_node(child, path)
            if found is not None:
                return found
        return None

    def visible_changes(self) -> list[object]:
        """The items of the comparison that the action filters show."""
        visible = self.proxy.visible_paths()
        return [
            change
            for change in self.model.changes
            if str(getattr(change, "path", "")).rstrip("/") in visible
        ]

    def set_destination_metadata(
        self, metadata: dict[str, tuple[int | None, str | None]]
    ) -> None:
        """Show the size and the date of the listed destination items."""
        self._destination_metadata = dict(metadata)
        self.model.set_destination_metadata(self._destination_metadata)

    def set_changes(
        self, changes: list[object], *, preserve_expansion: bool = False
    ) -> None:
        expanded_paths = self._expanded_paths() if preserve_expansion else set()
        trees = (self.source, self.action, self.destination)
        for tree in trees:
            tree.setUpdatesEnabled(False)
            tree.setCurrentIndex(QModelIndex())
            tree.selectionModel().clear()
        self.model.set_changes(changes)  # type: ignore[arg-type]
        if self._destination_metadata:
            # The metadata belongs to the comparison, not to the rows.
            self.model.set_destination_metadata(self._destination_metadata)
        # A model reset alone leaves the proxy with the previous row mapping.
        # Without this the new items, for example the unchanged ones of an
        # inventory, would only appear after the next comparison.
        self.proxy.refresh_filters(force=True)
        self._sync_visible_sizes()
        self.changes_updated.emit(list(self.model.changes))

        def restore_views() -> None:
            with self._frozen_updates():
                if expanded_paths:
                    self._expand_paths(expanded_paths)
                else:
                    # Expanding every row of a large tree keeps the UI busy for a
                    # long time. Show the first level and let the user expand further.
                    self.expand_initial()

        # Do not repaint proxy indexes until Qt has completed the source reset.
        QTimer.singleShot(0, restore_views)

    @contextmanager
    def _frozen_updates(self) -> Iterator[None]:
        """Lay out the trees only once while rows are expanded or collapsed."""
        self._update_freeze += 1
        trees = (self.source, self.action, self.destination)
        if self._update_freeze == 1:
            for tree in trees:
                tree.setUpdatesEnabled(False)
        try:
            yield
        finally:
            self._update_freeze -= 1
            if self._update_freeze == 0:
                for tree in trees:
                    tree.setUpdatesEnabled(True)
                    tree.viewport().update()

    def _expanded_paths(self) -> set[str]:
        paths: set[str] = set()
        stack = [
            self.proxy.index(row, 0) for row in range(self.proxy.rowCount())
        ]
        while stack:
            index = stack.pop()
            if not index.isValid() or not self.source.isExpanded(index):
                continue
            path = self._source_path_for_proxy_index(index)
            if path:
                paths.add(path)
            stack.extend(
                self.proxy.index(row, 0, index)
                for row in range(self.proxy.rowCount(index))
            )
        return paths

    def _expand_paths(self, paths: set[str]) -> None:
        with self._synced_expansion():
            stack = [
                self.proxy.index(row, 0) for row in range(self.proxy.rowCount())
            ]
            while stack:
                index = stack.pop()
                if not index.isValid():
                    continue
                path = self._source_path_for_proxy_index(index)
                if path not in paths:
                    continue
                for tree in (self.source, self.action, self.destination):
                    tree.expand(index)
                stack.extend(
                    self.proxy.index(row, 0, index)
                    for row in range(self.proxy.rowCount(index))
                )

    def _sync_visible_sizes(self) -> None:
        """Let the folder sizes follow the rows that the filters show."""
        self.model.set_visible_paths(self.proxy.visible_paths())

    def set_action_filter(self, actions: set[ChangeAction] | None) -> None:
        """Show only the given actions and refresh the overview."""
        self.proxy.set_visible_actions(actions)
        self._sync_visible_sizes()
        # The overview counts the items that the filters show.
        self.changes_updated.emit(list(self.model.changes))

    def _refresh_action_filter(self) -> None:
        # A decision can change a destination-only row into a delete row, so
        # action filters may need re-evaluation. When no action filter is
        # active, only the cached visible-path set has to be invalidated.
        if self.proxy.visible_actions() is not None:
            self.proxy.refresh_filters()
        else:
            self.proxy.refresh_filters(force=False)
        self._sync_visible_sizes()
        # The overview counts the items that the filters show.
        self.changes_updated.emit(list(self.model.changes))

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

    def set_path_filter(self, text: str) -> None:
        self.proxy.set_path_filter(text)
        QTimer.singleShot(0, self._expand_visible_matches)

    def _expand_visible_matches(self, limit: int = 4000) -> None:
        """Expand only the visible matches and their ancestors.

        The previous implementation expanded every row after each keystroke,
        which made large comparisons unusable.
        """
        expanded = 0
        stack = [
            self.proxy.index(row, 0)
            for row in range(self.proxy.rowCount())
        ]
        stack.reverse()
        while stack and expanded < limit:
            index = stack.pop()
            if self.proxy.rowCount(index):
                for tree in (self.source, self.action, self.destination):
                    tree.expand(index)
                expanded += 1
                children = [
                    self.proxy.index(row, 0, index)
                    for row in range(self.proxy.rowCount(index))
                ]
                children.reverse()
                stack.extend(children)

    def set_expand_mode(self, mode: str) -> None:
        """Choose how the folders are opened after a comparison."""
        self._expand_mode = mode

    def expand_initial(self, limit: int = 20000) -> None:
        """Open the folders the way the settings ask for.

        Very large comparisons stay collapsed: expanding ten thousand rows
        once is fast, but the view would no longer be overviewable.
        """
        mode = self._expand_mode
        if mode == "none" or len(self.model.changes) > limit:
            return
        with self._frozen_updates(), self._synced_expansion():
            for tree in (self.source, self.action, self.destination):
                if mode == "first":
                    for row in range(tree.model().rowCount()):
                        index = tree.model().index(row, 0)
                        if tree.model().rowCount(index):
                            tree.expand(index)
                else:
                    tree.expandAll()

    def expand_all(self) -> None:
        with self._frozen_updates(), self._synced_expansion():
            for tree in (self.source, self.action, self.destination):
                tree.expandAll()

    def collapse_all(self) -> None:
        with self._frozen_updates(), self._synced_expansion():
            for tree in (self.source, self.action, self.destination):
                tree.collapseAll()

    def save_view_state(self) -> None:
        settings = app_settings()
        settings.setValue(
            "comparison/splitter", encode_binary(self.splitter.saveState())
        )
        settings.setValue(
            "comparison/source-header",
            encode_binary(self.source.header().saveState()),
        )
        settings.setValue(
            "comparison/destination-header",
            encode_binary(self.destination.header().saveState()),
        )
        settings.sync()

    def _restore_view_state(self) -> None:
        settings = app_settings()
        state = decode_binary(settings.value("comparison/splitter"))
        if state is not None:
            self.splitter.restoreState(state)
        else:
            self.splitter.setSizes([450, ACTION_PANE_WIDTH, 450])
        source = decode_binary(settings.value("comparison/source-header"))
        destination = decode_binary(settings.value("comparison/destination-header"))
        if source is not None:
            self.source.header().restoreState(source)
        if destination is not None:
            self.destination.header().restoreState(destination)
        # A header state written by an older version also restores whether the
        # sections are clickable. The panes must stay sortable, so the flags
        # are applied again after the sizes and the hidden columns.
        for header in (
            self.source.header(),
            self.action.header(),
            self.destination.header(),
        ):
            header.setSectionsMovable(False)
            header.setSectionsClickable(True)
            header.setSortIndicatorShown(True)

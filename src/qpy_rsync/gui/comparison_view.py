from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .change_filter_proxy import ChangeTreeFilterProxyModel
from .change_tree_model import ChangeTreeModel


class ComparisonView(QWidget):
    """Synchronized source/action/destination tree panes."""

    diff_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = ChangeTreeModel(self)
        self.proxy = ChangeTreeFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.source = self._tree("Source")
        self.action = self._tree("Action")
        self.destination = self._tree("Destination")
        self._configure_columns()
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.source)
        self.splitter.addWidget(self.action)
        self.splitter.addWidget(self.destination)
        controls = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter changed paths")
        expand = QPushButton("Expand All")
        collapse = QPushButton("Collapse All")
        controls.addWidget(self.filter_edit, 1)
        controls.addWidget(expand)
        controls.addWidget(collapse)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        layout.addWidget(self.splitter)
        self.filter_edit.textChanged.connect(self.set_path_filter)
        expand.clicked.connect(self.expand_all)
        collapse.clicked.connect(self.collapse_all)
        self.splitter.splitterMoved.connect(lambda _position, _index: self.save_view_state())
        self.source.header().sectionResized.connect(lambda _logical, _old, _new: self.save_view_state())
        self.destination.header().sectionResized.connect(
            lambda _logical, _old, _new: self.save_view_state()
        )
        self._restore_view_state()
        self._synchronize()

    def _tree(self, label: str) -> QTreeView:
        tree = QTreeView()
        tree.setModel(self.proxy)
        tree.setObjectName(label.lower())
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tree.setSortingEnabled(False)
        tree.header().setStretchLastSection(False)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(lambda point, t=tree: self._show_context_menu(t, point))
        tree.doubleClicked.connect(self._request_diff)
        return tree

    def _show_context_menu(self, tree: QTreeView, point: object) -> None:
        index = tree.indexAt(point)
        if not index.isValid():
            return
        menu = QMenu(tree)
        action = menu.addAction("Open in Diff Tool")
        action.setEnabled(self._change_for_index(index) is not None)
        selected = menu.exec(tree.viewport().mapToGlobal(point))
        if selected is action:
            self._request_diff(index)

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
        self.action.setItemsExpandable(False)
        self.source.header().setSectionResizeMode(self.model.SOURCE_NAME, QHeaderView.ResizeMode.Stretch)
        self.source.header().setSectionResizeMode(self.model.SOURCE_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        self.source.header().setSectionResizeMode(self.model.SOURCE_TIME, QHeaderView.ResizeMode.ResizeToContents)
        self.action.header().setSectionResizeMode(self.model.ACTION, QHeaderView.ResizeMode.Stretch)
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
                origin.expanded.connect(lambda index, t=target: t.expand(self._column_zero(index)))
                origin.collapsed.connect(lambda index, t=target: t.collapse(self._column_zero(index)))
                origin.selectionModel().currentChanged.connect(
                    lambda current, _previous, t=target: self._set_current(t, current)
                )

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

    def set_changes(self, changes: list[object]) -> None:
        self.model.set_changes(changes)  # type: ignore[arg-type]
        # Expansion before the view processes the model reset can leave deep
        # synthetic parent nodes collapsed. Queue it for the next event turn.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.expand_all)

    def set_path_filter(self, text: str) -> None:
        self.proxy.set_path_filter(text)
        if text.strip():
            self.expand_all()

    def expand_all(self) -> None:
        for tree in (self.source, self.action, self.destination):
            tree.expandAll()

    def collapse_all(self) -> None:
        for tree in (self.source, self.action, self.destination):
            tree.collapseAll()

    def save_view_state(self) -> None:
        settings = QSettings()
        settings.setValue("comparison/splitter", self.splitter.saveState())
        settings.setValue("comparison/source-header", self.source.header().saveState())
        settings.setValue("comparison/destination-header", self.destination.header().saveState())
        settings.sync()

    def _restore_view_state(self) -> None:
        settings = QSettings()
        state = settings.value("comparison/splitter")
        if state is not None:
            self.splitter.restoreState(state)
        else:
            self.splitter.setSizes([450, 150, 450])
        source = settings.value("comparison/source-header")
        destination = settings.value("comparison/destination-header")
        if source is not None:
            self.source.header().restoreState(source)
        if destination is not None:
            self.destination.header().restoreState(destination)

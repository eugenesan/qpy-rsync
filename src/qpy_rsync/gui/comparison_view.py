from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QSplitter, QTreeView, QWidget

from .change_tree_model import ChangeTreeModel


class ComparisonView(QWidget):
    """Synchronized source/action/destination tree panes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = ChangeTreeModel(self)
        self.source = self._tree("Source")
        self.action = self._tree("Action")
        self.destination = self._tree("Destination")
        self._configure_columns()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.source)
        splitter.addWidget(self.action)
        splitter.addWidget(self.destination)
        splitter.setSizes([450, 150, 450])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self._synchronize()

    def _tree(self, label: str) -> QTreeView:
        tree = QTreeView()
        tree.setModel(self.model)
        tree.setObjectName(label.lower())
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tree.setSortingEnabled(False)
        tree.header().setStretchLastSection(True)
        return tree

    def _configure_columns(self) -> None:
        source_columns = {0, 1, 2}
        action_columns = {3}
        destination_columns = {4, 5, 6}
        for column in range(self.model.COLUMN_COUNT):
            self.source.setColumnHidden(column, column not in source_columns)
            self.action.setColumnHidden(column, column not in action_columns)
            self.destination.setColumnHidden(column, column not in destination_columns)
        self.action.setRootIsDecorated(False)
        self.action.setItemsExpandable(False)
        self.source.setColumnWidth(0, 260)
        self.destination.setColumnWidth(4, 260)

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
        self.source.expandAll()
        self.action.expandAll()
        self.destination.expandAll()

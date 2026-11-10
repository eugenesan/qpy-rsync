from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QSettings, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .change_filter_proxy import ChangeTreeFilterProxyModel
from .change_tree_model import ChangeTreeModel
from qpy_rsync.core.changes import ChangeAction


class ComparisonView(QWidget):
    """Synchronized source/action/destination tree panes."""

    diff_requested = Signal(object)
    decision_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = ChangeTreeModel(self)
        self.source_root = ""
        self.model.decision_changed.connect(self.decision_changed)
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
        self.expand_button = QPushButton("[v]")
        self.expand_button.setToolTip("Expand all comparison paths")
        self.expand_button.setAccessibleName("Expand all comparison paths")
        self.collapse_button = QPushButton("[^]")
        self.collapse_button.setToolTip("Collapse all comparison paths")
        self.collapse_button.setAccessibleName("Collapse all comparison paths")
        self.controls = QWidget(self)
        self.controls.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.filter_button = QPushButton("Filter/Find")
        self.filter_button.setToolTip("Focus the comparison path filter")
        self.filter_button.clicked.connect(self.focus_path_filter)
        controls.addWidget(self.filter_button)
        controls.addWidget(self.filter_edit, 1)
        controls.addWidget(self.expand_button)
        controls.addWidget(self.collapse_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)
        self.filter_edit.textChanged.connect(self.set_path_filter)
        self.expand_button.clicked.connect(self.expand_all)
        self.collapse_button.clicked.connect(self.collapse_all)
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
        is_unchanged = change is not None and getattr(change, "action", None) is ChangeAction.NO_CHANGE
        menu = QMenu(tree)
        copy_path_action = None
        diff_action = None
        reset_one = reset_subtree = reset_all = None
        if is_unchanged:
            copy_path_action = menu.addAction("Copy Path")
            copy_path_action.setEnabled(path is not None)
        else:
            diff_action = menu.addAction("Open in Diff Tool")
            diff_action.setEnabled(change is not None)
            if tree is self.action and path is not None:
                menu.addSeparator()
                reset_one = menu.addAction("Reset This Decision")
                reset_subtree = menu.addAction("Reset Subtree Decisions")
                reset_all = menu.addAction("Reset All Decisions")
                reset_all.setEnabled(self.model.decisions.has_explicit())
        selected = menu.exec(tree.viewport().mapToGlobal(point))
        if selected is diff_action:
            self._request_diff(index)
        elif selected is copy_path_action and path is not None:
            from PySide6.QtWidgets import QApplication

            root = getattr(self, "source_root", "")
            full_path = f"{root}/{path}" if root else path
            if root and root.endswith("/"):
                full_path = f"{root}{path}"
            QApplication.clipboard().setText(full_path)
        elif selected is reset_one and path is not None:
            self.model.reset_decision(path)
        elif selected is reset_subtree and path is not None:
            self.model.reset_subtree_decisions(path)
        elif selected is reset_all:
            answer = QMessageBox.question(
                self,
                "Reset all decisions",
                "Reset every manual checkbox decision to its inherited default?",
                QMessageBox.StandardButton.Reset | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Reset:
                self.model.reset_all_decisions()

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
        trees = (self.source, self.action, self.destination)
        for tree in trees:
            tree.setUpdatesEnabled(False)
            tree.setCurrentIndex(QModelIndex())
            tree.selectionModel().clear()
        self.model.set_changes(changes)  # type: ignore[arg-type]

        def restore_views() -> None:
            for tree in trees:
                tree.setUpdatesEnabled(True)
                tree.viewport().update()
            self.expand_all()

        # Do not repaint proxy indexes until Qt has completed the source reset.
        QTimer.singleShot(0, restore_views)

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
        # A proxy reset collapses every view. Expand after Qt finishes the
        # reset, for both a populated filter and a cleared filter.
        QTimer.singleShot(0, self.expand_all)

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

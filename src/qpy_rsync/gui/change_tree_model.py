from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ChangeDecisions

from .icons import ACTION_LABELS, action_icon


@dataclass(slots=True)
class TreeNode:
    name: str
    path: str
    parent: "TreeNode | None" = None
    change: Change | None = None
    children: list["TreeNode"] = field(default_factory=list)
    row_index: int = 0
    subtree_only_destination: bool = False

    def child(self, row: int) -> "TreeNode":
        return self.children[row]

    def row(self) -> int:
        return self.row_index


class ChangeTreeModel(QAbstractItemModel):
    decision_changed = Signal()
    SOURCE_NAME = 0
    SOURCE_SIZE = 1
    SOURCE_TIME = 2
    ACTION = 3
    DESTINATION_NAME = 4
    DESTINATION_SIZE = 5
    DESTINATION_TIME = 6
    COLUMN_COUNT = 7
    HEADERS = ("File/Directory", "Size", "Modified", "Action", "File/Directory", "Size", "Modified")

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.root = TreeNode("", "")
        self.decisions = ChangeDecisions()
        self.changes: list[Change] = []
        self.discarded_decisions = 0
        self.decisions_enabled = True
        self.stale = False
        self._action_header = "Action"
        self._override_paths: set[str] = set()

    def set_changes(self, changes: list[Change]) -> None:
        self.beginResetModel()
        self.changes = list(changes)
        self.discarded_decisions = self.decisions.reconcile(self.changes)
        self.root = TreeNode("", "")
        nodes: dict[str, TreeNode] = {"": self.root}
        for change in sorted(changes, key=lambda item: (item.path.count("/"), item.path)):
            clean_path = change.path.rstrip("/")
            parts = PurePosixPath(clean_path).parts
            current_path = ""
            parent = self.root
            for part in parts:
                current_path = f"{current_path}/{part}".lstrip("/")
                node = nodes.get(current_path)
                if node is None:
                    node = TreeNode(part, current_path, parent)
                    parent.children.append(node)
                    nodes[current_path] = node
                parent = node
            parent.change = change
        self._compute_subtree_flags(self.root)
        self._sort(self.root)
        self._assign_rows(self.root)
        self._override_paths = self.decisions.override_paths(self.changes)
        self.endResetModel()
        self._refresh_action_header()

    def _compute_subtree_flags(self, node: TreeNode) -> bool:
        """Return whether every change in this subtree is destination-only."""
        has_change = node.change is not None
        only_destination = (
            node.change is not None
            and node.change.action is ChangeAction.DESTINATION_ONLY
        )
        for child in node.children:
            child_only = self._compute_subtree_flags(child)
            child_has = child.change is not None or bool(child.children)
            only_destination = only_destination and child_only
            has_change = has_change or child_has
        node.subtree_only_destination = has_change and only_destination
        return node.subtree_only_destination

    def _sort(self, node: TreeNode) -> None:
        node.children.sort(key=lambda child: (not child.children, child.name.casefold()))
        for child in node.children:
            self._sort(child)

    def _assign_rows(self, node: TreeNode) -> None:
        for row, child in enumerate(node.children):
            child.row_index = row
            self._assign_rows(child)

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:  # noqa: B008
        parent_node = parent.internalPointer() if parent.isValid() else self.root
        if not 0 <= row < len(parent_node.children):
            return QModelIndex()
        return self.createIndex(row, column, parent_node.child(row))

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node: TreeNode = index.internalPointer()
        parent = node.parent
        if parent is None or parent is self.root:
            return QModelIndex()
        return self.createIndex(parent.row(), 0, parent)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        if parent.isValid() and parent.column() != 0:
            return 0
        node = parent.internalPointer() if parent.isValid() else self.root
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: ARG002, B008, N802
        return self.COLUMN_COUNT

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == self.ACTION:
                return self._action_header
            return self.HEADERS[section]
        return None

    def _refresh_action_header(self) -> None:
        modified = len(self._override_paths)
        self._action_header = (
            f"Action* ({modified} modified)" if modified else "Action"
        )
        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal, self.ACTION, self.ACTION
        )

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        node: TreeNode = index.internalPointer()
        change = node.change
        source_present = change is None or change.action is not ChangeAction.DESTINATION_ONLY
        destination_present = change is None or change.action is not ChangeAction.CREATE
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == self.SOURCE_NAME:
                return node.name if source_present else ""
            if index.column() == self.DESTINATION_NAME:
                return node.name if destination_present else ""
            if index.column() == self.ACTION:
                # Icons carry the action. Keeping the cell text empty leaves
                # maximum room for object names in the tree panes.
                return ""
            if change is None:
                return ""
            if index.column() == self.SOURCE_SIZE:
                return self._size(change.size) if source_present else ""
            if index.column() == self.DESTINATION_SIZE:
                return self._size(change.size) if change.action is ChangeAction.DESTINATION_ONLY else ""
            if index.column() == self.SOURCE_TIME:
                return change.modified_time or "" if source_present else ""
            if index.column() == self.DESTINATION_TIME:
                return ""  # rsync itemized output does not provide destination mtime.
        if role == Qt.ItemDataRole.DecorationRole and index.column() == self.ACTION:
            return self._decoration_for(node)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip_for(node, index.column())
        if (
            role == Qt.ItemDataRole.ForegroundRole
            and change is not None
            and index.column() != self.ACTION
        ):
            if change.action is ChangeAction.CREATE:
                return QColor("#208020")
            if change.action is ChangeAction.DESTINATION_ONLY:
                return QColor("#a05020")
        if (
            role == Qt.ItemDataRole.CheckStateRole
            and index.column() == self.ACTION
            and self._node_selectable(node)
        ):
            return (
                Qt.CheckState.Checked
                if self._effective_node(node) is ChangeDecision.INCLUDE
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.UserRole:
            return change
        if role == Qt.ItemDataRole.UserRole + 1:
            return self.decisions.explicit(node.path)
        return None

    def _tooltip_for(self, node: TreeNode, column: int) -> str:
        change = node.change
        if change is None:
            return node.path
        if column == self.ACTION:
            label = ACTION_LABELS.get(self.effective_action(node), "")
            details = f"{label}\n{change.itemized_code}: {change.reason}" if label else f"{change.itemized_code}: {change.reason}"
            return f"{change.path}\n{details}"
        return change.path

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.column() == self.ACTION:
            node: TreeNode = index.internalPointer()
            if self.decisions_enabled and self._node_selectable(node):
                flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not self.decisions_enabled:
            return False
        if role != Qt.ItemDataRole.CheckStateRole or not index.isValid() or index.column() != self.ACTION:
            return False
        node: TreeNode = index.internalPointer()
        if not self._node_selectable(node):
            return False
        state = Qt.CheckState(value)
        decision = (
            ChangeDecision.INCLUDE
            if state is Qt.CheckState.Checked
            else ChangeDecision.EXCLUDE
        )
        self.decisions.set(node.path, decision)
        self._override_paths = self.decisions.override_paths(self.changes)
        if node.children:
            # A whole subtree changed; refresh only the visible viewport rather
            # than emitting one signal per descendant row. The signals must be
            # paired, otherwise proxy persistent indexes (selection, current
            # item) are left dangling and later selection changes can crash.
            self.layoutAboutToBeChanged.emit()
            self.layoutChanged.emit()
        else:
            self.dataChanged.emit(
                index,
                index,
                [
                    Qt.ItemDataRole.CheckStateRole,
                    Qt.ItemDataRole.UserRole + 1,
                    Qt.ItemDataRole.DecorationRole,
                ],
            )
        self.decision_changed.emit()
        self._refresh_action_header()
        return True

    def effective_action(self, node: TreeNode) -> ChangeAction:
        change = node.change
        if change is None:
            return ChangeAction.NO_CHANGE
        action = change.action
        if (
            action is ChangeAction.DESTINATION_ONLY
            and self._effective_node(node) is ChangeDecision.INCLUDE
        ):
            return ChangeAction.DELETE
        return action

    def _decoration_for(self, node: TreeNode) -> Any:
        change = node.change
        action = self.effective_action(node)
        overridden = (not self.stale) and node.path in self._override_paths
        if change is None:
            # A directory present on both sides carries no own action.
            return action_icon(ChangeAction.NO_CHANGE)
        return action_icon(action, accent=overridden)

    def _node_selectable(self, node: TreeNode) -> bool:
        if node.change is None:
            return bool(node.children)
        return self.decisions.selectable(node.change)

    def _effective_node(self, node: TreeNode) -> ChangeDecision:
        inherited = self.decisions.inherited(node.path)
        if inherited is not None:
            return inherited
        if node.change is not None:
            return self.decisions.effective(node.change)
        if node.children and node.subtree_only_destination:
            return ChangeDecision.EXCLUDE
        return ChangeDecision.INCLUDE

    def reset_decision(self, path: str) -> None:
        self.decisions.reset(path)
        self._refresh_decisions()

    def reset_subtree_decisions(self, path: str) -> None:
        self.decisions.reset_subtree(path)
        self._refresh_decisions()

    def reset_all_decisions(self) -> None:
        self.decisions.clear()
        self._refresh_decisions()

    def _refresh_decisions(self) -> None:
        self._override_paths = self.decisions.override_paths(self.changes)
        self.layoutAboutToBeChanged.emit()
        self.layoutChanged.emit()
        self.decision_changed.emit()
        self._refresh_action_header()

    def decision_summary(self):
        return self.decisions.summary(self.changes)

    @staticmethod
    def _size(size: int | None) -> str:
        if size is None:
            return ""
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return ""

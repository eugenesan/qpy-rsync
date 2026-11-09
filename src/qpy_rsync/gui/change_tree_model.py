from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ChangeDecisions


@dataclass(slots=True)
class TreeNode:
    name: str
    path: str
    parent: "TreeNode | None" = None
    change: Change | None = None
    children: list["TreeNode"] = field(default_factory=list)

    def child(self, row: int) -> "TreeNode":
        return self.children[row]

    def row(self) -> int:
        return 0 if self.parent is None else self.parent.children.index(self)


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
        self._sort(self.root)
        self.endResetModel()

    def _sort(self, node: TreeNode) -> None:
        node.children.sort(key=lambda child: (not child.children, child.name.casefold()))
        for child in node.children:
            self._sort(child)

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
            return self.HEADERS[section]
        return None

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
                if change is None:
                    return ""
                action = change.action
                if (
                    action is ChangeAction.DESTINATION_ONLY
                    and self._effective_node(node) is ChangeDecision.INCLUDE
                ):
                    action = ChangeAction.DELETE
                return self._action_text(action, stale=self.stale)
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
        if role == Qt.ItemDataRole.ToolTipRole and change is not None:
            return f"{change.itemized_code}: {change.reason}"
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
        self.dataChanged.emit(
            index,
            index,
            [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.UserRole + 1],
        )
        self._emit_descendant_check_states(index.siblingAtColumn(0))
        self.decision_changed.emit()
        return True

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
        descendant_changes = list(self._descendant_changes(node))
        if descendant_changes and all(
            change.action is ChangeAction.DESTINATION_ONLY
            for change in descendant_changes
        ):
            return ChangeDecision.EXCLUDE
        return ChangeDecision.INCLUDE

    def _descendant_changes(self, node: TreeNode):
        for child in node.children:
            if child.change is not None:
                yield child.change
            yield from self._descendant_changes(child)

    def _emit_descendant_check_states(self, parent: QModelIndex) -> None:
        rows = self.rowCount(parent)
        if rows == 0:
            return
        first = self.index(0, self.ACTION, parent)
        last = self.index(rows - 1, self.ACTION, parent)
        self.dataChanged.emit(first, last, [Qt.ItemDataRole.CheckStateRole])
        for row in range(rows):
            self._emit_descendant_check_states(self.index(row, 0, parent))

    def reset_decision(self, path: str) -> None:
        self.decisions.reset(path)
        self._emit_all_check_states()
        self.decision_changed.emit()

    def reset_subtree_decisions(self, path: str) -> None:
        self.decisions.reset_subtree(path)
        self._emit_all_check_states()
        self.decision_changed.emit()

    def reset_all_decisions(self) -> None:
        self.decisions.clear()
        self._emit_all_check_states()
        self.decision_changed.emit()

    def _emit_all_check_states(self) -> None:
        rows = self.rowCount()
        if rows:
            self.dataChanged.emit(
                self.index(0, self.ACTION),
                self.index(rows - 1, self.ACTION),
                [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.UserRole + 1],
            )
        for row in range(rows):
            self._emit_descendant_check_states(self.index(row, 0))

    def decision_summary(self):
        return self.decisions.summary(self.changes)

    @staticmethod
    def _action_text(action: ChangeAction, *, stale: bool = False) -> str:
        fresh = {
            ChangeAction.CREATE: "→ create",
            ChangeAction.UPDATE_CONTENT: "→ update",
            ChangeAction.UPDATE_METADATA: "→ metadata",
            ChangeAction.DELETE: "× delete",
            ChangeAction.DESTINATION_ONLY: "keep ←",
            ChangeAction.REPLACE: "→ replace",
            ChangeAction.NO_CHANGE: "=",
            ChangeAction.MESSAGE: "!",
        }
        stale_text = {
            ChangeAction.CREATE: "create",
            ChangeAction.UPDATE_CONTENT: "update",
            ChangeAction.UPDATE_METADATA: "metadata",
            ChangeAction.DELETE: "delete",
            ChangeAction.DESTINATION_ONLY: "keep",
            ChangeAction.REPLACE: "replace",
            ChangeAction.NO_CHANGE: "unchanged",
            ChangeAction.MESSAGE: "message",
        }
        return (stale_text if stale else fresh)[action]

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

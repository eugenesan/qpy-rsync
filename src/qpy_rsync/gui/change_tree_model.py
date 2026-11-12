from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont

from qpy_rsync.core.units import format_size
from qpy_rsync.core.changes import (
    Change,
    ChangeAction,
    ChangeDecision,
    ChangeDecisions,
    ObjectKind,
)

from .icons import (
    ACTION_LABELS,
    action_icon,
    file_type_icon,
    folder_icon,
    folder_sync_icon,
    unchanged_icon,
)

ACTION_HEADER_ACCENT = "#0891B2"


def full_path(root: str, path: str) -> str:
    """Join an endpoint root and a relative comparison path."""
    clean_root = root.rstrip("/")
    clean_path = path.strip("/")
    if not clean_root:
        return clean_path
    if not clean_path:
        return clean_root
    return f"{clean_root}/{clean_path}"


@dataclass(slots=True)
class TreeNode:
    name: str
    path: str
    parent: "TreeNode | None" = None
    change: Change | None = None
    children: list["TreeNode"] = field(default_factory=list)
    row_index: int = 0
    subtree_only_destination: bool = False
    # The size of everything below a folder, so a folder row reports its
    # contents instead of the size of the directory itself.
    subtree_size: int = 0
    subtree_destination_size: int = 0

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
        self.source_root = ""
        self.destination_root = ""
        self.discarded_decisions = 0
        self.decisions_enabled = True
        self.stale = False
        self._action_header = "Actions"
        self._action_header_tooltip = "Actions"
        self._modified_count = 0
        self._destination_metadata: dict[str, tuple[int | None, str | None]] = {}
        self._visible_paths: set[str] | None = None
        self._sort_column = self.SOURCE_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder
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
        self._compute_sizes(self.root)
        self._sort(self.root)
        self._assign_rows(self.root)
        self._override_paths = self.decisions.override_paths(self.changes)
        self.endResetModel()
        self._refresh_action_header()

    def _compute_sizes(self, node: TreeNode) -> tuple[int, int]:
        """Sum the sizes of the items below a folder."""
        source_total = 0
        destination_total = 0
        for child in node.children:
            child_source, child_destination = self._compute_sizes(child)
            source_total += child_source
            destination_total += child_destination
        if (
            not node.children
            and node.change is not None
            and (self._visible_paths is None or node.path in self._visible_paths)
        ):
            change = node.change
            source_total += int(change.size or 0)
            destination_total += int(self._destination_size(change))
        node.subtree_size = source_total
        node.subtree_destination_size = destination_total
        return source_total, destination_total

    def _destination_size(self, change: Change) -> int:
        if change.destination_size is not None:
            return int(change.destination_size)
        size, _time = self._destination_info(change.path.rstrip("/"))
        return int(size or 0)

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
        node.children.sort(key=lambda child: self._sort_key(child, self._sort_column))
        if self._sort_order == Qt.SortOrder.DescendingOrder:
            node.children.reverse()
        for child in node.children:
            self._sort(child)

    def _is_directory(self, node: TreeNode) -> bool:
        if node.change is not None:
            return node.change.kind is ObjectKind.DIRECTORY
        return bool(node.children)

    def _size_value(self, node: TreeNode, column: int) -> int | None:
        if node.children:
            # A folder reports the objects it contains, not the size of its
            # own directory record.
            return (
                node.subtree_size
                if column == self.SOURCE_SIZE
                else node.subtree_destination_size
            )
        change = node.change
        if change is None:
            return None
        if column == self.SOURCE_SIZE:
            return change.size
        if change.destination_size is not None:
            return change.destination_size
        size, _time = self._destination_info(node.path)
        return size

    def _time_value(self, node: TreeNode, column: int) -> str | None:
        change = node.change
        if change is None:
            return None
        if column == self.SOURCE_TIME:
            return change.modified_time
        if change.destination_time:
            return change.destination_time
        _size, time = self._destination_info(node.path)
        return time

    def _sort_key(self, node: TreeNode, column: int) -> tuple:
        """Return the key a row is sorted by.

        The name is the tie breaker, so the order stays stable.
        """
        name = node.name.casefold()
        if column in (self.SOURCE_NAME, self.DESTINATION_NAME):
            # Directories come first, the way the tree is built.
            return (0 if self._is_directory(node) else 1, name)
        if column in (self.SOURCE_SIZE, self.DESTINATION_SIZE):
            size = self._size_value(node, column)
            return (size if size is not None else -1, name)
        if column in (self.SOURCE_TIME, self.DESTINATION_TIME):
            return (self._time_value(node, column) or "", name)
        if column == self.ACTION:
            action = self.effective_action(node)
            return (ACTION_LABELS.get(action, action.value).casefold(), name)
        return (name,)

    def sort_column(self) -> int:
        """Return the column the tree is sorted by."""
        return self._sort_column

    def sort_order(self) -> Qt.SortOrder:
        """Return the order the tree is sorted in."""
        return self._sort_order

    def sort_key_for_index(self, index: QModelIndex, column: int) -> tuple:
        """Return the key a row is sorted by, for the proxy."""
        if not index.isValid():
            return ("",)
        node: TreeNode = index.internalPointer()
        return self._sort_key(node, column)

    def sort(  # noqa: A003
        self,
        column: int,
        order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
    ) -> None:
        """Sort every level of the tree by the given column.

        A view without a sorted column asks for ``-1``; that request is
        ignored, so a queued sort cannot undo the order of the tree.
        """
        if column < 0:
            return
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._sort(self.root)
        self._assign_rows(self.root)
        self.layoutChanged.emit()

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
        if orientation == Qt.Orientation.Horizontal:
            if section == self.ACTION:
                if role == Qt.ItemDataRole.DisplayRole:
                    return self._action_header
                if role == Qt.ItemDataRole.ToolTipRole:
                    return self._action_header_tooltip
                if role == Qt.ItemDataRole.ForegroundRole and self._modified_count:
                    return QColor(ACTION_HEADER_ACCENT)
                return None
            if role == Qt.ItemDataRole.DisplayRole:
                return self.HEADERS[section]
        return None

    def _refresh_action_header(self) -> None:
        modified = len(self._override_paths)
        self._modified_count = modified
        # The header stays short so it fits into the fixed action column. The
        # number of modified decisions is shown in the header tooltip.
        self._action_header = "Actions*" if modified else "Actions"
        self._action_header_tooltip = (
            f"Actions* ({modified} modified)" if modified else "Actions"
        )
        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal, self.ACTION, self.ACTION
        )

    def set_visible_paths(self, paths: set[str] | None) -> None:
        """Restrict the folder sizes to the rows that the filters show.

        A folder row must not claim more bytes than the rows below it. The
        objects that a display filter hides no longer add to the total, and
        the unchanged objects add to it as soon as the inventory lists them.
        """
        self._visible_paths = None if paths is None else set(paths)
        self._compute_sizes(self.root)
        if not self.root.children:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self.root.children) - 1, self.COLUMN_COUNT - 1),
            [Qt.ItemDataRole.DisplayRole],
        )

    def set_destination_metadata(
        self, metadata: dict[str, tuple[int | None, str | None]]
    ) -> None:
        """Remember the size and the date of the listed destination items."""
        self._destination_metadata = dict(metadata)
        self._compute_sizes(self.root)
        if not self.root.children:
            return
        top = self.index(0, 0)
        if not top.isValid():
            return
        self.dataChanged.emit(
            top,
            self.index(len(self.root.children) - 1, self.COLUMN_COUNT - 1),
            [Qt.ItemDataRole.DisplayRole],
        )

    def _destination_info(self, path: str) -> tuple[int | None, str | None]:
        return self._destination_metadata.get(path, (None, None))

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
            if index.column() == self.SOURCE_SIZE:
                if not source_present:
                    return ""
                return self._size(self._size_value(node, self.SOURCE_SIZE))
            if index.column() == self.DESTINATION_SIZE:
                if not destination_present:
                    return ""
                return self._size(self._size_value(node, self.DESTINATION_SIZE))
            if change is None:
                return ""
            if index.column() == self.SOURCE_TIME:
                return change.modified_time or "" if source_present else ""
            if index.column() == self.DESTINATION_TIME:
                # The itemized output of a comparison does not carry the
                # modification time of the destination. An inventory knows it.
                if change.destination_time:
                    return change.destination_time
                _size, time = self._destination_info(node.path)
                return time or ""
        if role == Qt.ItemDataRole.DecorationRole:
            if index.column() == self.ACTION:
                return self._decoration_for(node)
            if index.column() in (self.SOURCE_NAME, self.DESTINATION_NAME):
                return self._item_icon(node)
        if (
            role == Qt.ItemDataRole.FontRole
            and change is not None
            and change.action is not ChangeAction.NO_CHANGE
            and index.column() != self.ACTION
        ):
            font = QFont()
            font.setBold(True)
            return font
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
        source_full = full_path(self.source_root, node.path)
        destination_full = full_path(self.destination_root, node.path)
        destination_column = column in {
            self.DESTINATION_NAME,
            self.DESTINATION_SIZE,
            self.DESTINATION_TIME,
        }
        if column == self.ACTION:
            if change is None:
                return f"Source: {source_full}\nDestination: {destination_full}"
            label = ACTION_LABELS.get(self.effective_action(node), "")
            details = (
                f"{label}\n{change.itemized_code}: {change.reason}"
                if label
                else f"{change.itemized_code}: {change.reason}"
            )
            return (
                f"Source: {source_full}\n"
                f"Destination: {destination_full}\n"
                f"{details}"
            )
        if destination_column:
            return destination_full
        return source_full

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
        if node.children or (change is not None and change.kind is ObjectKind.DIRECTORY):
            if action is ChangeAction.NO_CHANGE:
                # A directory present on both sides.
                return folder_sync_icon()
            return action_icon(action, accent=overridden)
        if action is ChangeAction.NO_CHANGE:
            # An unchanged item carries the tribar, not the equals of a folder.
            return unchanged_icon()
        return action_icon(action, accent=overridden)

    @staticmethod
    def _item_icon(node: TreeNode) -> Any:
        """Icon of the name columns: a folder or the type of the file."""
        if node.children or (
            node.change is not None and node.change.kind is ObjectKind.DIRECTORY
        ):
            return folder_icon()
        if node.change is not None and node.change.kind is ObjectKind.SYMLINK:
            return file_type_icon("link")
        return file_type_icon(node.name)

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
        return format_size(size)

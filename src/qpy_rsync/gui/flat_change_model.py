"""A flat comparison model, modelled after the FreeFileSync file grid.

FreeFileSync never builds a tree for the comparison. It keeps a flat list of
items and draws the directory hierarchy itself: the items of one directory
form a group, and the group header carries the path. This module does the
same, but the groups are real rows, so a directory can be pointed at and
acted on.

The model is a plain table model, so the views ask for the rows they paint
and nothing else. An eighty thousand item comparison therefore costs the
same as a small one.

The decisions are keyed by path in :mod:`qpy_rsync.core.changes`, so they
work with the flat rows without a change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont

from qpy_rsync.core.changes import (
    Change,
    ChangeAction,
    ChangeDecision,
    ChangeDecisions,
    HiddenItems,
    ObjectKind,
)
from qpy_rsync.core.units import format_size

from .change_tree_model import full_path
from .icons import (
    ACTION_LABELS,
    action_icon,
    file_type_icon,
    folder_icon,
    folder_sync_changed_icon,
    folder_sync_icon,
    unchanged_faded_icon,
)

ACTION_HEADER_ACCENT = "#0891B2"

# Role that carries the comparison path of a row. A directory row has no
# change of its own, so the path cannot be taken from the change.
PATH_ROLE = Qt.ItemDataRole.UserRole + 2


@dataclass(slots=True)
class FlatDirectory:
    """One directory of the comparison."""

    path: str
    name: str
    parent: str
    depth: int
    child_directories: list[str] = field(default_factory=list)
    files: list[int] = field(default_factory=list)
    # The change of the directory itself, when the comparison reported one.
    own_change: Change | None = None
    # The index of that change in the change list, or -1.
    own_change_index: int = -1
    # True when the directory holds anything at all.
    has_children: bool = False
    # Totals of the rows the filters show below this directory.
    subtree_items: int = 0
    subtree_size: int = 0
    subtree_destination_size: int = 0
    # Totals of the whole subtree, independent of the filters.
    subtree_changed: int = 0
    # Filled in while the filters run.
    path_ok: bool = False
    action_ok: bool = False
    visible: bool = False


@dataclass(slots=True)
class FlatRow:
    """One row of the flat list."""

    path: str
    name: str
    parent: str
    depth: int
    is_directory: bool
    change: Change | None
    # The index of the change in the change list, or -1 for a directory
    # without a change of its own.
    change_index: int
    # The directory the row belongs to.
    group: str


class FlatChangeModel(QAbstractTableModel):
    """The comparison as a flat list of directory groups and items.

    The rows are laid out the way the tree shows them when everything is
    expanded: a directory, the directories below it, then the items of the
    directory. The hierarchy is only painted; the model never expands
    anything.
    """

    decision_changed = Signal()

    SOURCE_NAME = 0
    SOURCE_ITEMS = 1
    SOURCE_SIZE = 2
    SOURCE_TIME = 3
    ACTION = 4
    DESTINATION_NAME = 5
    DESTINATION_ITEMS = 6
    DESTINATION_SIZE = 7
    DESTINATION_TIME = 8
    COLUMN_COUNT = 9
    HEADERS = (
        "Item",
        "Items",
        "Size",
        "Modified",
        "Action",
        "Item",
        "Items",
        "Size",
        "Modified",
    )

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.decisions = ChangeDecisions()
        # The items the user hid from the comparison with the space bar.
        self.hidden = HiddenItems()
        # When this is on, the hidden items stay in the list, dimmed.
        self.show_hidden = False
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
        self._sort_column = self.SOURCE_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._pattern = ""
        self._include_directory_contents = False
        self._visible_actions: set[ChangeAction] | None = None
        self._directories: dict[str, FlatDirectory] = {}
        # The parsed path of every change. The paths are split once, so the
        # filters and the sort do not repeat the work for every row.
        self._change_paths: list[str] = []
        self._change_parents: list[str] = []
        self._change_names: list[str] = []
        # The folded name of every change, used by the sort.
        self._change_folded: list[str] = []
        # Whether the filters show the change, and its size on the
        # destination side. Both are filled in while the filters run.
        self._change_visible: list[bool] = []
        self._change_destination_sizes: list[int] = []
        # The directories from the deepest one upwards. The order only
        # changes when the comparison changes.
        self._directory_order: list[str] | None = None
        self._rows: list[FlatRow] = []
        self._visible_rows: list[int] = []
        self._visible_row_of_path: dict[str, int] = {}
        self._visible_changes: list[Change] = []
        self._override_paths: set[str] = set()
        # Bumped whenever the layout changes, so a delegate can drop its
        # cached measurements.
        self.layout_token = 0

    # ------------------------------------------------------------------
    # Building the flat structure
    # ------------------------------------------------------------------
    def set_changes(self, changes: list[Change]) -> None:
        self.beginResetModel()
        self.changes = list(changes)
        self.discarded_decisions = self.decisions.reconcile(self.changes)
        self._build_directories()
        self._build_rows()
        self._apply_filters()
        self.endResetModel()
        self._refresh_action_header()

    def _build_directories(self) -> None:
        """Collect the directories of the comparison and their items."""
        self._directories = {"": FlatDirectory("", "", "", 0)}
        self._directory_order = None
        self._change_paths = []
        self._change_parents = []
        self._change_names = []
        self._change_folded = []
        self._change_visible = []
        self._change_destination_sizes = []

        def ensure(path: str) -> FlatDirectory:
            existing = self._directories.get(path)
            if existing is not None:
                return existing
            parent_path, _, name = path.rpartition("/")
            parent = ensure(parent_path)
            directory = FlatDirectory(
                path=path,
                name=name,
                parent=parent_path,
                depth=path.count("/"),
            )
            self._directories[path] = directory
            parent.child_directories.append(path)
            return directory

        for index, change in enumerate(self.changes):
            path = str(change.path).rstrip("/")
            if not path:
                self._change_paths.append("")
                self._change_parents.append("")
                self._change_names.append("")
                self._change_folded.append("")
                self._change_visible.append(False)
                continue
            parent_path, _, name = path.rpartition("/")
            self._change_paths.append(path)
            self._change_parents.append(parent_path)
            self._change_names.append(name)
            self._change_folded.append(name.casefold())
            self._change_visible.append(False)
            if change.kind is ObjectKind.DIRECTORY:
                # A directory that the comparison reported is a row of its
                # own and carries the change.
                directory = ensure(path)
                directory.own_change = change
                directory.own_change_index = index
                continue
            directory = ensure(parent_path)
            directory.files.append(index)

        for directory in self._directories.values():
            directory.has_children = bool(
                directory.files or directory.child_directories
            )
        self._refresh_destination_sizes()
        self._total_up_changed_counts()

    def _build_rows(self) -> None:
        """Lay the directories and their items out as a flat list.

        The order is the one the tree shows when everything is expanded: a
        directory, then its subdirectories, then its own items.
        """
        rows: list[FlatRow] = []

        def add(row: FlatRow) -> None:
            rows.append(row)

        def walk(path: str) -> None:
            directory = self._directories.get(path)
            if directory is None:
                return
            if path:
                add(
                    FlatRow(
                        path=directory.path,
                        name=directory.name,
                        parent=directory.parent,
                        depth=directory.depth,
                        is_directory=True,
                        change=directory.own_change,
                        change_index=(
                            directory.own_change_index
                            if directory.own_change_index >= 0
                            else -1
                        ),
                        group=path,
                    )
                )
            for child_path in sorted(
                directory.child_directories, key=self._directory_key
            ):
                walk(child_path)
            for index in sorted(directory.files, key=self._file_key):
                change = self.changes[index]
                item_path = self._change_paths[index]
                add(
                    FlatRow(
                        path=item_path,
                        name=self._change_names[index],
                        parent=path,
                        depth=path.count("/") + 1,
                        is_directory=False,
                        change=change,
                        change_index=index,
                        group=path,
                    )
                )

        walk("")
        self._rows = rows

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------
    def sort_column(self) -> int:
        return self._sort_column

    def sort_order(self) -> Qt.SortOrder:
        return self._sort_order

    def sort(  # noqa: A003
        self,
        column: int,
        order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
    ) -> None:
        """Sort the items of every directory by the given column."""
        if column < 0:
            return
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._build_rows()
        self._apply_filters()
        self.layoutChanged.emit()

    def _file_key(self, index: int) -> tuple:
        return self._item_sort_key(index, self._sort_column)

    def _directory_key(self, path: str) -> tuple:
        directory = self._directories.get(path)
        name = directory.name if directory is not None else path
        column = self._sort_column
        if column in (self.SOURCE_ITEMS, self.DESTINATION_ITEMS):
            return (directory.subtree_items if directory else 0, name.casefold())
        if column in (self.SOURCE_SIZE, self.DESTINATION_SIZE):
            return (directory.subtree_size if directory else 0, name.casefold())
        return (name.casefold(),)

    def _item_sort_key(self, index: int, column: int) -> tuple:
        change = self.changes[index]
        name = self._change_folded[index]
        if column in (self.SOURCE_SIZE, self.DESTINATION_SIZE):
            return (int(change.size or 0), name)
        if column in (self.SOURCE_TIME, self.DESTINATION_TIME):
            return (str(change.modified_time or ""), name)
        if column == self.ACTION:
            action = self.effective_action_of_change(change)
            return (ACTION_LABELS.get(action, action.value).casefold(), name)
        return (name,)

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------
    def set_path_filter(self, text: str) -> None:
        """Show only the items whose name matches the pattern.

        The pattern is matched against the name of an item, the same as in
        the tree. A pattern that ends with a slash also shows the contents
        of the matching directories.
        """
        value = text.strip()
        self._include_directory_contents = value.endswith("/")
        self._pattern = value.rstrip("/").casefold()
        self._refresh_filters()

    def set_visible_actions(self, actions: set[ChangeAction] | None) -> None:
        """Restrict the displayed rows to the given comparison actions."""
        self._visible_actions = None if actions is None else set(actions)
        self._refresh_filters()

    def visible_actions(self) -> set[ChangeAction] | None:
        return None if self._visible_actions is None else set(self._visible_actions)

    def _refresh_filters(self) -> None:
        self.layoutAboutToBeChanged.emit()
        self._apply_filters()
        self.layoutChanged.emit()

    def refresh_hidden(self) -> None:
        """Show the rows again after the user hid or showed items."""
        self.layoutAboutToBeChanged.emit()
        self._apply_filters()
        self.layoutChanged.emit()

    def _matches(self, name: str) -> bool:
        if not self._pattern:
            return True
        candidate = name.casefold()
        if any(character in self._pattern for character in "*?["):
            return fnmatchcase(candidate, self._pattern)
        return self._pattern in candidate

    def _apply_filters(self) -> None:
        """Decide which rows the filters show.

        The rules are the ones the tree used: a row is shown when it
        matches or when one of the items below it matches, and the action
        filter keeps a directory when one of the items below it is allowed.
        """
        directories = self._directories
        pattern = self._pattern
        pattern_active = bool(pattern) and pattern != "*"
        include_contents = self._include_directory_contents

        # Whether the directory or one of its ancestors matched.
        matched_above: dict[str, bool] = {"": False}
        for path, directory in directories.items():
            matched_above[path] = matched_above.get(
                directory.parent, False
            ) or (pattern_active and self._matches(directory.name))

        # The items of every directory.
        item_path_ok: dict[str, bool] = {}
        item_action_ok: dict[str, bool] = {}
        for path, directory in directories.items():
            group_matched = matched_above.get(path, False)
            for index in directory.files:
                change = self.changes[index]
                key = self._change_paths[index]
                path_ok = (not pattern_active) or self._matches(
                    self._change_names[index]
                )
                if not path_ok and include_contents and group_matched:
                    path_ok = True
                item_path_ok[key] = path_ok
                item_action_ok[key] = self._action_allowed(change)
                self._change_visible[index] = path_ok and item_action_ok[key]

        # The directories, from the deepest one upwards.
        ordered = sorted(
            (path for path in directories if path),
            key=lambda value: directories[value].depth,
            reverse=True,
        )
        for path in ordered:
            directory = directories[path]
            path_ok = (not pattern_active) or self._matches(directory.name)
            if not path_ok and include_contents and matched_above.get(
                directory.parent, False
            ):
                path_ok = True
            child_path_ok = False
            child_action_ok = False
            for child_path in directory.child_directories:
                child = directories[child_path]
                child_path_ok = child_path_ok or child.path_ok
                child_action_ok = child_action_ok or child.action_ok
            for index in directory.files:
                key = self._change_paths[index]
                child_path_ok = child_path_ok or item_path_ok.get(key, False)
                child_action_ok = child_action_ok or item_action_ok.get(key, False)
            if directory.own_change is not None:
                key = str(directory.own_change.path).rstrip("/")
                child_path_ok = child_path_ok or item_path_ok.get(key, False)
                child_action_ok = child_action_ok or item_action_ok.get(key, False)
            directory.path_ok = path_ok or child_path_ok
            directory.action_ok = (
                self._action_allowed(directory.own_change)
                if directory.own_change is not None
                else False
            ) or child_action_ok
            directory.visible = directory.path_ok and directory.action_ok

        # The rows of the visible directories.
        visible_rows: list[int] = []
        visible_change_indices: set[int] = set()
        visible_row_of_path: dict[str, int] = {}
        hidden = self.hidden
        show_hidden = self.show_hidden
        for index, row in enumerate(self._rows):
            if row.is_directory:
                directory = directories.get(row.path)
                if directory is None or not directory.visible:
                    continue
                if hidden.is_hidden(row.path) and not show_hidden:
                    continue
                # A directory that the comparison reported is a change of its
                # own, the same as in the tree.
                if directory.own_change_index >= 0:
                    visible_change_indices.add(directory.own_change_index)
            else:
                if not self._change_visible[row.change_index]:
                    continue
                if hidden.is_hidden(row.path) and not show_hidden:
                    continue
                visible_change_indices.add(row.change_index)
            visible_row_of_path[row.path] = len(visible_rows)
            visible_rows.append(index)
        self._visible_rows = visible_rows
        # The changes keep the order of the comparison, the same as in the
        # tree, so the overview counts them the same way.
        self._visible_changes = [
            self.changes[index]
            for index in sorted(visible_change_indices)
        ]
        self._visible_row_of_path = visible_row_of_path
        self._total_up_directories()
        self.layout_token += 1

    def _total_up_directories(self) -> None:
        """Total the visible items of every directory.

        The tree computed these totals by walking its nodes. The flat model
        walks the directories instead, which gives the same numbers in a
        fraction of the time.
        """
        for directory in self._directories.values():
            directory.subtree_items = 0
            directory.subtree_size = 0
            directory.subtree_destination_size = 0

        # The directories from the deepest one upwards, so a directory knows
        # the totals of the directories below it.
        hidden = self.hidden
        for path in self._ordered_directories():
            directory = self._directories[path]
            items = 0
            size = 0
            destination_size = 0
            for index in directory.files:
                if not self._change_visible[index]:
                    continue
                change = self.changes[index]
                if hidden.is_hidden(self._change_paths[index]):
                    continue
                items += 1
                size += int(change.size or 0)
                destination_size += self._change_destination_sizes[index]
            for child_path in directory.child_directories:
                child = self._directories[child_path]
                if not child.visible:
                    continue
                if hidden.is_hidden(child_path):
                    continue
                items += child.subtree_items
                size += child.subtree_size
                destination_size += child.subtree_destination_size
                if child.own_change is not None:
                    # A reported directory is an object of its own, so it
                    # counts once for the directory above it.
                    items += 1
                    if not child.has_children:
                        size += int(child.own_change.size or 0)
                        destination_size += self._destination_size(child.own_change)
            if directory.own_change is not None and not directory.has_children:
                # A directory that holds nothing reports its own size.
                size += int(directory.own_change.size or 0)
                destination_size += self._destination_size(directory.own_change)
            directory.subtree_items = items
            directory.subtree_size = size
            directory.subtree_destination_size = destination_size

    def _ordered_directories(self) -> list[str]:
        """The directories from the deepest one upwards."""
        if self._directory_order is None:
            self._directory_order = sorted(
                (path for path in self._directories if path),
                key=lambda value: self._directories[value].depth,
                reverse=True,
            )
        return self._directory_order

    def _total_up_changed_counts(self) -> None:
        """Count the changed items of every subtree.

        These numbers do not depend on the filters, exactly like in the tree.
        """
        for directory in self._directories.values():
            directory.subtree_changed = 0

        for path in self._ordered_directories():
            directory = self._directories[path]
            changed = 0
            for index in directory.files:
                change = self.changes[index]
                if change.action is not ChangeAction.NO_CHANGE:
                    changed += 1
            if directory.own_change is not None:
                if directory.own_change.action is not ChangeAction.NO_CHANGE:
                    changed += 1
            for child_path in directory.child_directories:
                changed += self._directories[child_path].subtree_changed
            directory.subtree_changed = changed

    def _action_allowed(self, change: Change | None) -> bool:
        if self._visible_actions is None:
            return True
        if change is None:
            return False
        return self.effective_action_of_change(change) in self._visible_actions

    def visible_paths(self) -> set[str]:
        """The paths of the rows that the filters show.

        The directories are included, the same as in the tree, so a caller
        that totals up the items below a directory finds them all.
        """
        paths: set[str] = set()
        for index in self._visible_rows:
            paths.add(self._rows[index].path)
        return paths

    def visible_changes(self) -> list[Change]:
        """The items of the comparison that the filters show."""
        return list(self._visible_changes)

    # ------------------------------------------------------------------
    # Qt model interface
    # ------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._visible_rows)

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

    def index_for_path(self, path: str) -> QModelIndex:
        """Return the index of the row with the given path."""
        row = self._visible_row_of_path.get(path.rstrip("/"))
        if row is None:
            return QModelIndex()
        return self.createIndex(row, 0)

    def row_path(self, row: int) -> str | None:
        """Return the comparison path of a visible row."""
        if not 0 <= row < len(self._visible_rows):
            return None
        return self._rows[self._visible_rows[row]].path

    def _row_data(self, row: int) -> FlatRow | None:
        if not 0 <= row < len(self._visible_rows):
            return None
        return self._rows[self._visible_rows[row]]

    def row_data(self, row: int) -> FlatRow | None:
        """Return the data of a visible row, for the delegate."""
        return self._row_data(row)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._row_data(index.row())
        if row is None:
            return None
        change = row.change
        source_present = (
            change is None or change.action is not ChangeAction.DESTINATION_ONLY
        )
        destination_present = change is None or change.action is not ChangeAction.CREATE
        directory = self._directories.get(row.path) if row.is_directory else None

        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == self.SOURCE_NAME:
                return row.name if source_present else ""
            if index.column() == self.DESTINATION_NAME:
                return row.name if destination_present else ""
            if index.column() == self.ACTION:
                return ""
            if index.column() == self.SOURCE_ITEMS:
                if not source_present or directory is None:
                    return ""
                return str(directory.subtree_items)
            if index.column() == self.DESTINATION_ITEMS:
                if not destination_present or directory is None:
                    return ""
                return str(directory.subtree_items)
            if index.column() == self.SOURCE_SIZE:
                if not source_present:
                    return ""
                if directory is not None:
                    return self._size(directory.subtree_size)
                return self._size(change.size if change else None)
            if index.column() == self.DESTINATION_SIZE:
                if not destination_present:
                    return ""
                if directory is not None:
                    return self._size(directory.subtree_destination_size)
                return self._size(self._destination_size(change) if change else None)
            if change is None:
                return ""
            if index.column() == self.SOURCE_TIME:
                return change.modified_time or "" if source_present else ""
            if index.column() == self.DESTINATION_TIME:
                if not destination_present:
                    return ""
                if change.destination_time:
                    return change.destination_time
                _size, time = self._destination_info(row.path)
                return time or ""
        if role == Qt.ItemDataRole.DecorationRole:
            if index.column() == self.ACTION:
                return self._decoration_for(row)
            if index.column() == self.SOURCE_NAME:
                if not source_present:
                    return None
                return self._item_icon(row)
            if index.column() == self.DESTINATION_NAME:
                if not destination_present:
                    return None
                return self._item_icon(row)
        if role == Qt.ItemDataRole.FontRole and change is not None:
            if change.action is ChangeAction.NO_CHANGE:
                font = QFont()
                font.setItalic(True)
                return font
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip_for(row, index.column())
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
            and self._row_selectable(row)
        ):
            return (
                Qt.CheckState.Checked
                if self._effective_row(row) is ChangeDecision.INCLUDE
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.UserRole:
            return change
        if role == Qt.ItemDataRole.UserRole + 1:
            return self.decisions.explicit(row.path)
        if role == PATH_ROLE:
            return row.path
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.column() == self.ACTION:
            row = self._row_data(index.row())
            if row is not None and self.decisions_enabled and self._row_selectable(row):
                flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not self.decisions_enabled:
            return False
        if role != Qt.ItemDataRole.CheckStateRole or not index.isValid():
            return False
        if index.column() != self.ACTION:
            return False
        row = self._row_data(index.row())
        if row is None or not self._row_selectable(row):
            return False
        state = Qt.CheckState(value)
        decision = (
            ChangeDecision.INCLUDE
            if state is Qt.CheckState.Checked
            else ChangeDecision.EXCLUDE
        )
        self.decisions.set(row.path, decision)
        self._refresh_decisions()
        return True

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------
    def effective_action_of_change(self, change: Change) -> ChangeAction:
        action = change.action
        if (
            action is ChangeAction.DESTINATION_ONLY
            and self._effective_change(change) is ChangeDecision.INCLUDE
        ):
            return ChangeAction.DELETE
        return action

    def _effective_change(self, change: Change) -> ChangeDecision:
        if not self.decisions.selectable(change):
            return ChangeDecision.EXCLUDE
        inherited = self.decisions.inherited(str(change.path).rstrip("/"))
        if inherited is not None:
            return inherited
        if change.action is ChangeAction.DESTINATION_ONLY:
            return ChangeDecision.EXCLUDE
        return ChangeDecision.INCLUDE

    def _row_selectable(self, row: FlatRow) -> bool:
        if row.change is not None:
            return self.decisions.selectable(row.change)
        directory = self._directories.get(row.path)
        return bool(directory is not None and directory.has_children)

    def _effective_row(self, row: FlatRow) -> ChangeDecision:
        inherited = self.decisions.inherited(row.path)
        if inherited is not None:
            return inherited
        if row.change is not None:
            return self._effective_change(row.change)
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
        self._apply_filters()
        self.layoutChanged.emit()
        self.decision_changed.emit()
        self._refresh_action_header()

    def decision_summary(self):
        return self.decisions.summary(self.changes)

    # ------------------------------------------------------------------
    # Icons and tooltips
    # ------------------------------------------------------------------
    def _decoration_for(self, row: FlatRow) -> Any:
        change = row.change
        directory = self._directories.get(row.path) if row.is_directory else None
        action = (
            self.effective_action_of_change(change)
            if change is not None
            else ChangeAction.NO_CHANGE
        )
        overridden = (not self.stale) and row.path in self._override_paths
        if row.is_directory:
            if action is ChangeAction.NO_CHANGE:
                if directory is not None and directory.subtree_changed:
                    return folder_sync_changed_icon()
                return folder_sync_icon()
            return action_icon(action, accent=overridden)
        if action is ChangeAction.NO_CHANGE:
            return unchanged_faded_icon()
        return action_icon(action, accent=overridden)

    def _item_icon(self, row: FlatRow) -> Any:
        if row.is_directory:
            return folder_icon()
        if row.change is not None and row.change.kind is ObjectKind.SYMLINK:
            return file_type_icon("link")
        return file_type_icon(row.name)

    def _tooltip_for(self, row: FlatRow, column: int) -> str:
        source_full = full_path(self.source_root, row.path)
        destination_full = full_path(self.destination_root, row.path)
        destination_column = column in {
            self.DESTINATION_NAME,
            self.DESTINATION_ITEMS,
            self.DESTINATION_SIZE,
            self.DESTINATION_TIME,
        }
        if column == self.ACTION:
            directory = self._directories.get(row.path) if row.is_directory else None
            if row.change is None:
                extra = (
                    f"\n{directory.subtree_changed} changed item(s) inside"
                    if directory is not None and directory.subtree_changed
                    else ""
                )
                return (
                    f"Source: {source_full}\nDestination: {destination_full}{extra}"
                )
            label = ACTION_LABELS.get(self.effective_action_of_change(row.change), "")
            if row.change.action is ChangeAction.NO_CHANGE:
                details = label
            else:
                detail_line = ": ".join(
                    part
                    for part in (row.change.itemized_code, row.change.reason)
                    if part
                )
                details = (
                    f"{label}\n{detail_line}"
                    if label and detail_line
                    else (label or detail_line)
                )
            return (
                f"Source: {source_full}\n"
                f"Destination: {destination_full}\n"
                f"{details}"
            )
        if destination_column:
            return destination_full
        return source_full

    # ------------------------------------------------------------------
    # Destination metadata
    # ------------------------------------------------------------------
    def set_destination_metadata(
        self, metadata: dict[str, tuple[int | None, str | None]]
    ) -> None:
        self._destination_metadata = dict(metadata)
        self._refresh_destination_sizes()
        self.layoutAboutToBeChanged.emit()
        self._apply_filters()
        self.layoutChanged.emit()

    def _refresh_destination_sizes(self) -> None:
        """Cache the size of every change on the destination side."""
        sizes: list[int] = []
        for change in self.changes:
            if change.destination_size is not None:
                sizes.append(int(change.destination_size))
            else:
                size, _time = self._destination_info(str(change.path).rstrip("/"))
                sizes.append(int(size or 0))
        self._change_destination_sizes = sizes

    def _destination_info(self, path: str) -> tuple[int | None, str | None]:
        return self._destination_metadata.get(path, (None, None))

    def _destination_size(self, change: Change) -> int:
        if change.destination_size is not None:
            return int(change.destination_size)
        size, _time = self._destination_info(str(change.path).rstrip("/"))
        return int(size or 0)

    @staticmethod
    def _size(size: int | None) -> str:
        return format_size(size)

    def _refresh_action_header(self) -> None:
        modified = len(self._override_paths)
        self._modified_count = modified
        self._action_header = "Actions*" if modified else "Actions"
        self._action_header_tooltip = (
            f"Actions* ({modified} modified)" if modified else "Actions"
        )
        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal, self.ACTION, self.ACTION
        )

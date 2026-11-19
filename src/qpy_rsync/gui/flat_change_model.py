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

from bisect import bisect_left
from contextlib import contextmanager
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Iterator

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont

from qpy_rsync.backend.diagnostics import debug_timing, timed
from qpy_rsync.backend.destination_sizes import (
    build_destination_size_index,
    destination_size,
)
from qpy_rsync.core.changes import (
    Change,
    ChangeAction,
    ChangeDecision,
    ChangeDecisions,
    DecisionHistory,
    ObjectKind,
)
from qpy_rsync.core.units import format_size

from .action_colours import colour_for
from .text_elide import elide_path

class ExcludedPaths:
    """The EXCLUDE decisions, exposed as the old exclusion API.

    Excluding an item used to be two states: a temporary exclusion and a
    persistent decision. Both now live in :class:`ChangeDecisions`; this view
    keeps the callers that still speak about exclusioning working while they are
    migrated.
    """

    def __init__(self, decisions: ChangeDecisions) -> None:
        self._decisions = decisions

    def __bool__(self) -> bool:
        return bool(self.paths())

    def paths(self) -> set[str]:
        return {
            path
            for path, decision in self._decisions.explicit_items()
            if decision is ChangeDecision.EXCLUDE
        }

    def count(self) -> int:
        return len(self.paths())

    def is_excluded(self, path: str) -> bool:
        return self._decisions.inherited(path) is ChangeDecision.EXCLUDE

    def add(self, path: str) -> None:
        self._decisions.set(path, ChangeDecision.EXCLUDE)

    def restore(self, path: str) -> None:
        self._decisions.reset_subtree(path)

    def toggle(self, path: str) -> bool:
        if self.is_excluded(path):
            self.restore(path)
            return False
        self.add(path)
        return True

    def clear(self) -> None:
        self._decisions.clear()


STALE_SUFFIX = "  [stale comparison]"
STALE_HELP_TEXT = (
    "A stale comparison is still browsable: you can move around the lists, "
    "open tools and add more filters. Decisions are disabled and "
    "synchronization is unavailable until you run Compare again."
)
from .paths import full_path
from .icons import (
    ACTION_LABELS,
    action_icon,
    file_type_icon,
    folder_icon,
    folder_sync_changed_icon,
    folder_sync_icon,
    root_folder_icon,
    unchanged_faded_icon,
)

ACTION_HEADER_ACCENT = "#0891B2"

# Role that carries the comparison path of a row. A directory row has no
# change of its own, so the path cannot be taken from the change.
PATH_ROLE = Qt.ItemDataRole.UserRole + 2
# Whether a row is drawn with the alternating background.
STRIPE_ROLE = Qt.ItemDataRole.UserRole + 3
# Whether the row is excluded, for the crossed-eye marker in the action column.
EXCLUDED_ROLE = Qt.ItemDataRole.UserRole + 4


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
    # The directory's own action is filtered out, but it is still needed as
    # the parent of visible items.
    faded: bool = False


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
    # Whether the row is drawn with the shaded background.
    alternate: bool = False
    # Whether the row is excluded from the sync. This is the unified per-row
    # state for decisions and excluded items.
    excluded: bool = False
    # Whether a directory row has anything below it to fold.
    has_children: bool = False
    # The directory object for directory rows.
    directory: object | None = None


class FlatChangeModel(QAbstractTableModel):
    """The comparison as a flat list of directory groups and items.

    The rows are laid out the way the tree shows them when everything is
    expanded: a directory, the directories below it, then the items of the
    directory. The hierarchy is only painted; the model never expands
    anything.
    """

    decision_changed = Signal(object)
    decision_edited = Signal(str)
    history_changed = Signal()

    SOURCE_NAME = 0
    SOURCE_ITEMS = 1
    SOURCE_SIZE = 2
    SOURCE_TIME = 3
    ACTION = 4
    DESTINATION_NAME = 5
    DESTINATION_ITEMS = 6
    DESTINATION_SIZE = 7
    DESTINATION_TIME = 8
    SOURCE_SIZE_BYTES = 9
    DESTINATION_SIZE_BYTES = 10
    COLUMN_COUNT = 11
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
        "Size (bytes)",
        "Size (bytes)",
    )

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.decisions = ChangeDecisions()
        self.preserve_decisions = True
        self.decision_history = DecisionHistory()
        self._decision_batch = 0
        # One source of truth for everything left out of the run. The old
        # names are kept as aliases until the UI and the plan stop using them.
        self.exclusions = ExcludedPaths(self.decisions)
        self.exclusion = self.exclusions
        # When this is on, excluded items stay in the list, dimmed.
        self._show_excluded = False
        # The directories whose children are folded out of the list. This is
        # view state only: the folded items still belong to the sync.
        self.collapsed: set[str] = set()
        # The row under the pointer. Every pane marks it, so the hover
        # follows the item and not the cell.
        self.hovered_row: int | None = None
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
        self._destination_index = build_destination_size_index({})
        self._sort_column = self.SOURCE_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._pattern = ""
        self._pattern_is_glob = False
        self._include_directory_contents = False
        self._directories_only = False
        self._visible_actions: set[ChangeAction] | None = None
        self.filter_directories: bool = False
        self.tooltip_width: int = 256
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
        self._change_path_ok: list[bool] = []
        self._change_action_ok: list[bool] = []
        self._change_destination_sizes: list[int] = []
        # Sizes of the changes, kept flat for the filter pass that also
        # collects the overview aggregates.
        self._change_sizes: list[int] = []
        # Decisions are rare compared with filter changes, so the effective
        # action of each change is computed once and reused by every pass.
        self._change_effective_actions: list[ChangeAction] = []
        # Per-folder (count, size) of the rows the filters show. The overview
        # consumes this instead of rescanning every change.
        self._overview_aggregates: dict[str, tuple[int, int]] = {}
        self._aggregate_counts: list[list[int]] = []
        # The directories from the deepest one upwards. The order only
        # changes when the comparison changes.
        self._directory_order: list[str] | None = None
        self._rows: list[FlatRow] = []
        self._visible_rows: list[int] = []
        self._visible_position_of_row: list[int] = []
        self._row_of_path: dict[str, int] = {}
        self._sorted_paths: list[str] = []
        # Parallel arrays for the hot filter loops. Python object attribute
        # access in a half-million-row loop costs more than the filtering
        # itself, so the repeated fields are kept in flat arrays.
        self._row_paths: list[str] = []
        self._row_is_dir: list[bool] = []
        self._row_change_index: list[int] = []
        self._row_parent: list[str] = []
        self._row_excluded: list[bool] = []
        self._row_directory: list[object | None] = []
        # Integer index of the folder each row belongs to. Filtering uses
        # these to update flat aggregate arrays without string dict lookups.
        self._row_dir_index: list[int] = []
        # Folded names and paths are built once so a search never casefolds
        # half a million strings. The match list is cached per search text
        # and layout generation.
        self._row_paths_folded: list[str] = []
        self._row_names_folded: list[str] = []
        self._search_cache_key: tuple[str, int] | None = None
        self._search_cache: list[int] = []
        self._visible_changes: list[Change] = []
        self._visible_change_indices: set[int] = set()
        self._override_paths: set[str] = set()
        # Bumped whenever the layout changes, so a delegate can drop its
        # cached measurements.
        self.layout_token = 0

    @property
    def show_excluded(self) -> bool:
        return self._show_excluded

    @show_excluded.setter
    def show_excluded(self, value: bool) -> None:
        self._show_excluded = bool(value)

    # ------------------------------------------------------------------
    # Building the flat structure
    # ------------------------------------------------------------------
    def set_changes(self, changes: list[Change]) -> None:
        self.beginResetModel()
        self.hovered_row = None
        self.changes = list(changes)
        self.discarded_decisions = self.decisions.reconcile(
            self.changes, preserve=self.preserve_decisions
        )
        self.decision_history.clear()
        self.history_changed.emit()
        self._build_directories()
        # A fold is meaningless when its directory is gone; keep the folds of
        # the directories that are still there.
        self.collapsed &= set(self._directories)
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
        self._change_path_ok = []
        self._change_action_ok = []
        self._change_destination_sizes = []
        self._change_sizes = [int(change.size or 0) for change in self.changes]
        self._change_effective_actions = [
            self.effective_action_of_change(change) for change in self.changes
        ]

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
            # The compared folder itself is reported as "." or "./" by rsync.
            # It is the root of the list, not an item inside it.
            if path in {".", "./"}:
                path = ""
            if not path:
                self._change_paths.append("")
                self._change_parents.append("")
                self._change_names.append("")
                self._change_folded.append("")
                self._change_visible.append(False)
                self._change_path_ok.append(False)
                self._change_action_ok.append(False)
                continue
            parent_path, _, name = path.rpartition("/")
            self._change_paths.append(path)
            self._change_parents.append(parent_path)
            self._change_names.append(name)
            self._change_folded.append(name.casefold())
            self._change_visible.append(False)
            self._change_path_ok.append(False)
            self._change_action_ok.append(False)
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

    def root_name(self) -> str:
        """The name of the compared folder, shown on the root row.

        Without a known folder the row stays empty; a dot would look like an
        item of the comparison.
        """
        path = self.source_root.rstrip("/")
        name = path.rpartition("/")[2]
        if name and name != ".":
            return name
        # Fall back to the full path; for the file-system root show "/". A
        # dot would look like an item of the comparison.
        if path and path != ".":
            return path
        if self.source_root and self.source_root != ".":
            return self.source_root
        return ""

    def destination_root_name(self) -> str:
        """The name of the destination folder, which may differ."""
        path = self.destination_root.rstrip("/")
        name = path.rpartition("/")[2]
        if name and name != ".":
            return name
        if path and path != ".":
            return path
        if self.destination_root and self.destination_root != ".":
            return self.destination_root
        return ""

    def _build_rows(self) -> None:
        """Lay the directories and their items out as a flat list.

        The order follows FreeFileSync's flat list: a directory, then its own
        items, then its subdirectories. Each directory and its own items are
        therefore contiguous, which keeps a directory next to its contents.
        """
        rows: list[FlatRow] = []
        row_of_path: dict[str, int] = {}

        def add(row: FlatRow) -> None:
            row_of_path[row.path] = len(rows)
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
                        has_children=directory.has_children,
                        directory=directory,
                    )
                )
            for index in sorted(
                directory.files,
                key=self._file_key,
                reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
            ):
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
            for child_path in sorted(
                directory.child_directories,
                key=self._directory_key,
                reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
            ):
                walk(child_path)

        # The compared folder itself is a row, so its totals can be read and
        # its checkbox decides the whole comparison at once.
        rows.append(
            FlatRow(
                path="",
                name=self.root_name(),
                parent="",
                depth=0,
                is_directory=True,
                change=None,
                change_index=-1,
                group="",
                has_children=bool(
                    self._directories.get("")
                    and self._directories[""].has_children
                ),
                directory=self._directories.get(""),
            )
        )
        walk("")
        # Sorting by size, date, count or action follows FreeFileSync: the
        # whole list is ordered, not each directory on its own. Sorting by
        # name keeps the hierarchy, because that is what makes a tree
        # readable.
        if self._sort_column not in (self.SOURCE_NAME, self.DESTINATION_NAME):
            rows.sort(
                key=self._row_sort_key,
                reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
            )
        self._rows = rows
        self._row_of_path = {row.path: index for index, row in enumerate(rows)}
        self._sorted_paths = sorted(self._row_of_path)
        self._row_paths = [row.path for row in rows]
        self._row_paths_folded = [row.path.casefold() for row in rows]
        self._row_names_folded = [row.name.casefold() for row in rows]
        self._search_cache_key = None
        self._search_cache = []
        self._row_is_dir = [row.is_directory for row in rows]
        self._row_change_index = [row.change_index for row in rows]
        self._row_parent = [row.parent for row in rows]
        self._row_excluded = [False] * len(rows)
        self._row_directory = [row.directory for row in rows]
        self._dir_paths = list(self._directories)
        self._dir_index = {path: index for index, path in enumerate(self._dir_paths)}
        self._row_dir_index = [self._dir_index.get(row.parent, 0) for row in rows]

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
        self.beginResetModel()
        self._build_rows()
        self._apply_filters()
        self.endResetModel()

    def _row_sort_key(self, row: FlatRow) -> tuple:
        """The key of one row when the whole list is sorted."""
        column = self._sort_column
        name = row.name.casefold()
        if row.is_directory:
            directory = self._directories.get(row.path)
            if directory is None:
                return (0, name, row.path)
            if column in (self.SOURCE_ITEMS, self.DESTINATION_ITEMS):
                return (directory.subtree_items, name, row.path)
            if column in (
                self.SOURCE_SIZE,
                self.DESTINATION_SIZE,
                self.SOURCE_SIZE_BYTES,
                self.DESTINATION_SIZE_BYTES,
            ):
                size = (
                    directory.subtree_size
                    if column in (self.SOURCE_SIZE, self.SOURCE_SIZE_BYTES)
                    else directory.subtree_destination_size
                )
                return (size, name, row.path)
            if column in (self.SOURCE_TIME, self.DESTINATION_TIME):
                own = directory.own_change
                return (str((own.modified_time if own else "") or ""), name, row.path)
            if column == self.ACTION:
                return ("", name, row.path)
            return (name, row.path)
        return self._item_sort_key(row.change_index, column) + (row.path,)

    def _file_key(self, index: int) -> tuple:
        return self._item_sort_key(index, self._sort_column)

    def _directory_key(self, path: str) -> tuple:
        directory = self._directories.get(path)
        name = directory.name if directory is not None else path
        column = self._sort_column
        if column in (self.SOURCE_ITEMS, self.DESTINATION_ITEMS):
            return (directory.subtree_items if directory else 0, name.casefold())
        if column in (
            self.SOURCE_SIZE,
            self.DESTINATION_SIZE,
            self.SOURCE_SIZE_BYTES,
            self.DESTINATION_SIZE_BYTES,
        ):
            size = (
                directory.subtree_size
                if column in (self.SOURCE_SIZE, self.SOURCE_SIZE_BYTES)
                else directory.subtree_destination_size
            )
            return (size if directory else 0, name.casefold())
        return (name.casefold(),)

    def _item_sort_key(self, index: int, column: int) -> tuple:
        change = self.changes[index]
        name = self._change_folded[index]
        if column in (
            self.SOURCE_SIZE,
            self.DESTINATION_SIZE,
            self.SOURCE_SIZE_BYTES,
            self.DESTINATION_SIZE_BYTES,
        ):
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
        # A pattern that ends with a slash filters directories in, never
        # files; files only appear below a matching directory.
        self._directories_only = self._include_directory_contents
        self._pattern = value.rstrip("/").casefold()
        self._pattern_is_glob = any(
            character in self._pattern for character in "*?["
        )
        self._refresh_filters()

    def set_visible_actions(
        self,
        actions: set[ChangeAction] | None,
        *,
        apply: bool = True,
    ) -> None:
        """Restrict the displayed rows to the given comparison actions.

        With ``apply`` off the filter is only remembered, so the next rebuild
        of the rows uses it without a second pass over the list.
        """
        self._visible_actions = None if actions is None else set(actions)
        if apply:
            self._refresh_filters()

    def visible_actions(self) -> set[ChangeAction] | None:
        return None if self._visible_actions is None else set(self._visible_actions)

    def visible_rows(self) -> list[int]:
        """The model row indices currently shown in the panes."""
        return list(self._visible_rows)

    def set_filter_directories(self, enabled: bool) -> None:
        """Apply the action filters to the reported directories as well."""
        if self.filter_directories == bool(enabled):
            return
        self.filter_directories = bool(enabled)
        self._refresh_filters()

    def _refresh_filters(self) -> None:
        with timed("model.filter_refresh"):
            self.beginResetModel()
            self._apply_filters()
            self.endResetModel()

    def set_excluded(self, path: str, excluded: bool) -> None:
        """Exclude or include a path with an incremental view refresh."""
        clean = path.rstrip("/")
        before = self._snapshot()
        if excluded:
            self.decisions.set(clean, ChangeDecision.EXCLUDE)
        else:
            self.decisions.reset_subtree(clean)
        self._record_decision(before)
        self._refresh_effective_actions({clean})
        self._after_excluded_change({clean})

    def reset_exclusions(self) -> None:
        """Clear every manual include and exclude decision."""
        before = self._snapshot()
        self.decisions.clear()
        self._record_decision(before)
        self._refresh_effective_actions(None)
        self._after_excluded_change(None)

    clear_exclusion = reset_exclusions

    def _after_excluded_change(self, paths: set[str] | None) -> None:
        self._override_paths = self.decisions.override_paths(self.changes)
        if paths is None:
            self._refresh_filters()
        else:
            self.refresh_decision_visibility(paths)

    def refresh_exclusions(self) -> None:
        """Show the rows again after the user excluded or restored items."""
        with timed("model.exclusion_refresh"):
            self.beginResetModel()
            self._apply_filters()
            self.endResetModel()

    def action_colours_changed(self) -> None:
        """Repaint the rows after the colours of the actions changed."""
        if not self.rowCount():
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self.rowCount() - 1, self.columnCount() - 1),
        )

    def is_collapsed(self, path: str) -> bool:
        """Whether the children of a directory are folded out of the list."""
        return path.rstrip("/") in self.collapsed

    def set_collapsed(self, path: str, collapsed: bool) -> None:
        """Fold or unfold the children of a directory.

        The compared folder is never folded: it is the parent of the tree.
        """
        clean = path.rstrip("/")
        directory = self._directories.get(clean)
        if directory is None or not directory.has_children or not clean:
            self.collapsed.discard(clean)
            return
        if collapsed:
            self.collapsed.add(clean)
        else:
            self.collapsed.discard(clean)

    def toggle_collapsed(self, path: str) -> bool:
        """Fold or unfold a directory. Returns the new folded state."""
        clean = path.rstrip("/")
        if self.is_collapsed(clean):
            self.set_collapsed(clean, False)
            return False
        self.set_collapsed(clean, True)
        return self.is_collapsed(clean)

    def collapse_all(self) -> None:
        """Fold every directory that has children.

        The compared folder stays open: it is the parent of the tree.
        """
        self.collapsed = {
            path
            for path, directory in self._directories.items()
            if directory.has_children and path
        }

    def expand_all(self) -> None:
        """Unfold every directory."""
        self.collapsed.clear()

    def clear_collapsed(self) -> None:
        """Forget the folds, for a new comparison."""
        self.collapsed.clear()

    def refresh_collapsed(self, paths: set[str] | None = None) -> None:
        """Show the rows again after a fold or an unfold.

        A single fold only changes the rows below that folder. Totals and
        aggregates must keep the folded items, so only the visible row list
        is patched; a full rebuild is used for collapse/expand all.
        """
        with timed("model.fold_refresh"):
            self.beginResetModel()
            if paths:
                self._patch_folded_rows(paths)
            else:
                self._rebuild_visible_rows()
            self.endResetModel()

    def _patch_folded_rows(self, paths: set[str]) -> None:
        """Add or remove only the rows below a folded or unfolded folder."""
        affected = self._affected_rows(paths)
        if not affected:
            return
        folded = self._collapsed_map()
        positions = [
            position
            for position, row in enumerate(self._visible_rows)
            if row in affected
        ]
        for position in sorted(positions, reverse=True):
            del self._visible_rows[position]
        for row_index in sorted(affected):
            if self._is_row_visible(self._rows[row_index], folded):
                self._visible_rows.insert(
                    bisect_left(self._visible_rows, row_index), row_index
                )
        self._visible_position_of_row = self._position_array()
        for position, row in enumerate(self._visible_rows):
            self._rows[row].alternate = position % 2 == 0
        self.layout_token += 1

    def _matches(
        self,
        name: str,
        path: str | None = None,
        *,
        is_directory: bool = False,
    ) -> bool:
        """Match the pattern against a name, or against the whole path.

        A pattern with a slash is matched against the relative path, so
        "docs/sub" finds the items inside that folder. Without a slash only
        the name is matched, which is what a search for a file name expects.
        """
        if not self._pattern:
            return True
        if self._directories_only and not is_directory:
            return False
        if self._directories_only and is_directory and not self._pattern_is_glob:
            # A pattern that ends with a slash names a directory: it matches
            # the directory with that name, not every name that contains it.
            if path is not None and "/" in self._pattern:
                return path.casefold() == self._pattern.casefold()
            return name.casefold() == self._pattern.casefold()
        if path is not None and "/" in self._pattern:
            candidate = path.casefold()
        else:
            candidate = name.casefold()
        if self._pattern_is_glob:
            return fnmatchcase(candidate, self._pattern)
        return self._pattern in candidate

    def _apply_filters(self) -> None:
        """Decide which rows the filters show.

        A row is shown when it matches or when one of the items below it
        matches, and the action filter keeps a directory when one of the
        items below it is allowed.
        """
        debug_timing("model.filter_phase", phase="start", changes=len(self.changes))
        directories = self._directories
        pattern_active = bool(self._pattern) and self._pattern != "*"
        include_contents = self._include_directory_contents
        # A path filter is a request to see the matches, so it temporarily
        # overrides the folds; clearing the filter brings them back.
        collapse_active = bool(self.collapsed) and not pattern_active
        directory_folded: dict[str, bool] = {"": False}
        if collapse_active:
            for path, directory in directories.items():
                directory_folded[path] = (
                    directory_folded.get(directory.parent, False)
                    or path in self.collapsed
                )

        # Whether the directory or one of its ancestors matched.
        directory_matched: dict[str, bool] = {"": False}
        for path, directory in directories.items():
            directory_matched[path] = directory_matched.get(
                directory.parent, False
            ) or (
                pattern_active
                and self._matches(
                    directory.name, directory.path, is_directory=True
                )
            )

        # The items of every directory.
        matches = self._matches
        change_paths = self._change_paths
        change_names = self._change_names
        visible = self._change_visible
        path_flags = self._change_path_ok
        action_flags = self._change_action_ok
        actions_visible = self._visible_actions
        effective_actions = self._change_effective_actions
        if pattern_active:
            for path, directory in directories.items():
                group_matched = directory_matched.get(path, False)
                for index in directory.files:
                    path_ok = matches(change_names[index], change_paths[index])
                    if not path_ok and include_contents and group_matched:
                        path_ok = True
                    action_ok = (
                        effective_actions[index] in actions_visible
                        if actions_visible is not None
                        else True
                    )
                    path_flags[index] = path_ok
                    action_flags[index] = action_ok
                    visible[index] = path_ok and action_ok
        elif actions_visible is None:
            for index in range(len(self.changes)):
                path_flags[index] = True
                action_flags[index] = True
                visible[index] = True
        else:
            for index, action in enumerate(effective_actions):
                action_ok = action in actions_visible
                path_flags[index] = True
                action_flags[index] = action_ok
                visible[index] = action_ok

        debug_timing("model.filter_phase", phase="changes_done")
        # The directories, from the deepest one upwards.
        for path in self._ordered_directories():
            directory = directories[path]
            path_ok = (not pattern_active) or self._matches(
                directory.name, directory.path, is_directory=True
            )
            if not path_ok and include_contents and directory_matched.get(
                directory.parent, False
            ):
                path_ok = True
            child_path_ok = False
            child_action_ok = False
            for child_path in directory.child_directories:
                child = directories[child_path]
                if child.action_ok:
                    child_action_ok = True
                    if child.path_ok:
                        child_path_ok = True
            for index in directory.files:
                if self._change_action_ok[index]:
                    child_action_ok = True
                    if self._change_path_ok[index]:
                        child_path_ok = True
            if directory.own_change_index >= 0:
                index = directory.own_change_index
                child_path_ok = child_path_ok or self._change_path_ok[index]
                child_action_ok = child_action_ok or self._change_action_ok[index]
            own_action_ok = (
                effective_actions[index] in actions_visible
                if directory.own_change is not None
                and actions_visible is not None
                else directory.own_change is not None
            )
            directory.path_ok = path_ok or child_path_ok
            directory.action_ok = own_action_ok or child_action_ok
            directory.faded = (
                self.filter_directories
                and directory.own_change is not None
                and not own_action_ok
            )
            directory.visible = directory.path_ok and directory.action_ok

        # The compared folder is always shown, so its totals and its
        # checkbox stay reachable.
        root = directories.get("")
        if root is not None and self.changes:
            root.visible = True
        debug_timing("model.filter_phase", phase="directories_done")
        # The rows of the visible directories.
        visible_rows: list[int] = []
        visible_change_indices: set[int] = set()
        # Collect the overview totals while walking the rows. The overview
        # used to rescan every change after this pass, which dominated the
        # cost of a global filter change on large comparisons.
        dir_paths = self._dir_paths
        aggregate_counts: list[list[int]] = [[0, 0] for _ in dir_paths]
        # The same totals without the excluded items feed the directory rows.
        # They are collected here so the end of the pass no longer has to
        # walk every change a second time.
        total_counts: list[list[int]] = [[0, 0, 0] for _ in dir_paths]
        change_sizes = self._change_sizes
        change_destination_sizes = self._change_destination_sizes
        row_dir_index = self._row_dir_index
        exclusion = self.exclusion
        has_exclusion = bool(exclusion)
        check_excluded = has_exclusion and not self.show_excluded
        excluded = self._excluded_paths()
        change_visible = self._change_visible
        change_path_ok = self._change_path_ok
        excluded_get = excluded.get
        rows = self._rows
        paths = self._row_paths
        is_dir = self._row_is_dir
        change_index = self._row_change_index
        row_excluded = self._row_excluded
        row_directory = self._row_directory
        excluded_fn = exclusion.is_excluded
        for index in range(len(rows)):
            path = paths[index]
            # The compared folder is not an item: keep its row reachable so
            # an exclusion of the whole list can always be undone.
            row_is_excluded = has_exclusion and bool(path) and excluded_fn(path)
            value = excluded_get(path, False) if excluded else False
            if value != row_excluded[index]:
                row_excluded[index] = value
                rows[index].excluded = value
            dir_index = row_dir_index[index]
            if is_dir[index]:
                directory = row_directory[index]
                if directory is None:
                    continue
                if row_is_excluded:
                    # A excluded folder is shown when the user asks for it,
                    # even when the action filters exclude its action.
                    if check_excluded or not directory.path_ok:
                        continue
                elif not directory.visible:
                    continue
                if (
                    directory.own_change_index >= 0
                    and not row_is_excluded
                    and not directory.faded
                ):
                    ci = directory.own_change_index
                    visible_change_indices.add(ci)
                    values = aggregate_counts[dir_index]
                    values[0] += 1
                    values[1] += change_sizes[ci]
            else:
                ci = change_index[index]
                if row_is_excluded:
                    # The same goes for a excluded item: the action filters
                    # do not hide what the user asked to see.
                    if check_excluded or not change_path_ok[ci]:
                        continue
                elif not change_visible[ci]:
                    continue
                if not row_is_excluded:
                    visible_change_indices.add(ci)
                    size = change_sizes[ci]
                    values = aggregate_counts[dir_index]
                    values[0] += 1
                    values[1] += size
                    if not value:
                        totals = total_counts[dir_index]
                        totals[0] += 1
                        totals[1] += size
                        totals[2] += change_destination_sizes[ci]
            # The rows below a folded directory are out of the list, but
            # they stay in the totals and in the overview.
            if (
                collapse_active
                and path
                and directory_folded.get(self._row_parent[index], False)
            ):
                continue
            rows[index].alternate = len(visible_rows) % 2 == 0
            visible_rows.append(index)
        debug_timing("model.filter_phase", phase="rows_done")
        self._visible_rows = visible_rows
        self._visible_change_indices = visible_change_indices
        self._visible_changes = [
            self.changes[index] for index in sorted(visible_change_indices)
        ]
        self._visible_position_of_row = self._position_array()
        self._aggregate_counts = aggregate_counts
        self._publish_overview_aggregates()
        self._total_up_from_aggregates(total_counts)
        debug_timing("model.filter_phase", phase="totals_done")
        self.layout_token += 1

    def _mark_excluded(self, excluded: dict[str, bool], path: str, value: bool) -> None:
        """Mark a path and its descendants in the excluded map."""
        base = path.rstrip("/")
        if not base:
            return
        index = bisect_left(self._sorted_paths, base)
        while index < len(self._sorted_paths):
            key = self._sorted_paths[index]
            if key == base or key.startswith(base + "/"):
                excluded[key] = value
                index += 1
                continue
            if key > base + "/":
                break
            index += 1

    def _excluded_paths(self) -> dict[str, bool]:
        """Compute effective exclusion per path from explicit decisions.

        Only explicit decisions are walked, so this is cheap even for half a
        million rows. Deeper decisions override their ancestors.
        """
        excluded: dict[str, bool] = {}
        items = sorted(
            self.decisions.explicit_items(),
            key=lambda item: item[0].count("/"),
        )
        for path, decision in items:
            self._mark_excluded(
                excluded, path, decision is ChangeDecision.EXCLUDE
            )
        return excluded

    def _update_excluded_rows(self, paths: set[str]) -> None:
        """Refresh the per-row excluded state for the given paths.

        Excluding a directory covers everything below it, so the affected
        rows are the path and all of its descendants, not just the row of
        the path itself. Only updating the latter leaves the children of a
        excluded directory in the list.
        """
        excluded = self._excluded_paths()
        for row_index in self._affected_rows(paths):
            row = self._rows[row_index]
            value = excluded.get(row.path, False)
            row.excluded = value
            self._row_excluded[row_index] = value

    def _collapsed_map(self) -> dict[str, bool]:
        pattern_active = bool(self._pattern) and self._pattern != "*"
        if not self.collapsed or pattern_active:
            return {"": False}
        folded: dict[str, bool] = {"": False}
        for path, directory in self._directories.items():
            folded[path] = (
                folded.get(directory.parent, False) or path in self.collapsed
            )
        return folded

    def _is_row_visible(self, row: FlatRow, folded: dict[str, bool]) -> bool:
        pattern_active = bool(self._pattern) and self._pattern != "*"
        if row.excluded and not self.show_excluded and row.path:
            return False
        if row.is_directory:
            directory = self._directories.get(row.path)
            if directory is None or not (directory.visible or row.excluded):
                return False
        elif not row.excluded and not self._change_visible[row.change_index]:
            return False
        if (
            self.collapsed
            and not pattern_active
            and row.path
            and folded.get(row.parent, False)
        ):
            return False
        return True

    def _affected_rows(self, paths: set[str]) -> set[int]:
        rows: set[int] = set()
        for path in paths:
            base = path.rstrip("/")
            if not base:
                return set(self._row_of_path.values())
            index = bisect_left(self._sorted_paths, base)
            while index < len(self._sorted_paths):
                key = self._sorted_paths[index]
                if key == base or key.startswith(base + "/"):
                    row = self._row_of_path.get(key)
                    if row is not None:
                        rows.add(row)
                    index += 1
                    continue
                if key > base + "/":
                    break
                index += 1
        return rows

    def _rebuild_visible_rows(
        self, excluded: dict[str, bool] | None = None
    ) -> None:
        """Rebuild the visible row list from the cached per-row state.

        This deliberately skips the expensive action/directory passes in
        :meth:`_apply_filters`. It is used for decision changes, where those
        results are unchanged; only the excluded state and the resulting row
        visibility differ.
        """
        pattern_active = bool(self._pattern) and self._pattern != "*"
        collapse_active = bool(self.collapsed) and not pattern_active
        directory_folded: dict[str, bool] = {"": False}
        if collapse_active:
            for path, directory in self._directories.items():
                directory_folded[path] = (
                    directory_folded.get(directory.parent, False)
                    or path in self.collapsed
                )
        visible_rows: list[int] = []
        visible_change_indices: set[int] = set()
        aggregates: list[list[int]] = [[0, 0] for _ in self._dir_paths]
        row_dir_index = self._row_dir_index
        change_sizes = self._change_sizes
        paths = self._row_paths
        row_excluded = self._row_excluded
        excluded_get = excluded.get if excluded is not None else None
        for index, row in enumerate(self._rows):
            if excluded_get is not None:
                path = paths[index]
                value = excluded_get(path, False)
                row_excluded[index] = value
                row.excluded = value
            if row.excluded and not self.show_excluded and row.path:
                continue
            if row.is_directory:
                directory = self._directories.get(row.path)
                if directory is None:
                    continue
                if not (directory.visible or row.excluded):
                    continue
                if (
                    directory.own_change_index >= 0
                    and not row.excluded
                    and not directory.faded
                ):
                    ci = directory.own_change_index
                    visible_change_indices.add(ci)
                    values = aggregates[row_dir_index[index]]
                    values[0] += 1
                    values[1] += change_sizes[ci]
            else:
                if not row.excluded and not self._change_visible[row.change_index]:
                    continue
                if not row.excluded:
                    ci = row.change_index
                    visible_change_indices.add(ci)
                    values = aggregates[row_dir_index[index]]
                    values[0] += 1
                    values[1] += change_sizes[ci]
            if (
                collapse_active
                and row.path
                and directory_folded.get(row.parent, False)
            ):
                continue
            row.alternate = len(visible_rows) % 2 == 0
            visible_rows.append(index)
        self._visible_rows = visible_rows
        self._visible_change_indices = visible_change_indices
        self._visible_changes = [
            self.changes[index] for index in sorted(visible_change_indices)
        ]
        self._visible_position_of_row = self._position_array()
        self._aggregate_counts = aggregates
        self._publish_overview_aggregates()
        self.layout_token += 1

    def _position_array(self) -> list[int]:
        positions = [-1] * len(self._rows)
        for position, index in enumerate(self._visible_rows):
            positions[index] = position
        return positions

    def _publish_overview_aggregates(self) -> None:
        self._overview_aggregates = {
            path: (values[0], values[1])
            for path, values in zip(self._dir_paths, self._aggregate_counts)
            if values[0]
        }

    def _change_aggregate(self, change_index: int, sign: int) -> None:
        """Add or remove one change from the cached overview totals."""
        parent = self._change_parents[change_index]
        directory_index = self._dir_index.get(parent, 0)
        values = self._aggregate_counts[directory_index]
        values[0] += sign
        values[1] += sign * self._change_sizes[change_index]

    def overview_aggregates(self) -> dict[str, tuple[int, int]]:
        """The per-folder totals of the items the filters show."""
        return self._overview_aggregates

    def all_folder_paths(self) -> list[str]:
        """Every folder of the comparison, including the filtered ones."""
        return list(self._directories)

    def search_matches(self, text: str) -> list[int]:
        """Visible rows matching ``text`` with the usual Find/Filter rules.

        This mirrors :meth:`_matches`: a trailing slash searches folders only
        and matches the name or path exactly, a slash inside the pattern
        searches the relative path as a substring, and ``* ? [ ]`` are globs.
        Search only moves the selection; it never changes the visible set.
        """
        value = text.strip().casefold()
        key = (value, self.layout_token)
        if key == self._search_cache_key:
            return self._search_cache
        if not value:
            matches: list[int] = []
        else:
            directories_only = value.endswith("/")
            pattern = value.rstrip("/") if directories_only else value
            is_glob = any(character in pattern for character in "*?[")
            by_path = "/" in pattern
            names = self._row_names_folded
            paths = self._row_paths_folded
            is_dir = self._row_is_dir
            # Search the whole comparison, not just the rows currently on
            # screen: a folded folder must not hide a match. Excluded rows
            # stay out, because jumping to a hidden row cannot select it.
            visible = [
                row for row in range(len(paths))
                if not self._row_excluded[row] or self.show_excluded
            ]
            candidate_source = paths if by_path else names
            if directories_only and not is_glob:
                # The filter compares the whole name (or path) for a folder
                # pattern, so "dir/" does not find "first-dir/".
                matches = [
                    row
                    for row in visible
                    if is_dir[row] and candidate_source[row] == pattern
                ]
            elif is_glob:
                matches = [
                    row
                    for row in visible
                    if (not directories_only or is_dir[row])
                    and fnmatchcase(candidate_source[row], pattern)
                ]
            else:
                matches = [
                    row for row in visible if pattern in candidate_source[row]
                ]
        self._search_cache_key = key
        self._search_cache = matches
        return matches

    def _patch_visible_rows(self, paths: set[str]) -> None:
        """Update only the rows affected by a decision change."""
        affected = self._affected_rows(paths)
        if not affected:
            return
        folded = self._collapsed_map()
        for row_index in affected:
            change_index = self._rows[row_index].change_index
            if change_index >= 0 and change_index in self._visible_change_indices:
                self._visible_change_indices.discard(change_index)
                self._change_aggregate(change_index, -1)
            directory = self._directories.get(self._rows[row_index].path)
            if (
                directory is not None
                and directory.own_change_index in self._visible_change_indices
            ):
                ci = directory.own_change_index
                self._visible_change_indices.discard(ci)
                self._change_aggregate(ci, -1)
        positions = [
            position
            for position, row_index in enumerate(self._visible_rows)
            if row_index in affected
        ]
        for position in sorted(positions, reverse=True):
            del self._visible_rows[position]
        additions: list[int] = []
        for row_index in sorted(affected):
            row = self._rows[row_index]
            if not self._is_row_visible(row, folded):
                continue
            additions.append(row_index)
            if row.excluded:
                continue
            change_index = row.change_index
            if change_index >= 0:
                if change_index not in self._visible_change_indices:
                    self._visible_change_indices.add(change_index)
                    self._change_aggregate(change_index, 1)
            elif row.is_directory:
                directory = self._directories.get(row.path)
                if (
                    directory is not None
                    and directory.own_change_index >= 0
                    and not directory.faded
                ):
                    ci = directory.own_change_index
                    if ci not in self._visible_change_indices:
                        self._visible_change_indices.add(ci)
                        self._change_aggregate(ci, 1)
        for row_index in additions:
            position = bisect_left(self._visible_rows, row_index)
            self._visible_rows.insert(position, row_index)
        with timed("model.patch_changes"):
            self._visible_changes = [
                self.changes[index] for index in sorted(self._visible_change_indices)
            ]
        with timed("model.patch_rowmap"):
            self._visible_position_of_row = self._position_array()
        with timed("model.patch_stripes"):
            for index, row in enumerate(self._visible_rows):
                self._rows[row].alternate = index % 2 == 0
        self._publish_overview_aggregates()
        self.layout_token += 1

    def refresh_decision_visibility(self, paths: set[str]) -> None:
        """Apply decision changes without a full filter recalculation."""
        with timed("model.decision_refresh"):
            self.beginResetModel()
            with timed("model.decision_excluded"):
                self._update_excluded_rows(paths)
            with timed("model.decision_rows"):
                self._patch_visible_rows(paths)
            with timed("model.decision_totals"):
                self._total_up_directories_for(paths)
            self.endResetModel()

    def refresh_excluded_visibility(self) -> None:
        """Show or hide every excluded row with one optimized pass."""
        with timed("model.excluded_refresh"):
            self.beginResetModel()
            with timed("model.excluded_map"):
                excluded = self._excluded_paths()
            with timed("model.excluded_rows_rebuild"):
                self._rebuild_visible_rows(excluded)
            with timed("model.excluded_totals"):
                self._total_up_directories_for(
                    {path for path, value in excluded.items() if value}
                )
            self.endResetModel()

    def _recompute_directory(self, path: str, excluded: dict[str, bool]) -> None:
        directory = self._directories.get(path)
        if directory is None:
            return
        items = 0
        size = 0
        destination_size = 0
        for index in directory.files:
            if not self._change_visible[index]:
                continue
            if excluded.get(self._change_paths[index], False):
                continue
            change = self.changes[index]
            items += 1
            size += int(change.size or 0)
            destination_size += self._change_destination_sizes[index]
        for child_path in directory.child_directories:
            child = self._directories[child_path]
            if not child.visible or excluded.get(child_path, False):
                continue
            items += child.subtree_items
            size += child.subtree_size
            destination_size += child.subtree_destination_size
        directory.subtree_items = items
        directory.subtree_size = size
        directory.subtree_destination_size = destination_size

    def _total_up_from_aggregates(self, counts: list[list[int]]) -> None:
        """Total the visible items of every directory in one short walk.

        The filter pass already collected the per-folder counts, so only the
        folders have to be visited here instead of every change. Parents are
        inserted before their children, so walking backwards is bottom-up.
        """
        directories = self._directories
        for directory in directories.values():
            directory.subtree_items = 0
            directory.subtree_size = 0
            directory.subtree_destination_size = 0
        paths = self._dir_paths
        for index in range(len(paths) - 1, -1, -1):
            directory = directories[paths[index]]
            values = counts[index]
            if values[0]:
                directory.subtree_items += values[0]
                directory.subtree_size += values[1]
                directory.subtree_destination_size += values[2]
            parent = directories.get(directory.parent) if index else None
            if parent is not None:
                parent.subtree_items += directory.subtree_items
                parent.subtree_size += directory.subtree_size
                parent.subtree_destination_size += directory.subtree_destination_size

    def _total_up_directories_for(self, paths: set[str]) -> None:
        """Recompute only the directories affected by the given paths."""
        excluded = self._excluded_paths()
        affected: set[str] = {"", *paths}
        for path in paths:
            parent = path.rpartition("/")[0]
            while parent:
                affected.add(parent)
                parent = parent.rpartition("/")[0]
        for path in self._ordered_directories():
            if path in affected:
                self._recompute_directory(path, excluded)
        self._recompute_directory("", excluded)

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
            path = self._rows[index].path
            # The compared folder itself is a synthetic row, not an item.
            if path:
                paths.add(path)
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
        model_row = self._row_of_path.get(path.rstrip("/"))
        if model_row is None:
            return QModelIndex()
        position = self._visible_position_of_row[model_row]
        if position < 0:
            return QModelIndex()
        return self.createIndex(position, 0)

    def row_count_total(self) -> int:
        """The number of rows in the comparison, including hidden ones."""
        return len(self._rows)

    def nearest_visible_path(self, path: str) -> str | None:
        """The visible row closest to ``path``, preferring the next one."""
        target = self._row_of_path.get(path.rstrip("/"))
        if target is None or not self._visible_rows:
            return None
        position = bisect_left(self._visible_rows, target)
        if position >= len(self._visible_rows):
            position = len(self._visible_rows) - 1
        return self.path_of_row_index(self._visible_rows[position])

    def path_of_row_index(self, index: int) -> str | None:
        """The path of a model row, regardless of folds or filters."""
        if not 0 <= index < len(self._rows):
            return None
        return self._rows[index].path

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
        # An item is only shown on the side where it exists. A new item is
        # only on the source, and an item that is deleted only on the
        # destination.
        source_present = change is None or change.action not in (
            ChangeAction.DESTINATION_ONLY,
            ChangeAction.DELETE,
        )
        destination_present = change is None or change.action is not ChangeAction.CREATE
        directory = self._directories.get(row.path) if row.is_directory else None

        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == self.SOURCE_NAME:
                if not source_present:
                    return ""
                if not row.path:
                    return self.root_name()
                return row.name
            if index.column() == self.DESTINATION_NAME:
                if not destination_present:
                    return ""
                if not row.path:
                    return self.destination_root_name()
                return row.name
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
            if index.column() == self.SOURCE_SIZE_BYTES:
                if not source_present:
                    return ""
                return str(
                    int(
                        directory.subtree_size
                        if directory is not None
                        else (change.size if change else 0) or 0
                    )
                )
            if index.column() == self.DESTINATION_SIZE_BYTES:
                if not destination_present:
                    return ""
                return str(
                    int(
                        directory.subtree_destination_size
                        if directory is not None
                        else (self._destination_size(change) if change else 0) or 0
                    )
                )
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
            and index.column() != self.ACTION
            and row.is_directory
            and (directory is not None and directory.faded)
        ):
            return QColor("#9ca3af")
        if (
            role == Qt.ItemDataRole.ForegroundRole
            and change is not None
            and index.column() != self.ACTION
        ):
            # The item carries the colour of its action.
            colour = colour_for(change.action)
            if colour is not None:
                return colour
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
        if role == STRIPE_ROLE:
            return row.alternate
        if role == EXCLUDED_ROLE:
            return self.exclusion.is_excluded(row.path)
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
        before = self._snapshot()
        self.decisions.set(row.path, decision)
        self._record_decision(before)
        self._after_decision_change({row.path})
        self.decision_edited.emit(str(row.path))
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

    @contextmanager
    def decision_batch(self) -> Iterator[None]:
        """Record several decision edits as one undoable step."""
        self._decision_batch += 1
        before = dict(self.decisions.explicit_items())
        try:
            yield
        finally:
            self._decision_batch -= 1
            if self._decision_batch == 0:
                self._record_decision(before)

    def _record_decision(self, before: dict[str, ChangeDecision]) -> None:
        if self._decision_batch:
            return
        after = dict(self.decisions.explicit_items())
        self.decision_history.record(before, after)
        self.history_changed.emit()

    def _snapshot(self) -> dict[str, ChangeDecision]:
        return dict(self.decisions.explicit_items())

    def undo_decision(self) -> bool:
        """Restore the decision state before the last edit."""
        current = self._snapshot()
        previous = self.decision_history.undo(current)
        if previous is None:
            return False
        self._apply_decision_snapshot(previous)
        return True

    def redo_decision(self) -> bool:
        """Reapply the decision state cancelled by the last undo."""
        current = self._snapshot()
        following = self.decision_history.redo(current)
        if following is None:
            return False
        self._apply_decision_snapshot(following)
        return True

    def _apply_decision_snapshot(self, decisions: dict[str, ChangeDecision]) -> None:
        """Restore a snapshot, patching only the paths that actually changed."""
        current = self._snapshot()
        changed = {
            path
            for path in current.keys() | decisions.keys()
            if current.get(path) != decisions.get(path)
        }
        self.decisions.replace(decisions)
        self._after_decision_change(changed or None)
        self.history_changed.emit()

    def reset_decision(self, path: str) -> None:
        clean = path.rstrip("/")
        before = self._snapshot()
        self.decisions.reset(clean)
        self._record_decision(before)
        self._after_decision_change({clean})

    def reset_subtree_decisions(self, path: str) -> None:
        clean = path.rstrip("/")
        before = self._snapshot()
        self.decisions.reset_subtree(clean)
        self._record_decision(before)
        self._after_decision_change({clean})

    def reset_all_decisions(self) -> None:
        before = self._snapshot()
        self.decisions.clear()
        self._record_decision(before)
        self._after_decision_change(None)

    def _refresh_effective_actions(self, paths: set[str] | None) -> None:
        """Recompute effective actions after a decision changes.

        Only the changed paths and their descendants can be affected, so a
        single decision does not pay for a pass over the whole comparison.
        """
        actions = self._change_effective_actions
        if paths is None or "" in paths:
            for index, change in enumerate(self.changes):
                actions[index] = self.effective_action_of_change(change)
            return
        for row_index in self._affected_rows(paths):
            row = self._rows[row_index]
            change_index = row.change_index
            if change_index >= 0:
                actions[change_index] = self.effective_action_of_change(
                    self.changes[change_index]
                )
            directory = self._directories.get(row.path)
            if (
                directory is not None
                and directory.own_change is not None
                and directory.own_change_index >= 0
            ):
                index = directory.own_change_index
                actions[index] = self.effective_action_of_change(self.changes[index])

    def _after_decision_change(self, paths: set[str] | None) -> None:
        """Update the view after a decision changed.

        A single path uses the incremental refresh. A whole-tree reset still
        needs the full filter pass, because it can affect every row.
        """
        self._refresh_effective_actions(paths)
        self._override_paths = self.decisions.override_paths(self.changes)
        if paths is None or "" in paths:
            self._refresh_filters()
        else:
            self.refresh_decision_visibility(paths)
        self.decision_changed.emit(paths)
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
            # The compared folder is the parent of the tree, so it gets its
            # own icon.
            return folder_icon() if row.path else root_folder_icon()
        if row.change is not None and row.change.kind is ObjectKind.SYMLINK:
            return file_type_icon("link")
        return file_type_icon(row.name)

    def _tooltip_for(self, row: FlatRow, column: int) -> str:
        if not row.path and self.stale:
            return STALE_HELP_TEXT
        source_full = full_path(self.source_root, row.path)
        destination_full = full_path(self.destination_root, row.path)
        source_display = elide_path(source_full, self.tooltip_width)
        destination_display = elide_path(destination_full, self.tooltip_width)
        destination_column = column in {
            self.DESTINATION_NAME,
            self.DESTINATION_ITEMS,
            self.DESTINATION_SIZE,
            self.DESTINATION_TIME,
            self.DESTINATION_SIZE_BYTES,
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
                    f"Source: {source_display}\nDestination: {destination_display}{extra}"
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
            source_modified = ""
            destination_modified = ""
            if row.change is not None:
                source_modified = row.change.modified_time or ""
                # The destination time is filled in later, by the metadata
                # listing, so it is taken from there.
                _size, destination_modified = self._destination_info(row.path)
                destination_modified = destination_modified or ""
            elif row.is_directory:
                directory = self._directories.get(row.path)
                if directory is not None and directory.own_change is not None:
                    source_modified = directory.own_change.modified_time or ""
                    _size, destination_modified = self._destination_info(row.path)
                    destination_modified = destination_modified or ""
            tooltip = (
                f"Source: {source_display}\n"
                f"Destination: {destination_display}\n"
                f"{details}"
            )
            if source_modified or destination_modified:
                tooltip += "\nModified:"
                if source_modified:
                    tooltip += f" source {source_modified}"
                if destination_modified:
                    tooltip += f", destination {destination_modified}"
            return tooltip
        if destination_column:
            return destination_display
        return source_display

    # ------------------------------------------------------------------
    # Destination metadata
    # ------------------------------------------------------------------
    def destination_metadata(self) -> dict[str, tuple[int | None, str | None]]:
        return self._destination_metadata

    def set_destination_metadata(
        self, metadata: dict[str, tuple[int | None, str | None]]
    ) -> None:
        self._destination_metadata = dict(metadata)
        self._destination_index = build_destination_size_index(
            self._destination_metadata
        )
        self._refresh_destination_sizes()
        self.layoutAboutToBeChanged.emit()
        self._apply_filters()
        self.layoutChanged.emit()

    def _refresh_destination_sizes(self) -> None:
        """Cache the size of every change on the destination side."""
        self._change_destination_sizes = [
            destination_size(change, self._destination_index)
            for change in self.changes
        ]

    def _destination_info(self, path: str) -> tuple[int | None, str | None]:
        return self._destination_metadata.get(path, (None, None))

    def _destination_size(self, change: Change) -> int:
        return destination_size(change, self._destination_index)

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

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QLabel,
    QMenu,
    QHBoxLayout,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.core.units import format_size

from .flat_comparison_view import _StretchableHeader
from .icons import ACTION_LABELS, ACCENT, action_icon

# The name FreeFileSync gives to the objects that live in the compared
# folder itself.
FILES_LABEL = "Files"


@dataclass(slots=True)
class OverviewNode:
    """One folder of the overview with the objects it contains."""

    name: str
    path: str
    parent: "OverviewNode | None" = None
    children: list["OverviewNode"] = field(default_factory=list)
    count: int = 0
    size: int = 0
    is_files: bool = False
    is_total: bool = False
    # Filled bottom-up once after the tree is built. Sorting compares these
    # repeatedly, so recomputing recursively on every access is expensive.
    _total_count: int = 0
    _total_size: int = 0

    @property
    def total_count(self) -> int:
        return self._total_count

    @property
    def total_size(self) -> int:
        return self._total_size

    def compute_totals(self) -> None:
        for child in self.children:
            child.compute_totals()
        self._total_count = self.count + sum(c.total_count for c in self.children)
        self._total_size = self.size + sum(c.total_size for c in self.children)


class OverviewModel(QAbstractItemModel):
    """The folder structure of a comparison with the size of every folder.

    Like the overview of FreeFileSync, every row is a folder and reports the
    number of objects and the size of that folder. The objects of the
    compared folder itself are listed in a "Files" row.
    """

    ShareRole = Qt.ItemDataRole.UserRole + 20

    FOLDER = 0
    SHARE = 1
    ITEMS = 2
    SIZE = 3
    COLUMN_COUNT = 4
    HEADERS = ("Item", "Share", "Items", "Size")

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.root = OverviewNode("", "")
        self._level_totals: dict[int, int] = {}
        self._folder_nodes: dict[str, OverviewNode] = {}
        self._files_node: OverviewNode | None = None
        self._sort_column = OverviewModel.SHARE
        self._sort_order = Qt.SortOrder.DescendingOrder
        # Folders with no visible objects stay in the tree but are hidden
        # from the view. Cached per parent so rowCount and index stay cheap.
        self._visible_children: dict[int, list[OverviewNode]] = {}
        self._full_structure = False
        self._applied_counts: dict[str, tuple[int, int]] = {}

    def set_statistics(self, summary: object | None, *, estimate: bool = False) -> None:
        """Show the selected amounts below the overview."""
        self.statistics.set_summary(summary, estimate=estimate)

    def set_changes(self, changes: list[Change], root_name: str = "") -> None:
        """Rebuild from a change list.

        Kept for callers that only have the changes; the comparison model
        feeds :meth:`set_aggregates` directly so the overview never has to
        walk every change again when a filter changes.
        """
        counts: dict[str, list[int]] = {}
        for change in changes:
            path = str(getattr(change, "path", "")).rstrip("/")
            if not path:
                continue
            parent = path.rpartition("/")[0]
            values = counts.get(parent)
            size = (
                0
                if change.kind is ObjectKind.DIRECTORY
                else int(getattr(change, "size", None) or 0)
            )
            if values is None:
                counts[parent] = [1, size]
            else:
                values[0] += 1
                values[1] += size
        self.set_aggregates(
            {parent: (values[0], values[1]) for parent, values in counts.items()},
            root_name,
        )

    def set_paths(self, paths: list[str], root_name: str = "") -> None:
        """Build the complete folder tree once for a new comparison.

        With every folder already in the tree, a filter only changes counts.
        Empty folders are hidden by the model instead of being removed and
        recreated on every filter change.
        """
        structure = {path: (0, 0) for path in paths}
        structure.setdefault("", (0, 0))
        self._build_structure(structure, root_name)
        self._structure_signature = (root_name, "*")
        self._full_structure = True
        self._applied_counts = {}
        self._finish_totals()
        self.layoutChanged.emit()

    def _node_for(self, path: str) -> OverviewNode:
        if path == "" and self._files_node is not None:
            return self._files_node
        return self._folder_nodes[path]

    def _apply_counts_incrementally(
        self, aggregates: dict[str, tuple[int, int]]
    ) -> bool:
        """Update only the folders whose counts changed.

        The subtree totals are propagated as deltas up the tree, so a single
        decision touches its folder and the ancestors above it instead of
        every folder of a large comparison.
        """
        previous = self._applied_counts
        if previous == aggregates:
            return False
        changed = [
            path
            for path in aggregates.keys() | previous.keys()
            if aggregates.get(path) != previous.get(path)
        ]
        if not changed:
            return False
        folders = self._folder_nodes
        total = self.root.children[0] if self.root.children else None
        affected: set[str] = set()
        for path in changed:
            node = self._node_for(path)
            old_count, old_size = node.count, node.size
            count, size = aggregates.get(path, (0, 0))
            node.count = count
            node.size = size
            count_delta, size_delta = count - old_count, size - old_size
            if not (count_delta or size_delta):
                continue
            # Every ancestor's total includes this folder's own count, so
            # propagate only the own delta. Children send their own deltas
            # separately; recomputing a parent from its children here would
            # count the same change twice.
            current = path
            while True:
                affected.add(current)
                folder = folders[current]
                folder._total_count += count_delta
                folder._total_size += size_delta
                if not current:
                    break
                current = current.rpartition("/")[0]
            if path == "" and node is not folders[""]:
                node._total_count += count_delta
                node._total_size += size_delta
            if total is not None:
                total._total_count += count_delta
                total._total_size += size_delta
        for path in sorted(affected, key=lambda item: item.count("/"), reverse=True):
            self._sort_node(folders[path])
        nodes = [folders[path] for path in affected]
        if total is not None:
            nodes.extend((total, self.root))
        self._refresh_visible_children(nodes)
        self._refresh_level_totals(nodes, total)
        self._applied_counts = dict(aggregates)
        return True

    def set_aggregates(
        self, aggregates: dict[str, tuple[int, int]], root_name: str = ""
    ) -> None:
        """Apply per-folder totals without rebuilding the tree every time.

        A new comparison builds the full tree with :meth:`set_paths`, so a
        filter change only updates counts on the existing nodes.
        """
        if not (
            self._full_structure
            and self._structure_signature == (root_name, "*")
        ):
            signature = (root_name, frozenset(aggregates))
            if signature != getattr(self, "_structure_signature", None):
                self._build_structure(aggregates, root_name)
                self._structure_signature = signature
                self._applied_counts = {}
            self._update_counts(aggregates)
            self._applied_counts = dict(aggregates)
            self._finish_totals()
            self.layoutChanged.emit()
        elif self._apply_counts_incrementally(aggregates):
            self.layoutChanged.emit()

    def _update_counts(self, aggregates: dict[str, tuple[int, int]]) -> None:
        folders = self._folder_nodes
        files = self._files_node
        for path, node in folders.items():
            count, size = aggregates.get(path, (0, 0))
            if path == "" and files is not None:
                node = files
            node.count = count
            node.size = size

    def _build_structure(
        self, aggregates: dict[str, tuple[int, int]], root_name: str
    ) -> None:
        self.beginResetModel()
        self.root = OverviewNode("", "")
        base = OverviewNode(root_name or "/", "", self.root)
        self.root.children.append(base)
        folders: dict[str, OverviewNode] = {"": base}
        for path, (count, size) in aggregates.items():
            if not path:
                continue
            node = self._ensure_folder(folders, path)
            node.count = count
            node.size = size
        self._files_node = None
        if "" in aggregates:
            count, size = aggregates[""]
            files = OverviewNode(
                FILES_LABEL, "", base, count=count, size=size, is_files=True
            )
            base.children.append(files)
            self._files_node = files
        self._folder_nodes = folders
        base.compute_totals()
        # A single Total root carries every row of the overview.
        total = OverviewNode("Total", "", self.root, is_total=True)
        total.children = base.children
        for child in total.children:
            child.parent = total
        total.compute_totals()
        self.root.children = [total] if total.children else []
        self.endResetModel()

    def _finish_totals(self) -> None:
        """Recompute the subtree totals and the shares after a count change."""
        total = self.root.children[0] if self.root.children else None
        if total is not None:
            total.compute_totals()
        self._sort_all()
        nodes = [self.root, *self._folder_nodes.values()]
        if total is not None:
            nodes.append(total)
        self._refresh_visible_children(nodes)
        self._refresh_level_totals(nodes, total)

    def update_paths(self, paths: set[str], changes: list[Change]) -> bool:
        """Update only the folders affected by the given decision changes.

        Returns False when the tree would need structural changes, in which
        case the caller should do a full rebuild.
        """
        if not paths or not self._folder_nodes:
            return False
        affected: set[str] = set()
        for path in paths:
            clean = str(path).rstrip("/")
            parent = clean.rpartition("/")[0]
            while True:
                affected.add(parent)
                if not parent:
                    break
                parent = parent.rpartition("/")[0]
        if any(path not in self._folder_nodes for path in affected):
            return False
        counts: dict[str, list[int]] = {path: [0, 0] for path in affected}
        for change in changes:
            path = str(getattr(change, "path", "")).rstrip("/")
            if not path:
                continue
            parent = path.rpartition("/")[0]
            if parent not in self._folder_nodes:
                # A decision added a folder that was not in the overview.
                return False
            values = counts.get(parent)
            if values is None:
                continue
            values[0] += 1
            if change.kind is not ObjectKind.DIRECTORY:
                values[1] += int(getattr(change, "size", None) or 0)
        # A folder that loses its last direct object has to disappear from
        # the tree; that is a structural change and needs a full rebuild.
        for path, (count, _size) in counts.items():
            node = self._folder_nodes[path]
            if path == "" and self._files_node is not None:
                node = self._files_node
            if count == 0 and node.count > 0:
                return False
        for path, (count, size) in counts.items():
            node = self._folder_nodes[path]
            if path == "" and self._files_node is not None:
                node = self._files_node
            node.count = count
            node.size = size
        for path in sorted(affected, key=len, reverse=True):
            self._folder_nodes[path].compute_totals()
        self._finish_totals()
        self.layoutChanged.emit()
        return True

    def _ensure_folder(self, folders: dict[str, OverviewNode], path: str) -> OverviewNode:
        node = folders.get(path)
        if node is not None:
            return node
        parent_path, _separator, name = path.rpartition("/")
        parent = self._ensure_folder(folders, parent_path)
        node = OverviewNode(name, path, parent)
        parent.children.append(node)
        folders[path] = node
        return node

    def _children(self, node: OverviewNode) -> list[OverviewNode]:
        return self._visible_children.get(id(node), [])

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:  # noqa: B008
        parent_node = parent.internalPointer() if parent.isValid() else self.root
        children = self._children(parent_node)
        if not 0 <= row < len(children):
            return QModelIndex()
        return self.createIndex(row, column, children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node: OverviewNode = index.internalPointer()
        parent = node.parent
        if parent is None or parent is self.root:
            return QModelIndex()
        row = self._children(parent.parent).index(parent)  # type: ignore[union-attr]
        return self.createIndex(row, 0, parent)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        if parent.isValid() and parent.column() != 0:
            return 0
        node = parent.internalPointer() if parent.isValid() else self.root
        return len(self._children(node))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: ARG002, B008, N802
        return self.COLUMN_COUNT

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> object:  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        node: OverviewNode = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == self.FOLDER:
                return node.name
            if index.column() == self.SHARE:
                # The bar delegate paints the bar and this percentage. The
                # folder tree lives in its own column, so indentation cannot
                # cut the text off.
                return self._percentage(index)
            if index.column() == self.ITEMS:
                return str(node.total_count)
            return format_size(node.total_size)
        if role == self.ShareRole:
            return self._share(index)
        if role == Qt.ItemDataRole.FontRole and node.is_total:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            if node.is_total:
                return (
                    f"All items in this comparison\n"
                    f"{node.total_count} item(s), {format_size(node.total_size)}"
                )
            return (
                f"{node.path or '/'}\n{node.total_count} item(s), "
                f"{format_size(node.total_size)}"
            )
        return None

    def _share(self, index: QModelIndex) -> float:
        node: OverviewNode = index.internalPointer()
        parent = node.parent
        total = self._level_totals.get(id(parent), 0) if parent is not None else 0
        if not total:
            return 0.0
        return min(1.0, node.total_size / total)

    def _percentage(self, index: QModelIndex) -> str:
        return f"{round(self._share(index) * 100)}%"

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:  # noqa: A003
        """Sort the folders by their number of objects or by their size."""
        self._sort_column = column
        self._sort_order = order
        # The rows move, so the model is reset; a layout change would leave
        # the accessibility interface with a stale row count.
        self.beginResetModel()
        self._sort_all()
        self._refresh_visible_children()
        self.endResetModel()

    def _refresh_visible_children(
        self, nodes: list[OverviewNode] | None = None
    ) -> None:
        if nodes is None:
            nodes = [self.root, *self._folder_nodes.values()]
            total = self.root.children[0] if self.root.children else None
            if total is not None:
                nodes.append(total)
        self._visible_children = {
            id(node): [child for child in node.children if child.total_count]
            for node in nodes
        }

    def _refresh_level_totals(
        self, nodes: list[OverviewNode], total: OverviewNode | None
    ) -> None:
        for node in nodes:
            self._level_totals[id(node)] = sum(
                child.total_size for child in node.children
            )
        if total is not None:
            self._level_totals[id(total)] = sum(
                child.total_size for child in total.children
            )
            self._level_totals[id(self.root)] = total.total_size

    def _sort_key(self):
        if self._sort_column == self.FOLDER:
            return lambda child: child.name.casefold()  # noqa: E731
        if self._sort_column == self.ITEMS:
            return lambda child: child.total_count  # noqa: E731
        return lambda child: child.total_size  # noqa: E731

    def _sort_node(self, node: OverviewNode) -> None:
        # A stable name sort first makes ties deterministic, so an incremental
        # update produces the same order as a full rebuild.
        node.children.sort(key=lambda child: child.name.casefold())
        node.children.sort(
            key=self._sort_key(),
            reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
        )

    def _sort_all(self) -> None:
        for node in [self.root, *self._folder_nodes.values()]:
            self._sort_node(node)


class OverviewBarDelegate(QStyledItemDelegate):
    """Draw the share of a folder as a bar with the percentage inside it."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        styled = QStyleOptionViewItem(option)
        styled.text = ""
        widget = styled.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, styled, painter, widget
        )
        share = index.data(OverviewModel.ShareRole)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if share is None or not text:
            return
        painter.save()
        painter.setClipRect(option.rect)
        # The bar grows from the left, the accent marks the share.
        bar = QColor(ACCENT)
        bar.setAlpha(120)
        width = int(option.rect.width() * float(share))
        painter.fillRect(
            option.rect.left(), option.rect.top(), width, option.rect.height(), bar
        )
        painter.setPen(option.palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            option.rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            text,
        )
        painter.restore()


def _header_height(widget: QWidget) -> int:
    """A header as short as its text allows, with room for the indicator."""
    metrics = widget.fontMetrics()
    return max(16, metrics.height() + 2)


class StatisticsBar(QWidget):
    """The selected amounts, the way FreeFileSync shows them.

    One line with the total and one line with an icon and a count per action,
    so the effect of the current selection is visible without reading the
    journal.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statistics-bar")
        self._rows: dict[str, QLabel] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(4)
        self.summary = QLabel("")
        self.summary.setObjectName("statistics-summary")
        tooltip = (
            "Selected: the items that are checked in the comparison,\n"
            "with their total size and the count of each change type. The icons "
            "below are the same types."
        )
        self.summary.setToolTip(tooltip)
        self.setToolTip(tooltip)
        actions_row.addWidget(self.summary)
        actions_row.addSpacing(8)
        for action, key in (
            (ChangeAction.CREATE, "created"),
            (ChangeAction.UPDATE_CONTENT, "updated"),
            (ChangeAction.UPDATE_METADATA, "metadata"),
            (ChangeAction.DELETE, "deleted"),
            (ChangeAction.DESTINATION_ONLY, "kept"),
        ):
            label_text = ACTION_LABELS.get(action, action.value)
            icon = QLabel()
            icon.setPixmap(action_icon(action).pixmap(16, 16))
            icon.setToolTip(label_text)
            value = QLabel("0")
            value.setToolTip(label_text)
            value.setMinimumWidth(26)
            actions_row.addWidget(icon)
            actions_row.addWidget(value)
            self._rows[key] = value
            if key == "deleted":
                self.deleted_size_label = QLabel("")
                self.deleted_size_label.setToolTip("Total size of deleted items")
                actions_row.addWidget(self.deleted_size_label)
        actions_row.addStretch(1)
        layout.addLayout(actions_row)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_summary(self, summary: object | None, *, estimate: bool = False) -> None:
        """Show the numbers of the current plan, or clear them."""
        if summary is None:
            self.summary.setText("")
            for label in self._rows.values():
                label.setText("0")
            self.deleted_size_label.setText("")
            return
        marker = " (estimate)" if estimate else ""
        self.summary.setText(
            f"{summary.included:,} item(s), {format_size(summary.included_size)}{marker}"
        )
        values = {
            "created": summary.creates,
            "updated": summary.updates,
            "metadata": summary.metadata,
            "deleted": summary.deletions,
            "kept": summary.retained_destination_only,
        }
        for key, value in values.items():
            self._rows[key].setText(f"{value:,}")
        size = getattr(summary, "deleted_size", 0)
        self.deleted_size_label.setText(f"({format_size(size)})")


class OverviewPane(QWidget):
    """A compact overview of the comparison, in the style of FreeFileSync."""

    folder_activated = Signal(str)
    # A folder the user excluded or restored, and the rsync rule they picked.
    exclusion_requested = Signal(str)
    restore_requested = Signal(str)
    filter_requested = Signal(str, str)

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("overview-pane")
        # Leave room for the deleted-items size in the statistics bar.
        self.setMinimumWidth(
            480 + self.fontMetrics().horizontalAdvance("0") * 15
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.model = OverviewModel(self)
        self.tree = QTreeView()
        self.tree.setObjectName("overview-tree")
        # The item column takes the free space but can still be dragged.
        self.tree.setHeader(
            _StretchableHeader(
                Qt.Orientation.Horizontal, self.tree, stretch_section=OverviewModel.FOLDER
            )
        )
        self.tree.setModel(self.model)
        self.tree.setUniformRowHeights(True)
        self.tree.setHeaderHidden(False)
        self.tree.setSortingEnabled(True)
        self.tree.setIndentation(12)
        self.tree.setItemDelegateForColumn(
            OverviewModel.SHARE, OverviewBarDelegate(self.tree)
        )
        self.tree.header().setSortIndicatorShown(True)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setFixedHeight(_header_height(self.tree))
        for section in range(OverviewModel.COLUMN_COUNT):
            self.tree.header().setSectionResizeMode(
                section, QHeaderView.ResizeMode.Interactive
            )
        self.tree.header().resizeSection(OverviewModel.FOLDER, 200)
        self.tree.header().resizeSection(OverviewModel.SHARE, 96)
        self.tree.header().resizeSection(OverviewModel.ITEMS, 56)
        # The size column is the same width as in the comparison panes.
        from PySide6.QtWidgets import QHeaderView as _QHeaderView
        metrics = self.tree.fontMetrics()
        self.tree.header().resizeSection(
            OverviewModel.SIZE, metrics.horizontalAdvance("0" * 11) + 8
        )
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.tree, 1)
        self.statistics = StatisticsBar(self)
        layout.addWidget(self.statistics, 0)

        # Share is the default order; its header carries the indicator.
        self.tree.sortByColumn(OverviewModel.SHARE, Qt.SortOrder.DescendingOrder)
        self.tree.activated.connect(self._folder_activated)
        # The same filtering as in the comparison list: the space bar exclusiones
        # the selected folder, the context menu filters it with an rsync
        # pattern.
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.installEventFilter(self)

    # ------------------------------------------------------------------
    # Hiding and filtering, the way the comparison list does it
    # ------------------------------------------------------------------
    def eventFilter(self, watched: object, event: object) -> bool:  # noqa: N802
        if (
            watched is self.tree
            and getattr(event, "type", lambda: None)() == QEvent.Type.KeyPress
            and getattr(event, "key", lambda: None)() == Qt.Key.Key_Space
        ):
            index = self.tree.currentIndex()
            if index.isValid():
                node: OverviewNode = index.internalPointer()
                if node.path and not node.is_total:
                    self.exclusion_requested.emit(node.path)
                    return True
        return super().eventFilter(watched, event)  # type: ignore[arg-type]

    def _show_context_menu(self, point: object) -> None:
        index = self.tree.indexAt(point)
        if not index.isValid():
            return
        node: OverviewNode = index.internalPointer()
        if not node.path or node.is_total:
            return
        from qpy_rsync.backend.rsync_patterns import phrases_for

        menu = QMenu(self.tree)
        heading = menu.addAction(node.path)
        heading.setEnabled(False)
        menu.addSeparator()
        exclusion_action = menu.addAction("Exclude Folder\tSpace")
        restore_action = menu.addAction("Restore Folder")
        menu.addSeparator()
        filter_menu = menu.addMenu("Exclude via Filter")
        filter_actions = []
        for phrase in phrases_for(node.path, is_directory=True):
            action = filter_menu.addAction(phrase.label)
            action.setData(phrase.pattern)
            filter_actions.append(action)
        selected = menu.exec(self.tree.viewport().mapToGlobal(point))
        if selected is exclusion_action:
            self.exclusion_requested.emit(node.path)
        elif selected is restore_action:
            self.restore_requested.emit(node.path)
        elif selected in filter_actions:
            self.filter_requested.emit(selected.text(), node.path)

    def _folder_activated(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        node: OverviewNode = index.internalPointer()
        if node.path and not node.is_total:
            self.folder_activated.emit(node.path)

    def set_statistics(self, summary: object | None, *, estimate: bool = False) -> None:
        """Show the selected amounts below the overview."""
        self.statistics.set_summary(summary, estimate=estimate)

    def set_changes(self, changes: list[Change], root_name: str = "") -> None:
        header = self.tree.header()
        column = header.sortIndicatorSection()
        order = header.sortIndicatorOrder()
        if column < 0:
            column = OverviewModel.SHARE
            order = Qt.SortOrder.DescendingOrder
        self.model.set_changes(changes, root_name)
        self.tree.sortByColumn(column, order)
        total = self.model.index(0, 0)
        if total.isValid():
            self.tree.expand(total)

    def set_paths(self, paths: list[str], root_name: str = "") -> None:
        """Build the folder tree of a new comparison once."""
        self.model.set_paths(paths, root_name)
        total = self.model.index(0, 0)
        if total.isValid():
            self.tree.expand(total)

    def set_aggregates(
        self, aggregates: dict[str, tuple[int, int]], root_name: str = ""
    ) -> None:
        """Apply totals collected by the comparison model's filter pass."""
        self.model.set_aggregates(aggregates, root_name)
        total = self.model.index(0, 0)
        if total.isValid():
            self.tree.expand(total)

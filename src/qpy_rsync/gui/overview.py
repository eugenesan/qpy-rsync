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

from qpy_rsync.core.changes import Change, ChangeAction
from qpy_rsync.core.units import format_size

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

    @property
    def total_count(self) -> int:
        """The number of objects of the folder including its subfolders."""
        return self.count + sum(child.total_count for child in self.children)

    @property
    def total_size(self) -> int:
        """The size of the folder including its subfolders."""
        return self.size + sum(child.total_size for child in self.children)


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

    def set_statistics(self, summary: object | None) -> None:
        """Show the selected amounts below the overview."""
        self.statistics.set_summary(summary)

    def set_changes(self, changes: list[Change], root_name: str = "") -> None:
        self.beginResetModel()
        self.root = OverviewNode("", "")
        base = OverviewNode(root_name or "/", "", self.root)
        self.root.children.append(base)
        folders: dict[str, OverviewNode] = {"": base}
        for change in changes:
            path = str(getattr(change, "path", "")).rstrip("/")
            if not path:
                continue
            parent_path, _separator, _name = path.rpartition("/")
            folder = self._ensure_folder(folders, parent_path)
            folder.count += 1
            folder.size += int(getattr(change, "size", None) or 0)
        self._prepare(folders)
        self.endResetModel()

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

    def _prepare(self, folders: dict[str, OverviewNode]) -> None:
        """Sort the folders and lift the rows of the compared folder."""
        base = folders[""]
        # The compared folder itself is not a row, so its objects get one.
        if base.count:
            base.children.append(
                OverviewNode(
                    FILES_LABEL,
                    base.path,
                    base,
                    count=base.count,
                    size=base.size,
                    is_files=True,
                )
            )
            base.count = 0
            base.size = 0
        for node in folders.values():
            node.children.sort(
                key=lambda child: (
                    -child.total_size,
                    -child.total_count,
                    child.name.casefold(),
                )
            )
        # The folders of the compared folder are the rows of the overview.
        # A single Total root carries the size and the item count of all of
        # them, so the overview can be read as one tree.
        total = OverviewNode("Total", "", self.root, is_total=True)
        total.children = base.children
        for child in total.children:
            child.parent = total
        self.root.children = [total] if total.children else []
        self._level_totals = {}
        for node in folders.values():
            self._level_totals[id(node)] = sum(
                child.total_size for child in node.children
            )
        self._level_totals[id(total)] = sum(
            child.total_size for child in total.children
        )
        self._level_totals[id(self.root)] = total.total_size

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:  # noqa: B008
        parent_node = parent.internalPointer() if parent.isValid() else self.root
        if not 0 <= row < len(parent_node.children):
            return QModelIndex()
        return self.createIndex(row, column, parent_node.children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node: OverviewNode = index.internalPointer()
        parent = node.parent
        if parent is None or parent is self.root:
            return QModelIndex()
        return self.createIndex(parent.parent.children.index(parent), 0, parent)  # type: ignore[union-attr]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        if parent.isValid() and parent.column() != 0:
            return 0
        node = parent.internalPointer() if parent.isValid() else self.root
        return len(node.children)

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
        self.layoutAboutToBeChanged.emit()
        self._sort(self.root, column, order)
        self.layoutChanged.emit()

    def _sort(self, node: OverviewNode, column: int, order: Qt.SortOrder) -> None:
        if column == self.FOLDER:
            key = lambda child: child.name.casefold()  # noqa: E731
        elif column == self.ITEMS:
            key = lambda child: child.total_count  # noqa: E731
        else:
            key = lambda child: child.total_size  # noqa: E731
        node.children.sort(key=key, reverse=order == Qt.SortOrder.DescendingOrder)
        for child in node.children:
            self._sort(child, column, order)


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
        heading = QLabel("Selected:")
        heading.setStyleSheet("font-weight: bold;")
        actions_row.addWidget(heading)
        self.summary = QLabel("")
        self.summary.setObjectName("statistics-summary")
        actions_row.addWidget(self.summary)
        actions_row.addSpacing(8)
        for action, key in (
            (ChangeAction.CREATE, "created"),
            (ChangeAction.UPDATE_CONTENT, "updated"),
            (ChangeAction.UPDATE_METADATA, "metadata"),
            (ChangeAction.REPLACE, "replaced"),
            (ChangeAction.DELETE, "deleted"),
            (ChangeAction.NO_CHANGE, "unchanged"),
        ):
            label_text = ACTION_LABELS.get(action, action.value)
            icon = QLabel()
            icon.setPixmap(action_icon(action).pixmap(16, 16))
            icon.setToolTip(label_text)
            value = QLabel("0")
            value.setToolTip(label_text)
            value.setMinimumWidth(22)
            actions_row.addWidget(icon)
            actions_row.addWidget(value)
            self._rows[key] = value
        actions_row.addStretch(1)
        layout.addLayout(actions_row)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_summary(self, summary: object | None) -> None:
        """Show the numbers of the current plan, or clear them."""
        if summary is None:
            self.summary.setText("")
            for label in self._rows.values():
                label.setText("0")
            return
        self.summary.setText(
            f"{summary.included:,} item(s), {format_size(summary.total_size)}"
        )
        values = {
            "created": summary.creates,
            "updated": summary.updates,
            "metadata": summary.metadata,
            "replaced": summary.replacements,
            "deleted": summary.deletions,
            "unchanged": summary.retained_destination_only,
        }
        for key, value in values.items():
            self._rows[key].setText(f"{value:,}")


class OverviewPane(QWidget):
    """A compact overview of the comparison, in the style of FreeFileSync."""

    folder_activated = Signal(str)
    # A folder the user hid or showed, and the rsync rule they picked.
    hide_requested = Signal(str)
    show_requested = Signal(str)
    filter_requested = Signal(str, str)

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("overview-pane")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.model = OverviewModel(self)
        self.tree = QTreeView()
        self.tree.setObjectName("overview-tree")
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
        self.tree.header().resizeSection(OverviewModel.SIZE, 84)
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # The size column takes the remaining width, so no empty band is left
        # at the right edge of the pane.
        self.tree.header().setSectionResizeMode(
            OverviewModel.FOLDER, QHeaderView.ResizeMode.Stretch
        )
        self.tree.header().setSectionResizeMode(
            OverviewModel.SIZE, QHeaderView.ResizeMode.Interactive
        )
        layout.addWidget(self.tree, 1)
        self.statistics = StatisticsBar(self)
        layout.addWidget(self.statistics, 0)

        # The size of a folder is the interesting number, like in FreeFileSync.
        self.tree.sortByColumn(OverviewModel.SIZE, Qt.SortOrder.DescendingOrder)
        self.tree.activated.connect(self._folder_activated)
        # The same filtering as in the comparison list: the space bar hides
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
                    self.hide_requested.emit(node.path)
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
        hide_action = menu.addAction("Hide Folder\tSpace")
        show_action = menu.addAction("Show Folder")
        menu.addSeparator()
        filter_menu = menu.addMenu("Exclude via Filter")
        filter_actions = []
        for phrase in phrases_for(node.path, is_directory=True):
            action = filter_menu.addAction(phrase.label)
            action.setData(phrase.pattern)
            filter_actions.append(action)
        selected = menu.exec(self.tree.viewport().mapToGlobal(point))
        if selected is hide_action:
            self.hide_requested.emit(node.path)
        elif selected is show_action:
            self.show_requested.emit(node.path)
        elif selected in filter_actions:
            self.filter_requested.emit(selected.text(), node.path)

    def _folder_activated(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        node: OverviewNode = index.internalPointer()
        if node.path and not node.is_total:
            self.folder_activated.emit(node.path)

    def set_statistics(self, summary: object | None) -> None:
        """Show the selected amounts below the overview."""
        self.statistics.set_summary(summary)

    def set_changes(self, changes: list[Change], root_name: str = "") -> None:
        header = self.tree.header()
        column = header.sortIndicatorSection()
        order = header.sortIndicatorOrder()
        if column < 0:
            column = OverviewModel.SIZE
            order = Qt.SortOrder.DescendingOrder
        self.model.set_changes(changes, root_name)
        self.tree.sortByColumn(column, order)
        self.tree.expandToDepth(0)

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QRect, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from qpy_rsync.core.changes import Change, ChangeAction

from .icons import ACTION_COLORS, ACTION_LABELS

# The markers of the overview use the same colors as the action icons.
LEGEND: tuple[tuple[ChangeAction, str], ...] = (
    (ChangeAction.CREATE, "New"),
    (ChangeAction.UPDATE_CONTENT, "Updated"),
    (ChangeAction.REPLACE, "Replaced"),
    (ChangeAction.DELETE, "Deleted"),
    (ChangeAction.DESTINATION_ONLY, "Kept"),
    (ChangeAction.NO_CHANGE, "Unchanged"),
)


@dataclass(slots=True)
class OverviewNode:
    """One folder of the overview with the objects it contains."""

    name: str
    path: str
    parent: "OverviewNode | None" = None
    children: list["OverviewNode"] = field(default_factory=list)
    source_markers: list[tuple[ChangeAction, str]] = field(default_factory=list)
    destination_markers: list[tuple[ChangeAction, str]] = field(default_factory=list)


class OverviewModel(QAbstractItemModel):
    """The folder structure of a comparison with the objects of every folder.

    Like the overview of FreeFileSync, the rows are the folders and every
    object of a folder is a small marker, coloured by its action.
    """

    MarkersRole = Qt.ItemDataRole.UserRole + 20

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.root = OverviewNode("", "")

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
            action = change.action
            parent_path, _separator, _name = path.rpartition("/")
            folder = self._ensure_folder(folders, parent_path)
            if action is not ChangeAction.DESTINATION_ONLY:
                folder.source_markers.append((action, path))
            if action in {
                ChangeAction.DELETE,
                ChangeAction.DESTINATION_ONLY,
                ChangeAction.NO_CHANGE,
            }:
                folder.destination_markers.append((action, path))
        for node in folders.values():
            node.children.sort(key=lambda child: child.name.casefold())
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
        return 2

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> object:  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return "Source" if section == 0 else "Destination"
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        node: OverviewNode = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            return node.name
        if role == self.MarkersRole:
            return (
                node.source_markers if index.column() == 0 else node.destination_markers
            )
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{node.path or '/'} ({len(node.source_markers)} source, {len(node.destination_markers)} destination)"
        return None


class OverviewDelegate(QStyledItemDelegate):
    """Draw the folder name and the markers of the objects it contains."""

    marker_clicked = Signal(str)

    MARKER_SIZE = 8
    MARKER_GAP = 2
    NAME_GAP = 10

    def _markers(self, index: QModelIndex) -> list[tuple[ChangeAction, str]]:
        markers = index.data(OverviewModel.MarkersRole)
        return list(markers) if markers else []

    def _marker_rects(
        self, option: QStyleOptionViewItem, index: QModelIndex
    ) -> list[tuple[QRect, ChangeAction, str]]:
        markers = self._markers(index)
        if not markers:
            return []
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        metrics = option.fontMetrics
        x = option.rect.x() + metrics.horizontalAdvance(str(name)) + self.NAME_GAP
        y = option.rect.y() + (option.rect.height() - self.MARKER_SIZE) // 2
        rects: list[tuple[QRect, ChangeAction, str]] = []
        for action, path in markers:
            rects.append((QRect(x, y, self.MARKER_SIZE, self.MARKER_SIZE), action, path))
            x += self.MARKER_SIZE + self.MARKER_GAP
        return rects

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        # The background is drawn by the style, the name and the markers by
        # this delegate.
        styled = QStyleOptionViewItem(option)
        styled.text = ""
        styled.icon = QIcon()
        widget = styled.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, styled, painter, widget
        )
        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        metrics = option.fontMetrics
        painter.save()
        # The markers belong to the cell, they must not spill into the next
        # column.
        painter.setClipRect(option.rect)
        painter.setPen(option.palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            option.rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(name, Qt.TextElideMode.ElideRight, option.rect.width()),
        )
        for rect, action, _path in self._marker_rects(option, index):
            painter.fillRect(rect, ACTION_COLORS.get(action, QColor("#64748b")))
        painter.restore()

    def mousePressEvent(
        self, event: object, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        position = getattr(event, "position", None)
        point = position() if callable(position) else getattr(event, "pos", lambda: None)()
        if point is not None:
            for rect, _action, path in self._marker_rects(option, index):
                if rect.contains(point.toPoint() if hasattr(point, "toPoint") else point):
                    self.marker_clicked.emit(path)
                    return
        super().mousePressEvent(event, option, index)


class OverviewPane(QWidget):
    """A compact overview of the comparison, in the style of FreeFileSync."""

    object_activated = Signal(str)

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("overview-pane")
        self.setMinimumWidth(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel("Overview")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        legend_grid = QGridLayout()
        legend_grid.setContentsMargins(0, 0, 0, 0)
        legend_grid.setHorizontalSpacing(6)
        legend_grid.setVerticalSpacing(2)
        for position, (action, label) in enumerate(LEGEND):
            swatch = QLabel()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(
                f"background-color: {ACTION_COLORS.get(action, QColor('#64748b')).name()};"
            )
            row, column = divmod(position, 3)
            legend_grid.addWidget(swatch, row, column * 2)
            legend_grid.addWidget(QLabel(label), row, column * 2 + 1)
        legend_grid.setColumnStretch(6, 1)
        layout.addLayout(legend_grid)

        self.model = OverviewModel(self)
        self.tree = QTreeView()
        self.tree.setObjectName("overview-tree")
        self.tree.setModel(self.model)
        self.delegate = OverviewDelegate(self.tree)
        self.tree.setItemDelegate(self.delegate)
        self.tree.setUniformRowHeights(True)
        self.tree.setHeaderHidden(False)
        self.tree.header().setStretchLastSection(False)
        # The markers need room, a busy folder scrolls the pane sideways.
        self.tree.setColumnWidth(0, 240)
        self.tree.setColumnWidth(1, 240)
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.delegate.marker_clicked.connect(self.object_activated.emit)
        layout.addWidget(self.tree, 1)

    def set_changes(self, changes: list[Change], root_name: str = "") -> None:
        self.model.set_changes(changes, root_name)
        self.tree.expandToDepth(0)

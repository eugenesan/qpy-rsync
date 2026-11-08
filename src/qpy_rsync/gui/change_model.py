from __future__ import annotations

from typing import Any

from qpy_rsync.core.changes import Change

try:
    from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
except ImportError:  # Allows backend-only tests without PySide6 installed.
    QAbstractTableModel = object  # type: ignore[assignment,misc]
    QModelIndex = Any  # type: ignore[assignment,misc]
    Qt = None  # type: ignore[assignment]


class ChangeTableModel(QAbstractTableModel):  # type: ignore[misc]
    HEADERS = ("Action", "Path", "Type", "Size", "Modified", "Reason")

    def __init__(self, changes: list[Change] | None = None, parent: object | None = None) -> None:
        if Qt is None:
            raise RuntimeError("PySide6 is required for ChangeTableModel")
        super().__init__(parent)  # type: ignore[call-arg]
        self._changes = list(changes or [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._changes)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = 0) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._changes):
            return None
        change = self._changes[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                change.action.value.replace("_", " ").title(),
                change.path,
                change.kind.value.title(),
                "" if change.size is None else str(change.size),
                change.modified_time or "",
                change.reason,
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{change.itemized_code}: {change.reason}"
        if role == Qt.ItemDataRole.UserRole:
            return change
        return None

    def headerData(self, section: int, orientation: Any, role: int = 0) -> Any:  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def set_changes(self, changes: list[Change]) -> None:
        self.beginResetModel()
        self._changes = list(changes)
        self.endResetModel()

    def change_at(self, row: int) -> Change:
        return self._changes[row]

from __future__ import annotations

from fnmatch import fnmatchcase

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt


class ChangeTreeFilterProxyModel(QSortFilterProxyModel):
    """Name/glob filter that keeps ancestors and optional directory subtrees."""

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self._pattern = ""
        self._include_directory_contents = False
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setRecursiveFilteringEnabled(True)
        self.setAutoAcceptChildRows(False)

    def set_path_filter(self, text: str) -> None:
        value = text.strip()
        self.beginFilterChange()
        self._include_directory_contents = value.endswith("/")
        self._pattern = value.rstrip("/").casefold()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        if not self._pattern or self._pattern == "*":
            return True
        model = self.sourceModel()
        if model is None:
            return False
        node = model.index(source_row, 0, source_parent).internalPointer()
        if self._matches(getattr(node, "name", "")):
            return True
        if not self._include_directory_contents:
            return False
        parent = getattr(node, "parent", None)
        while parent is not None:
            if self._matches(getattr(parent, "name", "")):
                return True
            parent = getattr(parent, "parent", None)
        return False

    def _matches(self, name: str) -> bool:
        candidate = name.casefold()
        if any(character in self._pattern for character in "*?["):
            return fnmatchcase(candidate, self._pattern)
        return self._pattern in candidate

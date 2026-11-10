from __future__ import annotations

from fnmatch import fnmatchcase

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt

from qpy_rsync.core.changes import ChangeAction


class ChangeTreeFilterProxyModel(QSortFilterProxyModel):
    """Name/glob filter with explicit ancestor and subtree matching.

    An additional display-only filter hides selected comparison actions.
    """

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self._pattern = ""
        self._include_directory_contents = False
        self._visible_actions: set[ChangeAction] | None = None
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setRecursiveFilteringEnabled(False)
        self.setAutoAcceptChildRows(False)

    def set_path_filter(self, text: str) -> None:
        value = text.strip()
        self.beginResetModel()
        self._include_directory_contents = value.endswith("/")
        self._pattern = value.rstrip("/").casefold()
        self.endResetModel()

    def set_visible_actions(self, actions: set[ChangeAction] | None) -> None:
        """Restrict displayed rows to the given comparison actions.

        ``None`` shows every action. This filter is display-only and never
        changes synchronization semantics.
        """
        self.beginResetModel()
        self._visible_actions = None if actions is None else set(actions)
        self.endResetModel()

    def visible_actions(self) -> set[ChangeAction] | None:
        return None if self._visible_actions is None else set(self._visible_actions)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return False
        index = model.index(source_row, 0, source_parent)
        if not self._action_allowed(index):
            return False
        if not self._pattern or self._pattern == "*":
            return True
        node = index.internalPointer()
        if self._matches(getattr(node, "name", "")):
            return True
        if self._include_directory_contents and self._ancestor_matches(node):
            return True
        for row in range(model.rowCount(index)):
            if self.filterAcceptsRow(row, index):
                return True
        return False

    def _action_allowed(self, index: QModelIndex) -> bool:
        if self._visible_actions is None:
            return True
        model = self.sourceModel()
        if model is None:
            return False
        node = index.internalPointer()
        change = getattr(node, "change", None)
        if change is not None:
            action = change.action
            if action is ChangeAction.DESTINATION_ONLY:
                decision = getattr(model, "decisions", None)
                if decision is not None and decision.explicit(node.path).value == "include":
                    action = ChangeAction.DELETE
            return action in self._visible_actions
        # A synthetic directory stays visible while it still has visible children.
        for row in range(model.rowCount(index)):
            if self._action_allowed(model.index(row, 0, index)):
                return True
        return False

    def _ancestor_matches(self, node: object) -> bool:
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

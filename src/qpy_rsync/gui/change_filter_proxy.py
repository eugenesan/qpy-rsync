from __future__ import annotations

from fnmatch import fnmatchcase

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt

from qpy_rsync.core.changes import ChangeAction


class ChangeTreeFilterProxyModel(QSortFilterProxyModel):
    """Name/glob filter with explicit ancestor and subtree matching.

    An additional display-only filter hides selected comparison actions.

    Filter decisions are computed once for the complete tree and cached. Doing
    the recursive work inside ``filterAcceptsRow`` made large trees quadratic
    and froze the UI.
    """

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self._pattern = ""
        self._include_directory_contents = False
        self._visible_actions: set[ChangeAction] | None = None
        self._visible_paths: set[str] = set()
        self._cache_valid = False
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setRecursiveFilteringEnabled(False)
        self.setAutoAcceptChildRows(False)

    def setSourceModel(self, model: object) -> None:  # noqa: N802
        previous = self.sourceModel()
        if previous is not None:
            for signal in (
                previous.modelReset,
                previous.layoutChanged,
                previous.dataChanged,
                previous.rowsInserted,
                previous.rowsRemoved,
            ):
                try:
                    signal.disconnect(self._invalidate_cache)
                except (RuntimeError, TypeError):
                    pass
        super().setSourceModel(model)  # type: ignore[arg-type]
        if model is not None:
            for signal in (
                model.modelReset,
                model.layoutChanged,
                model.dataChanged,
                model.rowsInserted,
                model.rowsRemoved,
            ):
                signal.connect(self._invalidate_cache)
        self._invalidate_cache()

    def _invalidate_cache(self, *_args: object) -> None:
        self._cache_valid = False

    def set_path_filter(self, text: str) -> None:
        value = text.strip()
        self._include_directory_contents = value.endswith("/")
        self._pattern = value.rstrip("/").casefold()
        self.refresh_filters()

    def set_visible_actions(self, actions: set[ChangeAction] | None) -> None:
        """Restrict displayed rows to the given comparison actions.

        ``None`` shows every action. This filter is display-only and never
        changes synchronization semantics.
        """
        self._visible_actions = None if actions is None else set(actions)
        self.refresh_filters()

    def visible_actions(self) -> set[ChangeAction] | None:
        return None if self._visible_actions is None else set(self._visible_actions)

    def refresh_filters(self, *, force: bool = True) -> None:
        """Re-evaluate rows without resetting the model.

        Avoiding ``beginResetModel`` preserves the user's expanded rows, which
        is essential when toggling display-only action filters.
        """
        if not force and self._visible_actions is None:
            self._invalidate_cache()
            return
        self._invalidate_cache()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return False
        if not self._cache_valid:
            self._rebuild_cache()
        index = model.index(source_row, 0, source_parent)
        node = index.internalPointer()
        return getattr(node, "path", None) in self._visible_paths

    def _rebuild_cache(self) -> None:
        self._visible_paths = set()
        self._cache_valid = True
        model = self.sourceModel()
        root = getattr(model, "root", None)
        if root is None:
            return
        pattern = self._pattern
        path_filter_active = bool(pattern) and pattern != "*"
        visible_actions = self._visible_actions

        def visit(node: object, ancestor_matches: bool) -> tuple[bool, bool]:
            name = getattr(node, "name", "")
            matches_self = self._matches(name)
            ancestor = ancestor_matches or matches_self
            path_self = (
                not path_filter_active
                or matches_self
                or (self._include_directory_contents and ancestor_matches)
            )
            action_self = self._action_allowed(model, node, visible_actions)
            path_child = False
            action_child = False
            visible_child = False
            for child in getattr(node, "children", ()):
                child_path, child_action, child_visible = visit(child, ancestor)
                path_child = path_child or child_path
                action_child = action_child or child_action
                visible_child = visible_child or child_visible
            path_ok = path_self or path_child
            action_ok = action_self or action_child
            visible = path_ok and action_ok
            path = getattr(node, "path", None)
            if visible and path:
                self._visible_paths.add(path)
            return path_ok, action_ok, visible

        for child in getattr(root, "children", ()):
            visit(child, False)

    @staticmethod
    def _action_allowed(
        model: object,
        node: object,
        visible_actions: set[ChangeAction] | None,
    ) -> bool:
        if visible_actions is None:
            return True
        change = getattr(node, "change", None)
        if change is None:
            # A synthetic directory has no action of its own; its visible
            # children keep it in the tree.
            return False
        effective = getattr(model, "effective_action", None)
        action = effective(node) if effective is not None else change.action
        return action in visible_actions

    def _matches(self, name: str) -> bool:
        if not self._pattern or self._pattern == "*":
            return True
        candidate = name.casefold()
        if any(character in self._pattern for character in "*?["):
            return fnmatchcase(candidate, self._pattern)
        return self._pattern in candidate

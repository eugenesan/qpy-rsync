"""Python side of the hybrid view layer.

The native module owns the four view models and the volatile decision table.
This wrapper hands a comparison over once, embeds the native QWidget in the
PySide6 hierarchy, and exposes the small decision-diff API the rest of the app
needs. It is opt-in; the Python view remains the default.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

_NATIVE_ACTION_CODE = {
    "create": 0,
    "update_content": 1,
    "update_metadata": 2,
    "delete": 3,
    "destination_only": 4,
    "no_change": 5,
    "message": 6,
}
_NATIVE_KINDS = (
    "file",
    "directory",
    "symlink",
    "device",
    "special",
    "unknown",
)

_ACTIVE: object | None = None
_MODULE: object | None = None


def module() -> object | None:
    """Return the extension module, or None when it is not built."""
    global _MODULE
    if _MODULE is None:
        try:
            from qpy_rsync import native_hybrid

            # An ABI-mismatched .so can import but fail when a binding is
            # used; verify the minimal surface before enabling the view.
            required = ("create_tables_widget", "create_overview_widget",
                        "load", "refresh", "shutdown")
            if not all(hasattr(native_hybrid, name) for name in required):
                return None
            _MODULE = native_hybrid
        except (ImportError, OSError, AttributeError):
            return None
    return _MODULE


class NativeHybridView:
    """A native four-pane comparison view driven from Python."""

    def __init__(self) -> None:
        from PySide6.QtWidgets import QWidget
        import shiboken6

        native = module()
        if native is None:
            raise RuntimeError("native_hybrid extension is not available")
        pointer = native.create_tables_widget()
        self._widget = shiboken6.wrapInstance(pointer, QWidget)
        overview_pointer = native.create_overview_widget()
        self.overview_widget = shiboken6.wrapInstance(overview_pointer, QWidget)
        if self._widget is None or self.overview_widget is None:
            raise RuntimeError("could not wrap the native QWidget")
        self._native = native
        self._action_icons: list[object] = []
        self.set_action_colours()
        self._paths: list[str] = []
        self.set_name_icons()
        self._handed_paths: list[str] | None = None
        global _ACTIVE
        _ACTIVE = self

    @property
    def widget(self):
        return self._widget

    @classmethod
    def active(cls) -> NativeHybridView | None:
        return _ACTIVE  # type: ignore[return-value]

    def on_context_menu(self, callback) -> None:
        self._native.set_context_callback(callback)

    def set_root_names(self, source: str, destination: str) -> None:
        self._native.set_root_names(source, destination)

    def select_path(self, path: str, *, focus: bool = False) -> None:
        self._native.select_path(path.rstrip("/"))
        if focus:
            self._native.focus_lists()

    def on_header_context_menu(self, callback) -> None:
        self._native.set_header_context_callback(callback)

    def set_profiling(self, enabled: bool) -> None:
        """Enable the native side of the timing diagnostics."""
        self._native.set_profiling_enabled(bool(enabled))

    def set_column_hidden(self, pane: int, column: int, hidden: bool) -> None:
        self._native.set_column_hidden(pane, column, hidden)

    def is_column_hidden(self, pane: int, column: int) -> bool:
        return bool(self._native.is_column_hidden(pane, column))

    def set_collapsed(self, path: str, value: bool) -> None:
        self.set_collapsed_by_path(path, value)

    def collapse_all(self, value: bool) -> None:
        self._native.collapse_all(value)

    def set_decision_by_path(self, path: str, decision: int) -> None:
        self._native.set_decision_by_path(path.rstrip("/"), decision)

    def reset_decisions(self, path: str = "", subtree: bool = False) -> None:
        self._native.reset_decisions(path.rstrip("/"), subtree)

    def path_id_for_path(self, path: str) -> int:
        return int(self._native.path_id_for_path(path.rstrip("/")))

    def path_of_id(self, path_id: int) -> str:
        return str(self._native.path_of_id(path_id))

    def is_directory(self, path: str) -> bool:
        return bool(self._native.is_directory_by_path(path.rstrip("/")))

    def is_collapsed(self, path: str) -> bool:
        return bool(self._native.is_collapsed_by_path(path.rstrip("/")))

    def decision_for_path(self, path: str) -> int:
        return int(self._native.decision_for_path(path.rstrip("/")))

    def set_name_icons(self) -> None:
        """Hand Python-generated file/folder icons to the native delegate."""
        import shiboken6

        from qpy_rsync.gui.icons import file_type_icon, folder_icon, root_folder_icon

        suffixes = set()
        for path in getattr(self, "_paths", []) or []:
            name = path.rsplit("/", 1)[-1]
            if "." in name:
                suffixes.add(name.rsplit(".", 1)[-1].casefold())
        icons = {"": file_type_icon("file")}
        for suffix in suffixes:
            icons[suffix] = file_type_icon("file." + suffix)
        folder = folder_icon()
        root = root_folder_icon()
        self._name_icons = [folder, root, *icons.values()]
        self._native.set_name_icons(
            int(shiboken6.getCppPointer(folder)[0]),
            int(shiboken6.getCppPointer(root)[0]),
            [
                (suffix, int(shiboken6.getCppPointer(icon)[0]))
                for suffix, icon in icons.items()
            ],
        )

    def set_action_colours(self) -> None:
        from qpy_rsync.core.changes import ChangeAction
        from qpy_rsync.gui.action_colours import current_colours

        colours = current_colours()
        order = (
            ChangeAction.CREATE,
            ChangeAction.UPDATE_CONTENT,
            ChangeAction.UPDATE_METADATA,
            ChangeAction.DELETE,
            ChangeAction.DESTINATION_ONLY,
            ChangeAction.NO_CHANGE,
            ChangeAction.MESSAGE,
        )
        self._native.set_action_colours([str(colours.get(a) or "") for a in order])
        # The Python generator is the single source of truth for action
        # icons. Hand the native layer the same QIcons used by the toolbar
        # and statistics bar, regenerated whenever colours change.
        import shiboken6

        from qpy_rsync.gui.icons import action_icon

        icons = [action_icon(action) for action in order]
        self._action_icons = icons  # keep the C++ objects alive
        self._native.set_action_icons(
            [int(shiboken6.getCppPointer(icon)[0]) for icon in icons]
        )

    def shutdown(self) -> None:
        """Drop Python callbacks before the interpreter shuts down."""
        self._native.shutdown()

    def set_changes_for_unchanged(self, count: int) -> None:
        """Fast path: unchanged items were removed, executable rows unchanged."""
        handed = self._handed_paths or []
        if len(handed) == count:
            return
        if len(handed) < count:
            return  # additions still take the regular handoff path
        self._native.truncate(count)
        self._handed_paths = handed[:count]
        self._paths = self._paths[:count]
        self._native.refresh()

    def set_changes_for_unchanged(self, count: int) -> None:
        """Fast path: unchanged items were removed, executable rows unchanged."""
        handed = self._handed_paths or []
        if len(handed) <= count:
            return
        self._native.truncate(count)
        self._handed_paths = handed[:count]
        self._paths = self._paths[:count]
        self._native.refresh()

    def set_changes(self, changes: Sequence[Any]) -> None:
        """Hand the dataset to native once; append only when it grows."""
        paths = [str(change.path).rstrip("/") for change in changes]
        self._paths = paths
        if self._handed_paths == paths:
            return
        prefix = self._handed_paths or []
        if prefix and len(paths) < len(prefix) and prefix[: len(paths)] == paths:
            self._native.truncate(len(paths))
            self._handed_paths = list(paths)
            self._paths = paths
            self._native.refresh()
            return
        start = len(prefix) if paths[: len(prefix)] == prefix else 0
        subset = changes[start:] if start else changes
        arrays = (
            [
                _NATIVE_ACTION_CODE.get(change.action.value, 6)
                for change in subset
            ],
            [_NATIVE_KINDS.index(change.kind.value) for change in subset],
            [int(change.size or 0) for change in subset],
            [0] * len(subset),
            [str(change.modified_time or "") for change in subset],
        )
        new_paths = paths[start:] if start else paths
        if start:
            self._native.append(new_paths, *arrays)
        else:
            self._native.load(new_paths, *arrays)
        self._handed_paths = list(paths)
        self.set_name_icons()
        self._native.refresh()

    def set_action_filter(self, actions) -> None:
        mask = -1 if not actions else 0
        for action in actions:
            code = _NATIVE_ACTION_CODE.get(getattr(action, "value", action), 6)
            if code < 32:
                mask |= 1 << code
        self._native.set_action_filter(mask)
        self._native.refresh_visible()

    def set_pattern(self, pattern: str, *, glob: bool = False,
                    directories_only: bool = False,
                    include_contents: bool = False) -> None:
        self._native.set_pattern(pattern, glob, directories_only, include_contents)
        self._native.refresh_visible()

    def set_sort(self, column: int, descending: bool = False) -> None:
        self._native.set_sort(column, descending)
        # Keep the header indicators in sync when sorting is routed from the
        # Python comparison view rather than from a native header click.
        from PySide6.QtCore import QSignalBlocker
        from PySide6.QtWidgets import QHeaderView, QTableView

        order = (
            __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.SortOrder.DescendingOrder
            if descending
            else __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.SortOrder.AscendingOrder
        )
        for table in self.widget.findChildren(QTableView):
            header = table.horizontalHeader()
            blocker = QSignalBlocker(header)
            header.setSortIndicator(column, order)
        self._native.refresh_visible()

    def set_collapsed_by_path(self, path: str, collapsed: bool) -> None:
        self._native.set_collapsed_by_path(path, collapsed)
        self._native.refresh_visible()

    def search(self, text: str) -> list[int]:
        return list(self._native.search_text(text))

    def selected_path(self) -> str:
        return str(self._native.selected_path())

    def path_of_row(self, row: int) -> str:
        return str(self._native.path_of_row(row))

    def row_count(self) -> int:
        return int(self._native.row_count())

    def on_selection_changed(self, callback) -> None:
        self._native.set_selection_callback(callback)

    def on_decision_changed(self, callback) -> None:
        """Call ``callback(path_id, decision)`` when the user edits a decision."""
        self._native.set_decision_callback(callback)

    def set_show_excluded(self, show: bool) -> None:
        self._native.set_show_excluded(show)

    def set_destination_metadata(self, metadata, *, merge: bool = False) -> None:
        self._native.apply_destination_metadata(metadata, merge)

    def apply_python_decisions(self, decisions) -> None:
        pairs = []
        for path, decision in decisions.items():
            try:
                path_id = self._paths.index(str(path).rstrip("/"))
            except ValueError:
                continue
            pairs.append((path_id, int(decision)))
        self._native.apply_python_decisions(pairs)

    def refresh_after_decision(self, path_id: int, decision: int) -> None:
        self._native.refresh_after_decision(path_id, decision)

    def refresh(self) -> None:
        self._native.refresh_visible()
        self._native.refresh()

    def set_checkstate(self, row: int, checked: bool) -> None:
        """Simulate the user toggling the decision checkbox in the native view."""
        self._native.set_checkstate(row, checked)

    def toggle_decision(self, path_id: int) -> None:
        self._native.toggle_decision(path_id)

    def decision_diff(self) -> list[tuple[int, int]]:
        return [tuple(pair) for pair in self._native.decision_diff()]


class NativeOverviewShim(QWidget):
    """Real QWidget wrapper for the native overview (drop-in for OverviewPane)."""

    folder_activated = Signal(str)
    exclusion_requested = Signal(str)
    restore_requested = Signal(str)
    filter_requested = Signal(str)

    def __init__(self, widget: QWidget) -> None:
        super().__init__()
        self.tree = widget
        from qpy_rsync.gui.overview import StatisticsBar

        # Hidden mirror so code that reads OverviewPane.statistics keeps
        # working while the native widget draws the visible stats footer.
        self.statistics = StatisticsBar()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        widget.setMinimumHeight(160)
        self.setMinimumHeight(180)

    def set_paths(self, *_args, **_kwargs) -> None:
        pass

    def set_aggregates(self, *_args, **_kwargs) -> None:
        pass

    def set_statistics(self, summary, *, estimate: bool = False) -> None:
        self.statistics.set_summary(summary, estimate=estimate)

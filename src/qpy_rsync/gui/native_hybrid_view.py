"""Python side of the hybrid view layer.

The native module owns the four view models and the volatile decision table.
This wrapper hands a comparison over once, embeds the native QWidget in the
PySide6 hierarchy, and exposes the small decision-diff API the rest of the app
needs. It is opt-in; the Python view remains the default.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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

            _MODULE = native_hybrid
        except (ImportError, OSError):
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
        pointer = native.create_widget()
        self._widget = shiboken6.wrapInstance(pointer, QWidget)
        if self._widget is None:
            raise RuntimeError("could not wrap the native QWidget")
        self._native = native
        global _ACTIVE
        _ACTIVE = self

    @property
    def widget(self):
        return self._widget

    @classmethod
    def active(cls) -> NativeHybridView | None:
        return _ACTIVE  # type: ignore[return-value]

    def shutdown(self) -> None:
        """Drop Python callbacks before the interpreter shuts down."""
        self._native.shutdown()

    def set_changes(self, changes: Sequence[Any]) -> None:
        """Hand the dataset to native exactly once."""
        self._native.load(
            [str(change.path).rstrip("/") for change in changes],
            [
                _NATIVE_ACTION_CODE.get(change.action.value, 6)
                for change in changes
            ],
            [_NATIVE_KINDS.index(change.kind.value) for change in changes],
            [int(change.size or 0) for change in changes],
            [0] * len(changes),
        )
        self._native.refresh()

    def row_count(self) -> int:
        return int(self._native.row_count())

    def on_decision_changed(self, callback) -> None:
        """Call ``callback(path_id, decision)`` when the user edits a decision."""
        self._native.set_decision_callback(callback)

    def set_checkstate(self, row: int, checked: bool) -> None:
        """Simulate the user toggling the decision checkbox in the native view."""
        self._native.set_checkstate(row, checked)

    def toggle_decision(self, path_id: int) -> None:
        self._native.toggle_decision(path_id)

    def decision_diff(self) -> list[tuple[int, int]]:
        return [tuple(pair) for pair in self._native.decision_diff()]

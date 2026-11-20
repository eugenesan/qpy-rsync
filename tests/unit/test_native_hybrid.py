"""Tests for the optional native Qt view layer.

Skip cleanly when the extension has not been built; the Python view remains
the shipped default.
"""

from __future__ import annotations

import pytest

pytest.importorskip("qpy_rsync.native_hybrid")

from PySide6.QtWidgets import QApplication  # noqa: E402

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind  # noqa: E402
from qpy_rsync.gui.native_hybrid_view import NativeHybridView  # noqa: E402


def test_native_view_handoff_and_decision_diff() -> None:
    application = QApplication.instance() or QApplication([])
    changes = [
        Change(f"d{i % 3}/f{i}.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", 10)
        for i in range(30)
    ]
    view = NativeHybridView()
    view.set_changes(changes)
    assert view.row_count() == 30
    before = view.decision_diff()
    view.set_checkstate(4, False)
    after = view.decision_diff()
    assert len(after) == len(before) + 1
    path_id, decision = after[-1]
    assert path_id == 4
    assert decision == 2  # Exclude
    view.shutdown()

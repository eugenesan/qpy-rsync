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
    # The native view adds one row per synthesized folder (d0..d2) plus the
    # virtual root on top of the 30 change rows.
    assert view.row_count() == 34
    before = view.decision_diff()
    view.set_checkstate(4, False)
    after = view.decision_diff()
    assert len(after) == len(before) + 1
    path_id, decision = after[-1]
    assert 0 <= path_id < 30
    assert decision == 2  # Exclude
    view.shutdown()


def test_undo_restores_the_excluded_row_and_cursor() -> None:
    application = QApplication.instance() or QApplication([])
    changes = [
        Change(f"d{i % 4}/f{i:04d}.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", i)
        for i in range(80)
    ]
    view = NativeHybridView()
    view.set_changes(changes)
    native = view._native
    from PySide6.QtWidgets import QTableView

    tables = sorted(view.widget.findChildren(QTableView), key=lambda t: t.x())
    source = tables[0]
    source.setFocus()
    original_row = 30
    original_path = view.path_of_row(original_row)
    source.setCurrentIndex(source.model().index(original_row, 0))
    application.processEvents()

    view.set_decision_by_path(original_path, 2)
    application.processEvents()
    assert view.decision_for_path(original_path) == 2
    assert view.path_of_row(source.currentIndex().row()) != original_path

    view.apply_python_decisions({})
    application.processEvents()
    assert view.decision_for_path(original_path) == 0
    assert view.path_of_row(source.currentIndex().row()) == original_path
    view.shutdown()


def test_excluding_a_symlink_hides_its_row() -> None:
    """A symlink whose listing path still carries `` -> target`` must behave
    like every other item when it is excluded."""
    application = QApplication.instance() or QApplication([])
    from qpy_rsync.backend.rsync_parser import parse_record

    link = parse_record(
        ">L+++++++++|qpy-rsync|4|qpy-rsync|2026/11/26-09:00:00|qpy-rsync|link -> target"
    )
    assert link is not None
    # Simulate a path that came from a listing rather than the parser: the
    # decision store and the native model must still agree on the key.
    link = link.__class__(
        "link -> target", link.action, link.kind, link.itemized_code,
        link.size, link.modified_time, link.link_target, link.reason,
    )
    view = NativeHybridView()
    view.set_changes([link, Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", 10)])
    application.processEvents()
    assert view._paths == ["link", "a.txt"]
    assert view.path_id_for_path("link") == 0
    assert "link" in [view.path_of_row(row) for row in range(view.row_count())]

    view.set_decision_by_path("link", 2)
    application.processEvents()
    assert view.decision_for_path("link") == 2
    assert "link" not in [view.path_of_row(row) for row in range(view.row_count())]

    # A decision mirrored from the Python side uses the same path key.
    view.apply_python_decisions({})
    application.processEvents()
    assert view.decision_for_path("link") == 0
    assert "link" in [view.path_of_row(row) for row in range(view.row_count())]
    view.shutdown()

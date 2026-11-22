"""Differential checks between the shipped Python view and the hybrid view.

Both windows are built from the same change list and driven through the same
user-level operations; the visible invariants must agree.
"""

from __future__ import annotations

import pytest

from PySide6.QtWidgets import QApplication

pytest.importorskip("qpy_rsync.native_hybrid")

from qpy_rsync.backend.rsync_parser import ParseResult  # noqa: E402
from qpy_rsync.gui.main_window import MainWindow  # noqa: E402
from qpy_rsync.services.compare_service import CompareResult  # noqa: E402
from qpy_rsync.storage.settings import app_settings  # noqa: E402
from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind  # noqa: E402


def _window(monkeypatch, *, hybrid: bool):
    monkeypatch.setenv("QPY_HYBRID_VIEW", "1" if hybrid else "0")
    settings = app_settings()
    settings.setValue("advanced/hybrid_view", False)
    settings.sync()
    window = MainWindow()
    window.source_edit.setText("/src/")
    window.destination_edit.setText("/dst/")
    window._active_profile = window._profile()
    window._baseline_profile = window._profile()
    changes = [
        Change(f"d{i % 3}/f{i:04d}.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", i)
        for i in range(24)
    ]
    window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
    QApplication.processEvents()
    return window


def test_python_and_native_views_agree(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    python = _window(monkeypatch, hybrid=False)
    native = _window(monkeypatch, hybrid=True)
    try:
        assert native._hybrid_view is not None

        def rows(window):
            return window.comparison.model.rowCount()

        assert rows(python) == rows(native) == 28

        # Excluding a file hides exactly that row in both views.
        path = "d1/f0001.txt"
        python.comparison.model.set_excluded(path, True)
        native._hybrid_view.set_decision_by_path(path, 2)
        app.processEvents()
        assert python.comparison.excluded_paths() == native.comparison.excluded_paths() == {path}
        assert rows(python) == rows(native) == 27

        # Undo restores it.
        python.comparison.model.set_excluded(path, False)
        native._hybrid_view.set_decision_by_path(path, 0)
        app.processEvents()
        assert rows(python) == rows(native) == 28

        # Folding a folder hides its descendants in both views.
        python.comparison.collapse_path("d0")
        native._hybrid_view.set_collapsed("d0", True)
        app.processEvents()
        assert rows(python) == rows(native) == 20

        # Selecting a path reports the same item in both views.
        target = "d2/f0002.txt"
        python.comparison.select_path(target)
        native._hybrid_view.select_path(target)
        app.processEvents()
        assert native._hybrid_view.selected_path() == target
    finally:
        python.close()
        native.close()
        app.processEvents()


def test_row_order_and_header_sorting_match(monkeypatch) -> None:
    from PySide6.QtCore import Qt

    app = QApplication.instance() or QApplication([])

    def build(hybrid: bool):
        monkeypatch.setenv("QPY_HYBRID_VIEW", "1" if hybrid else "0")
        settings = app_settings()
        settings.setValue("advanced/hybrid_view", False)
        settings.sync()
        window = MainWindow()
        window.source_edit.setText("/src/")
        window.destination_edit.setText("/dst/")
        window._active_profile = window._profile()
        window._baseline_profile = window._profile()
        paths = [
            "b/z.txt", "a/f2.txt", "a/sub/f1.txt", "a/f1.txt",
            "b/a.txt", "c/sub/deep/x.txt", "root.txt", "a/sub/f0.txt",
        ]
        changes = [
            Change(p, ChangeAction.CREATE, ObjectKind.FILE, ">f", i * 100)
            for i, p in enumerate(paths)
        ]
        window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
        app.processEvents()
        return window

    python = build(False)
    native = build(True)
    try:
        def rows(window):
            if window._hybrid_view is not None:
                return [
                    window._hybrid_view.path_of_row(r)
                    for r in range(window._hybrid_view.row_count())
                ]
            return [
                window.comparison.model.row_path(r)
                for r in range(window.comparison.model.rowCount())
            ]

        assert rows(python) == rows(native)
        for column in (0, 2):
            for descending in (False, True):
                order = (
                    Qt.SortOrder.DescendingOrder
                    if descending else Qt.SortOrder.AscendingOrder
                )
                python.comparison.model.sort(column, order)
                native._hybrid_view.set_sort(column, descending)
                app.processEvents()
                assert rows(python) == rows(native)
    finally:
        python.close()
        native.close()
        app.processEvents()

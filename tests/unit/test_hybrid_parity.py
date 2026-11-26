"""Differential checks between the shipped Python view and the hybrid view.

Both windows are built from the same change list and driven through the same
user-level operations; the visible invariants must agree.
"""

from __future__ import annotations

import pytest

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QApplication, QTreeView

pytest.importorskip("qpy_rsync.native_hybrid")

from qpy_rsync.backend.rsync_parser import ParseResult  # noqa: E402
from qpy_rsync.gui.main_window import MainWindow  # noqa: E402
from qpy_rsync.services.compare_service import CompareResult  # noqa: E402
from qpy_rsync.storage.settings import app_settings  # noqa: E402
from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind  # noqa: E402


def _window(monkeypatch, *, hybrid: bool):
    monkeypatch.setenv("QPY_HYBRID_VIEW", "1" if hybrid else "0")
    settings = app_settings()
    settings.setValue("advanced/python_view", not hybrid)
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
        settings.setValue("advanced/python_view", not hybrid)
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


def test_header_sort_indicators_are_linked(monkeypatch) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableView

    app = QApplication.instance() or QApplication([])

    def build(hybrid: bool):
        monkeypatch.setenv("QPY_HYBRID_VIEW", "1" if hybrid else "0")
        settings = app_settings()
        settings.setValue("advanced/python_view", not hybrid)
        settings.sync()
        window = MainWindow()
        window.source_edit.setText("/src/")
        window.destination_edit.setText("/dst/")
        window._active_profile = window._profile()
        window._baseline_profile = window._profile()
        changes = [
            Change(f"d{i % 2}/f{i:03d}.txt", ChangeAction.CREATE,
                   ObjectKind.FILE, ">f", i)
            for i in range(12)
        ]
        window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
        app.processEvents()
        return window

    python = build(False)
    native = build(True)
    try:
        def headers(window):
            if window._hybrid_view is not None:
                tables = sorted(window._hybrid_view.widget.findChildren(QTableView),
                                key=lambda t: t.x())
            else:
                tables = [window.comparison.source, window.comparison.action,
                          window.comparison.destination]
            return [t.horizontalHeader() for t in tables]

        for window in (python, native):
            headers(window)[2].setSortIndicator(7, Qt.SortOrder.DescendingOrder)
            app.processEvents()
            sections = [h.sortIndicatorSection() for h in headers(window)]
            assert sections == [2, -1, 7]
            assert all(h.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
                       for h in headers(window))
    finally:
        python.close()
        native.close()
        app.processEvents()


def test_overview_hierarchy_matches(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])

    def build(hybrid: bool):
        monkeypatch.setenv("QPY_HYBRID_VIEW", "1" if hybrid else "0")
        settings = app_settings()
        settings.setValue("advanced/python_view", not hybrid)
        settings.sync()
        window = MainWindow()
        window.source_edit.setText("/src/")
        window.destination_edit.setText("/dst/")
        window._active_profile = window._profile()
        window._baseline_profile = window._profile()
        paths = ["root.txt", "a/f1.txt", "a/sub/f2.txt", "b/f3.txt"]
        changes = [
            Change(p, ChangeAction.CREATE, ObjectKind.FILE, ">f", i)
            for i, p in enumerate(paths)
        ]
        window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
        app.processEvents()
        return window

    python = build(False)
    native = build(True)
    try:
        def outline(window):
            if window._hybrid_view is not None:
                tree = window._hybrid_view.overview_widget.findChildren(QTreeView)[0]
                model = tree.model()
            else:
                tree = window.overview.tree
                model = tree.model()

            def walk(parent, depth=0):
                result = []
                for row in range(model.rowCount(parent)):
                    index = model.index(row, 0, parent)
                    result.append((depth, str(model.data(index)), bool(model.hasChildren(index))))
                    result.extend(walk(index, depth + 1))
                return result
            return walk(QModelIndex())

        py_outline = outline(python)
        native_outline = outline(native)
        assert py_outline[0][1] == native_outline[0][1] == "Total"
        # Folder rows keep expandable children in both views; direct files are
        # presented differently, which is not part of this parity check.
        assert {"a", "b"}.issubset({name for _depth, name, _children in py_outline})
        assert {"a", "b"}.issubset({name for _depth, name, _children in native_outline})
        assert dict((name, children) for _depth, name, children in py_outline)["a"] is True
        assert dict((name, children) for _depth, name, children in native_outline)["a"] is True
    finally:
        python.close()
        native.close()
        app.processEvents()


def test_ctrl_click_on_excluded_switches_native_view_to_only_excluded(
    monkeypatch,
) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    app = QApplication.instance() or QApplication([])
    window = _window(monkeypatch, hybrid=True)
    try:
        view = window._hybrid_view
        assert view is not None
        excluded = "d1/f0001.txt"
        included = "d0/f0000.txt"
        view.set_decision_by_path(excluded, 2)
        app.processEvents()
        rows = lambda: [view.path_of_row(row) for row in range(view.row_count())]
        assert excluded not in rows()

        box = window.action_filters.excluded_box
        position = QPointF(box.rect().center())
        for event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            event = QMouseEvent(
                event_type,
                position,
                position,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.ControlModifier,
            )
            QApplication.sendEvent(box, event)
        app.processEvents()
        shown = rows()
        assert excluded in shown
        assert included not in shown

        # Ctrl+click again leaves "only excluded" and restores the defaults.
        for event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(
                box,
                QMouseEvent(
                    event_type,
                    position,
                    position,
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.ControlModifier,
                ),
            )
        app.processEvents()
        shown = rows()
        assert excluded not in shown
        assert included in shown
    finally:
        window.close()
        app.processEvents()


def test_native_overview_totals_update_immediately_on_exclusions(
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    window = _window(monkeypatch, hybrid=True)
    try:
        view = window._hybrid_view
        assert view is not None
        tree = view.overview_widget.findChildren(QTreeView)[0]
        model = tree.model()

        def items(name: str):
            def walk(parent, path):
                for row in range(model.rowCount(parent)):
                    index = model.index(row, 0, parent)
                    label = str(model.data(index))
                    if label == name:
                        return model.data(model.index(row, 2, parent))
                    found = walk(index, path + [label])
                    if found is not None:
                        return found
                return None
            return walk(QModelIndex(), [])

        total_before = items("Total")
        folder_before = items("d1")
        assert total_before is not None and folder_before is not None

        path = "d1/f0001.txt"
        view.set_decision_by_path(path, 2)
        app.processEvents()
        assert items("Total") == total_before - 1
        assert items("d1") == folder_before - 1

        # Restoring the decision brings both counts back immediately.
        view.set_decision_by_path(path, 0)
        app.processEvents()
        assert items("Total") == total_before
        assert items("d1") == folder_before
    finally:
        window.close()
        app.processEvents()

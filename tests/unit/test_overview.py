from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.gui.overview import OverviewModel, OverviewPane


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _changes() -> list[Change]:
    return [
        Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=100),
        Change("docs/b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......", size=200),
        Change("docs/old.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        Change("root.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=50),
        Change(
            "only-destination.txt",
            ChangeAction.DESTINATION_ONLY,
            ObjectKind.FILE,
            "*deleting",
        ),
    ]


def test_overview_reports_the_size_and_the_count_of_every_folder() -> None:
    app()
    model = OverviewModel()
    model.set_changes(_changes(), "source")

    # The rows are the folders of the compared root and the files in it.
    assert model.rowCount() == 2
    names = [model.data(model.index(row, 1), Qt.ItemDataRole.DisplayRole) for row in range(2)]
    assert names == ["docs", "Files"]

    docs_index = model.index(0, 1)
    assert model.data(docs_index, Qt.ItemDataRole.DisplayRole) == "docs"
    assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "3"
    assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "300 B"

    # The objects of the compared folder itself are listed in the Files row.
    files_index = model.index(1, 1)
    assert model.data(files_index, Qt.ItemDataRole.DisplayRole) == "Files"
    assert model.data(model.index(1, 2), Qt.ItemDataRole.DisplayRole) == "2"
    assert model.data(model.index(1, 3), Qt.ItemDataRole.DisplayRole) == "50 B"

    # The first column shows the share of the folder.
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "86%"
    assert model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole) == "14%"


def test_overview_sorts_the_folders_by_size_or_by_count() -> None:
    app()
    model = OverviewModel()
    model.set_changes(_changes(), "source")

    # The size is the default order, the biggest folder first.
    model.sort(3, Qt.SortOrder.DescendingOrder)
    assert model.index(0, 1).data() == "docs"

    # The Files row has fewer objects, so it comes first by the count.
    model.sort(2, Qt.SortOrder.DescendingOrder)
    assert model.index(0, 1).data() == "docs"
    model.sort(2, Qt.SortOrder.AscendingOrder)
    assert model.index(0, 1).data() == "Files"


def test_overview_pane_reports_the_activated_folder() -> None:
    application = app()
    pane = OverviewPane()
    pane.set_changes(_changes(), "source")
    application.processEvents()
    activated: list[str] = []
    pane.folder_activated.connect(activated.append)
    pane._folder_activated(pane.model.index(0, 1))
    assert activated == ["docs"]
    pane.close()
    application.processEvents()


def test_overview_follows_the_action_filters() -> None:
    from qpy_rsync.core.changes import ChangeAction
    from qpy_rsync.gui.comparison_view import ComparisonView

    application = app()
    view = ComparisonView()
    changes = [
        Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=100),
        Change("b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......", size=200),
    ]
    view.set_changes(changes)
    application.processEvents()
    assert len(view.visible_changes()) == 2

    # Hiding the updates removes the object from the overview as well.
    view.set_action_filter({ChangeAction.CREATE})
    application.processEvents()
    visible = view.visible_changes()
    assert [change.path for change in visible] == ["a.txt"]
    view.close()
    application.processEvents()

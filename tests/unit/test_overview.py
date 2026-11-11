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
        Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
        Change("docs/b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
        Change("docs/old.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        Change("root.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
        Change("only-destination.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting"),
    ]


def test_overview_groups_the_objects_by_their_folder() -> None:
    app()
    model = OverviewModel()
    model.set_changes(_changes(), "source")

    # The root of the overview is the source folder itself.
    assert model.rowCount() == 1
    root_index = model.index(0, 0)
    assert model.data(root_index, Qt.ItemDataRole.DisplayRole) == "source"
    root_markers = model.data(root_index, OverviewModel.MarkersRole)
    assert [action for action, _path in root_markers] == [ChangeAction.CREATE]
    # An object that only exists in the destination is not in the source.
    root_destination = model.data(
        model.index(0, 1), OverviewModel.MarkersRole
    )
    assert [action for action, _path in root_destination] == [
        ChangeAction.DESTINATION_ONLY
    ]

    # The objects of a folder belong to that folder.
    assert model.rowCount(root_index) == 1
    docs_index = model.index(0, 0, root_index)
    assert model.data(docs_index, Qt.ItemDataRole.DisplayRole) == "docs"
    docs_markers = model.data(docs_index, OverviewModel.MarkersRole)
    assert [action for action, _path in docs_markers] == [
        ChangeAction.CREATE,
        ChangeAction.UPDATE_CONTENT,
        ChangeAction.DELETE,
    ]
    # The destination knows the object that will be deleted.
    destination_markers = model.data(
        model.index(0, 1, root_index), OverviewModel.MarkersRole
    )
    assert [action for action, _path in destination_markers] == [
        ChangeAction.DELETE
    ]


def test_overview_pane_reports_the_activated_object() -> None:
    application = app()
    pane = OverviewPane()
    pane.set_changes(_changes(), "source")
    application.processEvents()
    activated: list[str] = []
    pane.object_activated.connect(activated.append)
    pane.delegate.marker_clicked.emit("docs/a.txt")
    assert activated == ["docs/a.txt"]
    pane.close()
    application.processEvents()

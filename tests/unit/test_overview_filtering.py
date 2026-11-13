"""The Overview pane stashes and filters folders like the comparison list."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.gui.overview import OverviewPane


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def pane_with_changes() -> OverviewPane:
    pane = OverviewPane()
    pane.set_changes(
        [
            Change("docs/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f", size=10),
            Change("pics/c.jpg", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f", size=30),
        ],
        "src",
    )
    return pane


def folder_row(pane: OverviewPane, name: str) -> int:
    total = pane.model.index(0, 0)
    for row in range(pane.model.rowCount(total)):
        index = pane.model.index(row, 0, total)
        if pane.model.data(index, Qt.ItemDataRole.DisplayRole) == name:
            return row
    return -1


def test_the_space_bar_on_a_folder_asks_to_stash_it() -> None:
    application = app()
    pane = pane_with_changes()
    fired: list[str] = []
    pane.stash_requested.connect(fired.append)
    row = folder_row(pane, "docs")
    assert row >= 0
    total = pane.model.index(0, 0)
    pane.tree.setCurrentIndex(pane.model.index(row, 0, total))
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier
    )
    assert pane.eventFilter(pane.tree, event) is True
    assert fired == ["docs"]
    pane.close()
    application.processEvents()


def test_the_space_bar_on_the_total_row_is_ignored() -> None:
    application = app()
    pane = pane_with_changes()
    fired: list[str] = []
    pane.stash_requested.connect(fired.append)
    pane.tree.setCurrentIndex(pane.model.index(0, 0))
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier
    )
    pane.eventFilter(pane.tree, event)
    assert fired == []
    pane.close()
    application.processEvents()

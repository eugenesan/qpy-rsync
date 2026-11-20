"""Show a MainWindow populated with synthetic changes for visual comparison."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.backend.rsync_parser import ParseResult
from qpy_rsync.services.compare_service import CompareResult
from qpy_rsync.gui.main_window import MainWindow

COUNT = int(os.environ.get("QPY_SHOW_COUNT", "2000"))
OUTPUT = os.environ.get("QPY_SHOW_SHOT", "")

app = QApplication([])
window = MainWindow()
window.source_edit.setText("/home/user/sample-src/")
window.destination_edit.setText("/home/user/sample-dst/")
window._active_profile = window._profile()
# Keep the exit prompt out of the capture flow.
window._baseline_profile = window._profile()
changes = []
for i in range(COUNT):
    path = f"d{i % 40}/sub{i % 7}/file-{i:05d}.txt"
    action = (
        ChangeAction.DELETE if i % 23 == 0
        else ChangeAction.UPDATE_CONTENT if i % 7 == 0
        else ChangeAction.UPDATE_METADATA if i % 11 == 0
        else ChangeAction.CREATE
    )
    changes.append(
        Change(path, action, ObjectKind.FILE, ">f", size=(i * 137) % 100000,
               modified_time="2026/11/20-12:34:56")
    )
window._comparison_finished(CompareResult(ParseResult(changes, []), "", 0))
window.showMaximized()
app.processEvents()
app.processEvents()
if OUTPUT:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QPixmap

    def grab() -> None:
        pixmap = window.grab()
        pixmap.save(OUTPUT)
        app.quit()

    QTimer.singleShot(300, grab)
    app.exec()
else:
    app.exec()

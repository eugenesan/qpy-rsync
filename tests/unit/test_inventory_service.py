import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading

from PySide6.QtCore import QEventLoop, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import Endpoint, SyncProfile
from qpy_rsync.services.inventory_service import InventoryService


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def profile() -> SyncProfile:
    return SyncProfile(
        "inventory",
        Endpoint(EndpointKind.LOCAL, "/src/"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
    )


def test_inventory_service_runs_off_the_gui_thread() -> None:
    application = app()
    calls: list[tuple[str, int]] = []
    started = threading.Event()

    def gather(_profile: SyncProfile, changed: list[Change]) -> list[Change]:
        calls.append((threading.current_thread().name, len(changed)))
        started.set()
        return [Change("same.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, "=")]

    service = InventoryService(gather=gather)
    results: list[tuple[int, list[Change]]] = []
    service.finished.connect(lambda token, result: results.append((token, list(result))))
    changed = [Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    token = service.gather(profile(), changed)

    loop = QEventLoop()
    service.finished.connect(lambda *_: loop.quit())
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    QThreadPool.globalInstance().waitForDone(5000)
    application.processEvents()

    assert started.is_set()
    assert calls
    assert calls[0][0] != threading.current_thread().name
    assert calls[0][1] == 1
    assert results
    assert results[0][0] == token
    assert results[0][1][0].path == "same.txt"


def test_inventory_service_returns_increasing_tokens() -> None:
    app()

    def gather(_profile: SyncProfile, _changed: list[Change]) -> list[Change]:
        return []

    service = InventoryService(gather=gather)
    first = service.gather(profile(), [])
    second = service.gather(profile(), [])
    service.cancel()
    assert second > first
    QThreadPool.globalInstance().waitForDone(5000)

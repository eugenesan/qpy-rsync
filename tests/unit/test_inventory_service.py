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


def test_inventory_service_reports_listing_progress() -> None:
    application = app()
    reports: list[tuple[str, int]] = []

    def gather(_profile: SyncProfile, _changed: list[Change], progress) -> list[Change]:
        progress("Source", 500)
        progress("Destination", 750)
        return []

    service = InventoryService(gather=gather)
    service.progress.connect(lambda _token, phase, count: reports.append((phase, count)))
    loop = QEventLoop()
    service.finished.connect(lambda *_: loop.quit())
    QTimer.singleShot(5000, loop.quit)
    service.gather(profile(), [])
    loop.exec()
    QThreadPool.globalInstance().waitForDone(5000)
    application.processEvents()
    assert ("Source", 500) in reports
    assert ("Destination", 750) in reports


def test_destination_metadata_is_listed_on_its_own(monkeypatch) -> None:
    from qpy_rsync.backend import inventory as inv

    def fake_paths(endpoint, profile=None, progress=None):
        from qpy_rsync.core.changes import ObjectKind

        return {
            "gone.txt": inv.InventoryEntry(
                ObjectKind.FILE, size=1234, modified_time="2024-01-02-03:04:05"
            ),
            "kept.txt": inv.InventoryEntry(
                ObjectKind.FILE, size=99, modified_time="2024-02-03-04:05:06"
            ),
        }

    monkeypatch.setattr(inv, "inventory_paths", fake_paths)
    from qpy_rsync.core.endpoints import parse_endpoint
    from qpy_rsync.core.models import SyncProfile

    profile = SyncProfile(
        name="t",
        source=parse_endpoint("/tmp/a"),
        destination=parse_endpoint("/tmp/b"),
    )
    result = inv.gather_destination_metadata(profile, [])
    assert result.unchanged == []
    assert result.destination_metadata["gone.txt"] == (1234, "2024-01-02-03:04:05")

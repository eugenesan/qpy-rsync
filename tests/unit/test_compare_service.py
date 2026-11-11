import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from qpy_rsync.backend.process_runner import ProcessResult
from qpy_rsync.services.compare_service import CompareService
from qpy_rsync.services.plan_validation_service import PlanValidationService


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_compare_service_streams_records_and_progress() -> None:
    app()
    service = CompareService()
    logs: list[str] = []
    progress: list[object] = []
    service.on_log = logs.append
    service.on_progress = progress.append

    service._stdout_chunk(">f.st......|qpy-rsync|8|qpy-rsync|2024/01/01|qpy-rsync|file")
    assert logs == []
    service._stdout_chunk(".txt\n\r             8 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=1/2)\r")
    assert logs == [">f.st......|qpy-rsync|8|qpy-rsync|2024/01/01|qpy-rsync|file.txt"]
    assert len(progress) == 1
    assert progress[0].files_completed == 1
    assert progress[0].percent == 50


def test_compare_service_reports_cancellation_without_finishing() -> None:
    app()
    service = CompareService()
    finished: list[object] = []
    cancelled: list[bool] = []
    service.on_finished = finished.append
    service.on_cancelled = lambda: cancelled.append(True)
    service._cancelled = True
    service._finish(ProcessResult(0, "", ""))
    assert cancelled == [True]
    assert finished == []


def test_compare_service_reports_crashed_run_as_error() -> None:
    app()
    service = CompareService()
    finished: list[object] = []
    cancelled: list[bool] = []
    errors: list[str] = []
    service.on_finished = finished.append
    service.on_cancelled = lambda: cancelled.append(True)
    service.on_error = errors.append
    service._finish(ProcessResult(-1, "", "", crashed=True))
    assert cancelled == []
    assert finished == []
    assert errors == ["rsync terminated unexpectedly before comparison completed."]


def test_plan_validation_service_streams_stdout() -> None:
    app()
    service = PlanValidationService()
    logs: list[str] = []
    service.on_log = logs.append
    service._stdout_chunk(">f.st......|qpy-rsync|8|qpy-rsync|2024/01/01|qpy-rsync|file.txt\n")
    service._stdout_chunk("             8 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)\n")
    assert logs == [">f.st......|qpy-rsync|8|qpy-rsync|2024/01/01|qpy-rsync|file.txt"]

from pathlib import Path

import pytest

from qpy_rsync.backend.process_runner import ProcessResult
from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ObjectKind
from qpy_rsync.core.enums import EndpointKind, SyncMode
from qpy_rsync.core.execution_plan import build_execution_plan
from qpy_rsync.core.models import BackupOptions, Endpoint, SyncProfile, TransferOptions
from qpy_rsync.services.sync_service import (
    SyncService,
    enforce_execution_boundary,
    explain_rsync_exit,
)


class FakeRunner:
    def __init__(self) -> None:
        self.on_started = lambda: None
        self.on_stdout = lambda _text: None
        self.on_stderr = lambda _text: None
        self.on_finished = lambda _result: None
        self.on_error = lambda _message: None
        self.spec = None
        self.cancelled = False

    def start(self, spec) -> None:
        self.spec = spec
        self.on_started()

    def cancel(self) -> None:
        self.cancelled = True


def profile(mode=SyncMode.UPDATE) -> SyncProfile:
    return SyncProfile(
        "smoke",
        Endpoint(EndpointKind.LOCAL, "/tmp/qpy-rsync-smoke/source/"),
        Endpoint(EndpointKind.LOCAL, "/tmp/qpy-rsync-smoke/destination/"),
        transfer=TransferOptions(sync_mode=mode),
        backup=BackupOptions(directory="/tmp/qpy-rsync-smoke/backup/"),
    )


def plan(item: SyncProfile):
    return build_execution_plan(
        item,
        [Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")],
        ChangeDecisions(),
    )


def test_execution_boundary_allows_ssh_endpoints() -> None:
    item = profile()
    item.source = Endpoint(EndpointKind.SSH, "host:/tmp/qpy-rsync-smoke/source/")
    enforce_execution_boundary(item)


def test_service_builds_real_sync_and_removes_private_filter() -> None:
    item = profile()
    runner = FakeRunner()
    service = SyncService(runner=runner)
    spec = service.synchronize(item, plan(item))
    assert "--dry-run" not in spec.arguments
    merge = next(arg for arg in spec.arguments if arg.startswith("--filter=merge "))
    filter_path = Path(merge.removeprefix("--filter=merge "))
    assert filter_path.exists()
    assert filter_path.stat().st_mode & 0o777 == 0o600
    runner.on_finished(ProcessResult(0, "ok", ""))
    assert not filter_path.exists()


def test_failure_reports_exit_and_cleans_filter() -> None:
    item = profile()
    runner = FakeRunner()
    service = SyncService(runner=runner)
    errors = []
    service.on_error = lambda message, cancelled=False: errors.append((message, cancelled))
    spec = service.synchronize(item, plan(item))
    merge = next(arg for arg in spec.arguments if arg.startswith("--filter=merge "))
    filter_path = Path(merge.removeprefix("--filter=merge "))
    runner.on_finished(ProcessResult(23, "", "partial"))
    assert "partial transfer" in errors[0][0]
    assert not errors[0][1]
    assert not filter_path.exists()


def test_cancel_delegates_and_reports_cancelled() -> None:
    item = profile()
    runner = FakeRunner()
    service = SyncService(runner=runner)
    errors = []
    service.on_error = lambda message, cancelled=False: errors.append((message, cancelled))
    service.synchronize(item, plan(item))
    service.cancel()
    assert runner.cancelled
    runner.on_finished(ProcessResult(20, "", "", crashed=True))
    assert errors[0][1]


def test_known_exit_explanation() -> None:
    assert "partial transfer" in explain_rsync_exit(23)


def test_service_reuses_the_confirmation_filter(tmp_path) -> None:
    item = profile()
    runner = FakeRunner()
    service = SyncService(runner=runner)
    filter_path = tmp_path / "plan.rules"
    filter_path.write_text("+ /new.txt\n", encoding="utf-8")
    spec = service.synchronize(item, plan(item), filter_path=filter_path)
    merge = next(arg for arg in spec.arguments if arg.startswith("--filter=merge "))
    assert Path(merge.removeprefix("--filter=merge ")) == filter_path
    runner.on_finished(ProcessResult(0, "ok", ""))
    # The owner of a supplied filter is responsible for removing it.
    assert filter_path.exists()

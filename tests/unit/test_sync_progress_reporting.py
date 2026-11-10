from qpy_rsync.services.sync_service import SyncService


class FakeRunner:
    def __init__(self) -> None:
        self.on_started = lambda: None
        self.on_stdout = lambda text: None
        self.on_stderr = lambda text: None
        self.on_finished = lambda result: None
        self.on_error = lambda message: None

    def start(self, spec) -> None:
        self.on_stdout("(xfr#4, to-chk=3/8)\n")


def test_sync_progress_reporting() -> None:
    service = SyncService(runner=FakeRunner())
    seen = []
    service.on_progress = seen.append
    from qpy_rsync.core.enums import EndpointKind
    from qpy_rsync.core.models import Endpoint, SyncProfile

    profile = SyncProfile(
        "p",
        Endpoint(EndpointKind.LOCAL, "/tmp/qpy-rsync-smoke/src"),
        Endpoint(EndpointKind.LOCAL, "/tmp/qpy-rsync-smoke/dst"),
    )
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
    from qpy_rsync.core.execution_plan import build_execution_plan
    from qpy_rsync.core.changes import ChangeDecisions

    changes = [Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    decisions = ChangeDecisions()
    decisions.reconcile(changes)
    plan = build_execution_plan(profile, changes, decisions)
    service.synchronize(profile, plan)
    assert len(seen) == 1
    assert seen[0].files_completed == 4
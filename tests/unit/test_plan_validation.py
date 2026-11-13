from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ChangeDecisions, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.execution_plan import build_execution_plan
from qpy_rsync.core.models import Endpoint, SyncProfile
from qpy_rsync.services.plan_validation_service import compare_plan_to_changes


def make_plan():
    profile = SyncProfile("plan", Endpoint(EndpointKind.LOCAL, "/src/"), Endpoint(EndpointKind.LOCAL, "/dst/"))
    changes = [
        Change("a", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
        Change("b", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
    ]
    decisions = ChangeDecisions(); decisions.reconcile(changes)
    decisions.set("b", ChangeDecision.EXCLUDE)
    return build_execution_plan(profile, changes, decisions)


def test_matching_validation_result_is_valid() -> None:
    mismatch = compare_plan_to_changes(
        make_plan(), [Change("a", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    )
    assert mismatch.valid


def test_validation_reports_missing_and_unexpected() -> None:
    mismatch = compare_plan_to_changes(
        make_plan(), [Change("other", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    )
    assert not mismatch.valid
    assert mismatch.missing[0][0] == "a"
    assert mismatch.unexpected[0][0] == "other"

def test_selected_destination_only_delete_matches_delete_result() -> None:
    profile = SyncProfile("plan", Endpoint(EndpointKind.LOCAL, "/src/"), Endpoint(EndpointKind.LOCAL, "/dst/"))
    change = Change("extra.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    decisions = ChangeDecisions(); decisions.set("extra.txt", ChangeDecision.INCLUDE)
    plan = build_execution_plan(profile, [change], decisions)
    mismatch = compare_plan_to_changes(
        plan,
        [Change("extra.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting")],
    )
    assert mismatch.valid


def test_cancellation_is_reported_once_when_error_and_finish_fire() -> None:
    from PySide6.QtWidgets import QApplication

    from qpy_rsync.backend.process_runner import ProcessResult
    from qpy_rsync.services.plan_validation_service import PlanValidationService

    application = QApplication.instance() or QApplication([])
    service = PlanValidationService()
    cancelled: list[str] = []
    errors: list[str] = []
    service.on_cancelled = lambda: cancelled.append("cancelled")
    service.on_error = lambda message: errors.append(message)
    service._cancelled = True

    service._error("process killed")
    service._finish(ProcessResult(exit_code=1, stdout="", stderr="", crashed=True))

    assert cancelled == ["cancelled"]
    assert errors == []
    application.processEvents()


def _two_files():
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    return [
        Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        Change("b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
    ]


def test_a_stashed_item_does_not_invalidate_the_plan() -> None:
    from qpy_rsync.core.changes import StashedItems
    from qpy_rsync.services.plan_validation_service import compare_plan_to_changes

    stash = StashedItems()
    stash.add("a.txt")
    profile = SyncProfile(
        "plan",
        Endpoint(EndpointKind.LOCAL, "/src/"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
    )
    plan = build_execution_plan(profile, _two_files(), ChangeDecisions(), stash)
    assert compare_plan_to_changes(plan, _two_files(), stash).valid

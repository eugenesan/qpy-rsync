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

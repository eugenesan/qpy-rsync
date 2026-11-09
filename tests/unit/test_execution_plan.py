from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ChangeDecisions, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.execution_plan import build_execution_plan, profile_fingerprint
from qpy_rsync.core.models import BackupOptions, Endpoint, SyncProfile


def profile() -> SyncProfile:
    return SyncProfile("plan", Endpoint(EndpointKind.LOCAL, "/src/"), Endpoint(EndpointKind.LOCAL, "/dst/"))


def test_execution_plan_is_immutable_and_summarized() -> None:
    item = profile()
    item.backup = BackupOptions(directory="/recovery")
    changes = [
        Change("new", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
        Change("old", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        Change("skip", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
    ]
    decisions = ChangeDecisions()
    decisions.reconcile(changes)
    decisions.set("skip", ChangeDecision.EXCLUDE)
    plan = build_execution_plan(item, changes, decisions)
    assert plan.summary.included == 2
    assert plan.summary.excluded == 1
    assert plan.summary.destructive == 1
    assert plan.summary.creates == 1
    assert plan.summary.deletions == 1
    assert plan.summary.backup_enabled
    assert plan.profile_fingerprint == profile_fingerprint(item)


def test_destination_only_inventory_is_not_executable() -> None:
    change = Change("kept", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    plan = build_execution_plan(profile(), [change], ChangeDecisions())
    assert plan.summary.included == 0
    assert plan.summary.excluded == 1

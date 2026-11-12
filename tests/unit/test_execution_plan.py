from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ChangeDecisions, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.execution_plan import build_execution_plan, check_plan_freshness, profile_fingerprint
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
    assert plan.summary.excluded == 0
    assert plan.summary.retained_destination_only == 1
def test_plan_freshness_detects_profile_and_comparison_changes() -> None:
    item = profile()
    changes = [Change("a", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")]
    decisions = ChangeDecisions()
    plan = build_execution_plan(item, changes, decisions)
    assert check_plan_freshness(plan, item, changes).fresh
    item.backup.directory = "/recovery"
    stale_profile = check_plan_freshness(plan, item, changes)
    assert not stale_profile.fresh
    assert "profile options changed" in stale_profile.reasons
    changed = [Change("a", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    stale_actions = check_plan_freshness(plan, profile(), changed)
    assert not stale_actions.fresh
    assert "comparison actions changed" in stale_actions.reasons


def test_equivalent_ad_hoc_profiles_have_same_fingerprint() -> None:
    first = profile()
    second = profile()
    assert first.profile_id != second.profile_id
    assert profile_fingerprint(first) == profile_fingerprint(second)


def test_semantic_profile_change_changes_fingerprint() -> None:
    first = profile()
    second = profile()
    second.transfer.delete = True
    assert profile_fingerprint(first) != profile_fingerprint(second)

def test_plan_summary_reports_modified_override() -> None:
    change = Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")
    decisions = ChangeDecisions()
    decisions.reconcile([change])
    decisions.set(change.path, ChangeDecision.EXCLUDE)
    plan = build_execution_plan(profile(), [change], decisions)
    assert plan.summary.modified == 1


def test_selected_destination_only_becomes_destructive_delete() -> None:
    change = Change("extra.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    decisions = ChangeDecisions()
    decisions.set(change.path, ChangeDecision.INCLUDE)
    plan = build_execution_plan(profile(), [change], decisions)
    assert plan.summary.included == 1
    assert plan.summary.retained_destination_only == 0
    assert plan.summary.deletions == 1
    assert plan.summary.destructive == 1
    assert plan.items[0].action is ChangeAction.DELETE
    assert plan.items[0].comparison_action is ChangeAction.DESTINATION_ONLY


def test_plan_summary_reports_the_included_size() -> None:
    profile = SyncProfile(
        "plan",
        Endpoint(EndpointKind.LOCAL, "/src/"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
    )
    changes = [
        Change("a.bin", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=1000),
        Change("b.bin", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......", size=2000),
        Change("c.bin", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
    ]
    decisions = ChangeDecisions()
    decisions.reconcile(changes)
    decisions.set("b.bin", ChangeDecision.EXCLUDE)
    plan = build_execution_plan(profile, changes, decisions)
    assert plan.summary.included == 2
    # Only the data that is transferred counts; the deletion frees space.
    assert plan.summary.total_size == 1000

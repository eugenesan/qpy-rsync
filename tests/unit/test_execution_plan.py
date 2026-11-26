from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ChangeDecisions, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from dataclasses import replace

from qpy_rsync.core.execution_plan import (
    PlanItem,
    build_execution_plan,
    check_plan_freshness,
    patch_plan_items_fingerprint,
    plan_items_fingerprint,
    profile_fingerprint,
)
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
    assert "comparison decisions changed" in stale_actions.reasons


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



def test_deleted_size_uses_destination_metadata_without_double_counting() -> None:
    changes = [
        Change("old/", ChangeAction.DELETE, ObjectKind.DIRECTORY, "*deleting"),
        Change("old/a", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        Change("old/b", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        Change("lone.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
    ]
    metadata = {
        "old": (4096, "t"),
        "old/a": (1000, "t"),
        "old/b": (2000, "t"),
        "lone.txt": (500, "t"),
    }
    plan = build_execution_plan(profile(), changes, ChangeDecisions(), metadata)
    assert plan.summary.deleted_size == 3500


def test_deleted_size_includes_reported_file_sizes_without_metadata() -> None:
    changes = [
        Change("old/", ChangeAction.DELETE, ObjectKind.DIRECTORY, "*deleting"),
        Change("old/a", ChangeAction.DELETE, ObjectKind.FILE, "*deleting", size=1000),
        Change("lone.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting",
               destination_size=500),
    ]
    plan = build_execution_plan(profile(), changes, ChangeDecisions())
    # No destination listing: the folder's deleted child and the explicit
    # destination size still count, while the folder itself is not added twice.
    assert plan.summary.deleted_size == 1500


def test_incremental_fingerprint_matches_full_rebuild() -> None:
    items = tuple(
        PlanItem(
            path=f"dir/file{i}.txt",
            action=ChangeAction.UPDATE_CONTENT,
            comparison_action=ChangeAction.UPDATE_CONTENT,
            kind=ObjectKind.FILE,
            included=True,
            destructive=False,
            size=i,
        )
        for i in range(4)
    )
    fingerprint = plan_items_fingerprint(items)
    updated = replace(items[-1], included=False)
    patched_items = items[:-1] + (updated,)
    assert patch_plan_items_fingerprint(
        fingerprint, [(items[-1], updated)]
    ) == plan_items_fingerprint(patched_items)
    assert fingerprint != plan_items_fingerprint(patched_items)
    # Filter-rule order matters, so reordering the same items must also
    # invalidate a cached filter file.
    assert plan_items_fingerprint(patched_items) != plan_items_fingerprint(
        patched_items[::-1]
    )

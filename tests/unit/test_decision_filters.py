from pathlib import Path

from qpy_rsync.backend.decision_filters import decision_filter_lines, temporary_decision_filter
from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ChangeDecisions, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.execution_plan import build_execution_plan
from qpy_rsync.core.models import Endpoint, SyncProfile


def plan():
    profile = SyncProfile("plan", Endpoint(EndpointKind.LOCAL, "/src/"), Endpoint(EndpointKind.LOCAL, "/dst/"))
    changes = [
        Change("docs", ChangeAction.UPDATE_METADATA, ObjectKind.DIRECTORY, ".d...p....."),
        Change("old.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
    ]
    decisions = ChangeDecisions(); decisions.reconcile(changes)
    decisions.set("docs", ChangeDecision.EXCLUDE); decisions.set("old.txt", ChangeDecision.EXCLUDE)
    return build_execution_plan(profile, changes, decisions)


def test_excluded_directory_and_delete_filters() -> None:
    assert decision_filter_lines(plan()) == [
        "- /docs/***", "P /old.txt", "- /old.txt"
    ]


def test_temporary_filter_is_private_and_removed() -> None:
    with temporary_decision_filter(plan()) as path:
        assert path.exists()
        assert path.stat().st_mode & 0o777 == 0o600
    assert not path.exists()

def test_included_child_overrides_excluded_directory() -> None:
    profile = SyncProfile("plan", Endpoint(EndpointKind.LOCAL, "/src/"), Endpoint(EndpointKind.LOCAL, "/dst/"))
    changes = [
        Change("docs", ChangeAction.UPDATE_METADATA, ObjectKind.DIRECTORY, ".d...p....."),
        Change("docs/keep.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
    ]
    decisions = ChangeDecisions(); decisions.reconcile(changes)
    decisions.set("docs", ChangeDecision.EXCLUDE)
    decisions.set("docs/keep.txt", ChangeDecision.INCLUDE)
    lines = decision_filter_lines(build_execution_plan(profile, changes, decisions))
    assert lines[:2] == ["+ /docs/", "+ /docs/keep.txt"]
    assert "- /docs/***" in lines

def test_retained_destination_only_is_protected_but_selected_delete_is_open() -> None:
    profile = SyncProfile("plan", Endpoint(EndpointKind.LOCAL, "/src/"), Endpoint(EndpointKind.LOCAL, "/dst/"))
    change = Change("extra.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    retained = build_execution_plan(profile, [change], ChangeDecisions())
    assert decision_filter_lines(retained) == ["P /extra.txt", "- /extra.txt"]
    decisions = ChangeDecisions(); decisions.set("extra.txt", ChangeDecision.INCLUDE)
    selected = build_execution_plan(profile, [change], decisions)
    assert decision_filter_lines(selected) == []

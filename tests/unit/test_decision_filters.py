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

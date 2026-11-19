from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind


def test_delete_property() -> None:
    change = Change("old", ChangeAction.DELETE, ObjectKind.FILE, "*deleting")
    assert change.is_deletion


def test_destination_only_is_not_a_delete_action() -> None:
    change = Change("kept", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    assert change.is_destination_only
    assert not change.is_deletion

from qpy_rsync.core.changes import ChangeDecision, ChangeDecisions


def test_directory_exclusion_is_inherited_and_child_can_override() -> None:
    decisions = ChangeDecisions()
    child = Change("docs/guide.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")
    decisions.set("docs", ChangeDecision.EXCLUDE)
    assert decisions.effective(child) is ChangeDecision.EXCLUDE
    decisions.set(child.path, ChangeDecision.INCLUDE)
    assert decisions.effective(child) is ChangeDecision.INCLUDE
    decisions.set(child.path, ChangeDecision.INHERIT)
    assert decisions.effective(child) is ChangeDecision.EXCLUDE


def test_message_and_no_change_records_are_not_selectable() -> None:
    decisions = ChangeDecisions()
    for action in (ChangeAction.MESSAGE, ChangeAction.NO_CHANGE):
        change = Change("note", action, ObjectKind.FILE, "")
        assert not decisions.selectable(change)
        assert decisions.effective(change) is ChangeDecision.EXCLUDE


def test_reconcile_discards_changed_identity() -> None:
    decisions = ChangeDecisions()
    original = Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")
    assert decisions.reconcile([original]) == 0
    decisions.set(original.path, ChangeDecision.EXCLUDE)
    assert decisions.reconcile([original]) == 0
    changed = Change("file.txt", ChangeAction.REPLACE, ObjectKind.FILE, "cL+++++++++")
    assert decisions.reconcile([changed]) == 1
    assert decisions.explicit("file.txt") is ChangeDecision.INHERIT


def test_summary_counts_included_excluded_and_destructive() -> None:
    decisions = ChangeDecisions()
    changes = [
        Change("new", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
        Change("old", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        Change("skip", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
    ]
    decisions.reconcile(changes)
    decisions.set("skip", ChangeDecision.EXCLUDE)
    assert decisions.summary(changes).included == 2
    assert decisions.summary(changes).excluded == 1
    assert decisions.summary(changes).destructive == 1

def test_destination_only_defaults_excluded_but_can_be_selected() -> None:
    decisions = ChangeDecisions()
    change = Change("extra.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    assert decisions.selectable(change)
    assert decisions.effective(change) is ChangeDecision.EXCLUDE
    decisions.set(change.path, ChangeDecision.INCLUDE)
    assert decisions.effective(change) is ChangeDecision.INCLUDE
    decisions.reset(change.path)
    assert decisions.effective(change) is ChangeDecision.EXCLUDE


def test_reconcile_preserves_decisions_by_path_when_requested() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ChangeDecision, ObjectKind

    old = [Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")]
    new = [Change("a.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting")]
    decisions = ChangeDecisions()
    decisions.set("a.txt", ChangeDecision.EXCLUDE)
    decisions.reconcile(old)

    assert decisions.reconcile(new) == 1
    assert decisions.explicit("a.txt") is ChangeDecision.INHERIT

    preserved = ChangeDecisions()
    preserved.set("a.txt", ChangeDecision.EXCLUDE)
    preserved.reconcile(old)
    assert preserved.reconcile(new, preserve=True) == 0
    assert preserved.explicit("a.txt") is ChangeDecision.EXCLUDE


def test_preservation_is_type_aware_and_flags_changed_decisions() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ChangeDecision, ObjectKind

    old = [Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f")]
    destination_only = [
        Change("a.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    ]

    excluded = ChangeDecisions()
    excluded.set("a.txt", ChangeDecision.EXCLUDE)
    excluded.reconcile(old)
    assert excluded.reconcile(destination_only, preserve=True) == 0
    assert excluded.explicit("a.txt") is ChangeDecision.EXCLUDE
    assert excluded.conflicts() == {}

    included = ChangeDecisions()
    included.set("a.txt", ChangeDecision.INCLUDE)
    included.reconcile(old)
    assert included.reconcile(destination_only, preserve=True) == 1
    assert included.explicit("a.txt") is ChangeDecision.INHERIT
    assert "destination-only" in included.conflicts()["a.txt"]
    assert included.accept_defaults_for_conflicts() == 1
    assert included.conflicts() == {}

    vanished = ChangeDecisions()
    vanished.set("a.txt", ChangeDecision.EXCLUDE)
    vanished.reconcile(old)
    assert vanished.reconcile([], preserve=True) == 1
    assert vanished.conflicts() == {}


def test_fresh_comparison_drops_stale_decisions_without_conflicts() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ChangeDecision, ObjectKind

    old = [Change("a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f")]
    new = [Change("a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f")]
    decisions = ChangeDecisions()
    decisions.set("a.txt", ChangeDecision.INCLUDE)
    decisions.reconcile(old)

    assert decisions.reconcile(new, preserve=False) == 1
    assert decisions.explicit("a.txt") is ChangeDecision.INHERIT
    assert decisions.conflicts() == {}


def test_inherited_destination_only_detection_is_opt_in() -> None:
    from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ChangeDecision, ObjectKind

    old = [
        Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
        Change("docs/b.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
    ]
    new = [
        Change("docs/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f"),
        Change("docs/b.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting"),
    ]

    def prepared():
        decisions = ChangeDecisions()
        decisions.set("docs", ChangeDecision.INCLUDE)
        decisions.reconcile(old)
        return decisions

    quiet = prepared()
    assert quiet.reconcile(new, preserve=True) == 0
    assert quiet.conflicts() == {}
    assert quiet.explicit("docs") is ChangeDecision.INCLUDE

    detect = prepared()
    assert detect.reconcile(new, preserve=True, detect_inherited=True) == 1
    assert "destination-only" in detect.conflicts()["docs"]
    assert detect.explicit("docs") is ChangeDecision.INHERIT

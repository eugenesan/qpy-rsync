from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind


def test_delete_property() -> None:
    change = Change("old", ChangeAction.DELETE, ObjectKind.FILE, "*deleting")
    assert change.is_deletion


def test_destination_only_is_not_a_delete_action() -> None:
    change = Change("kept", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")
    assert change.is_destination_only
    assert not change.is_deletion

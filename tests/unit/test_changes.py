from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind


def test_delete_property() -> None:
    change = Change("old", ChangeAction.DELETE, ObjectKind.FILE, "*deleting")
    assert change.is_deletion

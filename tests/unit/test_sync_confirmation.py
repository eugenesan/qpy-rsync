import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecisions, ObjectKind
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.execution_plan import build_execution_plan
from qpy_rsync.core.models import BackupOptions, Endpoint, SyncProfile
from qpy_rsync.gui.sync_confirmation import SyncConfirmationDialog, confirmation_summary


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def profile() -> SyncProfile:
    return SyncProfile(
        "confirm",
        Endpoint(EndpointKind.LOCAL, "/src/"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
        backup=BackupOptions(directory="/recovery"),
    )


def test_confirmation_summary_contains_verified_counts() -> None:
    item = profile()
    plan = build_execution_plan(
        item,
        [
            Change("new", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
            Change("old", ChangeAction.DELETE, ObjectKind.FILE, "*deleting"),
        ],
        ChangeDecisions(),
    )
    summary = confirmation_summary(item, plan)
    assert summary.source == "/src/"
    assert summary.destination == "/dst/"
    assert summary.included == 2
    assert summary.destructive == 1
    assert summary.backup == "/recovery"


def test_confirmation_requires_explicit_acknowledgement() -> None:
    application = app()
    item = profile()
    plan = build_execution_plan(
        item,
        [Change("new", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")],
        ChangeDecisions(),
    )
    dialog = SyncConfirmationDialog(item, plan)
    assert not dialog.confirm_button.isEnabled()
    dialog.acknowledge.setChecked(True)
    assert dialog.confirm_button.isEnabled()
    assert dialog.confirm_button.text() == "Synchronize Now"
    dialog.close()
    application.processEvents()

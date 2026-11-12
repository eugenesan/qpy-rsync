import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPlainTextEdit

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


def test_confirmation_is_ready_without_an_extra_acknowledgement() -> None:
    application = app()
    item = profile()
    plan = build_execution_plan(
        item,
        [Change("new", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")],
        ChangeDecisions(),
    )
    dialog = SyncConfirmationDialog(item, plan)
    summary = confirmation_summary(item, plan)
    assert dialog.confirm_button.isEnabled()
    assert dialog.confirm_button.text() == "Synchronize Now"
    # The fingerprint moved into the header; the old text box is gone.
    assert dialog.heading.text() == (
        "Review verified synchronization "
        f"(fingerprint: {summary.fingerprint})"
    )
    assert dialog.command is not None
    assert dialog.details.font().bold()
    # The stats are a table with two label/value pairs per row.
    assert dialog.stats.item(0, 0).text() == "Included"
    assert dialog.stats.item(0, 1).text() == "1"
    assert dialog.stats.item(0, 2).text() == "Update"
    assert dialog.stats.item(0, 3).text() == "0"
    assert dialog.stats.item(1, 0).text() == "Total size"
    assert dialog.stats.item(5, 2).text() == "Nested protection"
    command = dialog.command.toPlainText()
    assert dialog.command.isReadOnly()
    assert command.startswith("rsync ")
    assert "--itemize-changes" in command
    assert "--dry-run" not in command
    assert "/src/" in command and "/dst/" in command
    dialog.close()
    application.processEvents()


def test_confirmation_command_keeps_the_ssh_authority() -> None:
    application = app()
    item = SyncProfile(
        "ssh",
        Endpoint(EndpointKind.SSH, "/src/", host="example.org", user="alice"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
    )
    plan = build_execution_plan(
        item,
        [Change("new", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")],
        ChangeDecisions(),
    )
    dialog = SyncConfirmationDialog(item, plan)
    command = dialog.command.toPlainText()
    assert "alice@example.org:/src/" in command
    dialog.close()
    application.processEvents()

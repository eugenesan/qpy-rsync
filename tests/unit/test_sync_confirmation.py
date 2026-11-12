import os
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
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
    assert dialog.rules_label.text() == "Decision rules"
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
    assert dialog.rules.isReadOnly()
    assert (
        dialog.command.lineWrapMode()
        == dialog.command.LineWrapMode.WidgetWidth
    )
    assert (
        dialog.rules.lineWrapMode()
        == dialog.rules.LineWrapMode.WidgetWidth
    )
    assert (
        dialog.command.wordWrapMode()
        == dialog.command.wordWrapMode().WrapAtWordBoundaryOrAnywhere
    )
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


def test_confirmation_command_uses_the_real_filter_path() -> None:
    application = app()
    item = profile()
    plan = build_execution_plan(
        item,
        [Change("new", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")],
        ChangeDecisions(),
    )
    filter_path = Path("/tmp/qpy-rsync-plan-test.rules")
    dialog = SyncConfirmationDialog(item, plan, filter_path=filter_path)
    command = dialog.command.toPlainText()
    assert str(filter_path) in command
    assert "<temporary decision filter>" not in command
    assert dialog.rules_label.text() == f"Decision rules ({filter_path.name})"
    assert str(filter_path) in dialog.rules_label.toolTip()
    dialog.close()
    application.processEvents()


def test_command_and_rule_boxes_are_resizable_and_wrap() -> None:
    from PySide6.QtWidgets import QSizePolicy, QSplitter

    application = app()
    item = profile()
    plan = build_execution_plan(
        item,
        [Change("new", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")],
        ChangeDecisions(),
    )
    dialog = SyncConfirmationDialog(item, plan)
    assert isinstance(dialog.preview_splitter, QSplitter)
    assert dialog.preview_splitter.orientation() == Qt.Orientation.Vertical
    assert dialog.preview_splitter.count() == 2
    assert dialog.preview_splitter.widget(0).isAncestorOf(dialog.command)
    assert dialog.preview_splitter.widget(1).isAncestorOf(dialog.rules)
    for box in (dialog.command, dialog.rules):
        assert box.lineWrapMode() == box.LineWrapMode.WidgetWidth
        assert (
            box.sizePolicy().verticalPolicy()
            == QSizePolicy.Policy.Expanding
        )
    assert (
        dialog.stats.verticalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    dialog.close()
    application.processEvents()


def test_confirmation_shows_the_decision_rule_contents() -> None:
    application = app()
    item = profile()
    plan = build_execution_plan(
        item,
        [
            Change(
                "extra",
                ChangeAction.DESTINATION_ONLY,
                ObjectKind.FILE,
                "*deleting",
            )
        ],
        ChangeDecisions(),
    )
    dialog = SyncConfirmationDialog(item, plan)
    text = dialog.rules.toPlainText()
    assert "P /extra" in text
    assert "- /extra" in text
    dialog.close()
    application.processEvents()


def test_summary_table_ignores_wheel_scrolling() -> None:
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    application = app()
    item = profile()
    plan = build_execution_plan(
        item,
        [Change("new", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++")],
        ChangeDecisions(),
    )
    dialog = SyncConfirmationDialog(item, plan)
    bar = dialog.stats.verticalScrollBar()
    bar.setRange(0, 100)
    bar.setValue(0)
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(dialog.stats.viewport(), event)
    assert bar.value() == 0
    dialog.close()
    application.processEvents()

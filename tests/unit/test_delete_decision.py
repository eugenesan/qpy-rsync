"""Decision-only deletes: visible during Compare, deleted at sync time."""

from qpy_rsync.backend.decision_filters import decision_filter_lines
from qpy_rsync.core.changes import (
    Change,
    ChangeAction,
    ChangeDecision,
    ChangeDecisions,
    ObjectKind,
)
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.execution_plan import (
    build_execution_plan,
    check_plan_freshness,
    decision_signature,
)
from qpy_rsync.core.models import Endpoint, SyncProfile


def profile() -> SyncProfile:
    return SyncProfile(
        "plan", Endpoint(EndpointKind.LOCAL, "/src/"), Endpoint(EndpointKind.LOCAL, "/dst/")
    )


def unchanged(path: str, kind: ObjectKind = ObjectKind.FILE) -> Change:
    return Change(path, ChangeAction.NO_CHANGE, kind, "")


def test_delete_decision_on_unchanged_item_enters_plan() -> None:
    changes = [unchanged(".parentlock")]
    decisions = ChangeDecisions()
    decisions.reconcile(changes)
    decisions.set(".parentlock", ChangeDecision.DELETE)
    plan = build_execution_plan(profile(), changes, decisions)
    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.action is ChangeAction.DELETE
    assert item.comparison_action is ChangeAction.NO_CHANGE
    assert item.included and item.destructive and item.synthetic_delete
    assert plan.summary.deletions == 1
    assert plan.summary.destructive == 1
    assert decision_signature(decisions) != decision_signature(ChangeDecisions())


def test_synthetic_delete_uses_sender_side_filter_rule() -> None:
    changes = [unchanged(".parentlock"), unchanged("cache", ObjectKind.DIRECTORY)]
    decisions = ChangeDecisions()
    decisions.reconcile(changes)
    decisions.set(".parentlock", ChangeDecision.DELETE)
    decisions.set("cache", ChangeDecision.DELETE)
    plan = build_execution_plan(profile(), changes, decisions)
    assert decision_filter_lines(plan) == ["-s /.parentlock", "-s /cache/"]


def test_reconcile_keeps_delete_while_item_exists() -> None:
    changes = [unchanged("a.txt")]
    decisions = ChangeDecisions()
    decisions.reconcile(changes)
    decisions.set("a.txt", ChangeDecision.DELETE)
    assert decisions.reconcile(changes, preserve=True) == 0
    assert decisions.effective(changes[0]) is ChangeDecision.DELETE
    # A fresh comparison drops the delete request.
    assert decisions.reconcile(changes, preserve=False) == 1
    assert decisions.effective(changes[0]) is ChangeDecision.EXCLUDE


def test_plan_freshness_accepts_synthetic_delete() -> None:
    changes = [unchanged("a.txt")]
    decisions = ChangeDecisions()
    decisions.reconcile(changes)
    decisions.set("a.txt", ChangeDecision.DELETE)
    plan = build_execution_plan(profile(), changes, decisions)
    assert check_plan_freshness(
        plan, profile(), changes, decision_signature(decisions)
    ).fresh


def test_context_menu_offers_permanent_filter_and_decision_delete() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView

    application = QApplication.instance() or QApplication([])
    view = FlatComparisonView()
    changes = [unchanged(".parentlock")]
    view.set_changes(changes)
    index = view.model.index_for_path(".parentlock")
    row = view.model.row_data(index.row())
    _menu, actions = view._build_context_menu(
        view.action, ".parentlock", row.change, row
    )
    assert actions["delete_sync"] is not None
    assert [entry.data() for entry in actions["delete_filters"]] == [
        "-s *.parentlock", "-s .parentlock", "-s /.parentlock"
    ]
    view.close()
    application.processEvents()


def test_delete_request_sets_decision_and_delete_action() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView
    application = QApplication.instance() or QApplication([])
    view = FlatComparisonView()
    view.set_changes([unchanged(".parentlock")])
    view.delete_requested.connect(view.model.mark_delete)
    view.delete_requested.emit(".parentlock")
    change = view.model.changes[0]
    assert view.model.decisions.effective(change) is ChangeDecision.DELETE
    assert view.model.effective_action_of_change(change) is ChangeAction.DELETE
    index = view.model.index_for_path(".parentlock")
    tip = view.model.data(
        view.model.index(index.row(), view.model.ACTION), 3  # ToolTipRole
    )
    assert tip.endswith("\nDelete")
    view.close()
    application.processEvents()


def test_native_delete_decision_value_is_visible() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from qpy_rsync.gui.native_hybrid_view import NativeHybridView

    application = QApplication.instance() or QApplication([])
    view = NativeHybridView()
    view.set_changes([unchanged(".parentlock")])
    view.apply_python_decisions({".parentlock": 3})
    assert view.decision_for_path(".parentlock") == 3
    view.widget.close()
    application.processEvents()

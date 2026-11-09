from PySide6.QtCore import Qt

from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ObjectKind
from qpy_rsync.gui.change_tree_model import ChangeTreeModel


def test_action_column_checkbox_updates_explicit_decision() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    )
    index = model.index(0, model.ACTION)
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.data(index, Qt.ItemDataRole.UserRole + 1) is ChangeDecision.EXCLUDE
    assert model.decision_summary().excluded == 1


def test_synthetic_directory_controls_whole_subtree() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("docs/file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    )
    directory = model.index(0, model.ACTION)
    assert model.flags(directory) & Qt.ItemFlag.ItemIsUserCheckable
    assert model.setData(directory, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    child = model.index(0, model.ACTION, directory.siblingAtColumn(0))
    assert model.data(child, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    assert model.setData(directory, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.data(child, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked


def test_synthetic_directory_decision_survives_recompare() -> None:
    model = ChangeTreeModel()
    change = Change("docs/file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")
    model.set_changes([change])
    directory = model.index(0, model.ACTION)
    model.setData(directory, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    model.set_changes([change])
    assert model.discarded_decisions == 0


def test_recompare_reports_discarded_decision() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    )
    index = model.index(0, model.ACTION)
    model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    model.set_changes(
        [Change("file.txt", ChangeAction.REPLACE, ObjectKind.FILE, "cL+++++++++")]
    )
    assert model.discarded_decisions == 1

def test_stale_action_text_is_neutral_and_arrowless() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    )
    index = model.index(0, model.ACTION)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "→ update"
    model.stale = True
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "update"
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) is None

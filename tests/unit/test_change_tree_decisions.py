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

def test_reset_decision_subtree_and_all() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [
            Change("docs/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
            Change("docs/b.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
            Change("other.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
        ]
    )
    model.decisions.set("docs", ChangeDecision.EXCLUDE)
    model.decisions.set("docs/a.txt", ChangeDecision.INCLUDE)
    model.decisions.set("other.txt", ChangeDecision.EXCLUDE)
    model.reset_decision("docs/a.txt")
    assert model.decisions.explicit("docs/a.txt") is ChangeDecision.INHERIT
    model.reset_subtree_decisions("docs")
    assert model.decisions.explicit("docs") is ChangeDecision.INHERIT
    assert model.decisions.explicit("other.txt") is ChangeDecision.EXCLUDE
    model.reset_all_decisions()
    assert not model.decisions.has_explicit()

def test_destination_only_checkbox_toggles_keep_and_delete() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("extra.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")]
    )
    index = model.index(0, model.ACTION)
    assert model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "keep ←"
    assert model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "× delete"
    assert model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "keep ←"

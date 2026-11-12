from PySide6.QtCore import Qt

from qpy_rsync.core.changes import Change, ChangeAction, ChangeDecision, ObjectKind
from qpy_rsync.gui.change_tree_model import ACTION_HEADER_ACCENT, ChangeTreeModel


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

def test_action_column_is_icon_only_with_tooltip() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    )
    index = model.index(0, model.ACTION)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == ""
    assert not model.data(index, Qt.ItemDataRole.DecorationRole).isNull()
    model.stale = True
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == ""
    assert not model.data(index, Qt.ItemDataRole.DecorationRole).isNull()
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

def test_override_count_tracks_active_explicit_decisions() -> None:
    from PySide6.QtCore import Qt

    model = ChangeTreeModel()
    model.set_changes(
        [Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    )
    assert model.decision_summary().modified == 0
    assert model.headerData(model.ACTION, Qt.Horizontal, Qt.DisplayRole) == "Actions"
    index = model.index(0, model.ACTION)
    assert model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.decision_summary().modified == 1
    assert model.headerData(model.ACTION, Qt.Horizontal, Qt.DisplayRole) == "Actions*"
    assert (
        model.headerData(model.ACTION, Qt.Horizontal, Qt.ToolTipRole)
        == "Actions* (1 modified)"
    )
    model.reset_all_decisions()
    assert model.decision_summary().modified == 0
    assert model.headerData(model.ACTION, Qt.Horizontal, Qt.DisplayRole) == "Actions"


def test_destination_only_checkbox_toggles_keep_and_delete() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("extra.txt", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*deleting")]
    )
    index = model.index(0, model.ACTION)
    assert model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == ""
    assert not model.data(index, Qt.ItemDataRole.DecorationRole).isNull()
    assert model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.effective_action(index.internalPointer()) is ChangeAction.DELETE
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == ""
    assert model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.effective_action(index.internalPointer()) is ChangeAction.DESTINATION_ONLY
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == ""


def test_tooltips_show_full_object_path() -> None:
    from qpy_rsync.gui.change_tree_model import full_path

    model = ChangeTreeModel()
    model.source_root = "/home/user/Source"
    model.destination_root = "/mnt/backup/Destination"
    model.set_changes(
        [Change("docs/reports/file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    )
    assert full_path("/home/user/Source/", "/docs/") == "/home/user/Source/docs"
    directory = model.index(0, model.SOURCE_NAME)
    assert model.data(directory, Qt.ItemDataRole.ToolTipRole) == "/home/user/Source/docs"
    child = model.index(0, model.SOURCE_NAME, directory)
    assert model.data(child, Qt.ItemDataRole.ToolTipRole) == "/home/user/Source/docs/reports"
    leaf = model.index(0, model.SOURCE_NAME, child)
    assert (
        model.data(leaf, Qt.ItemDataRole.ToolTipRole)
        == "/home/user/Source/docs/reports/file.txt"
    )
    destination_leaf = leaf.siblingAtColumn(model.DESTINATION_NAME)
    assert (
        model.data(destination_leaf, Qt.ItemDataRole.ToolTipRole)
        == "/mnt/backup/Destination/docs/reports/file.txt"
    )
    action = leaf.siblingAtColumn(model.ACTION)
    tooltip = model.data(action, Qt.ItemDataRole.ToolTipRole)
    assert "/home/user/Source/docs/reports/file.txt" in tooltip
    assert "/mnt/backup/Destination/docs/reports/file.txt" in tooltip
    assert "Update" in tooltip


def test_action_header_keeps_the_count_in_the_tooltip() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("file.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......")]
    )
    assert model.headerData(model.ACTION, Qt.Horizontal, Qt.DisplayRole) == "Actions"
    index = model.index(0, model.ACTION)
    assert model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.headerData(model.ACTION, Qt.Horizontal, Qt.DisplayRole) == "Actions*"
    assert (
        model.headerData(model.ACTION, Qt.Horizontal, Qt.ToolTipRole)
        == "Actions* (1 modified)"
    )
    accent = model.headerData(model.ACTION, Qt.Horizontal, Qt.ForegroundRole)
    assert accent is not None
    assert accent.name().lower() == ACTION_HEADER_ACCENT.lower()


def test_folder_rows_report_the_size_of_their_contents() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [
            Change("dir/a.bin", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=1000),
            Change("dir/b.bin", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++", size=2000),
            Change("dir", ChangeAction.CREATE, ObjectKind.DIRECTORY, "cd+++++++++", size=4096),
        ]
    )
    folder = model.index(0, 0)
    assert folder.internalPointer().path == "dir"
    # The folder reports its contents, not the size of its directory record.
    assert model.data(model.index(0, model.SOURCE_SIZE)) == "2.9 KiB"
    assert model.index(0, model.SOURCE_SIZE).data() == "2.9 KiB"


def test_unchanged_tooltip_has_no_raw_itemized_separator() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [Change("same.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, "=")]
    )
    tooltip = model.data(
        model.index(0, model.ACTION), Qt.ItemDataRole.ToolTipRole
    )
    assert "Unchanged" in tooltip
    assert ":=" not in tooltip
    assert not tooltip.rstrip().endswith("=")


def test_unchanged_rows_are_italic_and_changed_rows_are_not_bold() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [
            Change("dir/changed.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f.st......"),
            Change("dir/same.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, "="),
            Change("new.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
        ]
    )
    directory = model.index(0, 0)
    assert directory.internalPointer().name == "dir"
    # A folder that holds changes is no longer bold.
    assert model.data(directory, Qt.ItemDataRole.FontRole) is None
    changed = model.index(1, 0)
    assert changed.internalPointer().name == "new.txt"
    assert model.data(changed, Qt.ItemDataRole.FontRole) is None
    same = model.index(1, 0, directory)
    font = model.data(same, Qt.ItemDataRole.FontRole)
    assert font is not None
    assert font.italic()
    assert not font.bold()


def test_folder_rows_report_all_items_in_their_hierarchy() -> None:
    model = ChangeTreeModel()
    model.set_changes(
        [
            Change("dir/a.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
            Change("dir/sub/b.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
            Change("dir/sub/c.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f+++++++++"),
        ]
    )
    directory = model.index(0, model.SOURCE_NAME)
    sub = model.index(0, model.SOURCE_NAME, directory)
    assert model.data(directory) == "dir"
    assert model.data(directory.siblingAtColumn(model.SOURCE_ITEMS)) == "3"
    assert model.data(sub) == "sub"
    assert model.data(sub.siblingAtColumn(model.SOURCE_ITEMS)) == "2"
    leaf = model.index(0, model.SOURCE_NAME, sub)
    assert model.data(leaf.siblingAtColumn(model.SOURCE_ITEMS)) == ""

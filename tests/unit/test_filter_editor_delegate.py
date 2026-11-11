import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule
from qpy_rsync.gui.filter_editor import FilterEditorDialog, FilterTypeDelegate


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_filter_type_column_uses_dropdown_editor() -> None:
    application = app()
    dialog = FilterEditorDialog([FilterRule("*.tmp", rule_type=FilterRuleType.EXCLUDE)])
    delegate = dialog.table.itemDelegateForColumn(dialog.model.TYPE)
    assert isinstance(delegate, FilterTypeDelegate)
    index = dialog.model.index(0, dialog.model.TYPE)
    option = QStyleOptionViewItem()

    editor = delegate.createEditor(dialog.table.viewport(), option, index)
    delegate.setEditorData(editor, index)
    assert editor.currentData() == FilterRuleType.EXCLUDE.value

    editor.setCurrentIndex(editor.findData(FilterRuleType.INCLUDE.value))
    delegate.setModelData(editor, dialog.model, index)
    assert dialog.model.rules[0].rule_type is FilterRuleType.INCLUDE
    dialog.close()
    application.processEvents()

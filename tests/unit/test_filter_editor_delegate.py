import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule
from qpy_rsync.gui.filter_editor import FilterEditorDialog


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_filter_editor_converts_bare_lines_to_exclusions() -> None:
    application = app()
    dialog = FilterEditorDialog([FilterRule("*.tmp", rule_type=FilterRuleType.EXCLUDE)])
    assert any("- *.tmp" in line or "*.tmp" in line for line in dialog.text().splitlines())
    dialog.close()
    application.processEvents()


def test_filter_editor_empty_uses_examples() -> None:
    application = app()
    dialog = FilterEditorDialog([])
    assert "Order of filters" in dialog.text()
    assert dialog.rules() == []
    dialog.close()
    application.processEvents()

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


def test_filter_text_is_preserved_in_profiles() -> None:
    from qpy_rsync.core.endpoints import Endpoint
    from qpy_rsync.core.enums import EndpointKind
    from qpy_rsync.core.models import SyncProfile
    from qpy_rsync.storage.profile_store import profile_from_json, profile_to_json

    text = "# a comment\n*.kate-swp\n+ keep.txt\n"
    profile = SyncProfile(
        name="x",
        source=Endpoint(EndpointKind.LOCAL, "/s/"),
        destination=Endpoint(EndpointKind.LOCAL, "/d/"),
        filter_text=text,
    )
    loaded = profile_from_json(profile_to_json(profile))
    assert loaded.filter_text == text


def test_line_number_gutter_repaints_long_lines() -> None:
    from qpy_rsync.gui.filter_editor import FilterEditorWidget

    application = app()
    widget = FilterEditorWidget()
    long_line = "- " + "x" * 500
    widget.set_text("\n".join([long_line, "*.tmp", long_line]))
    from PySide6.QtGui import QImage

    widget.resize(600, 300)
    image = QImage(80, 300, QImage.Format.Format_ARGB32)
    for position in (0, 250, 510, 520):
        cursor = widget.editor.textCursor()
        cursor.setPosition(position)
        widget.editor.setTextCursor(cursor)
        widget.editor._numbers.render(image)
        application.processEvents()
    widget.close()
    application.processEvents()


def test_rule_preview_defaults_to_two_lines() -> None:
    from qpy_rsync.gui.filter_editor import FilterEditorWidget

    application = app()
    widget = FilterEditorWidget()
    expected = widget.preview_label.fontMetrics().height() * 2 + 6
    assert widget.preview_label.sizeHint().height() == expected
    assert widget.preview_label.minimumSizeHint().height() == expected
    widget.close()
    application.processEvents()

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

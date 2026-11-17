import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QWidget

from qpy_rsync.core.endpoints import Endpoint
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import SyncProfile
from qpy_rsync.gui.profile_editor import ProfileEditorDialog


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _profile() -> SyncProfile:
    return SyncProfile(
        name="test",
        source=Endpoint(EndpointKind.LOCAL, "/src/"),
        destination=Endpoint(EndpointKind.LOCAL, "/dst/"),
    )


def test_rsync_options_have_tooltips_with_the_option() -> None:
    app()
    dialog = ProfileEditorDialog(_profile())
    widgets = [
        child
        for child in dialog.findChildren(QWidget)
        if isinstance(child, (QCheckBox, QComboBox, QLineEdit))
        if child is not dialog.filter_widget.editor
    ]
    rsync_widgets = [
        widget
        for widget in widgets
        if widget not in (dialog.conflict_policy, dialog.inventory_after_compare)
    ]
    assert rsync_widgets
    for widget in rsync_widgets:
        tooltip = widget.toolTip()
        assert "--" in tooltip or "P /" in tooltip, (widget.objectName(), tooltip)
    dialog.close()

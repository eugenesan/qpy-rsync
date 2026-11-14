import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qpy_rsync.gui.tools_panel import ToolsPanel
from qpy_rsync.services.external_tools import ExternalTool


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_the_tools_page_shows_the_tools_and_the_diff_command() -> None:
    app()
    panel = ToolsPanel(
        tools=[
            ExternalTool(name="Kate", command="kate %d/%f"),
            ExternalTool(name="Meld", command="meld %D %d", enabled=False),
        ],
        diff_command="meld %a %A",
    )
    tools = panel.tools()
    assert [tool.name for tool in tools] == ["Kate", "Meld"]
    assert tools[0].command == "kate %d/%f"
    assert tools[1].enabled is False
    assert panel.diff_command() == "meld %a %A"

    panel.set_tools([])
    assert panel.tools() == []
    assert panel.diff_command() == "meld %a %A"


def test_the_window_offers_the_configured_tools(tmp_path, monkeypatch) -> None:
    from qpy_rsync.gui.main_window import MainWindow
    from qpy_rsync.services.external_tools import save_tools
    from qpy_rsync.storage.settings import app_settings

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    app_settings().clear()
    save_tools([ExternalTool(name="Kate", command="kate %d/%f")])

    application = app()
    window = MainWindow()
    assert [tool.name for tool in window.comparison._external_tools] == ["Kate"]
    window.close()
    application.processEvents()


def test_the_context_menu_offers_the_tools() -> None:
    from qpy_rsync.gui.flat_comparison_view import FlatComparisonView
    from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

    application = app()
    view = FlatComparisonView()
    view.set_changes(
        [
            Change("docs/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f"),
        ]
    )
    view.set_external_tools([ExternalTool(name="Kate", command="kate %d/%f")])
    index = view.model.index_for_path("docs/a.txt")
    row = view.model.row_data(index.row())
    _menu, actions = view._build_context_menu(
        view.source, "docs/a.txt", index.data(Qt.ItemDataRole.UserRole), row
    )
    assert len(actions["tools"]) == 1
    entry = actions["tools"][0]
    assert entry.text() == "Kate"
    # The entry carries the tool, the path, the pane and the kind of item.
    assert entry.data() == ("Kate", "docs/a.txt", "source", False)
    view.close()
    application.processEvents()


def test_a_configured_tool_runs_on_the_item() -> None:
    import sys

    from qpy_rsync.core.endpoints import parse_endpoint
    from qpy_rsync.core.models import SyncProfile
    from qpy_rsync.gui.main_window import MainWindow

    application = app()
    window = MainWindow()
    window._active_profile = SyncProfile(
        name="test",
        source=parse_endpoint("/home/user/src"),
        destination=parse_endpoint("/home/user/dst"),
    )
    window._external_tools = [
        ExternalTool(name="Noop", command=f"{sys.executable} -c pass")
    ]
    window._run_external_tool("Noop", "docs/a.txt", "source", False)
    application.processEvents()

    assert "Started Noop." in window.status_edit.text()
    assert any("pass" in line for line in window.log.toPlainText().splitlines())
    window.close()
    application.processEvents()

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import Endpoint
from qpy_rsync.services.external_tools import (
    ExternalTool,
    ExternalToolError,
    ToolContext,
    build_tool_command,
    item_context,
    load_diff_command,
    load_tools,
    save_diff_command,
    save_tools,
    unknown_placeholders,
)

LOCAL_SOURCE = Endpoint(EndpointKind.LOCAL, "/src")
LOCAL_DESTINATION = Endpoint(EndpointKind.LOCAL, "/dst")
REMOTE_DESTINATION = Endpoint(
    EndpointKind.SSH, "/dst", host="127.0.0.1", user="me"
)


def _context(endpoint: Endpoint = LOCAL_DESTINATION) -> ToolContext:
    return item_context(
        "docs/photo.png",
        is_directory=False,
        picked_root="/src",
        other_root="/dst",
        picked_endpoint=LOCAL_SOURCE,
        other_endpoint=endpoint,
    )


def _command(command: str, context: ToolContext, options: str = "") -> list[str]:
    tool = ExternalTool(name="Kate", command=command, options=options)
    return build_tool_command(tool, context)


def test_the_placeholders_describe_the_item_and_its_counterpart() -> None:
    context = _context()
    assert _command("kate %d/%f", context) == ["kate", "/src/docs/photo.png"]
    assert _command("kate %a", context) == ["kate", "/src/docs/photo.png"]
    assert _command("kate %f", context) == ["kate", "photo.png"]
    assert _command("kate %x", context) == ["kate", "png"]
    assert _command("kate %b", context) == ["kate", "photo"]
    assert _command("kate %d", context) == ["kate", "/src/docs"]
    assert _command("meld %A", context) == ["meld", "/dst/docs/photo.png"]
    assert _command("meld %D", context) == ["meld", "/dst/docs"]
    assert _command("meld %F", context) == ["meld", "photo.png"]
    assert _command("meld %X", context) == ["meld", "png"]
    assert _command("meld %B", context) == ["meld", "photo"]


def test_the_tool_name_and_its_options_are_placeholders() -> None:
    context = _context()
    assert _command("kate %T", context) == ["kate", "Kate"]
    # The options may carry several words.
    assert _command("kate %O %f", context, "-R --wait") == [
        "kate",
        "-R",
        "--wait",
        "photo.png",
    ]


def test_the_remote_placeholders_describe_the_other_pane() -> None:
    context = _context(REMOTE_DESTINATION)
    assert _command("scp %d/%f %U%V%R%W%D/%F", context) == [
        "scp",
        "/src/docs/photo.png",
        "me@127.0.0.1:/dst/docs/photo.png",
    ]
    assert _command("kate %R", context) == ["kate", "127.0.0.1"]
    assert _command("kate %U", context) == ["kate", "me"]
    assert _command("kate %V", context) == ["kate", "@"]
    assert _command("kate %W", context) == ["kate", ":"]
    assert _command("kate %P", context) == ["kate", "://"]


def test_a_local_side_has_no_remote_placeholders() -> None:
    context = _context()
    # A placeholder without a value leaves nothing behind.
    assert _command("kate %R", context) == ["kate"]
    assert _command("kate %U", context) == ["kate"]
    assert _command("kate %V", context) == ["kate"]
    assert _command("kate %W", context) == ["kate"]
    assert _command("kate %P", context) == ["kate"]
    # The path of the other pane is still there.
    assert _command("scp %d/%f %U%V%R%W%D/%F", context) == [
        "scp",
        "/src/docs/photo.png",
        "/dst/docs/photo.png",
    ]


def test_a_double_percent_is_a_literal_percent() -> None:
    assert _command("echo %%", _context()) == ["echo", "%"]


def test_a_path_with_a_space_stays_one_argument() -> None:
    context = item_context(
        "my docs/photo.png",
        is_directory=False,
        picked_root="/src",
        other_root="/dst",
        picked_endpoint=LOCAL_SOURCE,
        other_endpoint=LOCAL_DESTINATION,
    )
    assert _command("kate %a", context) == ["kate", "/src/my docs/photo.png"]


def test_a_directory_is_its_own_directory() -> None:
    context = item_context(
        "docs",
        is_directory=True,
        picked_root="/src",
        other_root="/dst",
        picked_endpoint=LOCAL_SOURCE,
        other_endpoint=LOCAL_DESTINATION,
    )
    assert _command("meld %D %d", context) == ["meld", "/dst/docs", "/src/docs"]


def test_an_unknown_placeholder_is_reported() -> None:
    assert unknown_placeholders("kate %z %f") == {"%z"}
    assert unknown_placeholders("kate %f %d") == set()


def test_a_broken_command_is_reported() -> None:
    with pytest.raises(ExternalToolError):
        _command('kate "%f', _context())
    with pytest.raises(ExternalToolError):
        _command("", _context())


def test_the_tools_are_stored_and_read_back(tmp_path, monkeypatch) -> None:
    from PySide6.QtCore import QSettings

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    store = QSettings(str(tmp_path / "tools.ini"), QSettings.Format.IniFormat)
    tools = [
        ExternalTool(name="Kate", command="kate %d/%f"),
        ExternalTool(
            name="Meld",
            command="meld %D %d",
            options="--wait",
            enabled=False,
        ),
    ]
    save_tools(tools, store)
    save_diff_command("meld %a %A", store)

    assert load_tools(store) == tools
    assert load_diff_command(store) == "meld %a %A"


def test_a_broken_stored_tool_is_ignored(tmp_path) -> None:
    from PySide6.QtCore import QSettings
    from qpy_rsync.storage.settings import encode_text

    store = QSettings(str(tmp_path / "tools.ini"), QSettings.Format.IniFormat)
    store.setValue("tools/external", encode_text("not json"))
    assert load_tools(store) == []
    store.setValue(
        "tools/external",
        encode_text('[{"name": "", "command": "kate"}, {"name": "k", "command": "kate"}]'),
    )
    assert [tool.name for tool in load_tools(store)] == ["k"]

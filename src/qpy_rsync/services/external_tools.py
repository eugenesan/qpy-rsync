"""External tools that can be run on the items of the comparison.

A tool is a command with placeholders. The placeholders describe the item
that was picked in one pane and its counterpart in the other pane, so one
command works for every row of the list::

    kate %d/%f
    meld %D %d
    meld %D/%F %d/%f
    scp %d/%f %U%V%R%W%D/%F

The command is split into words first and the placeholders are filled in
afterwards, so a path with a space stays one argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
import shlex
from typing import Mapping, Protocol

from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.models import Endpoint

# Every placeholder a command may use, with the text the editor shows.
PLACEHOLDER_HELP: tuple[tuple[str, str], ...] = (
    ("%a", "the full path of the item in the picked pane"),
    ("%f", "the file name of the item in the picked pane"),
    ("%x", "the extension of that file name"),
    ("%b", "that file name without its extension"),
    ("%d", "the directory of the item in the picked pane"),
    ("%A", "the full path of the item in the other pane"),
    ("%F", "the file name of the item in the other pane"),
    ("%X", "the extension of that file name"),
    ("%B", "that file name without its extension"),
    ("%D", "the directory of the item in the other pane"),
    ("%R", "the host of the other pane, empty when it is local"),
    ("%U", "the user of the other pane, empty when it is local"),
    ("%V", "@ when the other pane has a user"),
    ("%W", ": when the other pane has a host"),
    ("%P", ":// for a remote pane, empty for a local one"),
    ("%T", "the name of the tool"),
    ("%O", "the options of the tool"),
    ("%%", "a literal %"),
)

_PLACEHOLDER = re.compile(r"%(%|[A-Za-z])")
_KNOWN = {name[1:] for name, _text in PLACEHOLDER_HELP if name != "%%"}

# The tools are stored as flat, plain INI keys.  ``tools/external/count``
# gives N, and tool i (1-based) uses ``tools/external/i/<field>``.
TOOLS_KEY = "tools/external"
TOOLS_COUNT_KEY = f"{TOOLS_KEY}/count"
TOOL_FIELDS = ("name", "command", "options", "enabled")
DIFF_COMMAND_KEY = "tools/diff-command"


class SettingsStore(Protocol):
    """The part of ``QSettings``/``SettingsRouter`` used for tool storage."""

    def value(self, key: str, default: object = None) -> object: ...

    def setValue(self, key: str, value: object) -> None: ...

    def remove(self, key: str) -> None: ...

    def sync(self) -> None: ...


def _tool_key(index: int, field: str) -> str:
    return f"{TOOLS_KEY}/{index}/{field}"


def _as_bool(value: object) -> bool:
    """Read a plain boolean, including one hand-edited in the INI file."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _tool_count(settings: SettingsStore) -> int:
    """The remembered number of tools, or 0 when it is missing or invalid."""
    try:
        count = int(settings.value(TOOLS_COUNT_KEY, 0))
    except (TypeError, ValueError):
        return 0
    return max(0, min(count, 1000))


class ExternalToolError(ValueError):
    """A tool command that cannot be used."""


@dataclass(slots=True, frozen=True)
class ExternalTool:
    """A tool the user can run on an item of the comparison."""

    name: str
    command: str
    options: str = ""
    enabled: bool = True


@dataclass(slots=True, frozen=True)
class ToolContext:
    """The item a tool runs on and the pane it was picked in."""

    # The full path, the directory and the name of the picked item.
    picked_full_path: str
    picked_directory: str
    picked_name: str
    # The same for the item of the other pane.
    other_full_path: str
    other_directory: str
    other_name: str
    # The endpoints behind the two panes.
    picked_endpoint: Endpoint
    other_endpoint: Endpoint
    tool_name: str = ""
    options: str = ""


def join_path(root: str, path: str) -> str:
    """Join an endpoint root and a relative comparison path."""
    clean_root = root.rstrip("/")
    clean_path = path.strip("/")
    if not clean_root:
        return clean_path
    if not clean_path:
        return clean_root
    return f"{clean_root}/{clean_path}"


def split_name(name: str) -> tuple[str, str]:
    """The name of a file and its extension, without the dot."""
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem:
        return name, ""
    return stem, extension


def item_context(
    path: str,
    *,
    is_directory: bool,
    picked_root: str,
    other_root: str,
    picked_endpoint: Endpoint,
    other_endpoint: Endpoint,
    tool_name: str = "",
    options: str = "",
) -> ToolContext:
    """Build the context of an item of the comparison."""
    clean = path.strip("/")
    picked_full = join_path(picked_root, clean)
    other_full = join_path(other_root, clean)
    name = PurePosixPath(clean).name if clean else ""
    if is_directory:
        picked_directory = picked_full
        other_directory = other_full
    else:
        picked_directory = str(PurePosixPath(picked_full).parent)
        other_directory = str(PurePosixPath(other_full).parent)
    return ToolContext(
        picked_full_path=picked_full,
        picked_directory=picked_directory,
        picked_name=name,
        other_full_path=other_full,
        other_directory=other_directory,
        other_name=name,
        picked_endpoint=picked_endpoint,
        other_endpoint=other_endpoint,
        tool_name=tool_name,
        options=options,
    )


def placeholder_values(
    tool: ExternalTool, context: ToolContext
) -> dict[str, str]:
    """The value of every placeholder for one item."""
    picked_stem, picked_extension = split_name(context.picked_name)
    other_stem, other_extension = split_name(context.other_name)
    endpoint = context.other_endpoint
    host = endpoint.host or ""
    user = endpoint.user or ""
    remote = endpoint.kind is not EndpointKind.LOCAL
    return {
        "a": context.picked_full_path,
        "f": context.picked_name,
        "x": picked_extension,
        "b": picked_stem,
        "d": context.picked_directory,
        "A": context.other_full_path,
        "F": context.other_name,
        "X": other_extension,
        "B": other_stem,
        "D": context.other_directory,
        "R": host,
        "U": user,
        "V": "@" if user else "",
        "W": ":" if host else "",
        "P": "://" if remote else "",
        "T": tool.name,
        "O": tool.options,
    }


def expand_placeholders(text: str, values: Mapping[str, str]) -> str:
    """Fill the placeholders of a text in."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "%":
            return "%"
        return values.get(key, match.group(0))

    return _PLACEHOLDER.sub(replace, text)


def unknown_placeholders(text: str) -> set[str]:
    """The placeholders of a text that the tool does not know."""
    found: set[str] = set()
    for match in _PLACEHOLDER.finditer(text):
        key = match.group(1)
        if key != "%" and key not in _KNOWN:
            found.add(match.group(0))
    return found


def build_tool_command(
    tool: ExternalTool, context: ToolContext
) -> list[str]:
    """The argument vector of a tool for one item."""
    values = placeholder_values(tool, context)
    try:
        parts = shlex.split(tool.command)
    except ValueError as exc:
        raise ExternalToolError(
            f"The command of {tool.name} is not a valid command line: {exc}"
        ) from exc
    if not parts:
        raise ExternalToolError(f"The command of {tool.name} is empty.")
    argv: list[str] = []
    for part in parts:
        expanded = expand_placeholders(part, values)
        if not expanded and part:
            # A placeholder without a value leaves nothing behind, so the
            # argument disappears instead of turning into an empty one.
            continue
        if "%O" in part:
            # The options may carry several words.
            try:
                argv.extend(shlex.split(expanded))
            except ValueError as exc:
                raise ExternalToolError(
                    f"The options of {tool.name} are not a valid command line: {exc}"
                ) from exc
            continue
        argv.append(expanded)
    if not argv:
        raise ExternalToolError(f"The command of {tool.name} is empty.")
    return argv


def load_tools(store: SettingsStore | None = None) -> list[ExternalTool]:
    """The tools the user configured, read from flat plain INI keys."""
    from qpy_rsync.storage.settings import app_settings

    settings: SettingsStore = store if store is not None else app_settings()
    tools: list[ExternalTool] = []
    for index in range(1, _tool_count(settings) + 1):
        name = str(settings.value(_tool_key(index, "name"), "") or "").strip()
        command = str(settings.value(_tool_key(index, "command"), "") or "").strip()
        if not name or not command:
            # A missing or incomplete entry is skipped, so a removed tool
            # does not shift the tools that come after it.
            continue
        options = str(settings.value(_tool_key(index, "options"), "") or "")
        enabled = _as_bool(settings.value(_tool_key(index, "enabled"), True))
        tools.append(
            ExternalTool(name=name, command=command, options=options, enabled=enabled)
        )
    return tools


def save_tools(
    tools: list[ExternalTool], store: SettingsStore | None = None
) -> None:
    """Remember the tools as flat, plain INI keys."""
    from qpy_rsync.storage.settings import app_settings

    settings: SettingsStore = store if store is not None else app_settings()
    # Drop the fields of tools that no longer exist so the file stays tidy
    # even though only the first ``count`` entries are read back.
    for index in range(len(tools) + 1, _tool_count(settings) + 1):
        for field in TOOL_FIELDS:
            settings.remove(_tool_key(index, field))
    settings.setValue(TOOLS_COUNT_KEY, len(tools))
    for index, tool in enumerate(tools, 1):
        settings.setValue(_tool_key(index, "name"), tool.name)
        settings.setValue(_tool_key(index, "command"), tool.command)
        settings.setValue(_tool_key(index, "options"), tool.options)
        settings.setValue(_tool_key(index, "enabled"), tool.enabled)
    settings.sync()


def load_diff_command(store: SettingsStore | None = None) -> str:
    """The diff tool command the user configured, if any."""
    from qpy_rsync.storage.settings import app_settings

    settings: SettingsStore = store if store is not None else app_settings()
    return str(settings.value(DIFF_COMMAND_KEY, "") or "")


def save_diff_command(command: str, store: SettingsStore | None = None) -> None:
    """Remember the diff tool command as a plain string."""
    from qpy_rsync.storage.settings import app_settings

    settings: SettingsStore = store if store is not None else app_settings()
    settings.setValue(DIFF_COMMAND_KEY, command)
    settings.sync()
